"""Full local role inventories through their actual paid native producers."""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
import tempfile
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_reference_pools import load_batch, local_pools, EXCLUDED
from hs_sim.engine import Game, IllegalAction, Keyword, PlayerSetup, ResolutionError, Scenario, Zone
from hs_sim.engine.crafted_faces import CraftedMinionRecipe
from hs_sim.engine.crafted_offers import CraftMinion, ResolveCraft, candidates
from hs_sim.engine.pools import sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.school_freeze import locked
from hs_sim.local_pool_format import build_cn37_local_pool_format, load_bindings
from hs_sim.targets import TargetValidationError

BEETLE, PENGUIN, MAMMOTH = 'CORE_LOOT_413', 'ICC_023', 'AV_128'
FIRE, KILL, WISP = 'CORE_CS2_029', 'CATA_EVENT_402', 'CORE_CS2_231'


@lru_cache(None)
def format_for(role='writer'):
    return build_cn37_local_pool_format()


def fixture(mode=None, role='writer'):
    if mode is not None:
        raise ValueError('Unknown Zombeast binding fixture mode')
    return format_for(role).registry


@lru_cache(None)
def seed_for(first, second):
    fmt = format_for(); r = fmt.registry
    spec = CraftMinion(1, TEMPLATE, FIRST, SECOND, 1, max_part_cost=5)
    rows = candidates(r, fmt.context, spec)
    partners = candidates(r, fmt.context, spec, first)
    for seed in range(10000):
        rng = Random(seed)
        if first in sample_candidates(rng, rows, 3, replacement=False) and second in sample_candidates(rng, partners, 3, replacement=False):
            return seed
    raise AssertionError('No deterministic full-inventory seed for the requested pair')


class ZombeastRolePoolTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)
    mode = None

    def game(self, hand=(TAMER,), *, player=1, first=BEETLE, second=PENGUIN, fmt=None):
        fmt = format_for() if fmt is None else fmt
        players = tuple(PlayerSetup('HERO_05' if p == player else 'HERO_08',
            hand=hand if p == player else (), deck=('CORE_EX1_028',)*8,
            mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player,
            seed=seed_for(first, second), generation_context=fmt.context), fmt.registry)

    def offer(self, g):
        return next(e.offer for option in g._frame.options for e in option.effects if type(e) is ResolveCraft)

    def pick(self, g, cid):
        option = next(option for option in g._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in option.effects))
        self.choose(g, option.id)

    def check_offer(self, g, stage, player=1):
        offer = self.offer(g); data, ref = load_batch()
        expected = ref['first_reference_ids'] if stage == 1 else [
            cid for cid in ref['second_reference_ids'] if cid != EXCLUDED]
        self.assertEqual(offer.candidates, tuple(sorted(expected)))
        self.assertEqual((offer.stage, offer.spec.max_part_cost, offer.spec.max_total_cost), (stage, 5, 10))
        self.assertEqual(g.state.pending_choice.player_id, player)
        rng = Random(); rng.setstate(offer.rng_before)
        rows = candidates(g.registry, g._generation_context, offer.spec, offer.first_card_id)
        self.assertEqual(sample_candidates(rng, rows, 3, replacement=False), offer.offered)
        self.assertEqual((rng.getstate(), g._rng.getstate()), (offer.rng_after, offer.rng_after))
        self.assertNotIn(EXCLUDED, offer.candidates)
        return offer

    def test_independent_reference_preserves_roles_exclusion_full_echo_metadata_and_local_uncertainty(self):
        data, reference = load_batch(); fmt = format_for(); r = fmt.registry
        for role in data['roles']:
            pool = r.pool(role['pool_id'], fmt.context)
            self.assertEqual(tuple(m.card_id for m in pool.members), tuple(reference[role['reference_field']]))
            self.assertEqual(tuple(m.weight for m in pool.members), (1,)*len(pool.members))
            self.assertEqual(pool.excluded_card_ids, tuple(role['excluded_card_ids']))
            self.assertTrue(pool.complete)
        self.assertEqual(set(r.pool_card(EXCLUDED).keywords), {Keyword.ECHO, Keyword.RUSH})
        self.assertNotIn(EXCLUDED, r.cards); self.assertNotIn(EXCLUDED, r.crafted_minion_parts)
        self.assertEqual(len(data['native_card_pins']), 71)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(fmt.formal_pool_complete)
        self.assertFalse(data['cn_calibrated']); self.assertFalse(data['source_equivalence_confirmed'])
        self.assertFalse(reference['runtime_bindings_added'])  # immutable source artifact
        self.assertEqual(load_bindings()['unresolved_pool_ids'], [])

    def test_all_declared_eligible_faces_resolve_without_coverage_filter_and_keep_zero_and_ten_costs(self):
        fmt = format_for(); r = fmt.registry
        spec = CraftMinion(1, TEMPLATE, FIRST, SECOND, 1, max_part_cost=5)
        first = candidates(r, fmt.context, spec); pairs = 0; costs = set()
        self.assertEqual(len(first), 34)
        for a in first:
            partners = candidates(r, fmt.context, spec, a.card_id)
            self.assertEqual(len(partners), 37)
            for z in partners:
                card = r.card(CraftedMinionRecipe(TEMPLATE, a.card_id, z.card_id).card_id)
                self.assertEqual(card.cost, r.card(a.card_id).cost+r.card(z.card_id).cost)
                self.assertEqual(card.attack, r.card(a.card_id).attack+r.card(z.card_id).attack)
                self.assertEqual(card.health, r.card(a.card_id).health+r.card(z.card_id).health)
                costs.add(card.cost); pairs += 1
        self.assertEqual(pairs, 1258); self.assertIn(10, costs)
        self.assertEqual(r.pool_card(PENGUIN).cost, 0)

    def test_both_actors_real_paid_tamer_uses_full_menus_zero_cost_part_and_native_deathrattle(self):
        recipe = CraftedMinionRecipe(TEMPLATE, BEETLE, PENGUIN)
        for player in (1, 2):
            with self.subTest(player=player):
                g = self.game((TAMER, KILL), player=player)
                source = self.play(g, TAMER, player=player); self.check_offer(g, 1, player)
                self.assertEqual(g.state.players[player].mana, 29)
                self.pick(g, BEETLE); self.check_offer(g, 2, player); self.pick(g, PENGUIN)
                made = self.entity(g, recipe.card_id, player).id
                self.assertEqual(g.state.entities[made].components, (BEETLE, PENGUIN))
                self.play(g, recipe.card_id, player=player)
                self.assertEqual(g.state.players[player].mana, 27)
                self.assertEqual((g.state.entities[made].attack, g.state.entities[made].health), (3, 4))
                self.play(g, KILL, made, player)
                self.assertEqual(g.state.entities[made].zone, Zone.GRAVEYARD)
                self.assertEqual(g.state.entities[g.state.players[player].hero_id].armor, 3)
                self.assertEqual(g.state.entities[source].zone, Zone.BOARD)

    def test_each_full_menu_restores_clone_and_replays_then_continues_same_selection_and_rng(self):
        g = self.game(); self.play(g, TAMER)
        for cid, stage in ((BEETLE, 1), (PENGUIN, 2)):
            self.check_offer(g, stage); restored = self.portable(g)
            self.pick(g, cid); self.pick(restored, cid)
            self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertIsNone(g.state.pending_choice)

    def test_actual_sidequest_needs_three_physical_plays_and_uses_same_full_roles_with_only_reward_discount(self):
        g = self.game((QUEST, PENGUIN, PENGUIN, WISP)); self.play(g, QUEST)
        for cid in (PENGUIN, PENGUIN):
            self.play(g, cid); self.assertIsNone(g.state.pending_choice)
        self.play(g, WISP); offer = self.check_offer(g, 1)
        self.assertEqual(offer.discount, 3); self.pick(g, BEETLE); self.check_offer(g, 2)
        restored = self.portable(g); self.pick(g, PENGUIN); self.pick(restored, PENGUIN)
        self.assertEqual(g.snapshot(), restored.snapshot())
        cid = CraftedMinionRecipe(TEMPLATE, BEETLE, PENGUIN).card_id
        self.play(g, cid); self.assertEqual(g.state.play_history[-1].cost, 0)
        self.assertEqual(g.state.players[1].mana, 29)

    def test_frozen_mammoth_from_full_real_offers_keeps_native_gate_until_successful_fire(self):
        g = self.game((TAMER, FIRE), second=MAMMOTH); self.play(g, TAMER)
        self.check_offer(g, 1); self.pick(g, BEETLE); self.check_offer(g, 2); self.pick(g, MAMMOTH)
        cid = CraftedMinionRecipe(TEMPLATE, BEETLE, MAMMOTH).card_id
        eid = self.play(g, cid); self.assertTrue(g.state.entities[eid].frozen); self.assertTrue(locked(g.state.entities[eid]))
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health), (8, 10))
        self.play(g, FIRE, g.state.players[2].hero_id)
        self.assertFalse(g.state.entities[eid].frozen); self.assertFalse(locked(g.state.entities[eid]))
        self.assertEqual(g.state.players[1].mana, 19)

    def test_late_native_face_or_adapter_failure_adds_no_metadata_and_cannot_crop_inventory(self):
        for mode in ('face', 'adapter'):
            fmt = build_cn37_local_pool_format(); r = fmt.registry
            del r._pool_cards[EXCLUDED]
            data, reference = load_batch(); cid = data['native_card_pins'][-1]['card_id']
            if mode == 'face': r._cards[cid] = replace(r.card(cid), attack=r.card(cid).attack+1)
            else: r._crafted_minion_parts.remove(cid)
            before = (dict(r.pool_cards), dict(r.pools))
            with self.assertRaises(TargetValidationError): local_pools(r, fmt.context)
            self.assertEqual((dict(r.pool_cards), dict(r.pools)), before)
            self.assertNotIn(EXCLUDED, r.pool_cards)
            self.assertEqual(len(data['roles'][1]['member_ids']), 38)

    def test_runtime_missing_native_adapter_rolls_back_paid_tamer_without_dropping_member_or_rng(self):
        fmt = build_cn37_local_pool_format(); r = fmt.registry
        r._crafted_minion_parts.remove(MAMMOTH)
        g = self.game(fmt=fmt); before = g.snapshot(); rng = g._rng.getstate()
        with self.assertRaises(ResolutionError): self.play(g, TAMER)
        self.assertEqual(g.snapshot(), before); self.assertEqual(g._rng.getstate(), rng)
        self.assertIn(MAMMOTH, [m.card_id for m in r.pool(SECOND, fmt.context).members])

    def test_runtime_missing_native_adapter_rolls_back_actual_third_quest_play_and_reward(self):
        fmt = build_cn37_local_pool_format(); fmt.registry._crafted_minion_parts.remove(MAMMOTH)
        g = self.game((QUEST, PENGUIN, PENGUIN, WISP), fmt=fmt)
        for cid in (QUEST, PENGUIN, PENGUIN): self.play(g, cid)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, WISP)
        self.assertEqual(g.snapshot(), before); self.assertIsNone(g.state.pending_choice)

    def test_source_and_bound_manifest_tampering_fail_without_silent_role_substitution(self):
        data, reference = load_batch()
        for name, value, target in (('reference', reference, 'REFERENCE_PATH'), ('binding', data, 'BATCH_PATH')):
            altered = json.loads(json.dumps(value))
            if name == 'reference': altered['second_reference_ids'].remove(MAMMOTH)
            else: altered['roles'][1]['member_ids'].remove(MAMMOTH)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'altered.json'; path.write_text(json.dumps(altered), encoding='utf8')
                with patch('hs_sim.cards.zombeast_reference_pools.'+target, path):
                    with self.assertRaises(TargetValidationError): load_batch()

    def test_invalid_second_choice_is_atomic_and_private_inventory_stays_out_of_player_views(self):
        g = self.game(); self.play(g, TAMER); self.pick(g, BEETLE); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.choose(g, 'not-an-offered-ingredient')
        self.assertEqual(g.snapshot(), before)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            for key in ('native_card_pins', 'metadata_only', 'rng_before', 'rng_after', 'resolution_frame', 'candidates'):
                self.assertNotIn('"'+key+'"', view)
        with self.assertRaises(UnsupportedDefinitionError): g.registry.card(EXCLUDED)


if __name__ == '__main__':
    unittest.main()
