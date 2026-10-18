"""Actual preselection work survives commitment, rollback and true Retry."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest

from hs_sim.engine import Game, SelectChoice, SnapshotError, Zone
from hs_sim.engine.card_discoveries import PUBLICATION, capture_turn_match, validate_turn_prefix
from hs_sim.engine.discovery_offers import (ACCEPTED, OriginalDiscoveryOffer, decode_offer,
    encode_offer, offer_for_result, unselected_options)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CopyCard
from hs_sim.engine.summon_sources import ResurrectMinion
import test_discovery_delivery_consumers as t
import test_card_discoveries as old


def accepted(g):
    return [e for e in g.events if e.kind == ACCEPTED]


def replace_unselected_recipe(g, offer, selected):
    option = next(o for o in offer.options if o.id not in selected)
    effect, = option.effects
    other = next(cid for cid in effect.offered_card_ids if cid != effect.selection.card_id)
    changed = replace(option, effects=(replace(effect, selection=replace(effect.selection, card_id=other)),))
    value = replace(offer, options=tuple(changed if o.id == option.id else o for o in offer.options))
    raw = encode_offer(g, value)
    assert decode_offer(g, raw) == value
    return raw


class OriginalDiscoveryOfferTests(unittest.TestCase):
    def test_pending_acceptance_keeps_all_original_work_before_any_selection_or_discount(self):
        g = t.game(); t.play(g, t.DISC)
        event, = accepted(g); offer = decode_offer(g, dict(event.data)['original_offer'])
        self.assertEqual((offer.choice, offer.options, offer.on_select),
            (g.state.pending_choice, g._frame.options, g._frame.on_select))
        self.assertEqual((g.state.card_discovery_history, t.completions(g)), ([], []))
        self.assertTrue(all(o.effects[0].choice_result is None for o in offer.options))
        t.portable(self, g)

    def test_gift_commitment_keeps_full_unselected_bindings_and_original_unbound_branches(self):
        g = t.game((t.GIFT,)); t.play(g, t.GIFT)
        raw = dict(accepted(g)[0].data)['original_offer']; original = decode_offer(g, raw)
        t.choose(g, key=g.state.pending_choice.options[0].id)
        row, = g.state.card_discovery_history
        self.assertEqual(row.original_offer, raw)
        self.assertEqual(offer_for_result(g, row.result), original)
        self.assertEqual(len(unselected_options(g, row.result)), 2)
        for option in original.options:
            branch, = option.effects
            self.assertIsNone(branch.choice_result); self.assertIsNone(branch.selection.result)
            self.assertEqual(len(branch.offered_gifts), 3)
            self.assertEqual(len({gift.id for gift in branch.offered_gifts}), 3)
        t.portable(self, g)

    def test_duplicate_physical_faces_keep_distinct_complete_original_references(self):
        g = t.game((t.COPY,), deck=(t.A, t.A, t.B)); before = set(g.state.players[1].deck)
        t.play(g, t.COPY); t.choose(g, t.A)
        row, = g.state.card_discovery_history; offer = offer_for_result(g, row.result)
        recipes = [o.effects[0] for o in offer.options]
        self.assertTrue(all(type(r) is CopyCard for r in recipes))
        self.assertEqual({r.card.entity_id for r in recipes}, before)
        self.assertEqual(len({r.card.card_id for r in recipes}), 2)
        self.assertTrue(all(r.card.zone == Zone.DECK for r in recipes))
        t.portable(self, g)

    def test_two_deferred_same_faces_preserve_each_full_original_menu_and_prior_receipt(self):
        g = t.game((t.ALL,)); t.play(g, t.ALL); t.choose(g, t.A)
        first, = g.state.card_discovery_history; original = first.original_offer
        t.portable(self, g); t.choose(g, t.A)
        one, two = g.state.card_discovery_history
        self.assertEqual(one.original_offer, original); self.assertNotEqual(one.result.choice.id, two.result.choice.id)
        second_offer = offer_for_result(g, two.result)
        for option in second_offer.options:
            self.assertEqual(option.effects[0].batch.selections[0].result, one.result)
        self.assertEqual([len(unselected_options(g, row.result)) for row in (one, two)], [2, 2])

    def test_map_retains_original_followup_links_but_reward_is_an_ordinary_menu(self):
        for source in (t.MAP, t.MAP_TAKE):
            g = t.game((source,)); t.play(g, source); t.choose(g, t.A)
            row, = g.state.card_discovery_history; offer = offer_for_result(g, row.result)
            self.assertEqual({o.effects[0].followup_id for o in offer.options}, {g.state.hand_choice_followups[0].id})
            self.assertTrue(all(o.effects[0].result is None for o in offer.options))
            t.play(g, t.A); self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.EFFECT)
            t.choose(g, t.B); self.assertEqual(len(accepted(g)), 1); t.portable(self, g)

    def test_board_and_selected_original_death_keep_the_actual_original_producer_work(self):
        g = t.game((t.BOARD,)); t.play(g, t.BOARD)
        original = decode_offer(g, dict(accepted(g)[0].data)['original_offer'])
        t.choose(g, t.A); row, = g.state.card_discovery_history
        self.assertEqual(offer_for_result(g, row.result), original); t.portable(self, g)
        g = t.game((t.KILL, t.DEAD), board=(t.CARD, t.A)); target = t.first(g, t.A, 'board').id
        t.play(g, t.KILL, target); t.play(g, t.DEAD)
        original = decode_offer(g, dict(accepted(g)[0].data)['original_offer'])
        self.assertTrue(all(type(o.effects[0]) is ResurrectMinion for o in original.options))
        t.choose(g, t.A); row, = g.state.card_discovery_history
        self.assertEqual(offer_for_result(g, row.result), original); t.portable(self, g)

    def test_automatic_spell_uses_one_shared_original_acceptance_without_a_pending_menu(self):
        g = t.game((t.AUTO,), pid=2); t.play(g, t.AUTO)
        row, = g.state.card_discovery_history; event, = accepted(g)
        self.assertEqual((row.result.choice.player_id, event.player_id), (2, 2))
        self.assertEqual(offer_for_result(g, row.result).choice, row.result.choice)
        self.assertIsNone(g.state.pending_choice); t.portable(self, g)

    def test_failed_acquisition_restores_the_original_open_offer_without_committing_new_work(self):
        g = t.game(mode='fail_acquire'); t.play(g, t.DISC); saved = g.snapshot()
        with self.assertRaises(ResolutionError): t.choose(g, t.A)
        self.assertEqual(g.snapshot(), saved); self.assertEqual(g.state.card_discovery_history, [])
        self.assertEqual(len(accepted(g)), 1); t.portable(self, g, 'fail_acquire')

    def test_generation_generic_menus_and_empty_discovery_do_not_accept_card_offers(self):
        for source in (t.GEN, t.MENU):
            g = t.game((source,)); t.play(g, source)
            if g.state.pending_choice: t.choose(g, t.A)
            self.assertEqual(accepted(g), [])
        g = old.game((old.EMPTY,)); rng = g.snapshot()['rng_state']; old.play(g, old.EMPTY)
        self.assertEqual((accepted(g), g.state.card_discovery_history), ([], []))
        self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_actual_retry_retires_old_acceptance_and_new_offer_keeps_its_own_original_identity(self):
        g = old.game((old.RETRY,)); old.play(g, old.RETRY); old.choose(g, old.A)
        first, = g.state.card_discovery_history; old.portable(self, g)
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ('retry',)))
        self.assertEqual(g.state.card_discovery_history, []); old.portable(self, g)
        old.choose(g, old.B); second, = g.state.card_discovery_history
        self.assertGreater(second.result.choice.id, first.result.choice.id)
        self.assertNotEqual(first.original_offer, second.original_offer)
        self.assertEqual(offer_for_result(g, second.result).choice, second.result.choice); old.portable(self, g)

    def test_full_immutable_cost_prefix_includes_original_offer_materials(self):
        g = t.game(); t.play(g, t.DISC); t.choose(g, t.A)
        fact = capture_turn_match(g.state, 1); row, = fact.records
        validate_turn_prefix(fact, g.state, g.registry)
        changed = replace(fact, records=(replace(row, original_offer=row.original_offer+' '),))
        with self.assertRaises(ValueError): validate_turn_prefix(changed, g.state, g.registry)

    def test_rehashed_committed_recipe_cannot_change_unselected_work_even_with_matching_publication(self):
        g = t.game(); t.play(g, t.DISC); t.choose(g, t.A)
        row, = g.state.card_discovery_history; offer = offer_for_result(g, row.result)
        raw = replace_unselected_recipe(g, offer, row.result.selected_ids)
        changed = replace(row, original_offer=raw); saved = deepcopy(g.snapshot()); count = 0
        def rewrite(value):
            nonlocal count
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == 'original_offer' and child == row.original_offer:
                        value[key] = raw; count += 1
                    else: rewrite(child)
            elif isinstance(value, list):
                for child in value: rewrite(child)
        for key, value in saved.items():
            if key != 'events': rewrite(value)
        self.assertGreater(count, 0)
        for event in saved['events']:
            if event['kind'] == PUBLICATION:
                event['data']['receipt'] = asdict(changed)
                event['data']['receipt_hash'] = canonical_hash(asdict(changed))
        with self.assertRaisesRegex((SnapshotError, ValueError), 'original accepted offer'):
            Game.from_snapshot(t.rehash(saved), t.registry('plain', 'reader'))

    def test_rehashed_waiting_acceptance_cannot_replace_one_original_unselected_branch(self):
        g = t.game(); t.play(g, t.DISC); saved = deepcopy(g.snapshot())
        offer = decode_offer(g, dict(accepted(g)[0].data)['original_offer'])
        raw = replace_unselected_recipe(g, offer, ())
        for event in saved['events']:
            if event['kind'] == ACCEPTED: event['data']['original_offer'] = raw
        with self.assertRaisesRegex((SnapshotError, ValueError), 'original accepted offer'):
            Game.from_snapshot(t.rehash(saved), t.registry('plain', 'reader'))

    def test_rehashed_missing_acceptance_cannot_be_replaced_by_the_committed_publication(self):
        g = t.game(); t.play(g, t.DISC); t.choose(g, t.A); saved = deepcopy(g.snapshot())
        for event in saved['events']:
            if event['kind'] == ACCEPTED: event['kind'] = 'fixture_retired_offer'
        with self.assertRaisesRegex((SnapshotError, ValueError), 'original accepted offer'):
            Game.from_snapshot(t.rehash(saved), t.registry('plain', 'reader'))

    def test_original_work_is_allowlisted_and_complete_and_never_enters_player_information(self):
        g = t.game(); t.play(g, t.DISC)
        offer = decode_offer(g, dict(accepted(g)[0].data)['original_offer'])
        with self.assertRaises(ValueError): replace(offer, options=offer.options[:-1])
        with self.assertRaises(ValueError): replace(offer, choice=replace(offer.choice, purpose=ChoicePurpose.EFFECT))
        raw = json.loads(encode_offer(g, offer)); raw['type'] = 'builtins.eval'
        with self.assertRaises(ValueError): decode_offer(g, json.dumps(raw))
        for phase in range(2):
            for pid in (1, 2):
                visible = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
                for name in ('original_offer', ACCEPTED, 'card_discovery_history', 'resolution_frame'):
                    self.assertNotIn('"'+name+'"', visible)
            if phase == 0: t.choose(g, t.A)
        t.portable(self, g)

    def test_previous_schema_rejects_without_synthesizing_missing_original_options(self):
        g = t.game(); saved = g.snapshot(); saved['schema_version'] = 378
        with self.assertRaises((SnapshotError, ValueError)): Game.from_snapshot(saved, g.registry)


if __name__ == '__main__': unittest.main()
