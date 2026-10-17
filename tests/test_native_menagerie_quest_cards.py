"""Real six-minion Quest, original submitted types and existing complete reward."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_ashalon_adaptation_cards import load_batch as reward_batch, register_native_ashalon_adaptation_cards
from hs_sim.cards.native_menagerie_quest_cards import CARD, REWARD, load_batch, register_native_menagerie_quest_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Rarity, Registry, RewindSpec, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone,
    match_minion_type_plays, played_minion_type_facts, submitted_minion_types)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, InvokeBehavior, RequestChoice,
    ReturnToHand, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import QuestProgress, TribeChangeSpec
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import ChangeMinionTribes, TribeState
from hs_sim.engine.zones import CardReference

P = 'k166.'
HERO, WATCH, BOUNCE, CHANGE, SUMMON = (P+x for x in ('hero', 'watch', 'bounce', 'change', 'summon'))
KINDS = ('beast', 'dragon', 'demon', 'elemental', 'mech', 'murloc')
A, D = P+'beast', P+'dragon'
DUAL, ALL, NONE, UNKNOWN, FACE, RETRY = (P+x for x in ('dual', 'all', 'none', 'unknown', 'face', 'retry'))
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.NONE, tribes=())


@lru_cache(maxsize=1)
def seed_definitions():
    full = build_registry()
    return tuple(full.card(x['record']['id']) for x in reward_batch()['existing_dependencies'])


@lru_cache(maxsize=None)
def registry(mode=None, role='writer'):
    r = Registry('menagerie-' + str(mode))
    for definition in seed_definitions(): r.register_card(definition)
    register_native_ashalon_adaptation_cards(r); register_native_menagerie_quest_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30, metadata=META))
    for name, tribes in [(x, (x,)) for x in KINDS] + [('dual', ('beast', 'dragon')), ('all', ('all',)), ('none', ()), ('unknown', None)]:
        r.register_card(CardDefinition(P+name, name, CardType.MINION, cost=1, attack=1, health=3, metadata=replace(META, tribes=tribes)))
    r.register_behavior(P+'face', lambda c: (Transform(c.source_id, NONE),))
    r.register_card(CardDefinition(FACE, FACE, CardType.MINION, cost=1, health=3,
        metadata=replace(META, tribes=('beast',)), battlecry=P+'face'))
    r.register_behavior(P+'retry', lambda c: ())
    r.register_card(CardDefinition(RETRY, RETRY, CardType.MINION, cost=1, health=3, battlecry=P+'retry',
        metadata=replace(META, tribes=('beast',)), keywords=(Keyword.REWIND,), rewind=RewindSpec()))
    bodies = {BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        CHANGE: lambda c: (ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]), TribeChangeSpec('set', ('dragon',)), c.source_id),),
        SUMMON: lambda c: (Summon(c.player_id, A), Summon(c.player_id, D))}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.HAND, Zone.BOARD), kinds=(CardType.MINION,), relation='friendly') if cid != SUMMON else None))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K166 deliberate quest failure')))
    def watch(c):
        if c.event.source_id != next((i for i in c.state.players[1].quests if c.state.entities[i].card_id == CARD), None): return ()
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, 1),)
        if mode == 'fatal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
        if mode == 'full': return tuple(AddToHand(1, NONE, c.source_id) for _ in range(10))
        return (RequestChoice(1, (ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Rollback',
            (InvokeBehavior(P+'fail', c.source_id, 1),))), c.source_id),)
    if mode:
        if mode == 'counter':
            r.register_behavior(P+'watch', lambda c: (CounterMinion(dict(c.event.data)['window_id']),))
            kind = 'minion_counter_check'
        else:
            r.register_behavior(P+'watch', watch)
            kind = 'quest_stage_completed' if mode in ('reward', 'full') else 'quest_progressed'
        r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, durability=4, metadata=META,
            triggers=(TriggerSpec(kind, P+'watch'),)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class MenagerieQuestTests(unittest.TestCase):
    def game(self, hand=None, mode=None):
        self.mode = mode
        hand = (CARD,) + tuple(P+x for x in KINDS) if hand is None else hand
        own = dict(weapon_card_id=WATCH) if mode and mode != 'counter' else {}
        other = dict(weapon_card_id=WATCH) if mode == 'counter' else {}
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=hand, deck=(NONE,)*9, mana=30, max_mana=30, mana_cap=30, **own),
            PlayerSetup(HERO, deck=(NONE,)*9, **other)), seed=166), registry(mode))
    def first(self, g, cid, zone='hand', pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None, pid=1):
        e = self.first(g, cid, pid=pid)
        g.apply(PlayCard(pid, e.id, target_id=target, position=len(g.state.players[pid].board) if e.kind == CardType.MINION else None))
        return e.id
    def progress(self, g, pid=1): return self.first(g, CARD, 'quests', pid).quest_progress
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); reader = registry(self.mode, 'reader')
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(saved, reader); self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved); self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        return other
    def corrupt(self, g, edit):
        value = deepcopy(g.snapshot()); edit(value)
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(value), registry(self.mode, 'reader'))
    def complete(self, g):
        self.play(g, CARD)
        for name in KINDS: self.play(g, P+name)

    def test_a0_complete_source_existing_reward_and_explicit_twelve_type_universe(self):
        data = load_batch(); r = registry(); card = r.card(CARD)
        self.assertEqual((card.cost, card.quest.stages[0].goal), (1, 6))
        self.assertEqual(len(data['types']), 12); self.assertIn('draenei', data['types'])
        self.assertEqual(r.card(REWARD), build_registry().card(REWARD))
        self.assertEqual(data['cards'][0]['record']['tags']['QUEST_PROGRESS_TOTAL'], 6)

    def test_a1_matching_is_one_physical_play_per_type_and_reassigns_previous_dual(self):
        types = ('beast', 'dragon', 'mech')
        self.assertEqual(len(match_minion_type_plays(((1, TribeState(('beast', 'dragon'))),), types)), 1)
        value = match_minion_type_plays(((1, TribeState(('beast', 'dragon'))), (2, TribeState(('beast',)))), types)
        self.assertEqual(value, ((1, 'dragon'), (2, 'beast')))
        self.assertEqual(len(match_minion_type_plays(tuple((i, TribeState(('all',))) for i in range(1, 8)), types)), 3)
        self.assertEqual(match_minion_type_plays(((1, TribeState(('all',), ('beast', 'dragon', 'mech'))),), types), ())
        with self.assertRaises(UnsupportedDefinitionError): match_minion_type_plays(((1, TribeState(('future_type',))),), types)

    def test_a2_real_six_distinct_plays_award_complete_ashalon_once(self):
        g = self.game(); self.complete(g)
        self.assertFalse(g.state.players[1].quests); self.assertEqual(len([i for i in g.state.players[1].hand if g.state.entities[i].card_id == REWARD]), 1)
        self.assertEqual(len([e for e in g.events if e.kind == 'quest_completed']), 1)
        self.assertEqual(len(match_minion_type_plays(played_minion_type_facts(g.state, 1), tuple(load_batch()['types']))), 6)
        self.portable(g)

    def test_a3_completed_plays_before_activation_never_retroactively_advance(self):
        g = self.game((A, CARD, D)); old = self.play(g, A); self.play(g, CARD)
        progress = self.progress(g); self.assertEqual((progress.value, progress.completed_before), (0, (1,)))
        self.play(g, D); self.assertEqual(self.progress(g).value, 1)
        facts = played_minion_type_facts(g.state, 1, exclude_ids=progress.completed_before)
        self.assertEqual([x[0] for x in facts], [3]); self.assertNotEqual(old, self.first(g, D, 'board').id); self.portable(g)

    def test_a4_dual_all_and_repeated_types_count_minions_without_double_counting(self):
        g = self.game((CARD, DUAL, A, D, ALL, ALL)); self.play(g, CARD)
        for cid, expected in zip((DUAL, A, D, ALL, ALL), (1, 2, 2, 3, 4)):
            self.play(g, cid); self.assertEqual(self.progress(g).value, expected)
        self.portable(g)

    def test_a5_same_physical_entity_different_plays_keep_original_submitted_changes(self):
        g = self.game((CARD, A, BOUNCE, CHANGE)); self.play(g, CARD); body = self.play(g, A)
        self.play(g, BOUNCE, body); self.play(g, CHANGE, body); self.play(g, A)
        self.assertEqual(self.progress(g).value, 2)
        facts = played_minion_type_facts(g.state, 1); self.assertEqual([x[1].members for x in facts], [('beast',), ('dragon',)])
        self.assertEqual([p.source_id for p in g.state.play_history if p.kind == CardType.MINION], [body, body]); self.portable(g)

    def test_a6_later_battlecry_transform_does_not_replace_original_submitted_type(self):
        g = self.game((CARD, FACE, A)); self.play(g, CARD); body = self.play(g, FACE)
        self.assertEqual(g.state.entities[body].card_id, NONE); self.play(g, A)
        self.assertEqual(self.progress(g).value, 1); self.assertEqual(submitted_minion_types(g.state.play_history[1]).members, ('beast',)); self.portable(g)

    def test_a7_ordinary_summons_and_typeless_minions_add_no_type_progress(self):
        g = self.game((CARD, SUMMON, NONE)); self.play(g, CARD); self.play(g, SUMMON); self.play(g, NONE)
        self.assertEqual(self.progress(g).value, 0); self.assertEqual(played_minion_type_facts(g.state, 1)[0][1].members, ()); self.portable(g)

    def test_a8_unknown_eligible_type_is_explicit_failure_and_full_rollback(self):
        g = self.game((CARD, UNKNOWN)); self.play(g, CARD); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown submitted minion types'): self.play(g, UNKNOWN)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(self.progress(g).value, 0)

    def test_a9_countered_committed_minion_still_has_original_completed_play_type(self):
        g = self.game((CARD, A, D), mode='counter'); self.play(g, CARD); self.play(g, A); self.play(g, D)
        self.assertEqual(self.progress(g).value, 2); self.assertFalse(g.state.players[1].board)
        self.assertTrue(all(p.countered for p in g.state.play_history if p.kind == CardType.MINION)); self.portable(g)

    def test_b0_progress_wait_restores_and_failure_rolls_back_original_choice_only(self):
        g = self.game((CARD, A), mode='progress'); self.play(g, CARD); self.play(g, A)
        self.assertEqual(self.progress(g).value, 1); other = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate quest failure'): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.choose(other); self.assertEqual(other.snapshot(), g.snapshot())

    def test_b1_real_reward_wait_retains_quest_slot_and_delivers_once_after_resume(self):
        g = self.game(mode='reward'); self.complete(g)
        self.assertTrue(self.progress(g).completing); self.assertNotIn(REWARD, [g.state.entities[i].card_id for i in g.state.players[1].hand])
        other = self.portable(g); self.choose(g); self.choose(other); self.assertEqual(other.snapshot(), g.snapshot())
        self.assertFalse(g.state.players[1].quests); self.assertEqual(self.first(g, REWARD).card_id, REWARD)

    def test_b2_full_hand_uses_existing_reward_overflow_and_still_completes_quest(self):
        g = self.game(mode='full'); self.complete(g)
        self.assertFalse(g.state.players[1].quests); self.assertNotIn(REWARD, [g.state.entities[i].card_id for i in g.state.players[1].hand])
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned' and g.state.entities[e.target_id].card_id == REWARD]), 1); self.portable(g)

    def test_b3_progress_reaction_failure_rolls_back_payment_entry_history_and_baseline(self):
        g = self.game((CARD, A), mode='fail'); self.play(g, CARD); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate quest failure'): self.play(g, A)
        self.assertEqual(g.snapshot(), saved)

    def test_b4_terminal_progress_keeps_only_actual_completed_occurrence(self):
        g = self.game((CARD, A), mode='fatal'); self.play(g, CARD); self.play(g, A)
        self.assertEqual(g.state.status, 'finished'); self.assertEqual(self.progress(g).value, 1); self.portable(g)

    def test_b5_minion_rewind_retires_first_attempt_and_never_counts_twice(self):
        g = self.game((CARD, RETRY)); self.play(g, CARD); self.play(g, RETRY)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(self.progress(g).value, 1); self.portable(g)
        self.choose(g, 'retry'); self.assertEqual(self.progress(g).value, 1)
        self.assertEqual(len(played_minion_type_facts(g.state, 1)), 1); self.portable(g)

    def test_c0_second_player_uses_own_completed_minion_roots(self):
        self.mode = None
        g = Game.from_scenario(Scenario((PlayerSetup(HERO, deck=(NONE,)*6),
            PlayerSetup(HERO, hand=(CARD, A, D), deck=(NONE,)*6, mana=20, max_mana=20, mana_cap=20)), active_player=2), registry())
        for cid in (CARD, A, D): self.play(g, cid, pid=2)
        self.assertEqual(self.progress(g, 2).value, 2); self.assertEqual(played_minion_type_facts(g.state, 1), ()); self.portable(g)

    def test_c1_completed_inventory_and_new_strict_field_validate_on_restore(self):
        g = self.game((A, CARD)); self.play(g, A); self.play(g, CARD)
        identity = self.first(g, CARD, 'quests').id
        def progress(saved): return next(e for e in saved['state']['entities'].values() if e['id'] == identity)['quest_progress']
        self.corrupt(g, lambda s: progress(s).update(completed_before=[999]))
        self.corrupt(g, lambda s: progress(s).update(completed_before=[1, 1]))
        self.corrupt(g, lambda s: progress(s).pop('completed_before'))
        self.corrupt(g, lambda s: s.update(schema_version=371)); self.portable(g)

    def test_c2_private_completed_inventory_and_original_tribes_stay_out_of_player_dto(self):
        g = self.game((A, CARD, D), mode='progress'); self.play(g, A); self.play(g, CARD); self.play(g, D)
        for pid in (1, 2):
            text = json.dumps(g.for_player(pid).observe()) + json.dumps(g.player_events(pid))
            for private in ('completed_before', 'quote_input', 'submitted_cost', 'AdvanceQuestFromPlayedTypes'):
                self.assertNotIn(private, text)
        self.choose(g)

    def test_c3_query_is_pure_frozen_and_excludes_only_real_completed_roots(self):
        g = self.game((A,)); self.play(g, A); before = g.snapshot(); rng = g._rng.getstate()
        for _ in range(3): self.assertEqual(played_minion_type_facts(g.state, 1)[0][1], TribeState(('beast',)))
        with self.assertRaises(ValueError): played_minion_type_facts(g.state, 1, exclude_ids=(999,))
        with self.assertRaises(ValueError): QuestProgress(1, completed_before=(True,))
        self.assertEqual(g.snapshot(), before); self.assertEqual(g._rng.getstate(), rng)


if __name__ == '__main__': unittest.main()
