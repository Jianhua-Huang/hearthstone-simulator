"""Mode selection, debug evidence and release semantics at real API boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.engine import Game, IllegalAction, PlayCard, ResolutionError, RuntimeMode, SelectChoice, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.runtime import DEBUG_RECORD_LIMIT, debug_log
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.synthetic import build_registry, demo_scenario
import test_assemble_offers as assembly


class RuntimeModes(unittest.TestCase):
    def test_debug_native_audit_and_explicit_schema_audit_are_separate(self):
        game = self.game('debug')
        with patch.object(FrameCodec, 'decode', side_effect=AssertionError('unnecessary roundtrip')):
            game.apply(self.command(game))
        original = FrameCodec.decode
        with patch.object(FrameCodec, 'decode', autospec=True, side_effect=original) as decode:
            game.audit()
            self.assertGreater(decode.call_count, 0)
        self.assertEqual(game.debug_log_failures, 0)

    def test_native_audit_rejects_corrupt_captured_state_and_payload_fields(self):
        game = self.game()
        game.apply(self.command(game))
        codec = FrameCodec(game.mechanics, game.registry)
        frame = deepcopy(game._frame)
        effect = frame.options[0].effects[0]
        effect.offer.before.players[1].mana_cap = -1
        with self.assertRaises(ValueError):
            codec.audit_runtime(frame)
        frame = deepcopy(game._frame)
        object.__setattr__(frame.options[0], 'id', True)
        with self.assertRaises(ValueError):
            codec.audit_runtime(frame)

    def game(self, mode='release'):
        game = assembly.AssembleOfferTests().game(hand=('repeat',))
        game.runtime_mode = mode
        return game

    def command(self, game):
        choice = game._state.pending_choice
        if choice is not None:
            return SelectChoice(choice.player_id, choice.id, (choice.options[0].id,))
        return PlayCard(1, game._state.players[1].hand[0])

    def test_default_release_never_collects_debug_or_runs_full_action_audit(self):
        game = self.game()
        self.assertIs(game.runtime_mode, RuntimeMode.RELEASE)
        with patch('hs_sim.engine.runtime.ActionTrace', side_effect=AssertionError('debug allocation')), \
                patch.object(Game, '_assert_stable', side_effect=AssertionError('full audit')):
            game.apply(self.command(game))
        self.assertEqual(game.debug_records, ())
        self.assertIsNone(game._debug_records)
        self.assertIsNone(game._debug_trace)

    def test_modes_match_nested_choices_history_replay_and_player_information(self):
        release, debug = self.game(), self.game('debug')
        for _ in range(3):
            command = self.command(release)
            self.assertEqual(release.apply(command), debug.apply(command))
            self.assertEqual(release.snapshot(), debug.snapshot())
            self.assertEqual(release.history, debug.history)
            for viewer in (1, 2):
                self.assertEqual(release.for_player(viewer).legal_actions(), debug.for_player(viewer).legal_actions())
        record = debug.debug_records[0]
        self.assertEqual(record['status'], 'ok')
        self.assertGreater(record['work_count'], 0)
        self.assertGreater(record['queue_peak'], 0)
        self.assertIn('resolve', record['stages_ms'])
        self.assertIn('audit', record['stages_ms'])
        self.assertGreater(record['event_count'], 0)
        self.assertNotIn('event_types', record)
        self.assertNotIn('work_types', record)
        self.assertNotIn('last_work', record)
        self.assertEqual(len(record['game_id']), 32)
        self.assertEqual({row['game_id'] for row in debug.debug_records}, {record['game_id']})
        self.assertEqual(len(debug.debug_records), 3)
        self.assertEqual(debug.debug_log_failures, 0)
        restored = replay(build_replay(release), assembly.registry(), mode='debug')
        self.assertIs(restored.runtime_mode, RuntimeMode.DEBUG)
        self.assertEqual(restored.snapshot(), release.snapshot())
        self.assertEqual(len(restored.debug_records), 3)
        self.assertIsNone(debug._debug_trace)

    def test_failed_audit_retains_stack_partial_work_and_transaction_rollback(self):
        game = self.game('debug')
        before = game.snapshot()
        with patch.object(Game, '_assert_stable', side_effect=ValueError('injected diagnostic failure')):
            with self.assertRaisesRegex(ResolutionError, 'injected diagnostic failure'):
                game.apply(self.command(game))
        self.assertEqual(game.snapshot(), before)
        record = game.debug_records[-1]
        self.assertEqual((record['status'], record['failed_stage']), ('error', 'audit'))
        self.assertIn('ValueError: injected diagnostic failure', record['traceback'])
        self.assertEqual(record['before'], record['after'])
        self.assertGreater(record['discarded_position']['events'], record['before']['events'])
        self.assertGreater(record['work_count'], 0)
        self.assertTrue(record['last_work'])
        self.assertLessEqual(len(record['last_work']), 32)
        self.assertIsNone(game._debug_trace)

    def test_invalid_input_is_still_rejected_and_debug_buffer_is_bounded(self):
        game = self.game('debug')
        before = game.snapshot()
        for _ in range(DEBUG_RECORD_LIMIT + 2):
            with self.assertRaises(IllegalAction):
                game.apply(PlayCard(1, 999999))
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(len(game.debug_records), DEBUG_RECORD_LIMIT)
        record = game.debug_records[0]
        self.assertEqual(record['failed_stage'], 'validate')
        record['before']['turn'] = -1
        self.assertNotEqual(game.debug_records[0]['before']['turn'], -1)

    def test_clone_inherits_mode_with_independent_empty_diagnostics(self):
        game = self.game('debug')
        game.apply(self.command(game))
        clone = game.clone()
        self.assertIs(clone.runtime_mode, RuntimeMode.DEBUG)
        self.assertEqual(clone.debug_records, ())
        clone.apply(self.command(clone))
        self.assertEqual(len(clone.debug_records), 1)
        self.assertEqual(len(game.debug_records), 1)
        self.assertNotEqual(clone.debug_records[0]['action'], game.debug_records[0]['action'])
        self.assertNotEqual(clone.debug_records[0]['game_id'], game.debug_records[0]['game_id'])

    def test_mode_is_host_configuration_and_external_restore_stays_strict(self):
        for mode in RuntimeMode:
            game = Game.from_scenario(demo_scenario(7), build_registry(), mode=mode)
            snapshot = game.snapshot()
            restored = Game.from_snapshot(snapshot, game.registry, mode=mode)
            self.assertIs(restored.runtime_mode, mode)
            self.assertEqual(restored.snapshot(), snapshot)
            self.assertEqual(restored.debug_records, ())
            self.assertIs(Game.from_snapshot(snapshot, game.registry).runtime_mode, RuntimeMode.RELEASE)
            bad = deepcopy(snapshot)
            bad['events_hash'] = '0' * 64
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, game.registry, mode=mode)

    def test_legacy_alias_and_boundary_mode_switch_do_not_change_saved_rules(self):
        game = self.game()
        before = game.snapshot()
        game.runtime_audits = True
        self.assertIs(game.runtime_mode, RuntimeMode.DEBUG)
        game.runtime_mode = 'release'
        self.assertFalse(game.runtime_audits)
        self.assertEqual(before, game.snapshot())
        with self.assertRaises(ValueError):
            game.runtime_mode = 'fastest'
        game._resolving = True
        try:
            with self.assertRaises(ResolutionError):
                game.runtime_mode = 'debug'
        finally:
            game._resolving = False

    def test_log_output_failure_preserves_success_and_original_exception(self):
        game = self.game('debug')
        with patch('hs_sim.engine.runtime.publish', side_effect=OSError('disk unavailable')):
            game.apply(self.command(game))
            before = game.snapshot()
            with self.assertRaises(IllegalAction):
                game.apply(PlayCard(1, 999999))
        self.assertEqual(game.snapshot(), before)
        self.assertEqual([row['status'] for row in game.debug_records], ['ok', 'error'])
        self.assertEqual(game.debug_log_failures, 2)

    def test_jsonl_writes_success_and_failure_without_changing_replay(self):
        game = self.game('debug')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested' / 'engine.jsonl'
            with debug_log(path):
                game.apply(self.command(game))
                with self.assertRaises(IllegalAction):
                    game.apply(PlayCard(1, 999999))
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(rows, list(game.debug_records))
        self.assertEqual(len(build_replay(game)['actions']), 1)
        self.assertEqual(game.debug_log_failures, 0)


if __name__ == '__main__':
    unittest.main()
