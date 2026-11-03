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
    def test_plain_price_matches_full_fact_and_requeries_local_external_payment_and_floor(self):
        from hs_sim.engine import costs
        from hs_sim.engine.model import CostModifier,CostSpec,Enchantment,HandLifetime,PaymentType
        match=game();state=match._state;entity=state.entities[state.players[1].hand[0]]
        entity.base_cost=7
        def compare():
            expected=costs.cost_quote_from_fact(costs.quote_input(state,match.registry,costs.capture_cost_input(entity)))
            with runtime_queries.query_materials(match):
                self.assertEqual(costs.quote_cost(state,match.registry,entity),expected)
            return expected
        self.assertEqual(compare().amount,7)
        eid=state.next_attachment_id;state.next_attachment_id+=1
        entity.enchantments.append(Enchantment(eid,cost=-2))
        self.assertEqual(compare().amount,5)
        eid=state.next_attachment_id;state.next_attachment_id+=1
        state.players[1].cost_modifiers.append(CostModifier(eid,CostSpec(delta=-3,payment=PaymentType.HEALTH),uses_remaining=1))
        entity.hand_lifetime=HandLifetime(None,state.turn,state.turn,4)
        quote=compare()
        self.assertEqual((quote.amount,quote.payment,quote.consumable_ids),(4,PaymentType.HEALTH,(eid,)))
        state.players[1].cost_modifiers.clear()
        self.assertEqual(compare().payment,PaymentType.MANA)

    def test_intrinsic_price_uses_full_live_fact_path(self):
        import test_player_spell_damage_cost_basics as fixtures
        from hs_sim.engine import costs
        case=fixtures.PlayerSpellDamageCostTests();case.setUp();match=case.game()
        entity=match._state.entities[match._state.players[1].hand[0]]
        with runtime_queries.query_materials(match):
            with patch.object(costs,'quote_input',wraps=costs.quote_input) as full:
                costs.quote_cost(match._state,match.registry,entity)
            self.assertEqual(full.call_count,1)

    def health_payload(self):
        import test_m5_health_outcomes as fixtures
        case=fixtures.HealthOutcomeTests();case.setUp()
        match=case.game(hand=('damage',))
        case.play(match,'damage',match._state.players[2].board[0])
        return match,match._state.damage_history[0].result

    def test_health_decode_reuses_only_one_operation_and_debug_stays_strict(self):
        from hs_sim.engine import health_outcomes
        match,raw=self.health_payload();saved=match.snapshot()
        expected=health_outcomes.result_from_payload(raw)
        with patch.object(health_outcomes,'_decode_result_payload',wraps=health_outcomes._decode_result_payload) as decode:
            with runtime_queries.query_materials(match):
                first=health_outcomes.result_from_payload(raw)
                self.assertIs(first,health_outcomes.result_from_payload(raw))
                self.assertEqual(first,expected);self.assertEqual(decode.call_count,1)
                debug=match.clone();debug.runtime_mode='debug'
                with runtime_queries.query_materials(debug):
                    self.assertEqual(health_outcomes.result_from_payload(raw),expected)
                    self.assertEqual(health_outcomes.result_from_payload(raw),expected)
                self.assertIs(health_outcomes.result_from_payload(raw),first)
                self.assertEqual(decode.call_count,3)
            with runtime_queries.query_materials(match):
                self.assertEqual(health_outcomes.result_from_payload(raw),expected)
            health_outcomes.result_from_payload(raw)
            self.assertEqual(decode.call_count,5)
        self.assertEqual(match.snapshot(),saved)

    def test_health_decode_cannot_confuse_equal_bool_int_or_cache_failure(self):
        from hs_sim.engine.health_outcomes import result_from_payload
        match,raw=self.health_payload()
        invalid=tuple((name,0 if name=='converted' else value) for name,value in raw)
        self.assertEqual(invalid,raw)
        with runtime_queries.query_materials(match):
            expected=result_from_payload(raw)
            for _ in range(2):
                with self.assertRaises(ValueError):result_from_payload(invalid)
            self.assertEqual(result_from_payload(raw),expected)

    def test_payload_memo_is_bounded_and_ignores_mutable_inputs(self):
        match=game();calls=[]
        def decode(value):calls.append(value);return len(value)
        mutable=([],)
        with runtime_queries.query_materials(match):
            for _ in range(2):runtime_queries.decode_immutable_payload(mutable,decode)
            self.assertEqual(len(calls),2)
            for i in range(1100):
                runtime_queries.decode_immutable_payload((i,),decode)
            self.assertEqual(len(runtime_queries._current.get()[2]),1024)
        self.assertIsNone(runtime_queries._current.get())

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
        fast,checked=release.apply(action),debug.apply(action)
        self.assertEqual(fast.events,checked.events)
        self.assertIsNone(fast.state_hash)
        self.assertEqual(checked.state_hash,release.state_hash())
        self.assertEqual(release.snapshot(),debug.snapshot())
        self.assertEqual(release.for_player(1).legal_actions(),debug.for_player(1).legal_actions())


if __name__=='__main__':unittest.main()
