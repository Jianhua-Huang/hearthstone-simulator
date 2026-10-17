"""Native Hiking Trail eligibility and original physical Map followup boundaries."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_hiking_trail_cards import CARD, BODY, POOL, load_batch, register_native_hiking_trail_cards
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Rarity, Registry, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import TribeChangeSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference, MoveCard

P = 'k167.'
HERO, WATCH, BEAST, D0, D1, D2, MECH, DUAL, ALL, NONE, UNKNOWN, FOREIGN, MISSING, FUTURE = (
    P+x for x in ('hero', 'watch', 'beast', 'd0', 'd1', 'd2', 'mech', 'dual', 'all', 'none', 'unknown', 'foreign', 'missing', 'future'))
SET, EXCLUDE, REENTER, SUMMON, AUTO = (P+x for x in ('set', 'exclude', 'reenter', 'summon', 'auto'))
CONTEXT = GenerationContext('k167-explicit-fixture', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())


@lru_cache(maxsize=None)
def registry(mode=None, pool='all', role='writer'):
    r = Registry('hiking-' + str(mode) + '-' + pool)
    register_native_hiking_trail_cards(r)
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30,
        metadata=replace(META, collectible=False, classes=(CardClass.SHAMAN,))))
    for cid, types in ((BEAST, ('beast',)), (D0, ('dragon',)), (D1, ('dragon',)), (D2, ('dragon',)),
            (MECH, ('mech',)), (DUAL, ('beast', 'dragon')), (ALL, ('all',)), (NONE, ()), (UNKNOWN, None), (FUTURE, ('future_type',))):
        card = CardDefinition(cid, cid, CardType.MINION, cost=1, attack=1, health=4, metadata=replace(META, tribes=types))
        r.register_card(card); r.register_pool_card(PoolCard.from_definition(card))
    foreign = CardDefinition(FOREIGN, FOREIGN, CardType.MINION, cost=1, health=4,
        metadata=replace(META, classes=(CardClass.MAGE,), tribes=('dragon',)))
    r.register_card(foreign); r.register_pool_card(PoolCard.from_definition(foreign))
    if pool in ('unadapted', 'foreign_missing'):
        missing = CardDefinition(MISSING, MISSING, CardType.MINION, health=2,
            metadata=replace(META, tribes=('dragon',), classes=(CardClass.MAGE,) if pool == 'foreign_missing' else (CardClass.NEUTRAL,)))
        r.register_pool_card(PoolCard.from_definition(missing))
    members = (D0, D1, D2) if pool == 'dragons' else (BEAST,) if pool == 'beasts' else (D0,) if pool == 'single' else () if pool == 'empty' else (
        BEAST, D0, D1, D2, MECH, DUAL, ALL, NONE, FOREIGN)
    if pool in ('unadapted', 'foreign_missing'): members += (MISSING,)
    if pool == 'unknown': members += (UNKNOWN,)
    if pool != 'none': r.register_pool(PoolDefinition(POOL, 'v1', CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(x) for x in members), complete=True))
    def return_from_deck(c):
        return (MoveCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, Zone.HAND, source_id=c.source_id),)
    r.register_behavior(P+'return', return_from_deck)
    bodies = {SET: lambda c: (ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]), TribeChangeSpec('set', ('dragon',)), c.source_id),),
        EXCLUDE: lambda c: (ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]), TribeChangeSpec('remove', ('dragon',)), c.source_id),),
        REENTER: lambda c: (MoveCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id, Zone.DECK, position='bottom', source_id=c.source_id),
            InvokeBehavior(P+'return', c.source_id, c.player_id, target_id=c.target_id)),
        SUMMON: lambda c: (Summon(c.player_id, BEAST),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), relation='friendly') if cid != SUMMON else None,
            metadata=replace(META, collectible=False)))
    r.register_behavior(P+'auto', lambda c: (CastSpell(c.player_id, CARD, c.source_id, choices='player'),))
    r.register_card(CardDefinition(AUTO, AUTO, CardType.MINION, cost=1, health=4, battlecry=P+'auto', metadata=replace(META, tribes=('beast',))))
    r.register_behavior(P+'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K167 deliberate failure')))
    if mode:
        def watch(c):
            roots = c.state.hand_choice_followups
            if not roots: return ()
            root = roots[-1]
            if c.event.kind == 'card_added_to_hand' and c.event.target_id != root.initial_entity_id: return ()
            if c.event.kind in ('card_played', 'minion_counter_check') and c.event.source_id != root.initial_entity_id: return ()
            if mode == 'counter': return (CounterMinion(dict(c.event.data)['window_id']),)
            if mode == 'terminal': return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
            if mode in ('initial_fail', 'play_fail'): return (InvokeBehavior(P+'fail', c.source_id, 1),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'), ChoiceOption('bad', 'Rollback',
                (InvokeBehavior(P+'fail', c.source_id, 1),))), c.source_id),)
        r.register_behavior(P+'watch', watch)
        event = 'card_added_to_hand' if mode in ('acquire', 'initial_fail') else 'minion_counter_check' if mode == 'counter' else 'card_played'
        r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, durability=4,
            triggers=(TriggerSpec(event, P+'watch'),), metadata=replace(META, collectible=False)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class HikingTrailTests(unittest.TestCase):
    def game(self, hand=(CARD,), mode=None, pool='all'):
        self.mode, self.pool = mode, pool
        extra = dict(weapon_card_id=WATCH) if mode else {}
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=hand, deck=(NONE,)*8, mana=30, max_mana=30, mana_cap=30, **extra),
            PlayerSetup(HERO, deck=(NONE,)*8)), seed=167, generation_context=CONTEXT), registry(mode, pool))
    def first(self, g, cid, zone='hand', pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None, pid=1, entity=None):
        e = self.first(g, cid, pid=pid) if entity is None else g.state.entities[entity]
        g.apply(PlayCard(pid, e.id, target_id=target, position=len(g.state.players[pid].board) if e.kind == CardType.MINION else None))
        return e.id
    def select(self, g, cid=None, key=None):
        q = g.state.pending_choice
        option = next(o for o in q.options if (key is None or o.id == key) and (cid is None or o.card_id == cid))
        g.apply(SelectChoice(q.player_id, q.id, (option.id,))); return option.card_id
    def root(self, g): return g.state.hand_choice_followups[-1]
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); reader = registry(self.mode, self.pool, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved); return other
    def corrupt(self, g, edit):
        saved = deepcopy(g.snapshot()); edit(saved)
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry(self.mode, self.pool, 'reader'))

    def test_a0_complete_raw_primary_face_contract_and_twelve_type_universe(self):
        d = load_batch(); c = registry().card(CARD)
        self.assertEqual((c.name, c.cost, c.on_play), (d['cards'][0]['record']['name'], 1, BODY))
        self.assertEqual(len(d['types']), 12); self.assertIn('draenei', d['types'])

    def test_a1_uses_original_own_types_and_existential_dual_all_candidate_membership(self):
        g = self.game((BEAST, CARD)); self.play(g, BEAST); self.play(g, CARD); root = self.root(g)
        self.assertNotIn('beast', root.request.query.tribes_any)
        eligible = {x.card_id for x in root.available_pool}
        self.assertNotIn(BEAST, eligible); self.assertNotIn(NONE, eligible); self.assertNotIn(FOREIGN, eligible)
        self.assertTrue({D0, DUAL, ALL, MECH} <= eligible); self.portable(g)

    def test_a2_all_types_used_is_proven_empty_without_pool_lookup_or_rng(self):
        g = self.game((ALL, CARD), pool='none'); self.play(g, ALL); before = g._rng.getstate(); self.play(g, CARD)
        self.assertFalse(g.state.hand_choice_followups); self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g._rng.getstate(), before); self.portable(g)

    def test_a3_all_with_original_exclusion_leaves_only_that_unplayed_type(self):
        g = self.game((ALL, EXCLUDE, CARD)); self.play(g, EXCLUDE, self.first(g, ALL).id); self.play(g, ALL); self.play(g, CARD)
        self.assertEqual(self.root(g).request.query.tribes_any, ('dragon',)); self.portable(g)

    def test_a4_hand_type_change_is_frozen_before_play_and_not_read_as_printed(self):
        g = self.game((BEAST, SET, CARD)); self.play(g, SET, self.first(g, BEAST).id); self.play(g, BEAST); self.play(g, CARD)
        root = self.root(g); self.assertNotIn('dragon', root.request.query.tribes_any); self.assertIn('beast', root.request.query.tribes_any)
        self.portable(g)

    def test_a5_ordinary_summons_are_not_submitted_minion_type_history(self):
        g = self.game((SUMMON, CARD)); self.play(g, SUMMON); self.play(g, CARD)
        self.assertIn('beast', self.root(g).request.query.tribes_any); self.portable(g)

    def test_a6_nested_map_sees_current_committed_not_yet_completed_minion(self):
        g = self.game((AUTO,)); self.play(g, AUTO)
        self.assertFalse(g.state.play_history[0].completed)
        self.assertNotIn('beast', self.root(g).request.query.tribes_any); self.portable(g)

    def test_a7_unknown_or_unreviewed_history_explicitly_rolls_back_map_payment(self):
        for cid, message in ((UNKNOWN, 'Unknown submitted minion types'), (FUTURE, 'unreviewed submitted minion type')):
            with self.subTest(cid=cid):
                g = self.game((cid, CARD)); self.play(g, cid); saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, message): self.play(g, CARD)
                self.assertEqual(g.snapshot(), saved)

    def test_a8_all_eligible_unadapted_or_unknown_pool_members_fail_before_sampling(self):
        for pool in ('unadapted', 'unknown'):
            with self.subTest(pool=pool):
                g = self.game(pool=pool); saved = g.snapshot()
                with self.assertRaises(ResolutionError): self.play(g, CARD)
                self.assertEqual(g.snapshot(), saved)
        g = self.game(pool='foreign_missing'); self.play(g, CARD)
        self.assertNotIn(MISSING, {x.card_id for x in self.root(g).available_pool})

    def test_a9_known_empty_eligible_pool_has_native_empty_record_and_no_rng(self):
        g = self.game((BEAST, CARD), pool='beasts'); self.play(g, BEAST); before = g._rng.getstate(); self.play(g, CARD)
        self.assertEqual(self.root(g).status, 'empty'); self.assertEqual(g._rng.getstate(), before); self.portable(g)

    def test_b0_real_selected_minion_reopens_original_other_choices_without_new_type_filter(self):
        g = self.game(pool='dragons'); self.play(g, CARD); self.select(g, D0)
        root = self.root(g); initial = root.initial_entity_id; before = g._rng.getstate()
        self.play(g, D0, entity=initial)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {D1, D2})
        self.assertEqual(self.root(g).trigger_play_id, g.state.play_history[-1].id)
        other = self.portable(g); self.select(g, D1); self.select(other, D1)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g._rng.getstate(), before)
        self.assertEqual(self.root(g).status, 'completed'); self.assertEqual(g.state.players[1].mana, 28)

    def test_b1_preexisting_same_face_does_not_borrow_original_physical_followup(self):
        g = self.game((D0, CARD), pool='dragons'); original = self.first(g, D0).id
        self.play(g, CARD); self.select(g, D0); selected = self.root(g).initial_entity_id
        self.play(g, D0, entity=original); self.assertIsNone(g.state.pending_choice); self.assertEqual(self.root(g).status, 'armed')
        self.play(g, D0, entity=selected); self.assertIsNotNone(g.state.pending_choice); self.portable(g)

    def test_b2_original_leaves_and_reenters_hand_without_rearming_old_residence(self):
        g = self.game((CARD, REENTER), pool='dragons'); self.play(g, CARD); self.select(g, D0)
        entity = self.root(g).initial_entity_id; old = self.root(g).hand_entry_id
        self.play(g, REENTER, entity); self.assertNotEqual(g.state.entities[entity].hand_entry_id, old)
        self.play(g, D0, entity=entity); self.assertEqual(self.root(g).status, 'lost'); self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_b3_original_global_turn_end_expires_reward_even_when_card_stays_in_hand(self):
        g = self.game(pool='dragons'); self.play(g, CARD); self.select(g, D0)
        entity = self.root(g).initial_entity_id; g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, D0, entity=entity); self.assertEqual(self.root(g).status, 'expired'); self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_b4_actual_hand_acquisition_wait_is_bound_before_observer_and_private_to_owner(self):
        g = self.game(mode='acquire', pool='dragons'); self.play(g, CARD); self.select(g, D0)
        self.assertEqual(self.root(g).status, 'armed'); other = self.portable(g)
        public = json.dumps(g.for_player(2).observe()) + json.dumps(g.player_events(2))
        for hidden in (D0, D1, D2, 'hand_choice_followups', 'rng_before', 'available_pool'): self.assertNotIn(hidden, public)
        self.select(g, key='ok'); self.select(other, key='ok'); self.assertEqual(g.snapshot(), other.snapshot())

    def test_b5_failed_initial_acquisition_rolls_back_selection_creation_and_rng(self):
        g = self.game(mode='initial_fail', pool='dragons'); self.play(g, CARD); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K167 deliberate failure'): self.select(g, D0)
        self.assertEqual(g.snapshot(), saved)

    def test_b6_consumed_waiting_reward_restores_and_failed_resume_does_not_pay_again(self):
        g = self.game(mode='play_wait', pool='dragons'); self.play(g, CARD); self.select(g, D0); self.play(g, D0)
        self.assertEqual(self.root(g).status, 'reward_queued'); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'K167 deliberate failure'): self.select(g, key='bad')
        self.assertEqual(g.snapshot(), saved); self.select(g, key='ok'); self.select(other, key='ok')
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.root(g).status, 'reward_offered')

    def test_b7_failed_play_reaction_rolls_back_payment_history_and_armed_followup(self):
        g = self.game(mode='play_fail', pool='dragons'); self.play(g, CARD); self.select(g, D0); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K167 deliberate failure'): self.play(g, D0)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(self.root(g).status, 'armed')

    def test_c0_countered_completed_original_minion_uses_existing_once_policy(self):
        g = self.game(mode='counter', pool='dragons'); self.play(g, CARD); self.select(g, D0); self.play(g, D0)
        self.assertTrue(g.state.play_history[-1].countered); self.assertEqual(self.root(g).status, 'reward_offered'); self.portable(g)

    def test_c1_second_player_has_separate_history_and_original_recipient(self):
        self.mode, self.pool = None, 'all'
        g = Game.from_scenario(Scenario((PlayerSetup(HERO, deck=(NONE,)*5),
            PlayerSetup(HERO, hand=(BEAST, CARD), deck=(NONE,)*5, mana=20, max_mana=20, mana_cap=20)),
            active_player=2, generation_context=CONTEXT), registry())
        self.play(g, BEAST, pid=2); self.play(g, CARD, pid=2)
        self.assertNotIn('beast', self.root(g).request.query.tribes_any); self.assertEqual(g.state.pending_choice.player_id, 2); self.portable(g)

    def test_c2_tampered_original_candidates_or_physical_hand_identity_are_rejected(self):
        g = self.game(pool='dragons'); self.play(g, CARD); self.select(g, D0)
        self.corrupt(g, lambda s: s['state']['hand_choice_followups'][0].update(hand_entry_id=999))
        self.corrupt(g, lambda s: s['state']['hand_choice_followups'][0]['offers'].pop())
        self.portable(g)

    def test_c3_terminal_during_original_play_cancels_owed_remaining_choice(self):
        g = self.game(mode='terminal', pool='dragons'); self.play(g, CARD); self.select(g, D0); self.play(g, D0)
        self.assertEqual(g.state.status, 'finished'); self.assertEqual(self.root(g).status, 'ended'); self.portable(g)


if __name__ == '__main__': unittest.main()
