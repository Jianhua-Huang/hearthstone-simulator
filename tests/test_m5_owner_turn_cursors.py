"""Actual opening and natural handoff, including rehashed cursor counterexamples."""
import json
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import Game, SnapshotError
from hs_sim.engine.serialization import canonical_hash


class CursorConsistencyTests(unittest.TestCase):
    setUp = fixtures.OwnerTurnActionTests.setUp
    constructed = fixtures.ConstructedOwnerTurnTests.constructed
    keep_mulligan = fixtures.ConstructedOwnerTurnTests.keep_mulligan
    fresh_registry = fixtures.OwnerTurnActionTests.fresh_registry
    game = fixtures.OwnerTurnActionTests.game
    end = fixtures.OwnerTurnActionTests.end
    portable = fixtures.OwnerTurnActionTests.portable

    def reject_rehashed(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as raised:
            Game.from_snapshot(snapshot, self.fresh_registry())
        self.assertNotIn('digest mismatch', str(raised.exception))

    def test_first_actual_cursor_cannot_move_into_completed_opening(self):
        game = self.constructed(first=2)
        self.keep_mulligan(game); self.keep_mulligan(game)
        self.portable(game)
        snapshot = game.snapshot()
        interval = snapshot['state']['owner_turn_history'][0]
        started = next(e for e in game.events if e.kind == 'game_started')
        self.assertEqual(started.sequence, interval['start_event']+1)
        snapshot['state']['owner_turn_history'][0]['start_event'] -= 1
        self.reject_rehashed(snapshot)

    def test_natural_handoff_cannot_leave_a_gap_between_close_and_start_event(self):
        game = self.game(); self.end(game)
        self.portable(game)
        snapshot = game.snapshot()
        before, after = snapshot['state']['owner_turn_history']
        self.assertEqual(before['closed_event'], after['start_event'])
        self.assertGreater(before['closed_event'], before['start_event'])
        before['closed_event'] -= 1
        self.reject_rehashed(snapshot)

    def test_natural_handoff_cannot_leave_a_gap_between_close_and_start_action(self):
        game = self.game(); self.end(game)
        self.portable(game)
        snapshot = game.snapshot()
        before, after = snapshot['state']['owner_turn_history']
        self.assertEqual(before['closed_action'], after['start_action'])
        self.assertGreater(before['closed_action'], before['start_action'])
        before['closed_action'] -= 1
        self.reject_rehashed(snapshot)
