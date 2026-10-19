"""Actual Shaladrassil: original higher-cost facts and all five ordered rewards."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.shaladrassil_cards import CORRUPTED, DREAMS, ROOT, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.effects import (AddToHand, ChoiceOption, InvokeBehavior,
    RandomDamage, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.held_higher_cost import ability
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CostSpec, HandProgressSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.zones import CardReference, CopyCard, ModifyStoredCost, MoveCard
from hs_sim.targets import canonical_digest

P = 'shaladrassil.test.'
HIGH, EQUAL, LOW, DISCOUNT, COPY, BASE, OUT, IN, AUTO, RECAST, HISTORY, RETURN, CREATE = (
    P+x for x in ('high', 'equal', 'low', 'discount', 'copy', 'base', 'out', 'in',
                 'auto', 'recast', 'history', 'return', 'create'))
WAIT, COMMIT, COUNTER, COUNTER_HIGH = (P+x for x in ('wait', 'commit', 'counter', 'counter_high'))
FILL = 'CS2_182'


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    meta = replace(r.card(FILL).metadata, deck_identity=None)
    def ref(c): return CardReference.capture(c.state.entities[c.target_id])
    def selected_cast(c):
        return next(x for x in c.state.cast_history if x.card_id == ROOT)
    def historical(c):
        selected = next(x.id for x in c.state.play_history if x.card_id == ROOT)
        query = WholeCardHistoryQuery(c.player_id, c.play.id, kinds=(CardType.SPELL,),
            exclude_play_ids=tuple(x.id for x in c.state.play_history
                if x.id < c.play.id and x.id != selected))
        return (ReplayWholeCards(c.player_id, c.source_id, query),)
    bodies = {
        HIGH: lambda c: (), EQUAL: lambda c: (), LOW: lambda c: (),
        DISCOUNT: lambda c: (ModifyStoredCost(ref(c), CostSpec(set_to=0), c.source_id),),
        COPY: lambda c: (CopyCard(ref(c), c.player_id, mode='current', source_id=c.source_id),),
        BASE: lambda c: (CopyCard(ref(c), c.player_id, mode='base', source_id=c.source_id),),
        OUT: lambda c: (MoveCard(ref(c), c.player_id, Zone.DECK, reset=True, source_id=c.source_id),),
        IN: lambda c: (MoveCard(ref(c), c.player_id, Zone.HAND, source_id=c.source_id),),
        AUTO: lambda c: (CastStoredSpell(ref(c), c.player_id, c.source_id),),
        RECAST: lambda c: (RecastSpell(c.player_id, selected_cast(c).id, c.source_id),),
        HISTORY: historical,
        RETURN: lambda c: (ReturnSpentSpell(SourceAllocationFact.capture(c.state,
            c.state.entities[selected_cast(c).source_id]), c.player_id),),
        CREATE: lambda c: (AddToHand(c.player_id, ROOT, c.source_id),),
    }
    for name, body in bodies.items():
        r.register_behavior(name, body)
        kw = {}
        if name in (DISCOUNT, COPY, BASE, OUT, IN, AUTO):
            kw['targeting'] = TargetSpec(zones=(Zone.DECK,) if name == IN else (Zone.HAND,),
                                       kinds=(CardType.SPELL,), relation='friendly')
        cost = {HIGH: 9, EQUAL: 8, LOW: 1, CREATE: 9}.get(name, 0)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost, on_play=name,
                                       metadata=meta, **kw))
    def fail(c): raise ResolutionError('Shaladrassil deliberate rollback')
    r.register_behavior(P+'fail', fail)
    for name in (WAIT, COMMIT, COUNTER, COUNTER_HIGH):
        def watch(c, mode=name):
            source = c.state.entities.get(c.event.source_id)
            if mode == WAIT:
                target = c.state.entities.get(c.event.target_id)
                if target is None or target.card_id not in (DREAMS[0], CORRUPTED[0]): return ()
            elif source is None or source.card_id != (ROOT if mode == COUNTER else HIGH):
                return ()
            if mode in (COUNTER, COUNTER_HIGH):
                return (CounterSpell(dict(c.event.data)['window_id']),)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('fail', 'Fail', (RandomDamage((c.state.players[2].hero_id,), 1, c.source_id),
                    InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
        r.register_behavior(name, watch)
        event = 'card_added_to_hand' if name == WAIT else 'card_committed'
        r.register_card(CardDefinition(name, name, CardType.MINION, health=9, metadata=meta,
                                       triggers=(TriggerSpec(event, name),)))
    r.validate(); r.freeze()
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class ShaladrassilTests(unittest.TestCase):
    def game(self, hand=(ROOT,), *, board=(), other_hand=(), seed=242846):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,)*12,
                        mana=30, max_mana=10, temporary_mana=20),
            PlayerSetup('HERO_08', hand=other_hand, deck=(FILL,)*12,
                        mana=30, max_mana=10, temporary_mana=20)), seed=seed), registry('writer'))
    def source(self, g, cid=ROOT, pid=None):
        pid = pid or g.state.active_player
        return next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
    def play(self, g, cid=ROOT, target=None, *, eid=None):
        return g.apply(PlayCard(g.state.active_player, eid or self.source(g, cid), target))
    def completed(self, g, eid): return ability(g.state.entities[eid]).consumed
    def rewards(self, g, result):
        return tuple(g.state.entities[e.target_id].card_id for e in result.events
            if e.kind == 'card_created' and e.target_id in g.state.entities and
               g.state.entities[e.target_id].card_id in DREAMS+CORRUPTED)
    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        return g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        r = registry('reader' if g.registry is registry('writer') else 'writer')
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, r)
        for candidate in (other, g.clone(), replay(build_replay(g), r)):
            self.assertEqual(candidate.snapshot(), saved)
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for private in ('held_higher_cost', 'higher_cost:', 'corrupt_candidates', 'resolution_frame', 'rng_state'):
                self.assertNotIn(private, wire)
        return other

    def test_a00_complete_source_and_ten_existing_exact_dream_definitions(self):
        data = load_batch(); r = registry('writer')
        self.assertEqual(len(data['cards'])+len(data['existing_dependencies'])+len(data['evidence_only']), 14)
        self.assertFalse(data['dependencies'])
        for row in data['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))), row['definition_sha256'])
        card = r.card(ROOT)
        self.assertEqual((card.cost, card.hand_progress.kind, card.hand_progress.keyword), (8, 'higher_cost_play', None))
        self.assertNotIn(Keyword.CORRUPT, card.keywords)

    def test_b00_normal_five_unique_dreams_pay_eight_once_without_player_choice(self):
        g = self.game(); result = self.play(g)
        self.assertEqual(set(self.rewards(g, result)), set(DREAMS))
        self.assertEqual(len(g.state.players[1].hand), 5); self.assertEqual(g.state.players[1].mana, 22)
        self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.cast_history[-1].held_higher_cost.completed)
        self.portable(g)

    def test_b01_completed_original_higher_cost_play_gets_all_corrupted_dreams(self):
        g = self.game((ROOT, HIGH)); source = self.source(g)
        self.play(g, HIGH); self.assertTrue(self.completed(g, source))
        self.assertNotIn(Keyword.CORRUPT, g.state.entities[source].keywords)
        result = self.play(g); self.assertEqual(set(self.rewards(g, result)), set(CORRUPTED))
        self.assertEqual(g.state.players[1].mana, 13)
        self.assertTrue(g.state.play_history[-1].held_higher_cost.completed)
        self.assertEqual(g.state.cast_history[-1].held_higher_cost, g.state.play_history[-1].held_higher_cost)
        self.portable(g)

    def test_b02_equal_or_lower_cost_and_opponent_play_do_not_qualify(self):
        for cid in (EQUAL, LOW):
            with self.subTest(cid=cid):
                g = self.game((ROOT, cid)); source = self.source(g)
                self.play(g, cid); self.assertFalse(self.completed(g, source))
                self.assertEqual(set(self.rewards(g, self.play(g))), set(DREAMS))
        g = self.game((ROOT,), other_hand=(HIGH,))
        source = self.source(g); g.apply(EndTurn(1)); self.play(g, HIGH)
        self.assertFalse(self.completed(g, source)); self.portable(g)

    def test_b03_actual_discounted_paid_price_controls_original_comparison(self):
        g = self.game((ROOT, HIGH, DISCOUNT)); source = self.source(g)
        self.play(g, DISCOUNT, self.source(g, HIGH)); self.play(g, HIGH)
        self.assertEqual(g.state.play_history[-1].cost, 0)
        self.assertFalse(self.completed(g, source))
        self.assertEqual(set(self.rewards(g, self.play(g))), set(DREAMS))

    def test_b04_current_held_discount_and_multiple_physical_sources(self):
        g = self.game((ROOT, ROOT, DISCOUNT, LOW)); sources = tuple(g.state.players[1].hand[:2])
        self.play(g, DISCOUNT, sources[0]); self.play(g, LOW)
        self.assertTrue(self.completed(g, sources[0])); self.assertFalse(self.completed(g, sources[1]))
        self.assertEqual(set(self.rewards(g, self.play(g, eid=sources[0]))), set(CORRUPTED))
        self.assertEqual(set(self.rewards(g, self.play(g, eid=sources[1]))), set(DREAMS))

    def test_b05_card_acquired_by_higher_cost_payload_was_not_held_at_submission(self):
        g = self.game((CREATE,)); self.play(g, CREATE); source = self.source(g)
        self.assertFalse(self.completed(g, source))
        self.assertEqual(set(self.rewards(g, self.play(g))), set(DREAMS)); self.portable(g)

    def test_b06_only_completed_play_advances_and_commit_wait_restores(self):
        g = self.game((ROOT, HIGH), board=(COMMIT,)); source = self.source(g)
        self.play(g, HIGH); self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(self.completed(g, source)); g = self.portable(g)
        self.choose(g); self.assertTrue(self.completed(g, source))
        self.assertEqual(set(self.rewards(g, self.play(g))), set(CORRUPTED)); self.portable(g)

    def test_c00_current_copy_inherits_condition_base_copy_does_not(self):
        g = self.game((ROOT, HIGH, COPY, BASE)); source = self.source(g)
        self.play(g, HIGH); self.play(g, COPY, source); current = g.state.players[1].hand[-1]
        self.play(g, BASE, source); base = g.state.players[1].hand[-1]
        self.assertTrue(self.completed(g, current)); self.assertFalse(self.completed(g, base))
        self.assertEqual(ability(g.state.entities[current]).progress_keys, ability(g.state.entities[source]).progress_keys)
        self.assertEqual(set(self.rewards(g, self.play(g, eid=current))), set(CORRUPTED))
        self.portable(g)

    def test_c01_physical_hand_reentry_resets_original_condition(self):
        g = self.game((ROOT, HIGH, OUT, IN)); source = self.source(g)
        self.play(g, HIGH); self.assertTrue(self.completed(g, source))
        self.play(g, OUT, source); self.play(g, IN, source)
        self.assertFalse(self.completed(g, source))
        self.assertEqual(set(self.rewards(g, self.play(g))), set(DREAMS)); self.portable(g)

    def test_d00_both_reward_sets_use_complete_random_order_including_full_hand_burns(self):
        orders = set()
        for high in (False, True):
            g = self.game((ROOT, HIGH) if high else (ROOT,), seed=19)
            if high: self.play(g, HIGH)
            result = self.play(g); order = self.rewards(g, result)
            expected = CORRUPTED if high else DREAMS
            self.assertEqual(set(order), set(expected)); self.assertNotEqual(order, expected)
            orders.add(order)
            full = self.game((ROOT, HIGH)+(FILL,)*8 if high else (ROOT,)+(FILL,)*9, seed=19)
            if high: self.play(full, HIGH)
            result = self.play(full)
            self.assertEqual(self.rewards(full, result), order)
            fit = 2 if high else 1
            created = tuple(full.state.entities[i].card_id for i in full.state.players[1].hand if full.state.entities[i].card_id in expected)
            self.assertEqual(created, order[:fit]); self.assertEqual(len(full.state.players[1].hand), 10)
            self.portable(full)
        self.assertEqual(len(orders), 2)

    def test_d01_notification_wait_preserves_original_order_condition_rng_and_replay(self):
        g = self.game((ROOT, HIGH), board=(WAIT,)); self.play(g, HIGH)
        self.play(g); self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(g.state.cast_history[-1].held_higher_cost.completed)
        g = self.portable(g); self.choose(g)
        self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand}, set(CORRUPTED))
        self.portable(g)

    def test_d02_failed_notification_choice_rolls_back_rng_order_and_all_condition_facts(self):
        g = self.game((ROOT, HIGH), board=(WAIT,)); self.play(g, HIGH); self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.portable(g)

    def test_e00_countered_source_keeps_submitted_fact_without_creating_rewards(self):
        g = self.game((ROOT, HIGH), board=(COUNTER,)); self.play(g, HIGH)
        result = self.play(g)
        self.assertFalse(self.rewards(g, result)); self.assertTrue(g.state.cast_history[-1].held_higher_cost.completed)
        self.assertEqual(g.state.cast_history[-1].failure, 'countered'); self.portable(g)

    def test_e01_countered_higher_cost_card_still_counts_as_completed_hand_play(self):
        g = self.game((ROOT, HIGH), board=(COUNTER_HIGH,)); source = self.source(g)
        self.play(g, HIGH); self.assertTrue(g.state.play_history[-1].countered)
        self.assertTrue(self.completed(g, source))
        self.assertEqual(set(self.rewards(g, self.play(g))), set(CORRUPTED)); self.portable(g)

    def test_e02_automatic_original_held_source_uses_earned_condition_without_hand_payment(self):
        for high in (False, True):
            with self.subTest(high=high):
                g = self.game((ROOT, HIGH, AUTO) if high else (ROOT, AUTO)); source = self.source(g)
                if high: self.play(g, HIGH)
                mana = g.state.players[1].mana
                self.assertEqual(set(self.rewards(g, self.play(g, AUTO, source))), set(CORRUPTED if high else DREAMS))
                self.assertEqual(g.state.players[1].mana, mana); self.portable(g)

    def test_f00_original_cast_and_whole_card_replay_keep_pre_return_condition(self):
        for driver in (RECAST, HISTORY):
            with self.subTest(driver=driver):
                g = self.game((ROOT, HIGH, RETURN, driver)); source = self.source(g)
                self.play(g); self.assertFalse(g.state.cast_history[0].held_higher_cost.completed)
                self.play(g, RETURN); self.play(g, HIGH); self.assertTrue(self.completed(g, source))
                self.assertEqual(set(self.rewards(g, self.play(g, driver))), set(DREAMS))
                self.assertFalse(g.state.cast_history[-1].held_higher_cost.completed); self.portable(g)

    def test_f01_original_earned_cast_and_whole_card_replay_survive_later_hand_reset(self):
        for driver in (RECAST, HISTORY):
            with self.subTest(driver=driver):
                g = self.game((ROOT, HIGH, RETURN, driver)); source = self.source(g)
                self.play(g, HIGH); self.play(g); self.play(g, RETURN)
                self.assertFalse(self.completed(g, source))
                self.assertEqual(set(self.rewards(g, self.play(g, driver))), set(CORRUPTED))
                self.assertTrue(g.state.cast_history[-1].held_higher_cost.completed); self.portable(g)

    def test_f02_second_player_has_its_own_original_comparison_and_rewards(self):
        g = self.game(other_hand=(ROOT, HIGH)); g.apply(EndTurn(1))
        self.play(g, HIGH)
        # Refresh the real owner turn; no direct state or resource mutation.
        g.apply(EndTurn(2)); g.apply(EndTurn(1))
        self.assertEqual(set(self.rewards(g, self.play(g))), set(CORRUPTED)); self.portable(g)

    def test_g00_finite_declaration_rejects_unrelated_payloads_and_old_schema(self):
        for kw in ({'goal': 2}, {'zone': Zone.DECK}, {'on_complete': 'always'}, {'condition_id': 'other'}):
            with self.assertRaises(ValueError): HandProgressSpec('higher_cost_play', **kw)
        g = self.game(); saved = g.snapshot(); saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry('reader'))

    def test_g01_forged_live_witness_and_missing_original_play_cast_facts_are_rejected(self):
        g = self.game((ROOT, HIGH)); source = self.source(g); self.play(g, HIGH)
        saved = g.snapshot()
        rows = saved['state']['entities'].values() if isinstance(saved['state']['entities'], dict) else saved['state']['entities']
        row = next(e for e in rows if e['id'] == source)
        a = next(a for a in row['abilities'] if a['kind'] == 'hand_progress')
        parts = a['progress_keys'][0].split(':'); parts[3] = str(int(parts[3])+1)
        a['progress_keys'][0] = ':'.join(parts)
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry('reader'))
        self.play(g)
        for kind in ('play_history', 'cast_history'):
            saved = g.snapshot(); saved['state'][kind][-1]['held_higher_cost'] = None
            with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry('reader'))


if __name__ == '__main__': unittest.main()
