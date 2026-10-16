"""Finite random recipient selection and existing guarded grant continuations."""
from dataclasses import replace
import json
from random import Random
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, InvokeBehavior,
    RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.random_minion_keywords import RandomGrantMinionKeywords
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from opening_fixtures import metadata

KEYS = (Keyword.DIVINE_SHIELD, Keyword.TAUNT)


def registry(mode='normal'):
    r = Registry('isolated-random-minion-keywords-'+mode)
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=40, metadata=metadata()))
    r.register_card(CardDefinition('body', 'Body', CardType.MINION, attack=1, health=5, metadata=metadata()))
    r.register_card(CardDefinition('ready', 'Both keywords already', CardType.MINION,
        health=5, keywords=KEYS, metadata=metadata()))
    r.register_card(CardDefinition('sleep', 'Dormant', CardType.MINION, health=5,
                                   dormant_turns=2, metadata=metadata()))
    r.register_behavior('fail', lambda c: (AddToHand(c.player_id, 'missing.random.keyword'),))

    def wait(c, extra=()):
        return RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior('fail', c.source_id, c.player_id),)),
            *extra,
        ), source_id=c.source_id)

    def random(c):
        refs = tuple(MinionReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].board)
        if mode == 'reverse':
            refs = tuple(reversed(refs))
        if mode in ('future', 'nonminion'):
            refs = (replace(refs[0], **({'zone_epoch': refs[0].zone_epoch+1} if mode == 'future' else {'card_id':'hero'})),)
        effect = RandomGrantMinionKeywords(refs, KEYS, 999999 if mode == 'bad_source' else c.source_id)
        if mode in ('stale', 'same_entity'):
            effects = (ReturnToHand(refs[0].entity_id),)
            if mode == 'same_entity':
                effects += (SummonFromZone(c.player_id, zone=Zone.HAND, selection='first',
                    source_id=c.source_id, cause=SummonCause.capture(c)),)
            return (*effects, effect)
        return (wait(c), effect) if mode == 'pause' else (effect,)

    r.register_behavior('random', random)
    r.register_card(CardDefinition('random', 'Random original recipient', CardType.SPELL,
                                   on_play='random', metadata=metadata()))
    def watch(c):
        entity = c.state.entities[c.event.target_id]
        if entity.card_id != 'body' or Keyword.TAUNT in entity.keywords:
            return ()
        return (wait(c, (
            ChoiceOption('bounce', 'Return and create another', (ReturnToHand(entity.id), Summon(1, 'body'))),
            ChoiceOption('control', 'Change controller', (ChangeControl(entity.id, 2),)),
        )),)
    r.register_behavior('watch', watch)
    r.register_card(CardDefinition('watch', 'Grant observer', CardType.MINION, health=5,
        triggers=(TriggerSpec('ability_granted', 'watch'),), metadata=metadata()))
    r.validate()
    return r


