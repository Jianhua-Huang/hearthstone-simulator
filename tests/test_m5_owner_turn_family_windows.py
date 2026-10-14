"""Real Combo/EndTurn history windows, including capture-clock negatives."""
from copy import deepcopy
import json
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, Keyword, SnapshotError
from hs_sim.engine.serialization import canonical_hash

def check_json_serializable(name, value):
    # Isolated RED artifacts are preserved; production tests do not write sources.
    json.dumps(value, ensure_ascii=False)


def works(snapshot):
    fields = snapshot['resolution_frame']['fields']
    return [*fields['prefix']['tuple'], *fields['continuation']['tuple']]


class AdditionalFamilyHistoryWindowTests(unittest.TestCase):
    setUp = fixtures.OwnerTurnActionTests.setUp
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    end = fixtures.OwnerTurnActionTests.end
    choose = fixtures.OwnerTurnActionTests.choose
    fresh_registry = fixtures.OwnerTurnActionTests.fresh_registry
    portable = fixtures.OwnerTurnActionTests.portable

    def history_game(self, next_card):
        game = self.game(hand=('dragon', next_card, 'arcane'))
        self.play(game, 'dragon')
        self.end(game); self.end(game)
        self.assertEqual([(row.turn, row.closed) for row in game.state.owner_turn_history],
                         [(1, True), (2, True), (3, False)])
        self.assertIsNotNone(game.state.owner_turn_history[-1].publication_event)
        face, = [play.played_face for play in game.state.play_history]
        self.assertEqual((face.owner_turn_id, face.card_id, face.metadata.tribes), (1, 'dragon', ('dragon',)))
        return game

    def original_window_negatives(self, game, family, select):
        original = self.portable(game)
        check_json_serializable(f'{family}-waiting-original', original)
        self.assertIsNotNone(game.state.pending_choice)
        for variant in ('immutable_start_cursor',):
            with self.subTest(family=family, original_fact=variant):
                bad = deepcopy(original)
                marker = select(works(bad))
                saved = marker['fields']['context']['fields']['state']['state']
                self.assertEqual(saved['owner_turn_history'][0]['start_event'],
                                 original['state']['owner_turn_history'][0]['start_event'])
                self.assertIsNotNone(saved['owner_turn_history'][-1]['publication_event'])
                saved['owner_turn_history'][0]['start_event'] += 1
                self.assertEqual(bad['state'], original['state'])
                self.assertEqual(bad['events'], original['events'])
                bad['state_hash'] = canonical_hash({k: v for k, v in bad.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                check_json_serializable(f'{family}-{variant}-mutated-original-window', bad)
                with self.assertRaises(SnapshotError) as raised:
                    Game.from_snapshot(bad, self.fresh_registry())
                self.assertNotIn('digest mismatch', str(raised.exception))
        # The complete current timeline published at action3, strictly before
        # this actual captured action5: pending is locally clock-inconsistent.
        observation = deepcopy(original)
        old = select(works(observation))['fields']['context']['fields']['state']['state']
        published = deepcopy(old['owner_turn_history'][-1])
        old['owner_turn_history'][-1]['publication_event'] = None
        old['owner_turn_history'][-1]['publication_action'] = None
        observation['state_hash'] = canonical_hash({k: v for k, v in observation.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        check_json_serializable(f'{family}-erased-publication-observation-snapshot', observation)
        self.assertGreater(old['action_number'], published['publication_action'])
        with self.assertRaises(SnapshotError) as publication_raised:
            Game.from_snapshot(observation, self.fresh_registry())
        error = str(publication_raised.exception)
        self.assertNotIn('digest mismatch', error)
        check_json_serializable(f'{family}-erased-publication-observation', {
            'scope': 'Actual later-window original publication deletion must reject by capture clock',
            'original_actual_interval': published,
            'original_context_action': old['action_number'],
            'original_context_play_history_actions': [(row['id'], row['action']) for row in old['play_history']],
            'original_context_event': select(works(original))['fields']['context']['fields']['event'],
            'current_state_unchanged': observation['state'] == original['state'],
            'full_event_timeline_unchanged': observation['events'] == original['events'],
            'restored': False, 'restore_error': error,
            'source_origin_authentication_claimed': False})
        self.assertEqual(game.snapshot(), original)
        self.choose(game)
        self.assertIsNone(game.state.pending_choice)
        self.portable(game)
        check_json_serializable(f'{family}-legal-completed', game.snapshot())
        return game

    def test_real_combo_waiting_binds_complete_old_owner_and_face_history(self):
        self.r.register_card(CardDefinition('h1-combo-choice', 'H1 Combo', CardType.MINION,
            health=5, metadata=fixtures.metadata(('beast',)), keywords=(Keyword.COMBO,), combo='choice'))
        game = self.history_game('h1-combo-choice')
        self.play(game, 'arcane')
        self.play(game, 'h1-combo-choice')
        play = game.state.play_history[-1]
        self.assertFalse(play.completed)
        self.assertEqual(play.played_face.owner_turn_id, 3)
        self.assertEqual(len(game.state.combo_history), 1)
        def select(items):
            matches = [item for item in items if type(item) is dict
                and item.get('type') == 'hs_sim.engine.combo_acceptance.FinishComboAcceptance'
                and item['fields']['phase'] == 'activation'
                and item['fields']['context']['fields']['play']['fields']['id'] == play.id]
            self.assertEqual(len(matches), 1)
            return matches[0]
        select(works(game.snapshot()))
        self.original_window_negatives(game, 'combo', select)
        self.assertTrue(game.state.play_history[-1].completed)
        self.assertTrue(all(record.completed for record in game.state.combo_history))

    def test_real_natural_end_turn_waiting_binds_complete_old_owner_and_face_history(self):
        game = self.history_game('end-watcher')
        self.play(game, 'end-watcher')
        self.end(game)
        self.assertEqual(game.state.turn, 3)
        self.assertFalse(game.state.owner_turn_history[-1].closed)
        self.assertIsNotNone(game.state.owner_turn_history[-1].end_event)
        self.assertEqual(len(game.state.end_turn_batches), 3)
        group = game.state.end_turn_batches[-1]
        self.assertFalse(group.completed)
        def select(items):
            matches = [item for item in items if type(item) is dict
                and item.get('type') == 'hs_sim.engine.end_turns.FinishEndTurnBatch'
                and item['fields']['batch']['fields']['id'] == group.id]
            self.assertEqual(len(matches), 1)
            return matches[0]
        marker = select(works(game.snapshot()))
        # Finish stores the exact pre-batch original state, not a virtual installed group.
        self.assertEqual(len(marker['fields']['context']['fields']['state']['state']['end_turn_batches']), group.id - 1)
        self.original_window_negatives(game, 'end-turn', select)
        self.assertTrue(game.state.end_turn_batches[-1].completed)
        self.assertTrue(all(record.completed for record in game.state.end_turn_history))
        self.assertTrue(game.state.owner_turn_history[2].closed)
        self.assertEqual((game.state.turn, game.state.active_player), (4, 2))
