"""Actual existing turn-start keyword expiry can suspend before start events."""
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import CardDefinition, CardType, EndTurn, Keyword, PlayCard, TimedKeywordSpec
from hs_sim.engine.effects import ChoiceOption, Damage, GainArmor, RequestChoice
from hs_sim.engine.model import TriggerSpec
from hs_sim.engine.resolver import PlayFromHand


class StartExpiryIntervalTests(unittest.TestCase):
    setUp = fixtures.OwnerTurnActionTests.setUp
    game = fixtures.OwnerTurnActionTests.game
    fresh_registry = fixtures.OwnerTurnActionTests.fresh_registry
    portable = fixtures.OwnerTurnActionTests.portable
    choose = fixtures.OwnerTurnActionTests.choose
    reject_rehashed = fixtures.OwnerTurnActionTests.reject_rehashed
    query = fixtures.OwnerTurnActionTests.query

    def startup_game(self, behavior, *, hand=()):
        self.r.register_card(CardDefinition('cloak-start', 'cloak-start', CardType.MINION,
            health=5, metadata=fixtures.metadata(), keywords=(Keyword.STEALTH,),
            timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),)))
        self.r.register_behavior('startup-expiry', behavior)
        self.r.register_card(CardDefinition('startup-watch', 'startup-watch', CardType.MINION,
            health=5, metadata=fixtures.metadata(), triggers=(TriggerSpec('attachments_expired', 'startup-expiry'),)))
        game = self.game(hand=hand, board=('cloak-start', 'startup-watch'))
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        return game

    def startup_paid_game(self, card):
        kind = self.r.card(card).kind
        return self.startup_game(lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('ok', 'ok', (PlayFromHand(PlayCard(c.player_id,
                next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == card),
                position=len(c.state.players[c.player_id].board) if kind == CardType.MINION else None)),)),),
            source_id=c.source_id)], hand=(card,))

    def test_real_started_interval_survives_start_expiry_waiting_before_begin_turn_events(self):
        self.r.register_card(CardDefinition('cloak-start', 'cloak-start', CardType.MINION,
            health=5, metadata=fixtures.metadata(), keywords=(Keyword.STEALTH,),
            timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),)))
        self.r.register_behavior('pause-start-expiry', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('ok', 'ok', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
        self.r.register_card(CardDefinition('start-expiry-watch', 'start-expiry-watch', CardType.MINION,
            health=5, metadata=fixtures.metadata(), triggers=(TriggerSpec('attachments_expired', 'pause-start-expiry'),)))
        game = self.game(board=('cloak-start', 'start-expiry-watch'))
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual((game.state.turn, game.state.active_player), (3, 1))
        self.assertEqual([(r.turn, r.closed) for r in game.state.owner_turn_history], [(1, True), (2, True), (3, False)])
        self.assertFalse(any(e.kind == 'turn_started' and dict(e.data).get('turn') == 3 for e in game.events))
        self.portable(game)
        snapshot = game.snapshot()
        continuation = snapshot['resolution_frame']['fields']['continuation']['tuple']
        saved = [w for w in continuation if type(w) is dict and w.get('type') == 'hs_sim.engine.resolver.BeginTurnEvents']
        self.assertEqual(len(saved), 1)
        continuation.remove(saved[0])
        self.reject_rehashed(snapshot)
        self.choose(game)
        self.assertTrue(any(e.kind == 'turn_started' and dict(e.data).get('turn') == 3 for e in game.events))
        row = game.state.owner_turn_history[-1]
        self.assertGreater(row.publication_action, row.start_action)
        self.portable(game)

    def test_real_expiry_lethal_records_preclear_start_interruption_without_publication(self):
        game = self.startup_game(lambda c: [Damage(c.state.players[2].hero_id, 50)])
        self.assertEqual((game.state.turn, game.state.status), (3, 'finished'))
        row = game.state.owner_turn_history[-1]
        self.assertFalse(row.closed)
        self.assertIsNone(row.publication_event)
        self.assertEqual((row.start_interruption.root_action, row.start_interruption.pending_work,
                          row.start_interruption.pending_count), (row.start_action, 'BeginTurnEvents', 1))
        self.assertFalse(any(e.kind == 'turn_started' and dict(e.data).get('turn') == 3 for e in game.events))
        self.assertEqual(self.query(game).owner_turn.turn, 1)
        snapshot = self.portable(game)
        snapshot['state']['owner_turn_history'][-1]['start_interruption'] = None
        self.reject_rehashed(snapshot)

    def test_interrupted_start_witness_cannot_rewrite_queued_work_count_or_terminal_cursor(self):
        game = self.startup_game(lambda c: [Damage(c.state.players[2].hero_id, 50)])
        for field, value in (('pending_count', 2), ('root_action', 1), ('game_ended_event', 1)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['owner_turn_history'][-1]['start_interruption'][field] = value
                self.reject_rehashed(snapshot)

    def test_real_paid_spell_waiting_before_publication_preserves_original_and_resumes_new_action(self):
        game = self.startup_paid_game('choice')
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        play, = game.state.play_history
        self.assertEqual(play.played_face.owner_turn_id, 3)
        self.assertIsNone(play.played_face.opening_stage)
        self.assertFalse(play.completed)
        self.assertIsNone(game.state.owner_turn_history[-1].publication_event)
        self.portable(game)
        self.choose(game)
        self.assertTrue(game.state.play_history[0].completed)
        row = game.state.owner_turn_history[-1]
        self.assertGreater(row.publication_action, play.action)
        snapshot = self.portable(game)
        snapshot['state']['owner_turn_history'][-1]['publication_action'] = row.start_action
        self.reject_rehashed(snapshot)

    def test_real_paid_battlecry_waiting_before_publication_closes_own_original_windows(self):
        self.r.register_card(CardDefinition('startup-bc', 'startup-bc', CardType.MINION,
            health=5, metadata=fixtures.metadata(('dragon',)), battlecry='choice'))
        game = self.startup_paid_game('startup-bc')
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.play_history[0].played_face.owner_turn_id, 3)
        self.assertIsNone(game.state.owner_turn_history[-1].publication_event)
        self.portable(game)
        self.choose(game)
        self.assertTrue(game.state.play_history[0].completed)
        self.assertTrue(all(b.completed for b in game.state.battlecry_history))
        self.assertIsNotNone(game.state.owner_turn_history[-1].publication_event)
        self.portable(game)

    def test_real_paid_terminal_spell_before_publication_keeps_committed_face_and_interrupts_root(self):
        game = self.startup_paid_game('terminal')
        self.choose(game)
        self.assertEqual(game.state.status, 'finished')
        play, = game.state.play_history
        self.assertEqual(play.played_face.owner_turn_id, 3)
        self.assertFalse(play.completed)
        row = game.state.owner_turn_history[-1]
        self.assertIsNotNone(row.start_interruption)
        self.assertEqual(row.start_interruption.root_action, row.start_action)
        self.assertGreater(row.start_interruption.game_ended_action, row.start_action)
        self.assertIsNone(row.publication_event)
        self.assertFalse(row.closed)
        self.portable(game)

    def test_published_start_event_pointer_cannot_be_removed_or_borrow_opponent_event(self):
        game = self.startup_game(lambda c: [])
        for event_id, action in ((None, None),
                (game.state.owner_turn_history[1].publication_event, game.state.owner_turn_history[1].publication_action)):
            with self.subTest(event=event_id):
                snapshot = game.snapshot()
                row = snapshot['state']['owner_turn_history'][-1]
                row['publication_event'], row['publication_action'] = event_id, action
                self.reject_rehashed(snapshot)