class RandomMinionKeywordTests(unittest.TestCase):
    def game(self, board=('body','body'), mode='normal'):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=('random',), board=board),
                                            PlayerSetup('hero', board=('body',))), seed=89), registry(mode))

    def play(self, g):
        g.apply(PlayCard(1, g.state.players[1].hand[0]))

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry(mode))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(mode)).snapshot(), saved)
        return other

    def test_one_rng_choice_gives_both_keywords_to_the_same_physical_minion(self):
        g = self.game()
        rng = Random(); rng.setstate(g._rng.getstate())
        expected = rng.choice(sorted(g.state.players[1].board))
        self.play(g)
        choices = [e.target_id for e in g.events if e.kind == 'random_choice']
        self.assertEqual(choices, [expected])
        self.assertEqual(g._rng.getstate(), rng.getstate())
        for eid in g.state.players[1].board:
            self.assertEqual(g.state.entities[eid].keywords, set(KEYS) if eid == expected else set())
        self.assertFalse(g.state.entities[g.state.players[2].board[0]].keywords)
        self.portable(g)

    def test_candidate_order_does_not_change_physical_weights_or_random_stream(self):
        a, b = self.game(), self.game(mode='reverse')
        self.play(a); self.play(b)
        self.assertEqual([e.target_id for e in a.events if e.kind == 'random_choice'],
                         [e.target_id for e in b.events if e.kind == 'random_choice'])
        self.assertEqual(a._rng.getstate(), b._rng.getstate())

    def test_empty_pool_is_explicit_noop_without_randomness(self):
        g = self.game(())
        rng = g._rng.getstate(); self.play(g)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertFalse(any(e.kind == 'random_choice' for e in g.events))

    def test_dormant_candidates_are_ineligible_without_randomness(self):
        g = self.game(('sleep',))
        rng = g._rng.getstate(); self.play(g)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertFalse(g.state.entities[g.state.players[1].board[0]].keywords)

    def test_already_shielded_and_taunting_minion_remains_a_full_candidate(self):
        g = self.game(('ready',))
        self.play(g)
        entity = g.state.entities[g.state.players[1].board[0]]
        self.assertEqual(entity.keywords, set(KEYS))
        self.assertEqual(sum(a.kind == 'keyword' for a in entity.abilities), 4)
        self.assertEqual(sum(e.kind == 'random_choice' for e in g.events), 1)

    def test_left_original_is_not_in_random_pool(self):
        g = self.game(('body',), 'stale')
        rng = g._rng.getstate(); self.play(g)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertFalse(g.state.players[1].board)
        self.assertFalse(g.state.entities[g.state.players[1].hand[0]].keywords)

    def test_same_entity_reentry_does_not_satisfy_old_captured_candidate(self):
        g = self.game(('body',), 'same_entity')
        eid = g.state.players[1].board[0]
        epoch = g.state.entities[eid].zone_epoch
        rng = g._rng.getstate(); self.play(g)
        self.assertEqual(g.state.players[1].board, [eid])
        self.assertGreater(g.state.entities[eid].zone_epoch, epoch)
        self.assertFalse(g.state.entities[eid].keywords)
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g, 'same_entity')

    def test_unexecuted_producer_saves_restores_and_replays_before_rng(self):
        g = self.game(mode='pause')
        rng = g._rng.getstate(); self.play(g)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertIn('RandomGrantMinionKeywords', json.dumps(g.snapshot()['resolution_frame']))
        other = self.portable(g, 'pause')
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())

    def test_waiting_producer_failure_rolls_back_rng_and_original_choice(self):
        g = self.game(mode='pause'); self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.portable(g, 'pause')

    def test_grant_reaction_can_remove_original_without_rebinding_second_grant(self):
        g = self.game(('body','watch'))
        # The chosen recipient must be the body for this residence boundary.
        rng = Random(); rng.setstate(g._rng.getstate())
        if rng.choice(sorted(g.state.players[1].board)) != g.state.players[1].board[0]:
            g = self.game(('body','watch'), 'pause')
            self.play(g); self.choose(g)
        else:self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        old = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == 'body')
        self.choose(g, 'bounce')
        new = next(i for i in g.state.players[1].board if g.state.entities[i].card_id == 'body')
        self.assertNotEqual(new, old)
        self.assertNotIn(Keyword.TAUNT, g.state.entities[new].keywords)
        self.assertNotIn(Keyword.TAUNT, g.state.entities[old].keywords)

    def test_constructor_rejects_duplicate_weights_mutable_refs_and_unknown_keywords(self):
        g = self.game(); ref = MinionReference.capture(g.state.entities[g.state.players[1].board[0]])
        for refs, keys in (([ref],KEYS), ((ref,ref),KEYS), ((ref,),()), ((ref,),(Keyword.RUSH,)),
                           ((ref,),(Keyword.TAUNT,Keyword.TAUNT)), ((ref,),('taunt',))):
            with self.assertRaises(ValueError):RandomGrantMinionKeywords(refs, keys)

    def test_unknown_source_future_material_and_nonminion_face_fail_atomically(self):
        for mode, board in (('bad_source',()), ('future',('body',)), ('nonminion',('body',))):
            g = self.game(board, mode); before = g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g)
            self.assertEqual(g.snapshot(), before)
