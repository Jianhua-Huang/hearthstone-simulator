"""Native fixed summons, current deck condition and each original forced attacker."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards.lowest_health_demons_card import CARD, TOKENS, load_batch, register_lowest_health_demons_card
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup, Registry,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, Draw,
    InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck, CardReference

P = 'k211.'
HERO, LOW, HIGH, WALL, TAUNT, STEALTH, DORMANT, WATCH, SPELL, POWER = (
    P+x for x in ('hero', 'low', 'high', 'wall', 'taunt', 'stealth', 'dormant', 'watch', 'spell', 'power'))


@lru_cache(None)
def registry(mode=None):
    r = Registry(P+'host'); register_lowest_health_demons_card(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=80))
    r.register_behavior(P+'empty', lambda c: ())
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('Deliberate Hounds rollback')))
    def wait(c):
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(P+'death', lambda c: wait(c) if mode == 'death' else ())
    for cid, attack, health, keywords, extra in (
        (LOW, 1, 2, (), {}), (HIGH, 1, 8, (), {}), (WALL, 5, 20, (), {}),
        (TAUNT, 0, 20, (Keyword.TAUNT,), {}), (STEALTH, 0, 2, (Keyword.STEALTH,), {}),
        (DORMANT, 0, 1, (), {'dormant_turns': 2}),
        (POWER, 0, 20, (), {'spell_damage': 9}),
    ):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack, health=health,
            deathrattle=P+'death' if cid == LOW else None, keywords=keywords, **extra))
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, on_play=P+'empty'))
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id),)
    r.register_behavior(P+'reenter', reenter)
    def watch(c):
        event = c.event; target = c.state.entities.get(event.target_id)
        if event.kind == 'minion_summoned' and target is not None and target.card_id in TOKENS:
            if mode == 'summon': return wait(c)
            if mode == 'draw': return (Draw(c.player_id, 1, c.source_id),)
            if mode == 'insert' and target.card_id == TOKENS[0]:
                return (AddToDeck(c.player_id, HIGH, position='bottom', source_id=c.source_id),)
            if mode == 'nested' and not any(x.request.cause.source.entity_id == c.source_id for x in c.state.card_summon_history):
                return (SummonByCard(c.player_id, (SummonEntryMaterial(TOKENS[0]),), SummonCause.capture(c)),)
            if mode == 'kill_first' and target.card_id == TOKENS[0]: return (Destroy(target.id, c.source_id),)
            if mode == 'steal_first' and target.card_id == TOKENS[0]: return (ChangeControl(target.id, 3-c.player_id),)
        if event.kind == 'random_choice' and dict(event.data).get('producer') == 'attack_lowest_health_enemy':
            if mode == 'selection': return wait(c)
            if mode == 'bounce':
                attacker = c.state.entities[event.target_id]
                return (ReturnToHand(attacker.id), InvokeBehavior(P+'reenter', c.source_id, c.player_id, attacker.id))
        if event.kind == 'attack_declared':
            source = c.state.entities.get(event.source_id)
            if source is not None and source.card_id in TOKENS:
                if mode == 'attack': return wait(c)
                if mode == 'fail_attack': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
                if mode == 'fill_deck': return (AddToDeck(c.player_id, HIGH, position='bottom', source_id=c.source_id),)
        return ()
    r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        triggers=tuple(TriggerSpec(k, P+'watch') for k in ('minion_summoned', 'random_choice', 'attack_declared'))))
    r.validate(); return r


class LowestHealthDemonsTests(unittest.TestCase):
    def game(self, board=(), enemy=(HIGH,), deck=(), actor=1, mode=None, seed=211):
        self.mode = mode
        own = PlayerSetup(HERO, hand=(CARD,), board=board, deck=deck, mana=20, max_mana=20, mana_cap=20)
        other = PlayerSetup(HERO, board=enemy, mana=20, max_mana=20, mana_cap=20)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own),
            active_player=actor, seed=seed), registry(mode))
    def play(self, g):
        p = g.state.active_player; source = g.state.players[p].hand[0]
        g.apply(PlayCard(p, source)); return source
    def attacks(self, g): return [e for e in g.events if e.kind == 'attack_declared']
    def dogs(self, g, p=None):
        p = g.state.active_player if p is None else p
        return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id in TOKENS]
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def finish(self, g):
        while g.state.pending_choice is not None: self.choose(g)
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry.__wrapped__(self.mode)
        restored = Game.from_snapshot(deepcopy(saved), r)
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        return restored
    def test_complete_original_rows_and_explicit_uncalibrated_token_identity(self):
        from hs_sim.cards import build_registry
        r = build_registry(); data = load_batch()
        self.assertEqual(len(data['official_observations']), 2)
        self.assertFalse(data['identity_policy']['official_mapping_confirmed'])
        self.assertEqual(r.card(CARD).cost, 4)
        self.assertEqual([(r.card(cid).attack, r.card(cid).health, r.card(cid).metadata.tribes) for cid in TOKENS],
            [(3, 2, ('demon',)), (3, 2, ('demon',))])
        self.assertEqual(r.summon_attack_profiles[CARD].card_ids, TOKENS)
    def test_real_payment_two_ordered_deliveries_and_full_summon_group_precedes_combat(self):
        g = self.game(); source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 16)
        self.assertEqual([e.card_id for e in self.dogs(g)], list(TOKENS))
        self.assertEqual(len(self.attacks(g)), 2)
        events = [e.kind for e in g.events]
        self.assertLess(max(i for i, k in enumerate(events) if k == 'minion_summoned'), events.index('attack_declared'))
        roots = g.state.card_summon_history
        self.assertEqual([r.request.materials[0].card_id for r in roots], list(TOKENS))
        self.assertTrue(all(x.request.cause.source.entity_id == source for x in roots))
        self.assertEqual(len(g.state.cast_history), 1); self.portable(g)
    def test_remaining_minion_in_own_deck_disables_only_attacks(self):
        for deck in ((HIGH,), (SPELL, HIGH)):
            g = self.game(deck=deck); self.play(g)
            self.assertEqual(len(self.dogs(g)), 2); self.assertFalse(self.attacks(g))
            self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck], list(deck))
    def test_spell_only_or_empty_deck_attacks_and_spell_bonus_does_not_increase_combat_damage(self):
        for deck in ((), (SPELL, SPELL)):
            g = self.game(board=(POWER,), enemy=(), deck=deck); self.play(g)
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 74)
            self.assertEqual(len(self.attacks(g)), 2)
    def test_each_member_reselects_current_lowest_after_the_previous_target_dies(self):
        g = self.game(enemy=(LOW, HIGH)); ids = tuple(g.state.players[2].board); self.play(g)
        self.assertEqual([e.target_id for e in self.attacks(g)], list(ids))
        self.assertEqual(g.state.entities[ids[0]].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[ids[1]].health, 5); self.portable(g)
    def test_equal_minimum_uses_original_rng_and_then_current_damaged_target(self):
        g = self.game(enemy=(HIGH, HIGH)); candidates = tuple(sorted(g.state.players[2].board))
        rng = random.Random(); rng.setstate(g._rng.getstate()); first = rng.choice(candidates); rng.choice((first,))
        self.play(g)
        self.assertEqual([e.target_id for e in self.attacks(g)], [first, first])
        self.assertEqual(g._rng.getstate(), rng.getstate()); self.portable(g)
    def test_forced_attacks_ignore_taunt_and_stealth_without_granting_charge_or_rush(self):
        g = self.game(enemy=(TAUNT, STEALTH)); target = g.state.players[2].board[1]; self.play(g)
        self.assertEqual(self.attacks(g)[0].target_id, target)
        self.assertTrue(all(Keyword.RUSH not in d.keywords and Keyword.CHARGE not in d.keywords for d in self.dogs(g)))
    def test_dormant_lower_health_is_not_a_live_enemy_candidate(self):
        g = self.game(enemy=(DORMANT, HIGH)); dormant, high = g.state.players[2].board; self.play(g)
        self.assertEqual([e.target_id for e in self.attacks(g)], [high, high])
        self.assertEqual(g.state.entities[dormant].health, 1)
    def test_partial_and_full_capacity_do_not_refill_after_combat_creates_space(self):
        for count, expected in ((6, 1), (7, 0)):
            g = self.game(board=(HIGH,)*count, enemy=(WALL,)); self.play(g)
            self.assertEqual(len(g.state.card_summon_history), 2)
            self.assertEqual(len(self.attacks(g)), expected)
            self.assertEqual(len(self.dogs(g)), 0)
            self.portable(g)
    def test_existing_and_nested_same_face_minions_do_not_join_original_attackers(self):
        g = self.game(board=(TOKENS[0], WATCH), mode='nested'); original = g.state.players[1].board[0]; self.play(g)
        self.assertEqual(len(self.attacks(g)), 2)
        attackers = {e.source_id for e in self.attacks(g)}; self.assertNotIn(original, attackers)
        self.assertEqual(len(self.dogs(g)), 4); self.portable(g)
    def test_killed_or_stolen_original_member_does_not_rebind_to_another_dog(self):
        for mode in ('kill_first', 'steal_first'):
            g = self.game(board=(WATCH,), mode=mode); self.play(g)
            self.assertEqual(len(self.attacks(g)), 1)
            self.assertEqual(g.state.entities[self.attacks(g)[0].source_id].card_id, TOKENS[1])
            self.portable(g)
    def test_attacker_bounce_reentry_during_selection_cannot_reuse_old_residence(self):
        g = self.game(board=(WATCH,), mode='bounce'); self.play(g)
        self.assertFalse(self.attacks(g)); self.assertEqual(len(self.dogs(g)), 2); self.portable(g)
    def test_deck_condition_is_evaluated_after_summon_reactions(self):
        g = self.game(board=(WATCH,), deck=(HIGH,), mode='draw'); self.play(g)
        self.assertEqual(len(self.attacks(g)), 2)
        g = self.game(board=(WATCH,), mode='insert'); self.play(g)
        self.assertEqual(len(self.dogs(g)), 2); self.assertFalse(self.attacks(g))
    def test_accepted_group_does_not_recheck_deck_after_first_combat(self):
        g = self.game(board=(WATCH,), mode='fill_deck'); self.play(g)
        self.assertEqual(len(self.attacks(g)), 2); self.assertEqual(len(g.state.players[1].deck), 2)
    def test_summon_selection_attack_and_death_waits_restore_and_continue_exactly_once(self):
        for mode in ('summon', 'selection', 'attack', 'death'):
            g = self.game(board=(WATCH,), enemy=(LOW, HIGH), mode=mode); self.play(g)
            self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
            before = g.snapshot()
            with self.assertRaises(ResolutionError): self.choose(g, 'fail')
            self.assertEqual(g.snapshot(), before)
            self.finish(g); self.finish(restored); self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(len(self.attacks(g)), 2); self.portable(g)
    def test_combat_reaction_failure_rolls_back_payment_all_summons_rng_and_combat(self):
        g = self.game(board=(WATCH,), mode='fail_attack'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), before)
    def test_both_seats_and_private_materials_do_not_leak_in_player_views(self):
        for actor in (1, 2):
            g = self.game(actor=actor); self.play(g); self.assertEqual(len(self.attacks(g)), 2)
            for viewer in (1, 2):
                text = json.dumps(g.observe(viewer))
                for key in ('request_card_ids', 'target_policy', 'rng_state', 'card_summon_history'):
                    self.assertNotIn(key, text)
            self.portable(g)
    def test_profile_patterns_and_old_schema_reject_incomplete_or_conflicting_materials(self):
        profile = registry().summon_attack_profiles[CARD]
        for changes in ({'request_card_ids': TOKENS[:1]}, {'request_card_ids': tuple(reversed(TOKENS))},
                {'target_policy': 'original'}, {'combat_relation': 'any_minions'}):
            with self.assertRaises(ValueError): replace(profile, **changes)
        g = self.game(); self.play(g); bad = deepcopy(g.snapshot()); bad['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())


if __name__ == '__main__': unittest.main()
