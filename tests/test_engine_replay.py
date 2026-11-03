"""Replay integration checks using explicit synthetic behaviors, never game data."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.engine.actions import EndTurn, PlayCard
from hs_sim.engine.effects import RandomDamage
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import ReplayError, build_replay, load_replay, replay, save_replay
from hs_sim.engine.serialization import event_to_dict


def make_registry(version="replay-fixture-v1"):
    registry = Registry(version)

    def random_bolt(context):
        opponent = context.state.players[3 - context.player_id]
        candidates = (opponent.hero_id, *opponent.board)
        return (RandomDamage(candidates, 2, context.source_id),)

    registry.register_behavior("random_bolt", random_bolt)
    registry.register_card(CardDefinition("hero", "测试英雄", CardType.HERO, health=30))
    registry.register_card(CardDefinition("soldier", "测试随从", CardType.MINION,
                                          cost=2, attack=2, health=3))
    registry.register_card(CardDefinition("random", "随机伤害", CardType.SPELL,
                                          cost=1, on_play="random_bolt"))
    return registry


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.registry = make_registry()

    def make_game(self, seed=47):
        scenario = Scenario(
            players=(
                PlayerSetup("hero", hand=("random", "random"), max_mana=10, mana=10),
                PlayerSetup("hero", board=("soldier", "soldier")),
            ),
            seed=seed,
            name="随机复现测试",
        )
        return Game.from_scenario(scenario, self.registry)

    def cast_random(self, game):
        entity_id = game.state.players[1].hand[0]
        return game.apply(PlayCard(1, entity_id))

    def completed_game(self, mode='release'):
        game = self.make_game()
        game.runtime_mode = mode
        self.cast_random(game)
        self.cast_random(game)
        game.apply(EndTurn(1))
        return game

    def test_seeded_actions_reproduce_state_events_and_history(self):
        first, second = self.make_game(), self.make_game()
        for _ in range(2):
            first_result = self.cast_random(first)
            second_result = self.cast_random(second)
            self.assertEqual(first_result.state_hash, second_result.state_hash)
            self.assertIsNone(first_result.state_hash)
            self.assertEqual(first.state_hash(), second.state_hash())
            self.assertEqual([event_to_dict(e) for e in first_result.events],
                             [event_to_dict(e) for e in second_result.events])
        payload = build_replay(first)
        restored = replay(payload, self.registry)
        self.assertEqual(restored.snapshot(), first.snapshot())
        self.assertEqual(restored.history, first.history)
        self.assertEqual(build_replay(restored), payload)

    def test_utf8_file_round_trip_accepts_bom_and_unicode_path(self):
        game = self.completed_game()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "对局回放.json"
            self.assertEqual(save_replay(game, path), path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload, build_replay(game))
            restored = load_replay(path, self.registry)
            self.assertEqual(restored.snapshot(), game.snapshot())
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
            self.assertEqual(load_replay(path, self.registry).state_hash(), game.state_hash())

    def test_tampered_state_and_event_hashes_report_exact_step(self):
        original = build_replay(self.completed_game('debug'))
        for name, index in (("state_hash", 0), ("events_hash", 1)):
            with self.subTest(name=name):
                payload = deepcopy(original)
                payload["actions"][index][name] = "0" * 64
                with self.assertRaises(ReplayError) as caught:
                    replay(payload, self.registry)
                self.assertEqual(caught.exception.step, index + 1)
                self.assertIn(f"{name} mismatch", str(caught.exception))

    def test_altered_or_malformed_actions_are_rejected_at_their_step(self):
        original = build_replay(self.completed_game('debug'))
        altered_actions = (
            {"type": "end_turn", "player_id": 2},
            {"type": "end_turn", "player_id": 1},
            {"type": "unimplemented", "player_id": 1},
            {"type": "play_card", "player_id": 1},
            {"type": "end_turn", "player_id": True},
        )
        for action in altered_actions:
            with self.subTest(action=action):
                payload = deepcopy(original)
                payload["actions"][0]["action"] = action
                with self.assertRaises(ReplayError) as caught:
                    replay(payload, self.registry)
                self.assertEqual(caught.exception.step, 1)

    def test_origin_rejects_incompatible_versions_and_registry(self):
        original = build_replay(self.make_game())
        for field, value in (("schema_version", 999), ("mechanics_version", "future-rules"),
                             ("registry_fingerprint", "0" * 64)):
            with self.subTest(field=field):
                payload = deepcopy(original)
                payload["origin"][field] = value
                with self.assertRaises(ReplayError) as caught:
                    replay(payload, self.registry)
                self.assertEqual(caught.exception.step, 0)
                self.assertIn("cannot restore origin", str(caught.exception))
        with self.assertRaises(ReplayError):
            replay(original, make_registry("different-registry-version"))

    def test_schema_rejects_unknown_missing_and_incorrectly_typed_fields(self):
        original = build_replay(self.completed_game())
        malformed = [None, [], {}, {**original, "extra": True}]
        for field, value in (("schema_version", True), ("schema_version", "1"),
                             ("schema_version", 3), ("origin", []), ("actions", {}),
                             ("final_state_hash", None), ("final_events_hash", 'A' * 64)):
            malformed.append({**original, field: value})
        for field in ("origin", "actions"):
            payload = deepcopy(original)
            del payload[field]
            malformed.append(payload)
        for record in (None, {}, {**original["actions"][0], "extra": None},
                       {**original["actions"][0], "action": []},
                       {**original["actions"][0], "state_hash": 1},
                       {**original["actions"][0], "events_hash": "A" * 64}):
            malformed.append({**original, "actions": [record]})
        for payload in malformed:
            with self.subTest(payload_type=type(payload).__name__), self.assertRaises(ReplayError):
                replay(payload, self.registry)

    def test_release_step_does_not_encode_or_hash_audit_payloads(self):
        game = self.make_game()
        with patch.object(Game, 'state_hash', side_effect=AssertionError('automatic state audit')), \
                patch('hs_sim.engine.game.canonical_hash', side_effect=AssertionError('automatic event audit')):
            result = self.cast_random(game)
        self.assertIsNone(result.state_hash)
        self.assertEqual(game.history[0]['state_hash'], None)
        self.assertEqual(game.history[0]['events_hash'], None)
        self.assertEqual(game.debug_records, ())
        # Export computes final commitments without re-running actions.
        with patch.object(Game, 'apply', side_effect=AssertionError('export must not simulate')):
            payload = build_replay(game)
        self.assertEqual(payload['schema_version'], 2)
        self.assertEqual(payload['final_state_hash'], game.state_hash())
        self.assertEqual(replay(payload, self.registry).snapshot(), game.snapshot())

    def test_release_replay_checks_complete_final_state_and_events(self):
        game = self.completed_game()
        original = build_replay(game)
        self.assertTrue(all(row['state_hash'] is row['events_hash'] is None for row in original['actions']))
        for field in ('final_state_hash', 'final_events_hash'):
            bad = deepcopy(original)
            bad[field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ReplayError) as caught:
                replay(bad, self.registry)
            self.assertIn(field, str(caught.exception))
            self.assertEqual(caught.exception.step, len(original['actions']))
        # The final check also covers truncation of an otherwise legal prefix.
        bad = deepcopy(original)
        bad['actions'].pop()
        with self.assertRaisesRegex(ReplayError, 'final_state_hash mismatch'):
            replay(bad, self.registry)
        with self.assertRaisesRegex(ReplayError, 'final_state_hash mismatch'):
            empty = build_replay(self.make_game())
            empty['final_state_hash'] = '0' * 64
            replay(empty, self.registry)

    def test_debug_and_legacy_replay_keep_exact_step_checks_in_release_reader(self):
        game = self.completed_game('debug')
        modern = build_replay(game)
        legacy = {key: deepcopy(modern[key]) for key in ('origin', 'actions')}
        legacy['schema_version'] = 1
        restored = replay(legacy, self.registry)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(build_replay(restored), modern)
        for field in ('state_hash', 'events_hash'):
            bad = deepcopy(legacy)
            bad['actions'][1][field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(ReplayError) as caught:
                replay(bad, self.registry)
            self.assertEqual(caught.exception.step, 2)
        legacy['actions'][0]['state_hash'] = None
        legacy['actions'][0]['events_hash'] = None
        with self.assertRaises(ReplayError):
            replay(legacy, self.registry)

    def test_mode_switch_records_only_requested_audits_and_replays_in_either_mode(self):
        game = self.make_game()
        self.cast_random(game)
        game.runtime_mode = 'debug'
        result = self.cast_random(game)
        self.assertEqual(result.state_hash, game.state_hash())
        self.assertEqual(game.debug_records[-1]['state_hash'], result.state_hash)
        game.runtime_mode = 'release'
        game.apply(EndTurn(1))
        payload = build_replay(game)
        self.assertEqual([row['state_hash'] is not None for row in payload['actions']], [False, True, False])
        for mode in ('release', 'debug'):
            restored = replay(payload, self.registry, mode=mode)
            self.assertEqual(restored.snapshot(), game.snapshot())
            self.assertEqual(build_replay(restored), payload)
        bad = deepcopy(payload)
        bad['actions'][0]['events_hash'] = '0' * 64
        with self.assertRaises(ReplayError):
            replay(bad, self.registry)

    def test_branch_origin_preserves_rng_and_does_not_embed_previous_actions(self):
        game = self.make_game()
        self.cast_random(game)
        midpoint = game.snapshot()
        branch = Game.from_snapshot(midpoint, self.registry)
        self.assertEqual(branch.history, [])
        original_result = self.cast_random(game)
        branch_result = self.cast_random(branch)
        self.assertEqual(original_result, branch_result)
        payload = build_replay(branch)
        self.assertEqual(len(payload["actions"]), 1)
        self.assertEqual(payload["origin"], midpoint)
        self.assertNotIn("history", payload["origin"])
        self.assertEqual(replay(payload, self.registry).snapshot(), game.snapshot())
        with tempfile.TemporaryDirectory() as folder:
            path = save_replay(branch, Path(folder) / "branch.json")
            self.assertEqual(load_replay(path, self.registry).snapshot(), game.snapshot())

    def test_exports_are_detached_and_empty_replays_restore_without_actions(self):
        game = self.make_game()
        empty = build_replay(game)
        self.assertEqual(replay(empty, self.registry).snapshot(), game.snapshot())
        self.cast_random(game)
        original = build_replay(game)
        exported = build_replay(game)
        exported["origin"].clear()
        exported["actions"][0]["action"].clear()
        self.assertEqual(build_replay(game), original)
        replay(original, self.registry)
        self.assertEqual(build_replay(game), original)

    def test_file_errors_and_ambiguous_json_are_wrapped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            with self.assertRaises(ReplayError):
                load_replay(path, self.registry)
            for content in ('{', '{"schema_version":1,"schema_version":1}',
                            '{"schema_version":NaN}', '{"schema_version":Infinity}'):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ReplayError) as caught:
                    load_replay(path, self.registry)
                self.assertEqual(caught.exception.step, 0)
            path.write_bytes(b"\xff\xfe\x00")
            with self.assertRaises(ReplayError):
                load_replay(path, self.registry)
            with self.assertRaises(ReplayError):
                save_replay(self.make_game(), Path(folder))


if __name__ == "__main__":
    unittest.main()
