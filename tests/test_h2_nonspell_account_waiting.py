"""One necessary H2 cross-boundary: non-Mana paid Minion payment reactions.

Only real PlayCard/EndTurn/SelectChoice and registered public effects produce
the histories, finite fee source, account debit and waiting boundary. This is
a fresh candidate test, not evidence that the formal source already passed.
"""
from copy import deepcopy
import json
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game,
    IntrinsicCostSpec, PaymentType, PlayCard, PlayerSetup, ResolutionError,
    Scenario, SelectChoice)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, GainArmor,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.model import CostSpec, Resource, TriggerSpec
from hs_sim.engine.paid_hand_acceptance import (CHOICE_DIGEST,
    FinishPaidHandAcceptance, PaidHandChoiceBoundaryProof, validate_tail,
    validate_choice_boundary)
from hs_sim.engine.replay import build_replay, replay


SUBJECT = 'h2.account.waiting.minion'
PREPARE = 'h2.account.waiting.prepare'
WATCHER = 'h2.account.waiting.watcher'
FAIL = 'h2.account.waiting.fail'
FAIL_MESSAGE = 'H2 account waiting deliberate selection failure'


def fail_selection(context):
    raise ResolutionError(FAIL_MESSAGE)


def payment_reaction(context):
    source = context.event.source_id
    if (source is None or context.state.entities[source].card_id != SUBJECT
            or context.event.player_id != context.player_id):
        return []
    return [RequestChoice(context.player_id, (
        ChoiceOption('ok', 'Continue the paid Minion'),
        ChoiceOption('fail', 'Fail after a real resource effect', (
            GainArmor(context.player_id, 7),
            InvokeBehavior(FAIL, source, context.player_id),
        )),
    ), source_id=source)]


def registry(payment):
    result = fixtures.registry()
    result.register_behavior(FAIL, fail_selection)
    result.register_behavior(PREPARE, lambda context: [AddCostModifier(
        context.player_id, CostSpec(delta=-1, payment=payment,
            card_types=(CardType.MINION,), card_ids=(SUBJECT,)),
        uses_remaining=1, source_id=context.source_id)])
    result.register_behavior(SUBJECT, lambda context: [GainArmor(context.player_id, 2)])
    result.register_behavior(WATCHER, payment_reaction)
    result.register_card(CardDefinition(PREPARE, PREPARE, CardType.SPELL,
        on_play=PREPARE, metadata=fixtures.metadata()))
    result.register_card(CardDefinition(SUBJECT, SUBJECT, CardType.MINION,
        cost=5, attack=1, health=5, battlecry=SUBJECT,
        metadata=fixtures.metadata(('dragon',)),
        intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))
    result.register_card(CardDefinition(WATCHER, WATCHER, CardType.MINION,
        health=8, metadata=fixtures.metadata(),
        triggers=(TriggerSpec(payment.value + '_spent', WATCHER),)))
    return result


def amounts(state):
    player = state.players[1]
    hero = state.entities[player.hero_id]
    return (player.mana, hero.health, hero.armor,
        player.resources[Resource.CORPSES])


