"""Action-local reuse must keep strict input handling and branch isolation."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import unittest
from unittest.mock import patch

from hs_sim.engine import PlayCard, ResolutionError, SelectChoice
from hs_sim.engine import continuations as codec_module, frame_materials as cache
from hs_sim.engine.continuations import FrameCodec, type_name
from hs_sim.engine.model import TurnSchedule
import test_assemble_offers as fixtures


class FrameMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.game = fixtures.AssembleOfferTests().game()
        self.game.runtime_audits = True
        self.registry = self.game.registry
        self.state = self.game._state
        self.codec = FrameCodec(self.game.mechanics, self.registry)

    def test_repeated_states_skip_reconversion_but_return_independent_values(self):
        original = self.codec.encode(self.state)
        with patch.object(codec_module, 'state_to_dict', wraps=codec_module.state_to_dict) as encode, \
                patch.object(codec_module, 'state_from_dict', wraps=codec_module.state_from_dict) as decode, \
                patch.object(codec_module, 'validate_invariants', wraps=codec_module.validate_invariants) as validate:
            with cache.action_frame_materials(self.registry):
                wire = self.codec.encode((self.state, self.state))
                left, right = self.codec.decode(wire)
                again = self.codec.decode(self.codec.encode(left))
                self.assertEqual((encode.call_count, decode.call_count, validate.call_count), (1, 1, 2))
                self.assertEqual(self.codec.encode(again), original)
                self.assertIsNot(left, right)
                self.assertIsNot(left.players[1].deck, right.players[1].deck)
                self.assertIsNot(left.entities, right.entities)
                left.players[1].deck.clear()
                self.assertEqual(right.players[1].deck, self.state.players[1].deck)
        self.assertIsNone(cache._current.get())

    def test_changed_nested_state_and_scalar_type_are_not_hidden(self):
        with cache.action_frame_materials(self.registry):
            original = self.codec.encode(self.state)
            self.state.players[1].mana -= 1
            changed = self.codec.encode(self.state)
            self.assertNotEqual(original, changed)
            self.state.active_player = True
            with self.assertRaises(ValueError):
                self.codec.encode(self.state)

    def test_editing_wire_does_not_poison_canonical_materials(self):
        with cache.action_frame_materials(self.registry):
            wire = self.codec.encode(self.state)
            expected = deepcopy(wire)
            wire['state']['active_player'] = True
            with self.assertRaises(ValueError):
                self.codec.decode(wire)
            self.assertEqual(self.codec.encode(self.state), expected)

    def test_external_equal_wire_and_next_action_still_decode_strictly(self):
        with patch.object(codec_module, 'state_from_dict', wraps=codec_module.state_from_dict) as decode:
            with cache.action_frame_materials(self.registry):
                wire = self.codec.encode(self.state)
                self.codec.decode(wire)
                self.codec.decode(deepcopy(wire))
                self.codec.decode(wire)
                self.assertEqual(decode.call_count, 2)
            with cache.action_frame_materials(self.registry):
                self.codec.decode(wire)
                self.assertEqual(decode.call_count, 3)

    def test_mutating_first_decoded_branch_does_not_change_other_decodes(self):
        with cache.action_frame_materials(self.registry):
            wire = self.codec.encode(self.state)
            first = self.codec.decode(wire)
            first.players[1].mana -= 1
            next_branch = self.codec.decode(wire)
            self.assertEqual(next_branch.players[1].mana, self.state.players[1].mana)

    def test_native_schema_changes_reach_original_validation(self):
        with cache.action_frame_materials(self.registry):
            self.codec.encode(self.state)
            with patch.object(TurnSchedule, '__post_init__', side_effect=ValueError('changed schema')):
                with self.assertRaisesRegex(ValueError, 'changed schema'):
                    self.codec.encode(self.state)

    def test_foreign_payload_constructors_keep_original_path(self):
        calls = []

        @dataclass(frozen=True)
        class Foreign:
            value: int

            def __post_init__(self):
                calls.append(self.value)

        self.codec.types[type_name(Foreign)] = Foreign
        value = (self.state, Foreign(2), self.state)
        calls.clear()
        expected = self.codec.decode(self.codec.encode(value))
        original_calls = list(calls)
        calls.clear()
        with cache.action_frame_materials(self.registry):
            actual = self.codec.decode(self.codec.encode(value))
        self.assertEqual(actual, expected)
        self.assertEqual(calls, original_calls)

    def test_mutable_registry_and_unusual_state_fall_back(self):
        mutable = fixtures.registry()
        codec = FrameCodec(self.game.mechanics, mutable)
        with patch.object(codec_module, 'state_to_dict', wraps=codec_module.state_to_dict) as encode:
            with cache.action_frame_materials(mutable):
                codec.encode(self.state)
                codec.encode(self.state)
            self.assertEqual(encode.call_count, 2)
        self.state.extra = object()
        self.assertIsNone(cache.GraphGuard.capture(self.state))

    def test_foreign_enum_disables_reuse_before_constructor(self):
        class Foreign(Enum):
            VALUE = 'value'

        self.codec.types[type_name(Foreign)] = Foreign
        with cache.action_frame_materials(self.registry):
            wire = self.codec.encode(self.state)
            self.codec.encode(Foreign.VALUE)
            self.assertFalse(cache._current.get().enabled)
            self.assertEqual(self.codec.decode(wire), self.state)
        with cache.action_frame_materials(self.registry):
            self.codec.encode(self.state)
            value = self.codec.decode({'enum': type_name(Foreign), 'value': 'value'})
            self.assertIs(value, Foreign.VALUE)
            self.assertFalse(cache._current.get().enabled)

    def test_foreign_native_constructor_disables_state_reuse(self):
        original = TurnSchedule.__init__

        def constructor(*args, **kwargs):
            return original(*args, **kwargs)

        with patch.object(TurnSchedule, '__init__', constructor):
            self.assertIsNone(cache.GraphGuard.capture(self.state))

    def test_graph_guard_detects_order_alias_and_nested_changes(self):
        value = {'a': [1], 'b': [2]}
        guard = cache.GraphGuard.capture(value)
        self.assertTrue(guard.matches(value))
        value['a'][0] = True
        self.assertFalse(guard.matches(value))
        value = {'a': [1], 'b': [2]}
        guard = cache.GraphGuard.capture(value)
        value['a'] = value.pop('a')
        self.assertFalse(guard.matches(value))
        value = {'a': [1], 'b': [1]}
        guard = cache.GraphGuard.capture(value)
        value['b'] = value['a']
        self.assertFalse(guard.matches(value))

    def test_guarded_copy_preserves_aliases_and_cycles_without_sharing(self):
        child = [1]
        loop = (child,)
        child.append(loop)
        value = {'a': child, 'b': child, 'set': {2, 3}}
        guard = cache.GraphGuard.capture(value)
        cloned = guard.detached()
        actual = cloned.root
        self.assertTrue(cloned.matches(actual))
        self.assertIs(actual['a'], actual['b'])
        self.assertIs(actual['a'][1][0], actual['a'])
        self.assertIsNot(actual['a'], child)
        actual['set'].add(4)
        self.assertEqual(value['set'], {2, 3})
        self.assertFalse(cloned.matches(actual))

    def test_capacity_and_nested_scope_are_bounded_and_independent(self):
        with patch.object(cache.FrameMaterials, 'MAX_STATES', 2), \
                patch.object(cache.FrameMaterials, 'MAX_WIRES', 2):
            with cache.action_frame_materials(self.registry):
                parent = cache._current.get()
                for n in range(4):
                    state = deepcopy(self.state)
                    self.codec.decode(self.codec.encode(state))
                self.assertLessEqual(len(parent.states), 2)
                self.assertLessEqual(len(parent.wires), 2)
                with cache.action_frame_materials(self.registry):
                    self.assertIsNot(cache._current.get(), parent)
                self.assertIs(cache._current.get(), parent)
        self.assertIsNone(cache._current.get())

    def test_registry_change_fails_before_transaction_commit_and_cleans_scope(self):
        before = self.game.snapshot()
        original_encode = codec_module.state_to_dict

        def mutate(state):
            result = original_encode(state)
            self.registry._version = 'changed-during-action'
            return result

        version = self.registry.version
        try:
            with patch.object(codec_module, 'state_to_dict', mutate):
                with self.assertRaises(ResolutionError):
                    self.game.apply(PlayCard(1, self.state.players[1].hand[0]))
        finally:
            self.registry._version = version
        self.assertIsNone(cache._current.get())
        self.assertEqual(self.game.snapshot(), before)

    def test_native_assembly_matches_uncached_action_and_hash(self):
        cached, original = self.game.clone(), self.game.clone()
        action = PlayCard(1, self.state.players[1].hand[0])
        actual = cached.apply(action)
        with patch.object(cache, 'action_frame_materials', lambda registry, **kwargs: nullcontext()):
            expected = original.apply(action)
        self.assertEqual(actual, expected)
        self.assertEqual(cached.snapshot(), original.snapshot())
        self.assertEqual([cached.observe(p) for p in (1, 2)], [original.observe(p) for p in (1, 2)])

    def test_native_debug_choices_do_not_need_state_wire_materials(self):
        g = fixtures.AssembleOfferTests().game(hand=('repeat',))
        g.runtime_audits = True
        original = cache.FrameMaterials.encode_state
        with patch.object(cache.FrameMaterials, 'encode_state', autospec=True, side_effect=original) as encode:
            g.apply(PlayCard(1, g._state.players[1].hand[0]))
            self.assertEqual(encode.call_count, 0)
            encode.reset_mock()
            choice = g._state.pending_choice
            g.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
            self.assertIsNotNone(g._state.pending_choice)
            self.assertEqual(encode.call_count, 0)
            encode.reset_mock()
            choice = g._state.pending_choice
            g.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
            self.assertIsNone(g._state.pending_choice)
            self.assertEqual(encode.call_count, 0)


if __name__ == '__main__':
    unittest.main()
