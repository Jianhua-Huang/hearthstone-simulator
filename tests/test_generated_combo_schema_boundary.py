"""The new origin-aware private wire explicitly rejects previous schema117."""
import unittest
from hs_sim.engine import Game, SnapshotError


class GeneratedComboSchemaBoundaryTests(unittest.TestCase):
    def test_previous117_schema_requires_its_original_engine(self):
        from tests.test_generated_combo_repetition import GeneratedComboRepetitionTests, registry
        game = GeneratedComboRepetitionTests().game()
        snapshot = game.snapshot()
        self.assertEqual(snapshot['schema_version'], 266)
        snapshot['schema_version'] = 117
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, registry())
        self.assertIn('schemas 1 through 265 need their original engines', str(error.exception))
