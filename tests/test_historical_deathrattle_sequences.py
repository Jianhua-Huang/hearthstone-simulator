"""Umbra's actual multi-minion span retains every later selection while waiting."""
import unittest
import test_historical_deathrattle_cards as f


class HistoricalDeathrattleSequenceTests(unittest.TestCase):
    game = f.HistoricalDeathrattleTests.game
    entity = f.HistoricalDeathrattleTests.entity
    play = f.HistoricalDeathrattleTests.play
    kill = f.HistoricalDeathrattleTests.kill
    armor = f.HistoricalDeathrattleTests.armor
    roots = f.HistoricalDeathrattleTests.roots
    rows = f.HistoricalDeathrattleTests.rows
    choose = f.HistoricalDeathrattleTests.choose
    portable = f.HistoricalDeathrattleTests.portable

    @classmethod
    def setUpClass(cls):
        cls.r = f.registry()

    def test_each_selected_minion_keeps_its_waiting_span_and_middle_failure_rolls_back(self):
        g = self.game((f.P + 'kill',) * 3 + (f.UMBRA,), (f.WAIT,) * 3)
        for _ in range(3):
            self.kill(g, f.WAIT)
            self.choose(g)
        self.play(g, f.UMBRA)
        root = self.roots(g)[0]
        data = dict(root.data)
        self.assertEqual(len(data['selected']), 3)
        for index, carrier in enumerate(data['carriers']):
            self.assertIsNotNone(g.state.pending_choice)
            rows = self.rows(g)
            self.assertEqual(len(rows), index + 1)
            self.assertTrue(all(row.completed for row in rows[:-1]))
            self.assertEqual(rows[-1].capture.carrier_id, carrier)
            self.assertFalse(rows[-1].completed)
            self.portable(g)
            if index == 1:
                original = g.snapshot()
                with self.assertRaises(f.ResolutionError):
                    self.choose(g, 'bad')
                self.assertEqual(g.snapshot(), original)
            self.choose(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.armor(g), 18)
        self.assertTrue(all(row.completed for row in self.rows(g)))
        self.assertEqual(len(g.state.death_history), 3)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
