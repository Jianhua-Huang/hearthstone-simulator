"""Cross-layer paid-hand fee example; no official calibration claim."""
import unittest

from examples.spell_cost_matching import AFTER, BEFORE, MIDDLE, PROFILE, run
from hs_sim.engine.model import CardType


class SpellCostNativeTests(unittest.TestCase):
    def test_two_original_windows_keep_full_facts_and_quota_after_live_sources_change(self):
        game, waiting, positions = run()
        roots = [p for p in game.state.play_history if p.kind == CardType.SPELL]
        self.assertEqual([p.card_id for p in roots], [BEFORE, MIDDLE, AFTER])
        self.assertEqual([p.cost for p in roots], [1, 3, 3])
        self.assertEqual([p.submitted_cost.printed_cost for p in roots], [5, 5, 5])
        self.assertEqual([p.submitted_cost.quote.local_amount for p in roots], [1, 1, 1])
        self.assertEqual([p.spell_payload.casts for p in roots], [2, 3, 1])
        for root in roots:
            self.assertEqual(len(root.spell_submission.cost_facts.window_quotes), 1)
            self.assertEqual(len(root.spell_payload.cost_facts.window_quotes), 1)
            self.assertEqual(root.spell_submission.cost_facts.window_quotes[0].profile_id, PROFILE)
            self.assertEqual(root.spell_payload.cost_facts.window_quotes[0].profile_id, PROFILE)
            self.assertEqual(root.spell_submission.cost_facts.window_quotes[0].amount, 3)
            self.assertTrue(root.spell_acceptance_closed)
        self.assertEqual([p.spell_payload.cost_facts.window_quotes[0].amount for p in roots], [3, 1, 3])
        self.assertEqual([p['iteration'] for p in positions], [1, 2, 1, 2, 3, 1])
        self.assertEqual(len(waiting), 6)
        self.assertEqual(len(game.history), 10)
        self.assertEqual([m.uses_remaining for m in game.state.players[1].spell_modifiers], [1, 2])


if __name__ == '__main__':
    unittest.main()
