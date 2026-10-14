"""The actual physical retained-result wire uses its own strict schema119."""
import unittest
from hs_sim.engine import Game, SnapshotError
from tests import test_generated_intrinsic_retention as intrinsic_fixture


class GeneratedIntrinsicSchemaBoundaryTests(unittest.TestCase):
    def test_current119_rejects_prior_wires_with_explicit_original_engine_error(self):
        game = intrinsic_fixture.GeneratedIntrinsicRetentionTests().prepared_game()
        snapshot = game.snapshot()
        self.assertEqual(snapshot['schema_version'], 266)
        for old in (1, 109, 117, 118):
            with self.subTest(schema=old):
                snapshot['schema_version'] = old
                with self.assertRaises(SnapshotError) as error:
                    Game.from_snapshot(snapshot, intrinsic_fixture.registry())
                self.assertIn('schemas 1 through 265 need their original engines', str(error.exception))
