"""Fast native execution preserves results, isolation and strict imports."""
from copy import deepcopy
from dataclasses import dataclass
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import Game, PlayCard, SelectChoice, ResolutionError, SnapshotError
from hs_sim.engine import continuations
from hs_sim.engine.continuations import FrameCodec, type_name
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.serialization import canonical_hash
import test_assemble_offers as fixtures


class RuntimeAuditTests(unittest.TestCase):
    def game(self, hand=('assemble',)):
        return fixtures.AssembleOfferTests().game(hand=hand)

    def play(self, game):
        return PlayCard(1, game._state.players[1].hand[0])

    def choose(self, game):
        choice = game._state.pending_choice
        return SelectChoice(choice.player_id, choice.id, (choice.options[0].id,))

    def test_normal_and_audited_nested_choices_have_identical_complete_results(self):
        normal = self.game(('repeat',))
        audited = normal.clone()
        audited.runtime_audits = True
        for n in range(3):
            command = self.play(normal) if n == 0 else self.choose(normal)
            self.assertEqual(normal.apply(command), audited.apply(command))
            self.assertEqual(normal.snapshot(), audited.snapshot())
            self.assertEqual(normal.history, audited.history)
            self.assertEqual([normal.for_player(p).legal_actions() for p in (1, 2)],
                             [audited.for_player(p).legal_actions() for p in (1, 2)])
            normal.audit()
        self.assertIsNone(normal._state.pending_choice)
        self.assertEqual(normal._state.players[1].mana, 9)

    def test_full_audit_is_opt_in_and_audit_failure_rolls_back(self):
        normal, audited = self.game(), self.game()
        audited.runtime_audits = True
        before = audited.snapshot()
        with patch.object(Game, '_assert_stable', side_effect=ValueError('audit failure')):
            normal.apply(self.play(normal))
            with self.assertRaisesRegex(ResolutionError, 'audit failure'):
                audited.apply(self.play(audited))
        self.assertEqual(audited.snapshot(), before)
        normal.audit()

    def test_runtime_setting_is_inherited_by_clone_but_not_saved_as_a_rule(self):
        game = self.game()
        before = game.snapshot()
        game.runtime_audits = True
        self.assertTrue(game.clone().runtime_audits)
        self.assertEqual(game.snapshot(), before)
        restored = Game.from_snapshot(before, fixtures.registry())
        self.assertFalse(restored.runtime_audits)
        self.assertEqual(restored.snapshot(), before)

    def test_external_snapshot_still_rejects_rehashed_corruption(self):
        game = self.game()
        game.apply(self.play(game))
        snapshot = game.snapshot()
        snapshot['state']['active_player'] = True
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, fixtures.registry())

    def test_direct_frame_copy_matches_old_wire_roundtrip(self):
        game = self.game()
        game.apply(self.play(game))
        codec = FrameCodec(game.mechanics, game.registry)
        expected = codec.encode(codec.decode(codec.encode(game._frame)))
        copied = codec.copy_runtime(game._frame)
        self.assertEqual(codec.encode(copied), expected)
        self.assertEqual(codec.encode_runtime(copied), expected)

    def test_each_captured_context_gets_its_own_state_and_canonical_map_order(self):
        game = self.game()
        state = deepcopy(game._state)
        state.entities = dict(reversed(tuple(state.entities.items())))
        value = RuleContext(state, state.players[1].hero_id, 1)
        codec = FrameCodec(game.mechanics, game.registry)
        left, right = codec.copy_runtime((value, value))
        self.assertIsNot(left.state, right.state)
        self.assertEqual(list(left.state.entities), sorted(left.state.entities))
        left.state.players[1].deck.clear()
        self.assertEqual(right.state.players[1].deck, state.players[1].deck)
        self.assertIsNot(left.state.players[1], state.players[1])

    def test_encoding_memo_is_local_and_returned_wire_branches_are_independent(self):
        game = self.game()
        codec = FrameCodec(game.mechanics, game.registry)
        state = game._state
        expected = codec.encode((state, state))
        with patch.object(continuations, 'state_to_dict', wraps=continuations.state_to_dict) as encode:
            actual = codec.encode_runtime((state, state))
            self.assertEqual(encode.call_count, 1)
            self.assertEqual(actual, expected)
            state.players[1].mana = 7
            self.assertEqual(codec.encode_runtime(state)['state']['players']['1']['mana'], 7)
            self.assertEqual(encode.call_count, 2)
        actual['tuple'][0]['state']['players']['1']['mana'] = 1
        self.assertEqual(actual['tuple'][1]['state']['players']['1']['mana'], 10)

    def test_foreign_payload_constructor_and_validation_stay_on_original_path(self):
        calls = []

        @dataclass(frozen=True)
        class External:
            amount: int

            def __post_init__(self):
                calls.append(self.amount)

        game = self.game()
        codec = FrameCodec(game.mechanics, game.registry)
        codec.types[type_name(External)] = External
        value = External(2)
        calls.clear()
        expected = codec.decode(codec.encode(value))
        expected_calls = list(calls)
        calls.clear()
        self.assertEqual(codec.copy_runtime(value), expected)
        self.assertEqual(calls, expected_calls)
        bad = deepcopy(value)
        object.__setattr__(bad, 'amount', 'wrong')
        with self.assertRaises(ValueError):
            codec.check_runtime(bad)

    def test_explicit_audit_does_not_mutate_the_live_match(self):
        game = self.game()
        game.apply(self.play(game))
        snapshot, history = game.snapshot(), game.history
        game.audit()
        self.assertEqual(game.snapshot(), snapshot)
        self.assertEqual(game.history, history)

    def test_cached_frame_wire_is_private_and_replaced_on_each_new_choice(self):
        game = self.game(('repeat',))
        game.apply(self.play(game))
        first = game.snapshot()
        clone = game.clone()
        damaged = game.snapshot()
        damaged['resolution_frame']['fields']['choice_id'] = 999
        self.assertEqual(game.snapshot(), first)
        self.assertEqual(clone.snapshot(), first)
        game.apply(self.choose(game))
        second = game.snapshot()
        self.assertNotEqual(first['resolution_frame'], second['resolution_frame'])
        codec = FrameCodec(game.mechanics, game.registry)
        self.assertEqual(second['resolution_frame'], codec.encode(game._frame))
        self.assertEqual(clone.snapshot(), first)
        game.apply(self.choose(game))
        self.assertIsNone(game.snapshot()['resolution_frame'])
        self.assertIsNone(game._frame_encoding)

    def test_waiting_snapshots_reuse_encoding_and_audited_mode_recomputes(self):
        game = self.game()
        game.apply(self.play(game))
        original = FrameCodec.encode_runtime
        with patch.object(FrameCodec, 'encode_runtime', autospec=True, side_effect=original) as encode:
            first = game.snapshot()
            self.assertEqual(game.snapshot(), first)
            self.assertEqual(encode.call_count, 0)
            game.runtime_audits = True
            self.assertEqual(game.snapshot(), first)
            self.assertEqual(encode.call_count, 1)


if __name__ == '__main__':
    unittest.main()
