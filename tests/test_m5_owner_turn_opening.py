"""Preserve proven pre-first paid route without fabricating an own interval."""
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import (CardDefinition, CardType, DeckPolicy, DeckSpec, Game, MatchSetup,
    OpeningHook, PlayCard, SelectChoice, SpellSchool)
from hs_sim.engine.effects import ChoiceOption, RequestChoice, Summon
from hs_sim.engine.model import TriggerSpec
from hs_sim.engine.resolver import PlayFromHand


class OpeningPaidPhaseTests(unittest.TestCase):
    setUp = fixtures.OwnerTurnActionTests.setUp
    fresh_registry = fixtures.OwnerTurnActionTests.fresh_registry
    portable = fixtures.OwnerTurnActionTests.portable
    reject_rehashed = fixtures.OwnerTurnActionTests.reject_rehashed
    school = fixtures.OwnerTurnActionTests.school
    choose = fixtures.OwnerTurnActionTests.choose

    def opening(self, *, payload_choice=False, actual_start_play=False):
        def free_play(c):
            source = next(i for i in c.state.players[c.player_id].hand
                          if c.state.entities[i].card_id == 'free')
            return [PlayFromHand(PlayCard(c.player_id, source))]
        self.r.register_behavior('free-play', free_play)
        self.r.register_card(CardDefinition('free', 'free', CardType.SPELL, spell_school=SpellSchool.ARCANE,
            on_play='choice' if payload_choice else 'nothing', metadata=fixtures.metadata()))
        self.r.register_card(CardDefinition('start-paid-watcher', 'start-paid-watcher', CardType.MINION,
            health=5, metadata=fixtures.metadata(), triggers=(TriggerSpec('turn_started', 'free-play'),)))
        def opening_plan(c):
            effects = (Summon(c.player_id, 'start-paid-watcher'),) if actual_start_play else tuple(free_play(c))
            return [RequestChoice(c.player_id, (ChoiceOption('pay', 'pay', effects),), source_id=c.source_id)]
        self.r.register_behavior('after-mulligan-paid', opening_plan)
        self.r.register_card(CardDefinition('paid-hook', 'paid-hook', CardType.MINION,
            health=5, metadata=fixtures.metadata(), opening_hooks=(OpeningHook('after_mulligan', 'after-mulligan-paid'),)))
        policy = DeckPolicy('h1-opening-paid', 'synthetic-h1-opening-paid', 'experimental', tuple(self.r.cards),
                            deck_size=8, max_copies=8)
        decks = (DeckSpec('hero1', 'power1', fixtures.CardClass.MAGE, ('paid-hook',)+('free',)*7),
                 DeckSpec('hero2', 'power2', fixtures.CardClass.WARRIOR, ('free',)*8))
        game = Game.from_decks(MatchSetup(decks, policy, 'coin', first_player=1), self.r)
        for _ in range(2):
            choice = game.state.pending_choice
            game.apply(SelectChoice(choice.player_id, choice.id, ()))
        self.assertEqual((game.state.opening.stage, game.state.action_number), ('starting', 2))
        self.assertEqual(game.state.owner_turn_history, [])
        self.assertFalse(game.state.play_history)
        self.portable(game)
        self.choose(game, 'pay')
        return game

    def test_after_mulligan_paid_route_completes_before_same_action_real_start(self):
        game = self.opening()
        self.assertEqual(game.state.opening.stage, 'complete')
        play, = game.state.play_history
        interval, = game.state.owner_turn_history
        self.assertEqual((play.action, interval.start_action), (3, 3))
        self.assertTrue(play.completed)
        self.assertEqual((play.played_face.owner_turn_id, play.played_face.opening_stage,
                          play.played_face.opening_first_player), (None, 'starting', 1))
        committed = next(e for e in game.events if e.kind == 'card_committed')
        self.assertLessEqual(committed.sequence, interval.start_event)
        self.assertFalse(self.school(game).matched)
        self.portable(game)

    def test_pre_first_body_choice_restores_with_paid_root_and_no_actual_interval(self):
        game = self.opening(payload_choice=True)
        self.assertEqual(game.state.opening.stage, 'starting')
        self.assertEqual(game.state.owner_turn_history, [])
        play, = game.state.play_history
        self.assertFalse(play.completed)
        self.assertIsNone(play.played_face.owner_turn_id)
        self.assertFalse(self.school(game).matched)
        self.portable(game); self.choose(game)
        self.assertEqual(game.state.opening.stage, 'complete')
        self.assertEqual((game.state.play_history[0].action, game.state.owner_turn_history[0].start_action), (3, 4))
        self.assertIsNone(game.state.play_history[0].played_face.owner_turn_id)
        self.portable(game)

    def test_same_action_pre_first_root_cannot_claim_actual_started_interval(self):
        game = self.opening(); snapshot = game.snapshot()
        face = snapshot['state']['play_history'][0]['played_face']
        face['owner_turn_id'], face['opening_stage'], face['opening_first_player'] = 1, None, None
        self.reject_rehashed(snapshot)

    def test_same_action_genuine_start_listener_root_cannot_claim_pre_first_phase(self):
        game = self.opening(actual_start_play=True)
        play, = game.state.play_history
        interval, = game.state.owner_turn_history
        self.assertEqual((play.action, interval.start_action), (3, 3))
        self.assertEqual(play.played_face.owner_turn_id, 1)
        self.assertIsNone(play.played_face.opening_stage)
        committed = next(e for e in game.events if e.kind == 'card_committed')
        self.assertGreater(committed.sequence, interval.start_event)
        self.portable(game)
        snapshot = game.snapshot(); face = snapshot['state']['play_history'][0]['played_face']
        face['owner_turn_id'], face['opening_stage'], face['opening_first_player'] = None, 'starting', 1
        self.reject_rehashed(snapshot)
