"""Native public-action H1 integration candidate; no official timing claim."""
import unittest

from examples.owner_turn_history import ARCANE, BEAST, DRAGON, QUERY, UNSCHOOLED, run


class OwnerTurnNativeTests(unittest.TestCase):
    def test_frozen_face_and_nonactive_closed_interval_drive_paid_spell_choice(self):
        game, waiting, positions, observations = run()
        first, unschooled, arcane, query = game.state.play_history
        self.assertEqual([play.card_id for play in game.state.play_history],
                         [DRAGON, UNSCHOOLED, ARCANE, QUERY])
        self.assertEqual([play.cost for play in game.state.play_history], [1, 0, 2, 1])
        self.assertEqual(first.played_face.metadata.tribes, ('dragon',))
        self.assertEqual(game.state.entities[first.source_id].card_id, BEAST)
        self.assertEqual([value.player_id for value in game.state.owner_turn_history], [1, 2, 1])
        self.assertEqual([value.closed for value in game.state.owner_turn_history], [True, True, False])
        self.assertEqual([position['owner_turn_id'] for position in positions], [1, 3])
        self.assertEqual([position['paid'] for position in positions], [2, 1])
        self.assertEqual(len(waiting), 2)
        self.assertEqual(len(game.history), 8)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 5)
        self.assertEqual(observations['opponent_active'], observations['next_own_active'])
        self.assertTrue(observations['opponent_active']['dragon']['matched'])
        self.assertFalse(observations['opponent_active']['beast']['matched'])
        self.assertFalse(observations['opponent_active']['unschooled']['matched'])
        self.assertEqual([row['matched'] for row in observations['opponent_active']['arcane']['rows']],
                         [False, True])
        self.assertTrue(observations['unknown_query_rolled_back'])


if __name__ == '__main__':
    unittest.main()
