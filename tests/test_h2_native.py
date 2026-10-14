"""H2 native public-player composition; isolated synthetic candidate."""
import unittest
from examples.intrinsic_costs import MINION, SPELL, run

class IntrinsicNativeTests(unittest.TestCase):
    def test_both_real_owner_histories_intrinsic_layers_and_complete_paid_waiting(self):
        game, waiting, checkpoints, quotes, generated = run()
        self.assertEqual(len(waiting), 6)
        self.assertEqual([row['completed'] for row in checkpoints], [False,True,False,False,True,False])
        self.assertEqual([row['cost'] for row in checkpoints], [2,2,2,5,5,5])
        self.assertEqual([quotes[f'p{pid}.{card}']['amount'] for pid in (1,2) for card in (MINION,SPELL)], [2,2,5,5])
        self.assertEqual(quotes['p1.false']['rows'], [False,False,False])
        self.assertEqual(generated, {'intrinsic':2,'initial':4,'external':3,'minimum_final':6})
        self.assertEqual(quotes['p1.after-finite-use']['amount'], 3)
        self.assertTrue(all(play.completed for play in game.state.play_history))

if __name__=='__main__': unittest.main()
