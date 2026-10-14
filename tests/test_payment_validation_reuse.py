"""Behavioral safeguards for cheaper payment proof validation."""
from copy import deepcopy
from dataclasses import replace
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, PaymentType, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice
from hs_sim.engine.model import Resource
from hs_sim.engine.paid_hand_acceptance import (FinishPaidHandAcceptance,
    validate_queue, validate_tail)
from hs_sim.engine.payment_projection import (project_payment,
    validate_spell_payment_submission)
from hs_sim.engine.play_history import prepare_play
from hs_sim.engine.replay import build_replay, replay


def registry():
    result = Registry('payment-validation-reuse-tests')
    result.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    result.register_behavior('wait', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('ok', 'Resolve', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
    result.register_card(CardDefinition('unit', 'Unit', CardType.MINION,
        cost=2, health=3, battlecry='wait'))
    return result


class PaymentValidationReuseTests(unittest.TestCase):
    def game(self):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=('unit',), mana=10, max_mana=10),
            PlayerSetup('hero', mana=10, max_mana=10)), seed=17), registry())

    def payment(self, payment_type):
        game = self.game()
        before = game.state
        before.action_number += 1
        before.players[1].resources[Resource.CORPSES] = 4
        before.entities[before.players[1].hero_id].armor = 3
        source = before.entities[before.players[1].hand[0]]
        quote = replace(quote_cost(before, game.registry, source), payment=payment_type)
        prepared = prepare_play(before, game.registry, source, None, quote)
        projected = project_payment(before, quote, cause_reason='PlayFromHand')
        submitted = deepcopy(projected.final_state)
        submitted.play_history.append(prepared)
        return before, quote, prepared, projected, submitted

    def waiting(self):
        game = self.game()
        source = game.state.players[1].hand[0]
        game.apply(PlayCard(1, source))
        queue = (*game._frame.prefix, *game._frame.continuation)
        tail = next(work for work in queue if type(work) is FinishPaidHandAcceptance)
        return game, queue, tail

    def test_final_comparison_matches_staged_projection_for_every_currency(self):
        for payment_type in PaymentType:
            with self.subTest(payment=payment_type):
                before, quote, prepared, projected, submitted = self.payment(payment_type)
                untouched = deepcopy(before)
                validate_spell_payment_submission(before, quote, prepared, submitted)
                self.assertEqual(before, untouched)
                self.assertEqual(projected.final_state.play_history, [])

    def test_final_comparison_rejects_rewritten_resources_for_every_currency(self):
        for payment_type in PaymentType:
            with self.subTest(payment=payment_type):
                before, quote, prepared, _, submitted = self.payment(payment_type)
                submitted.players[1].mana -= 1
                with self.assertRaises(ValueError):
                    validate_spell_payment_submission(before, quote, prepared, submitted)

    def test_public_projection_keeps_all_stages_detached(self):
        before, _, _, projected, _ = self.payment(PaymentType.HEALTH)
        original = deepcopy(before)
        resource = deepcopy(projected.resource_state)
        captures = deepcopy(projected.captures)
        projected.final_state.players[1].hand.clear()
        projected.final_state.entities[before.players[1].hero_id].armor = 99
        self.assertEqual(before, original)
        self.assertEqual(projected.resource_state, resource)
        self.assertEqual(projected.captures, captures)
        projected.resource_state.players[1].hand.clear()
        self.assertEqual(projected.captures, captures)

    def test_next_queue_check_rejects_mutated_payment_proof(self):
        game, queue, tail = self.waiting()
        validate_queue(game._state, game.registry, queue, game=game)
        tail.proof.payment_state.players[1].mana -= 1
        with self.assertRaises(ValueError):
            validate_queue(game._state, game.registry, queue, game=game)

    def test_next_queue_check_rejects_mutated_submission_base(self):
        game, queue, tail = self.waiting()
        validate_queue(game._state, game.registry, queue, game=game)
        tail.submission_base.players[1].mana -= 1
        with self.assertRaises(ValueError):
            validate_queue(game._state, game.registry, queue, game=game)

    def test_missing_tail_is_rejected_after_a_successful_check(self):
        game, queue, tail = self.waiting()
        validate_queue(game._state, game.registry, queue, game=game)
        with self.assertRaises(ValueError):
            validate_queue(game._state, game.registry,
                tuple(work for work in queue if work is not tail), game=game)

    def test_submission_property_still_returns_an_independent_state(self):
        game, _, tail = self.waiting()
        submitted = tail.submission_state
        submitted.players[1].hand.clear()
        submitted.players[1].mana = 0
        self.assertNotEqual(submitted, tail.submission_state)
        self.assertIsNone(validate_tail(tail, game.registry))

    def test_waiting_restore_clone_replay_and_resume_are_identical(self):
        game, _, _ = self.waiting()
        snapshot = game.snapshot()
        copies = (game, Game.from_snapshot(snapshot, registry()), game.clone(),
                  replay(build_replay(game), registry()))
        for candidate in copies:
            self.assertEqual(candidate.snapshot(), snapshot)
            choice = candidate.state.pending_choice
            candidate.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
        self.assertTrue(all(candidate.snapshot() == game.snapshot() for candidate in copies))
        self.assertEqual(game.state.players[1].mana, 8)
        hero = game.state.entities[game.state.players[1].hero_id]
        self.assertEqual(hero.armor, 1)


if __name__ == '__main__':
    unittest.main()
