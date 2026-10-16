"""The new origin-aware private wire explicitly rejects previous schema117."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import unittest
from hs_sim.engine import Game, SnapshotError


class GeneratedComboSchemaBoundaryTests(unittest.TestCase):
    def test_previous117_schema_requires_its_original_engine(self):
        from tests.test_generated_combo_repetition import GeneratedComboRepetitionTests, registry
        game = GeneratedComboRepetitionTests().game()
        snapshot = game.snapshot()
        self.assertEqual(snapshot['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        snapshot['schema_version'] = 117
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, registry())
        self.assertIn(f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1} need their original engines', str(error.exception))
