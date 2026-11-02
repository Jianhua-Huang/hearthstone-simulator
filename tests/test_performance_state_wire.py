"""State wire fast paths preserve complete output and deepcopy semantics."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import serialization
from test_performance_frame_metadata import game


class StateWirePerformanceTests(unittest.TestCase):
    def setUp(self):self.game=game()

    def test_native_state_matches_complete_legacy_wire_and_key_order(self):
        state=self.game._state
        expected_entities={str(k):serialization.entity_to_dict(v) for k,v in sorted(state.entities.items())}
        expected=serialization._state_to_dict_legacy(state)
        actual=serialization.state_to_dict(state)
        self.assertEqual(actual,expected)
        self.assertEqual(actual['entities'],expected_entities)
        self.assertEqual(json.dumps(actual),json.dumps(expected))

    def test_native_wire_json_keys_scalars_aliases_and_unicode_match_legacy(self):
        from hs_sim.engine.model import Resource
        shared=[1,True,None,-0.0,1e-20,10**50,'\U0001d11e','\ud834\udd1e']
        values={7:'first','7':'overwritten',None:'null',False:'false',1.5:'float',
                Resource.CORPSES:'enum','shared':shared,'again':shared,'tuple':(shared,)}
        self.game._state.armor_gain_history=[values]
        actual=serialization.state_to_dict(self.game._state)
        expected=serialization._state_to_dict_legacy(self.game._state)
        self.assertEqual(json.dumps(actual,ensure_ascii=False),json.dumps(expected,ensure_ascii=False))
        row=actual['armor_gain_history'][0]
        self.assertIsNot(row['shared'],row['again'])
        row['shared'].clear()
        self.assertEqual(row['again'],shared)
        self.assertEqual(row['tuple'],[shared])

    def test_extension_fallback_keeps_hook_order_and_late_mutation(self):
        seen=[];shared={'items':[]}
        class First:
            def __deepcopy__(self,memo):seen.append('first');return shared
        class Second:
            def __deepcopy__(self,memo):seen.append('second');shared['items'].append(7);return 2
        self.game._state.armor_gain_history=[First(),Second()]
        expected=serialization._state_to_dict_legacy(self.game._state)
        expected_order=seen[:];seen.clear();shared['items'].clear()
        actual=serialization.state_to_dict(self.game._state)
        self.assertEqual(seen,expected_order)
        self.assertEqual(actual,expected)
        self.assertEqual(actual['armor_gain_history'],[{'items':[7]},2])

    def test_keyword_reducer_hooks_are_not_skipped(self):
        from copyreg import dispatch_table
        seen=[]
        def reduce_set(value):seen.append(len(value));return set,(tuple(value),)
        with patch.dict(dispatch_table,{set:reduce_set}):
            expected=serialization._state_to_dict_legacy(self.game._state)
            expected_order=seen[:];seen.clear()
            actual=serialization.state_to_dict(self.game._state)
        self.assertEqual(actual,expected)
        self.assertTrue(expected_order)
        self.assertEqual(seen,expected_order)

    def test_non_json_values_and_nonfinite_numbers_keep_original_rejections(self):
        for value in (float('nan'),float('inf'),b'bytes',{1,2}):
            self.game._state.armor_gain_history=[value]
            with self.assertRaises((ValueError,TypeError)) as expected:
                serialization._state_to_dict_legacy(self.game._state)
            with self.assertRaises(type(expected.exception)):
                serialization.state_to_dict(self.game._state)

    def test_public_entity_wire_still_returns_json_and_detached_values(self):
        entity=next(iter(self.game._state.entities.values()))
        result=serialization.entity_to_dict(entity)
        self.assertEqual(result,json.loads(json.dumps(result)))
        result['abilities'].clear()
        self.assertIsNot(result['abilities'],entity.abilities)

    def test_state_decode_still_detaches_input_and_restores_full_state(self):
        value=serialization.state_to_dict(self.game._state);before=deepcopy(value)
        decoded=serialization.state_from_dict(value)
        self.assertEqual(value,before)
        self.assertEqual(serialization.state_to_dict(decoded),before)
        decoded.players[1].hand.clear()
        self.assertEqual(value,before)

    def test_wire_copy_preserves_aliases_cycles_order_and_scalar_types(self):
        shared=[1,True,None,-0.0,'\U0001d11e','\ud834\udd1e']
        value={'second':shared,'first':shared};value['self']=value
        result=serialization._copy_state_wire(value)
        self.assertEqual(list(result),list(value))
        self.assertEqual(result['first'],deepcopy(shared))
        self.assertEqual([type(v) for v in result['first']],[type(v) for v in shared])
        self.assertIs(result['first'],result['second'])
        self.assertIs(result['self'],result)
        self.assertIsNot(result['first'],shared)

    def test_container_subclass_and_extension_hooks_keep_deepcopy_behavior(self):
        class ExtendedList(list):pass
        class Hook:
            def __init__(self,target):self.target=target
            def __deepcopy__(self,memo):return Hook(deepcopy(self.target,memo))
        shared=ExtendedList([[]]);value=[shared,Hook(shared),shared]
        result=serialization._copy_state_wire(value)
        self.assertIs(type(result[0]),ExtendedList)
        self.assertIs(result[0],result[1].target)
        self.assertIs(result[0],result[2]);self.assertIsNot(result[0],shared)

    def test_dictionary_extension_hooks_keep_value_before_key_order(self):
        seen=[]
        class Hook:
            def __init__(self,name):self.name=name
            def __deepcopy__(self,memo):seen.append(self.name);return self
        value={Hook('key'):Hook('value')}
        deepcopy(value);expected=list(seen);seen.clear()
        serialization._copy_state_wire(value)
        self.assertEqual(seen,expected)

    def test_decode_strict_types_and_unknown_fields_remain_rejected(self):
        original=serialization.state_to_dict(self.game._state)
        for field,value in [('next_entity_id',True),('unknown',1),('players',[])]:
            row=deepcopy(original);row[field]=value
            with self.assertRaises(ValueError):serialization.state_from_dict(row)

    def test_static_lookup_is_live_and_preserves_dynamic_namespace_errors(self):
        registry=self.game.registry;card=registry.card('plain')
        changed=replace(card,attack=3);registry._cards['plain']=changed
        self.assertIs(registry.card('plain'),changed)
        registry._cards['assemble:invalid']=replace(card,id='assemble:invalid')
        for invalid in ('assemble:invalid',True,'unknown'):
            with self.assertRaises(ValueError):registry.card(invalid)


if __name__=='__main__':unittest.main()
