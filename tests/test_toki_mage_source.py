"""The complete declared Mage view and original Toki physical-return program."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_champions_of_azeroth import fixture, UNIT, PREFIX
from hs_sim.cards import toki_mage_source as native
from hs_sim.cards.champions_of_azeroth import CHOICES
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import Game, PlayCard, PlayerSetup, ResolutionError, Scenario, SnapshotError
from hs_sim.engine.model import CardClass, Zone
from hs_sim.engine.pools import resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.local_pool_format import ROOT

CARD = native.SOURCE
SEED = 3277
SELECTED = ('WON_113', 'CS2_026', 'CS2_025')


class TokiMageSourceTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(role).registry)

    def game(self, *, watch=None, hand=(CARD,), hero='HERO_08', player=1):
        f = fixture()
        own = PlayerSetup(hero, hand=hand, deck=(UNIT,) * 6,
            mana=60, max_mana=60, mana_cap=60)
        other = PlayerSetup('HERO_08', deck=(UNIT,) * 6,
            board=(PREFIX + watch,) if watch else ())
        return Game.from_scenario(Scenario((own, other) if player == 1 else (other, own),
            active_player=player, seed=SEED, generation_context=f.context), f.registry)

    def plans(self, g, player=1):
        return [e.issued_spell_set for e in g.state.players[player].player_effects
            if e.issued_spell_set is not None]

    def test_complete_181_raw_view_is_recomputed_from_fixed_catalog_without_executable_filter(self):
        d = native.load_batch()
        path = ROOT / d['fixed_catalog']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), d['fixed_catalog_sha256'])
        raw = json.loads(path.read_text(encoding='utf-8'))
        expected = [r for r in raw if r['type'] == 'SPELL' and r['collectible']
            and r['card_set_id'] in d['past_set_policy']['set_ids']
            and set(metadata_from_record(r).classes) & {CardClass.MAGE, CardClass.NEUTRAL}]
        self.assertEqual(expected, [v['record'] for v in d['mage_complete_raw_records']])
        self.assertEqual(len(expected), 181)
        self.assertTrue({'RLK_590', 'WON_113'} <= set(d['mage_member_ids']))
        self.assertFalse(d['membership_uses_executable_coverage'] or d['formal_pool_complete'] or d['cn_calibrated'])

    def test_extended_union_retains_original_201_and_44_prefixes_and_178_actual_candidates(self):
        f = fixture()
        d = native.load_batch()
        pool = f.registry.pool(native.POOL, f.context)
        self.assertEqual([v.card_id for v in pool.members[:201]], d['merged_member_ids'])
        self.assertEqual(len(pool.members),206)
        self.assertEqual([v.card_id for v in pool.members[:44]], d['prior_member_ids'])
        self.assertTrue(all(v.weight == 1 for v in pool.members))
        self.assertFalse(pool.excluded_card_ids)
        rows = resolve_candidates(f.registry, f.context, native.POOL, native.QUERY,
            current_class=CardClass.MAGE, source_card_id=CARD, exclude_source_by_rule=True)
        self.assertEqual([asdict(v) for v in rows], d['actual_members'])
        self.assertEqual(len(rows), 178)
        self.assertEqual(set(d['mage_member_ids']) - {v.card_id for v in rows}, {'SW_450', 'ULD_433', 'UNG_028'})
        native.validate_native(f.registry, d)

    def test_actual_toki_pays_three_and_delivers_original_three_with_complete_candidate_receipt(self):
        g = self.game()
        source = self.play(g, CARD)
        plan, = self.plans(g)
        self.assertEqual(plan.selected, SELECTED)
        self.assertEqual(plan.source_id, source)
        self.assertEqual(len(plan.candidates), 178)
        self.assertEqual([a.card_id for a in plan.allocations], list(SELECTED))
        self.assertEqual(len({a.entity_id for a in plan.allocations}), 3)
        self.assertEqual(g.state.players[1].mana, 57)
        self.portable(g)

    def test_issued_champions_is_really_playable_and_original_source_death_does_not_lose_return(self):
        g = self.game(hand=(CARD, 'CS2_029'))
        source = self.play(g, CARD)
        ids = [a.entity_id for a in self.plans(g)[0].allocations]
        self.play(g, 'CS2_029', source)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        g.apply(PlayCard(1, ids[0]))
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], list(CHOICES))
        self.choose(g, CHOICES[0])
        for eid in ids[1:]:
            g.apply(PlayCard(1, eid))
        self.assertFalse(self.plans(g))
        self.assertEqual(len([i for i in g.state.players[1].hand if g.state.entities[i].card_id == CARD]), 1)
        self.assertEqual(g.state.players[1].mana, 44)
        self.assertEqual(sum(e.kind == 'issued_spell_set_reward_delivered' for e in g.events), 1)
        self.portable(g)

    def test_all_three_full_view_deliveries_suspend_and_resume_without_resampling(self):
        g = self.game(watch='wait')
        self.play(g, CARD)
        restored = self.portable(g)
        for index in range(3):
            plan, = self.plans(g)
            self.assertEqual(plan.selected, SELECTED)
            self.assertEqual(len(plan.allocations), index + 1)
            self.choose(g)
            self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_real_random_delivery_failure_and_waiting_choice_failure_restore_full_state(self):
        g = self.game(watch='fail')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, CARD)
        self.assertEqual(g.snapshot(), before)
        g = self.game(watch='wait')
        self.play(g, CARD)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)

    def test_full_hand_keeps_three_original_allocations_and_burned_names_without_shrinking_pool(self):
        g = self.game(hand=(CARD,) + (UNIT,) * 9)
        self.play(g, CARD)
        plan, = self.plans(g)
        self.assertEqual(plan.selected, SELECTED)
        self.assertEqual([a.zone for a in plan.allocations], [Zone.HAND, Zone.GRAVEYARD, Zone.GRAVEYARD])
        self.assertEqual(len(plan.candidates), 178)
        self.assertEqual(len(g.state.players[1].hand), 10)

    def test_unreviewed_class_remains_closed_with_atomic_real_entry_failure(self):
        f = fixture()
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry, f.context, native.POOL, native.QUERY,
                current_class=CardClass.ROGUE, source_card_id=CARD, exclude_source_by_rule=True)
        g = self.game(hero='HERO_03')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, CARD)
        self.assertEqual(g.snapshot(), before)

    def test_full_hidden_inventory_and_original_member_receipts_stay_out_of_opponent_dto_and_events(self):
        g = self.game(player=2)
        self.play(g, CARD, player=2)
        text = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
        for key in ('WON_113', 'CS2_026', 'CS2_025', 'issued_spell_set', 'native_pins',
                'rng_before', 'acceptance_event', native.POOL):
            self.assertNotIn(key, text)
        self.assertEqual(len(self.plans(g, 2)[0].candidates), 178)
        self.portable(g)

    def test_rehashed_saved_plan_cannot_crop_its_full_original_candidate_inventory(self):
        g = self.game(watch='wait')
        self.play(g, CARD)
        bad = deepcopy(g.snapshot())
        plan = next(e['issued_spell_set'] for e in bad['state']['players']['1']['player_effects']
            if e['issued_spell_set'] is not None)
        plan['candidates'] = plan['candidates'][1:]
        bad['events_hash'] = canonical_hash(bad['events'])
        bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, fixture('independent-reader').registry)