class NonSpellAccountWaitingTests(unittest.TestCase):
    def play(self, game, card):
        source = next(identity for identity in game.state.players[1].hand
            if game.state.entities[identity].card_id == card)
        kind = game.registry.card(card).kind
        game.apply(PlayCard(1, source, position=len(game.state.players[1].board)
            if kind == CardType.MINION else None))
        return source

    def portable(self, game, payment):
        saved = json.loads(json.dumps(game.snapshot()))
        independent = registry(payment)
        self.assertIsNot(independent, game.registry)
        self.assertEqual(independent.fingerprint(), game.registry.fingerprint())
        branches = (Game.from_snapshot(saved, independent), game.clone(),
            replay(build_replay(game), registry(payment)))
        for branch in branches:
            self.assertEqual(branch.snapshot(), saved)
        return branches

    def test_nonspell_nonmana_payment_reaction_waiting_keeps_original_tail_and_rolls_back_failed_resume(self):
        for payment in (PaymentType.HEALTH, PaymentType.ARMOR, PaymentType.CORPSES):
            with self.subTest(payment=payment):
                game = Game.from_scenario(Scenario((
                    PlayerSetup('hero1', hand=('beast', 'dragon', PREPARE, SUBJECT),
                        board=(WATCHER,), deck=('empty',) * 12, max_mana=10,
                        mana=10, armor=4 if payment == PaymentType.ARMOR else 0,
                        corpses=4 if payment == PaymentType.CORPSES else 0),
                    PlayerSetup('hero2', deck=('empty',) * 12, max_mana=10, mana=10),
                ), seed=1591), registry(payment))
                self.play(game, 'beast')
                self.play(game, 'dragon')
                game.apply(EndTurn(1))
                game.apply(EndTurn(2))
                self.play(game, PREPARE)
                before_amounts = amounts(game.state)
                source = self.play(game, SUBJECT)
                play = game.state.play_history[-1]
                quote = play.submitted_cost.quote
                self.assertEqual((play.kind, play.cost, play.payment),
                    (CardType.MINION, 1, payment))
                self.assertEqual((quote.intrinsic.amount, quote.local_amount,
                    quote.amount, quote.payment), (2, 2, 1, payment))
                self.assertEqual(tuple(row.matched for row in
                    quote.intrinsic.condition_facts[0].rows), (False, True))
                self.assertEqual(len(quote.consumable_ids), 1)
                self.assertFalse(game.state.players[1].cost_modifiers)
                expected_amounts = list(before_amounts)
                expected_amounts[{PaymentType.HEALTH: 1, PaymentType.ARMOR: 2,
                    PaymentType.CORPSES: 3}[payment]] -= 1
                self.assertEqual(amounts(game.state), tuple(expected_amounts))
                self.assertIsNotNone(game.state.pending_choice)
                self.assertFalse(play.completed)
                self.assertIsNone(play.paid_hand_close)
                self.assertEqual(game._frame.paid_hand_acceptances, (play.id,))
                tails = tuple(work for work in
                    (*game._frame.prefix, *game._frame.continuation)
                    if type(work) is FinishPaidHandAcceptance)
                self.assertEqual(len(tails), 1)
                tail, = tails
                self.assertEqual(tail.play_id, play.id)
                self.assertEqual(tail.proof.prepared_play.submitted_cost, play.submitted_cost)
                self.assertIsNone(tail.proof.prepared_play.combo_submission_receipt_id)
                self.assertEqual(amounts(tail.proof.payment_state), before_amounts)
                self.assertEqual(tail.proof.payment_state.players[1].cost_modifiers[0].uses_remaining, 1)
                self.assertEqual(amounts(tail.submission_state), tuple(expected_amounts))
                self.assertFalse(tail.submission_state.players[1].cost_modifiers)
                validate_tail(tail, game.registry)
                boundary = game._frame.paid_hand_choice_boundary
                self.assertIs(type(boundary), PaidHandChoiceBoundaryProof)
                self.assertEqual(tuple(work for work in boundary.work
                    if type(work) is FinishPaidHandAcceptance), tails)
                self.assertEqual(boundary.state.pending_choice, game.state.pending_choice)
                event = game.events[boundary.event.sequence - 1]
                self.assertEqual((event.kind, event.source_id), ('choice_requested', source))
                self.assertEqual(len(dict(event.data)[CHOICE_DIGEST]), 64)
                validate_choice_boundary(game)
                codec = FrameCodec(game.mechanics, game.registry)
                self.assertEqual(codec.decode(codec.encode(game._frame)), game._frame)
                branches = self.portable(game, payment)
                for branch in (game, *branches):
                    before = deepcopy(branch.snapshot())
                    history = deepcopy(branch.history)
                    replay_before = deepcopy(build_replay(branch))
                    pending = branch.state.pending_choice
                    with self.assertRaisesRegex(ResolutionError, FAIL_MESSAGE):
                        branch.apply(SelectChoice(pending.player_id, pending.id, ('fail',)))
                    self.assertEqual(branch.snapshot(), before)
                    self.assertEqual(branch.history, history)
                    self.assertEqual(build_replay(branch), replay_before)
                    validate_choice_boundary(branch)
                    pending = branch.state.pending_choice
                    branch.apply(SelectChoice(pending.player_id, pending.id, ('ok',)))
                for branch in branches:
                    self.assertEqual(branch.snapshot(), game.snapshot())
                final = game.state.play_history[-1]
                self.assertTrue(final.completed)
                self.assertIsNotNone(final.paid_hand_close)
                self.assertIsNone(final.paid_hand_interrupt)
                self.assertEqual(final.submitted_cost, play.submitted_cost)
                self.assertIsNone(game.state.pending_choice)
                self.assertIsNone(game._frame)
                expected_amounts[2] += 2
                self.assertEqual(amounts(game.state), tuple(expected_amounts))
                uses = [row for row in game.state.cost_use_history if row.source_id == source]
                spent = [event for event in game.events
                    if event.kind == payment.value + '_spent' and event.source_id == source]
                self.assertEqual((len(uses), len(spent)), (1, 1))
                self.assertEqual((uses[0].amount, uses[0].payment, uses[0].consumable_ids),
                    (1, payment, quote.consumable_ids))
                self.assertEqual(len([row for row in game.state.play_history
                    if row.source_id == source]), 1)
                self.portable(game, payment)


if __name__ == '__main__':
    unittest.main()
