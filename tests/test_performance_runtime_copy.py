"""Native copies retain transaction isolation and Python extension protocols."""
from copy import deepcopy as reference_copy
from copyreg import dispatch_table
from dataclasses import dataclass
import unittest
from unittest.mock import patch

from hs_sim.engine import PlayCard, SelectChoice
from hs_sim.engine.effects import GainArmor
from hs_sim.engine.runtime_copy import deepcopy
from test_performance_frame_metadata import game


class RuntimeCopyTests(unittest.TestCase):
    def test_empty_sets_keep_aliases_isolation_and_registered_reducers(self):
        shared = set()
        source = [shared, shared, set(), {1, 2}]
        actual = deepcopy(source)
        self.assertEqual(actual, reference_copy(source))
        self.assertIs(actual[0], actual[1])
        self.assertIsNot(actual[0], actual[2])
        self.assertIsNot(actual[0], shared)
        actual[0].add(3)
        self.assertEqual(shared, set())
        with patch.dict(dispatch_table, {set: lambda value: (set, ((17,),))}):
            self.assertEqual(deepcopy(set()), reference_copy(set()))

    def test_mutable_aliases_cycles_and_tuple_cycles(self):
        shared = [1, True, -0.0, None, '\ud834\udd1e']
        loop = []; ring = (loop,); loop.append(ring)
        source = {'second': shared, 'first': shared, 'ring': ring}
        source['self'] = source
        actual = deepcopy(source); expected = reference_copy(source)
        self.assertEqual(list(actual), list(expected))
        self.assertEqual(actual['first'], expected['first'])
        self.assertEqual([type(x) for x in actual['first']], [type(x) for x in expected['first']])
        self.assertIs(actual['first'], actual['second'])
        self.assertIs(actual, actual['self'])
        self.assertIs(actual['ring'][0][0], actual['ring'])
        self.assertIsNot(actual['ring'], ring)
        self.assertIsNot(actual['first'], shared)

    def test_native_records_keep_extra_attributes_and_shared_children(self):
        state = game()._state
        state.extra = state.players[1].hand
        state.circular = state
        actual = deepcopy(state)
        self.assertIs(actual.extra, actual.players[1].hand)
        self.assertIs(actual.circular, actual)
        self.assertEqual(list(vars(actual)), list(vars(state)))
        actual.extra.clear()
        self.assertTrue(state.players[1].hand)

    def test_extension_hooks_share_memo_and_value_before_key_order(self):
        seen = []
        class Hook:
            def __init__(self, label, child): self.label, self.child = label, child
            def __deepcopy__(self, memo):
                seen.append(self.label)
                return Hook(self.label, reference_copy(self.child, memo))
        shared = [[]]
        source = [{Hook('key', shared): Hook('value', shared)}, shared]
        expected = reference_copy(source); expected_order = seen[:]; seen.clear()
        actual = deepcopy(source)
        self.assertEqual(seen, expected_order)
        key, value = next(iter(actual[0].items()))
        self.assertIs(key.child, value.child)
        self.assertIs(value.child, actual[1])
        self.assertIsNot(actual[1], shared)

    def test_container_subclasses_and_slots_follow_original_protocols(self):
        class ExtendedList(list): pass
        @dataclass(frozen=True, slots=True)
        class Slotted:
            items: object
        child = ExtendedList([[]]); source = [child, Slotted(child), child]
        actual = deepcopy(source); expected = reference_copy(source)
        self.assertEqual(actual, expected)
        self.assertIs(type(actual[0]), ExtendedList)
        self.assertIs(actual[0], actual[1].items)
        self.assertIs(actual[0], actual[2])
        self.assertIsNot(actual[0], child)

    def test_unknown_class_metadata_and_enum_copy_overrides_fall_back(self):
        from enum import Enum
        class Extension:
            def __init__(self): self.items = [[]]
        Extension.__module__ = {}
        value = Extension(); actual = deepcopy(value)
        self.assertIs(type(actual), Extension)
        self.assertEqual(actual.items, reference_copy(value).items)
        self.assertIsNot(actual.items, value.items)
        class CustomEnum(Enum):
            VALUE = 1
            def __deepcopy__(self, memo): return ['custom']
        self.assertEqual(deepcopy(CustomEnum.VALUE), reference_copy(CustomEnum.VALUE))

    def test_native_class_copy_and_state_hooks_use_reference_path(self):
        value = GainArmor(1, 3)
        with patch.object(GainArmor, '__deepcopy__', lambda self, memo: 'copied', create=True):
            self.assertEqual(deepcopy(value), reference_copy(value))
        def getstate(self): return {'player_id': 2, 'amount': 8, 'source_id': None}
        with patch.object(GainArmor, '__getstate__', getstate):
            self.assertEqual(deepcopy(value), reference_copy(value))

    def test_native_instance_copy_hook_and_registered_reducer_are_respected(self):
        value = GainArmor(1, 3)
        object.__setattr__(value, '__deepcopy__', lambda memo: 'instance')
        self.assertEqual(deepcopy(value), reference_copy(value))
        value = GainArmor(1, 3)
        object.__setattr__(value, '__getstate__', lambda: {'player_id': 2, 'amount': 9})
        self.assertEqual(deepcopy(value), reference_copy(value))
        value = GainArmor(1, 3)
        with patch.dict(dispatch_table, {GainArmor: lambda value: (GainArmor, (2, 9))}):
            self.assertEqual(deepcopy(value), reference_copy(value))

    def test_extension_mutating_later_class_copy_protocol_invalidates_decision(self):
        first, last = GainArmor(1, 3), GainArmor(2, 4)
        class InstallHook:
            def __deepcopy__(self, memo):
                GainArmor.__deepcopy__ = lambda self, memo: 'installed'
                return self
        try:
            actual = deepcopy([first, InstallHook(), last])
            self.assertEqual(actual[0], first)
            self.assertEqual(actual[2], 'installed')
        finally:
            del GainArmor.__deepcopy__

    def test_public_state_and_waiting_clone_do_not_share_mutable_material(self):
        original = game()
        source = original._state.players[1].hand[0]
        original.apply(PlayCard(1, source))
        before = original.snapshot(); clone = original.clone()
        self.assertEqual(clone.snapshot(), before)
        public = original.state; public.players[1].board.clear()
        clone._state.players[1].board.clear()
        self.assertEqual(original.snapshot(), before)
        other = original.clone(); choice = other._state.pending_choice
        other.apply(SelectChoice(1, choice.id, ('ok',)))
        self.assertEqual(original.snapshot(), before)
        self.assertNotEqual(other.snapshot(), before)

    def test_waiting_clone_detaches_boundary_origin_history_and_keyword_sets(self):
        original = game()
        original.apply(PlayCard(1, original._state.players[1].hand[0]))
        snapshot, history, origin = original.snapshot(), original.history, original.origin
        branch = original.clone()
        branch._frame.paid_hand_choice_boundary.state.players[1].hand.append(99999)
        branch._history[0]['action']['player_id'] = 2
        branch._origin['state']['players']['1']['hand'].clear()
        entity_id = original._state.players[1].board[0]
        from hs_sim.engine.model import Keyword
        branch._state.entities[entity_id].keywords.add(Keyword.TAUNT)
        self.assertEqual(original.snapshot(), snapshot)
        self.assertEqual(original.history, history)
        self.assertEqual(original.origin, origin)

    def test_complete_apply_and_player_view_match_reference_copy(self):
        from hs_sim.engine import game as game_module, resolver, payment_projection, paid_hand_acceptance, assemble_offers, spell_acceptance, spell_cost_proof
        modules = (game_module, resolver, payment_projection, paid_hand_acceptance,
                   assemble_offers, spell_acceptance, spell_cost_proof)
        from contextlib import ExitStack
        original = game(); fast = original.clone(); slow = original.clone()
        action = PlayCard(1, original._state.players[1].hand[0])
        fast_result = fast.apply(action)
        with ExitStack() as stack:
            for module in modules: stack.enter_context(patch.object(module, 'deepcopy', reference_copy))
            stack.enter_context(patch.object(payment_projection, 'copy_native', reference_copy))
            slow_result = slow.apply(action)
        self.assertEqual(fast_result, slow_result)
        self.assertEqual(fast.snapshot(), slow.snapshot())
        self.assertEqual([fast.for_player(p).legal_actions() for p in (1, 2)],
                         [slow.for_player(p).legal_actions() for p in (1, 2)])
        choice = fast._state.pending_choice
        action = SelectChoice(choice.player_id, choice.id, ('ok',))
        fast_result = fast.apply(action)
        with ExitStack() as stack:
            for module in modules: stack.enter_context(patch.object(module, 'deepcopy', reference_copy))
            stack.enter_context(patch.object(payment_projection, 'copy_native', reference_copy))
            slow_result = slow.apply(action)
        self.assertEqual(fast_result, slow_result)
        self.assertEqual(fast.snapshot(), slow.snapshot())
        self.assertEqual(fast.history, slow.history)


if __name__ == '__main__': unittest.main()
