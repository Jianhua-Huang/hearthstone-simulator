"""Exercise the actual module entry point using temporary replay output paths."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "examples" / "scenarios" / "basic.json"
ACTIONS = ROOT / "examples" / "actions" / "basic.json"


class EngineCliTests(unittest.TestCase):
    def test_modes_save_identical_final_commitments_and_debug_writes_step_audits(self):
        with tempfile.TemporaryDirectory() as folder:
            release, debug = Path(folder) / 'release.json', Path(folder) / 'debug.json'
            log = Path(folder) / 'actions.jsonl'
            first = self.run_cli('simulate', SCENARIO, '--actions', ACTIONS, '--replay-out', release)
            second = self.run_cli('simulate', SCENARIO, '--actions', ACTIONS, '--replay-out', debug,
                                  '--mode', 'debug', '--debug-log', log)
            self.assertEqual(self.summary(first), self.summary(second))
            fast, audited = (json.loads(path.read_text(encoding='utf-8')) for path in (release, debug))
            for key in ('schema_version', 'origin', 'final_state_hash', 'final_events_hash'):
                self.assertEqual(fast[key], audited[key])
            self.assertEqual([row['action'] for row in fast['actions']],
                             [row['action'] for row in audited['actions']])
            self.assertTrue(all(row['state_hash'] is row['events_hash'] is None for row in fast['actions']))
            self.assertTrue(all(len(row['state_hash']) == len(row['events_hash']) == 64 for row in audited['actions']))
            rows = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row['status'] == 'ok' and 'audit' in row['stages_ms'] for row in rows))
            replay_log = Path(folder) / 'replay.jsonl'
            replayed = self.run_cli('replay', debug, '--mode', 'debug', '--debug-log', replay_log)
            self.assertEqual(self.summary(second), self.summary(replayed))
            self.assertEqual(len(replay_log.read_text(encoding='utf-8').splitlines()), 3)

    def test_debug_failure_is_logged_and_release_rejects_debug_log_option(self):
        with tempfile.TemporaryDirectory() as folder:
            actions, log = Path(folder) / 'invalid.json', Path(folder) / 'failed.jsonl'
            actions.write_text('[{"type":"end_turn","player_id":2}]', encoding='utf-8')
            self.run_cli('simulate', SCENARIO, '--actions', actions, '--mode', 'debug',
                         '--debug-log', log, expected_code=2)
            row = json.loads(log.read_text(encoding='utf-8'))
            self.assertEqual((row['status'], row['failed_stage']), ('error', 'validate'))
            self.assertIn('IllegalAction', row['traceback'])
            absent = Path(folder) / 'release.jsonl'
            self.run_cli('demo', '--debug-log', absent, expected_code=2)
            self.assertFalse(absent.exists())

    def test_match_stops_at_mulligan_and_saves_pending_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / 'pending.json'
            replay = Path(folder) / 'replay.json'
            result = self.run_cli('match', ROOT / 'examples/matches/constructed.json',
                                  '--snapshot-out', snapshot, '--replay-out', replay)
            state = self.summary(result)
            self.assertEqual(state['opening_stage'], 'mulligan')
            self.assertEqual(state['actions'], 0)
            self.assertEqual(state['pending_choice']['purpose'], 'mulligan')
            self.assertEqual(json.loads(snapshot.read_text(encoding='utf-8'))['schema_version'], SNAPSHOT_SCHEMA_VERSION)
            restored = self.run_cli('replay', replay, '--card-set', 'representative')
            self.assertEqual(self.summary(restored), state)

    def test_match_action_script_finishes_opening_and_plays_coin(self):
        result = self.run_cli('match', ROOT / 'examples/matches/constructed.json',
                              '--actions', ROOT / 'examples/actions/constructed.json')
        state = self.summary(result)
        self.assertEqual(state['opening_stage'], 'complete')
        self.assertEqual(state['actions'], 4)
        self.assertIsNone(state['pending_choice'])

    def run_cli(self, *args, expected_code=0):
        result = subprocess.run(
            [sys.executable, "-m", "hs_sim", *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, expected_code,
                         f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertNotIn("Traceback", result.stderr)
        return result

    def summary(self, result):
        # Per-action lines begin with their action numbers; only the final
        # human-readable JSON summary starts an unindented object on a new line.
        start = result.stdout.rfind("\n{")
        self.assertGreaterEqual(start, 0, result.stdout)
        return json.loads(result.stdout[start + 1:])

    def test_demo_saves_nested_output_and_cli_replay_reproduces_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "回放" / "嵌套目录" / "seed-7.json"
            run = self.run_cli("demo", "--seed", 7, "--replay-out", path)
            summary = self.summary(run)
            self.assertEqual(summary["status"], "finished")
            self.assertGreater(summary["actions"], 0)
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["actions"]), summary["actions"])
            self.assertIsNone(payload["actions"][-1]["state_hash"])
            self.assertEqual(payload["final_state_hash"], summary["state_hash"])
            restored = self.run_cli("replay", path)
            self.assertIn("回放逐步校验通过", restored.stdout)
            self.assertEqual(self.summary(restored), summary)

    def test_checked_in_scenario_and_actions_run_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "example.json"
            run = self.run_cli("simulate", SCENARIO, "--actions", ACTIONS,
                               "--events", "--replay-out", path)
            summary = self.summary(run)
            self.assertEqual(summary["actions"], 3)
            self.assertEqual(summary["turn"], 2)
            self.assertEqual(summary["status"], "playing")
            self.assertEqual(summary["players"]["1"]["board"], 1)
            self.assertEqual(summary["players"]["2"]["board"], 1)
            self.assertIn('"kind": "minion_died"', run.stdout)
            self.assertEqual(self.summary(self.run_cli("replay", path)), summary)

    def test_invalid_actions_return_friendly_error_without_writing_output(self):
        cases = (
            {},
            [{"type": "unknown", "player_id": 1}],
            [{"type": "end_turn", "player_id": True}],
            [{"type": "end_turn", "player_id": 1, "unexpected": 0}],
            [{"type": "end_turn", "player_id": 2}],
            [{"type": "play_card", "player_id": 1, "entity_id": 999999}],
        )
        with tempfile.TemporaryDirectory() as folder:
            actions = Path(folder) / "invalid.json"
            output = Path(folder) / "should-not-exist.json"
            for payload in cases:
                with self.subTest(payload=payload):
                    actions.write_text(json.dumps(payload), encoding="utf-8")
                    result = self.run_cli("simulate", SCENARIO, "--actions", actions,
                                          "--replay-out", output, expected_code=2)
                    self.assertIn("错误：", result.stderr)
                    self.assertFalse(output.exists())

    def test_action_limited_demo_reports_unfinished_match(self):
        result = self.run_cli("demo", "--seed", 7, "--max-actions", 1)
        summary = self.summary(result)
        self.assertEqual(summary["status"], "playing")
        self.assertIsNone(summary["winner"])
        self.assertEqual(summary["actions"], 1)
        self.assertIn("对局尚未结束", result.stdout)
        self.assertNotIn('"status": "finished"', result.stdout)

    def test_target_report_keeps_unknown_full_pool_separate_from_samples(self):
        result = json.loads(self.run_cli('target').stdout)
        self.assertEqual(result['coverage_kind'], 'representative_sample')
        self.assertGreater(result['sample_cards'], 0)
        self.assertIsNone(result['full_pool_count'])
        self.assertIsNone(result['full_pool_coverage_percent'])

    def test_real_reborn_fixture_replays_only_with_matching_card_package(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reborn.json'
            result = self.run_cli('simulate', ROOT / 'examples/scenarios/reborn.json',
                                  '--actions', ROOT / 'examples/actions/reborn.json',
                                  '--card-set', 'representative', '--events', '--replay-out', path)
            self.assertEqual(self.summary(result)['actions'], 3)
            self.assertEqual(result.stdout.count('"kind": "minion_reborn"'), 1)
            replay = self.run_cli('replay', path, '--card-set', 'representative')
            self.assertEqual(self.summary(replay), self.summary(result))
            self.run_cli('replay', path, expected_code=2)

    def test_corrupted_replay_returns_step_error_and_nonpositive_limit_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "damaged.json"
            self.run_cli("demo", "--max-actions", 1, "--mode", "debug",
                         "--debug-log", Path(folder) / 'debug.jsonl', "--replay-out", path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["actions"][0]["state_hash"] = "0" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_cli("replay", path, expected_code=2)
            self.assertIn("step 1", result.stderr)
            self.assertIn("state_hash mismatch", result.stderr)
            self.run_cli("demo", "--max-actions", 1, "--replay-out", path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(payload['actions'][0]['state_hash'])
            payload['final_state_hash'] = '0' * 64
            path.write_text(json.dumps(payload), encoding='utf-8')
            result = self.run_cli('replay', path, expected_code=2)
            self.assertIn('final_state_hash mismatch', result.stderr)
        invalid_limit = self.run_cli("demo", "--max-actions", 0, expected_code=2)
        self.assertIn("必须填写正整数", invalid_limit.stderr)


if __name__ == "__main__":
    unittest.main()
