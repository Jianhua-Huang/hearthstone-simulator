"""Release query scopes reuse static definitions without caching live rules."""
from contextlib import nullcontext
from copy import deepcopy
import unittest
from unittest.mock import patch

from hs_sim.engine import Game,PlayCard
from hs_sim.engine import assembly_materials,assemble_faces,intrinsic_costs,runtime_queries
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.serialization import canonical_hash
import test_assemble_offers as fixtures
from test_performance_frame_metadata import game


class RuntimeQueryTests(unittest.TestCase):
    def test_public_actions_share_static_faces_and_match_uncached_full_query(self):
        recipe=assemble_faces.AssembleRecipe('a','b','top').card_id
        match=fixtures.AssembleOfferTests().game(hand=(recipe,));saved=match.snapshot()
        assembly_materials._owners.clear()
        with patch.object(assemble_faces,'_resolve_face',wraps=assemble_faces._resolve_face)as resolved:
            actual=match.for_player(1).legal_actions()
            self.assertEqual(resolved.call_count,1)
        with patch.object(runtime_queries,'query_materials',lambda match:nullcontext()):
            expected=match.for_player(1).legal_actions()
        self.assertEqual(actual,expected);self.assertEqual(match.snapshot(),saved)

    def test_release_omits_repeated_history_audit_but_debug_and_direct_quotes_keep_it(self):
        match=game();source=match._state.entities[match._state.players[1].hand[0]]
        expected=match.legal_actions()
        with patch.object(intrinsic_costs,'validate_history',side_effect=ValueError('history audit')):
            self.assertEqual(match.legal_actions(),expected)
            with self.assertRaisesRegex(ValueError,'history audit'):quote_cost(match._state,match.registry,source)
            match.runtime_mode='debug'
            with self.assertRaisesRegex(ValueError,'history audit'):match.legal_actions()
        self.assertTrue(runtime_queries.audit_query_inputs(match.registry))

    def test_scopes_restore_after_failure_and_nested_debug_is_not_downgraded(self):
        match=game();debug=match.clone();debug.runtime_mode='debug'
        with self.assertRaisesRegex(ValueError,'stop'):
            with runtime_queries.query_materials(match):
                self.assertFalse(runtime_queries.audit_query_inputs(match.registry))
                with runtime_queries.query_materials(debug):
                    self.assertTrue(runtime_queries.audit_query_inputs(match.registry))
                    with runtime_queries.query_materials(match):
                        self.assertTrue(runtime_queries.audit_query_inputs(match.registry))
                self.assertFalse(runtime_queries.audit_query_inputs(match.registry))
                raise ValueError('stop')
        self.assertTrue(runtime_queries.audit_query_inputs(match.registry))
        self.assertIsNone(assembly_materials._current.get())

    def test_release_cost_quotes_keep_results_without_reauditing_every_source(self):
        from hs_sim.engine import costs
        match=game();source=match._state.entities[match._state.players[1].hand[0]]
        expected=quote_cost(match._state,match.registry,source)
        with patch.object(costs,'validated_cost_source_inventory',wraps=costs.validated_cost_source_inventory)as audit:
            with runtime_queries.query_materials(match):
                self.assertEqual(quote_cost(match._state,match.registry,source),expected)
            self.assertEqual(audit.call_count,0)
            self.assertEqual(quote_cost(match._state,match.registry,source),expected)
            self.assertEqual(audit.call_count,1)
            match.runtime_mode='debug'
            with runtime_queries.query_materials(match):
                self.assertEqual(quote_cost(match._state,match.registry,source),expected)
            self.assertEqual(audit.call_count,2)

    def test_nested_debug_checks_an_existing_release_material(self):
        match=fixtures.AssembleOfferTests().game();debug=match.clone();debug.runtime_mode='debug'
        recipe=assemble_faces.AssembleRecipe('a','b','top').card_id
        with runtime_queries.query_materials(match):
            old=match.registry.card(recipe);attack=old.attack
            object.__setattr__(old,'attack',999)
            with runtime_queries.query_materials(debug):
                repaired=match.registry.card(recipe)
                self.assertEqual(repaired.attack,attack);self.assertIsNot(repaired,old)

    def test_explicit_validation_and_external_restore_remain_strict_inside_release(self):
        from hs_sim.engine.owner_turns import validate_history
        match=game();state=deepcopy(match._state);state.owner_turn_history.clear()
        snapshot=match.snapshot();snapshot['state']['owner_turn_history']=[]
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()
            if k not in('schema_version','events','events_hash','state_hash')})
        with runtime_queries.query_materials(match):
            with self.assertRaises(ValueError):validate_history(state,match.registry)
            with self.assertRaises(ValueError):Game.from_snapshot(snapshot,match.registry)

    def test_release_and_debug_actual_payment_choice_outputs_remain_identical(self):
        release=game();debug=release.clone();debug.runtime_mode='debug'
        action=PlayCard(1,release._state.players[1].hand[0])
        self.assertEqual(release.apply(action),debug.apply(action))
        self.assertEqual(release.snapshot(),debug.snapshot())
        self.assertEqual(release.for_player(1).legal_actions(),debug.for_player(1).legal_actions())


if __name__=='__main__':unittest.main()
