"""Independent real P1 closing combinations, only in a frozen-source copy."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import CardDefinition, CardType, Game, IntrinsicCostSpec, Keyword, PlayCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddCostModifier, ChoiceOption, Damage, GainArmor, RequestChoice
from hs_sim.engine.model import CostSpec, PaidHandClose, RewindSpec, TriggerSpec
from hs_sim.engine.paid_hand_acceptance import FinishPaidHandAcceptance, PaidHandChoiceBoundaryProof, set_progress
from hs_sim.engine.play_history import update_play
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_acceptance import FinishSpellAcceptance, _bind_live
from hs_sim.engine.spell_cost_proof import validate_hand_cost_proof_live
from hs_sim.engine import SnapshotError


def outer_body(context):
    source = next(identity for identity in context.state.players[context.player_id].hand
        if context.state.entities[identity].card_id == 'review.inner')
    action = PlayCard(context.player_id, source, position=len(context.state.players[context.player_id].board))
    return [RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Actually play inner hand Minion', (PlayFromHand(action),)),),
        source_id=context.source_id)]


def inner_body(context):
    return [RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Finish inner Minion', (GainArmor(context.player_id, 1),)),),
        source_id=context.source_id)]


def terminal_after_play(context):
    if context.play is None or context.play.card_id != 'review.terminal':
        return []
    return [RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Actual lethal completion reaction',
            (Damage(context.state.players[3-context.player_id].hero_id, 50),)),),
        source_id=context.source_id)]


def retry_body(context):
    return [RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Finish actual retry face',
            (GainArmor(context.player_id, context.rewind_attempt + 1),)),),
        source_id=context.source_id)]


def retry_payment(context):
    return [AddCostModifier(context.player_id,
        CostSpec(delta=-1, card_ids=('review.retry1',)), uses_remaining=1)]



def closed_then_wait(context):
    source = next(identity for identity in context.state.players[context.player_id].hand
        if context.state.entities[identity].card_id == 'review.same-action-inner')
    play = PlayFromHand(PlayCard(context.player_id, source,
        position=len(context.state.players[context.player_id].board)))
    after = RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Continue after naturally closed paid root',
            (GainArmor(context.player_id, 1),)),), source_id=context.source_id)
    return [RequestChoice(context.player_id,
        (ChoiceOption('ok', 'Actually play paid Minion then request another choice',
            (play, after)),), source_id=context.source_id)]

def registry():
    result = fixtures.registry()
    for identity, body in (('review.outer', outer_body), ('review.inner', inner_body),
            ('review.after', terminal_after_play), ('review.retry.body', retry_body),
            ('review.retry.payment', retry_payment)):
        result.register_behavior(identity, body)
    for identity, cost, body in (('review.outer', 2, 'review.outer'),
            ('review.inner', 3, 'review.inner'), ('review.terminal', 2, None)):
        result.register_card(CardDefinition(identity, identity, CardType.MINION,
            cost=cost, health=5, battlecry=body, metadata=fixtures.metadata()))
    result.register_card(CardDefinition('review.after', 'review.after', CardType.MINION,
        health=5, metadata=fixtures.metadata(),
        triggers=(TriggerSpec('card_played', 'review.after'),)))
    result.register_card(CardDefinition('review.retry.payment', 'review.retry.payment', CardType.SPELL,
        on_play='review.retry.payment', metadata=fixtures.metadata()))
    common = dict(cost=5, attack=1, health=5, battlecry='review.retry.body',
        metadata=fixtures.metadata(('dragon',)), intrinsic_costs=(IntrinsicCostSpec(delta=-3),))
    result.register_card(CardDefinition('review.retry1', 'review.retry1', CardType.MINION,
        rewind=RewindSpec(1, 'review.retry0'), keywords=(Keyword.REWIND,), **common))
    result.register_card(CardDefinition('review.retry0', 'review.retry0', CardType.MINION, **common))
    result.register_behavior('review.closed-then-wait', closed_then_wait)
    result.register_card(CardDefinition('review.closed-then-wait', 'review.closed-then-wait',
        CardType.SPELL, on_play='review.closed-then-wait', metadata=fixtures.metadata()))
    result.register_card(CardDefinition('review.same-action-inner', 'review.same-action-inner',
        CardType.MINION, cost=2, health=5, metadata=fixtures.metadata()))
    return result


class IndependentP1ClosingTests(unittest.TestCase):
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    end = fixtures.OwnerTurnActionTests.end
    choose = fixtures.OwnerTurnActionTests.choose

    def setUp(self):
        self.r = registry()

    def portable(self, game):
        saved = json.loads(json.dumps(game.snapshot()))
        fresh = registry()
        self.assertIsNot(fresh, self.r)
        self.assertEqual(fresh.fingerprint(), self.r.fingerprint())
        restored = Game.from_snapshot(saved, fresh)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry()).snapshot(), saved)
        return restored

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
            if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as raised:
            Game.from_snapshot(saved, registry())
        self.assertNotIn('digest mismatch', str(raised.exception))

    def tails(self, game):
        return [work for work in (*game._frame.prefix, *game._frame.continuation)
            if type(work) is FinishPaidHandAcceptance]

    def test_nested_actual_hand_roots_wait_and_close_inner_first(self):
        game = self.game(('review.outer', 'review.inner'))
        self.play(game, 'review.outer')
        self.portable(game)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        outer, inner = game.state.play_history
        self.assertEqual((outer.action, inner.action), (1, 2))
        self.assertEqual((outer.cost, inner.cost, game.state.players[1].mana), (2, 3, 5))
        self.assertEqual(tuple(tail.play_id for tail in self.tails(game)), (inner.id, outer.id))
        self.assertEqual(game._frame.paid_hand_acceptances, (inner.id, outer.id))
        restored = self.portable(game)
        queue = list(game._frame.continuation)
        locations = [index for index, work in enumerate(queue) if type(work) is FinishPaidHandAcceptance]
        self.assertEqual(len(locations), 2)
        queue[locations[0]], queue[locations[1]] = queue[locations[1]], queue[locations[0]]
        altered = replace(game._frame, continuation=tuple(queue))
        saved = game.snapshot()
        saved['resolution_frame'] = FrameCodec(game.mechanics, self.r).encode(altered)
        self.reject(saved)
        saved = game.snapshot()
        del saved['resolution_frame']['fields']['continuation']['tuple'][locations[0]]
        self.reject(saved)
        self.choose(game)
        self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertIsNone(game.state.pending_choice)
        closed_outer, closed_inner = game.state.play_history
        self.assertTrue(closed_outer.completed and closed_inner.completed)
        self.assertEqual((closed_outer.paid_hand_close.action, closed_inner.paid_hand_close.action), (3, 3))
        self.assertLess(closed_inner.paid_hand_close.event_cursor, closed_outer.paid_hand_close.event_cursor)
        self.assertEqual(tuple(row.amount for row in game.state.cost_use_history), (2, 3))
        self.portable(game)

    def test_completed_card_played_reaction_terminal_certifies_before_clear(self):
        game = self.game(('review.terminal',), board=('review.after',))
        self.play(game, 'review.terminal')
        play = game.state.play_history[-1]
        self.assertTrue(play.completed)
        self.assertIsNone(play.paid_hand_close)
        self.assertEqual(game._frame.paid_hand_acceptances, (play.id,))
        self.assertEqual(len(self.tails(game)), 1)
        self.portable(game)
        saved = game.snapshot()
        queue = saved['resolution_frame']['fields']['continuation']['tuple']
        queue[:] = [work for work in queue
            if not work.get('type', '').endswith('FinishPaidHandAcceptance')]
        self.reject(saved)
        self.choose(game)
        play = game.state.play_history[-1]
        self.assertNotEqual(game.state.status, 'playing')
        self.assertTrue(play.completed)
        self.assertFalse(play.interrupted)
        self.assertIsNone(play.paid_hand_close)
        interruption = play.paid_hand_interrupt
        self.assertIsNotNone(interruption)
        event = game.events[interruption.game_ended_event-1]
        self.assertEqual((event.kind, event.action), ('game_ended', interruption.action))
        self.assertIsNone(game._frame)
        self.assertEqual((game.state.players[1].mana, play.cost), (8, 2))
        self.portable(game)

    def test_nonspell_retry_changed_face_keeps_original_intrinsic_quote(self):
        game = self.game(('dragon', 'review.retry.payment', 'review.retry1'))
        self.play(game, 'dragon')
        self.end(game)
        self.end(game)
        self.play(game, 'review.retry.payment')
        source = self.play(game, 'review.retry1')
        self.assertEqual(game.state.play_history[-1].cost, 1)
        self.portable(game)
        self.choose(game)
        self.assertEqual(game.state.pending_choice.purpose.value, 'rewind')
        self.portable(game)
        self.choose(game, 'retry')
        self.assertIsNotNone(game.state.pending_choice)
        play = game.state.play_history[-1]
        tail, = self.tails(game)
        quote = play.submitted_cost.quote
        self.assertEqual((play.card_id, game.state.entities[source].card_id,
            tail.proof.payment_state.entities[source].card_id),
            ('review.retry0', 'review.retry0', 'review.retry0'))
        self.assertEqual((quote.quote_input.card_id, quote.intrinsic.card_id,
            quote.intrinsic.amount, quote.amount, play.submitted_cost.quote_origin),
            ('review.retry1', 'review.retry1', 2, 1, 'rewind_root'))
        self.assertEqual((tail.proof.rewind_anchor.attempt, tail.proof.rewind_session.attempt), (1, 1))
        self.assertEqual(tail.proof.rewind_anchor.before.entities[source].card_id, 'review.retry1')
        validate_hand_cost_proof_live(tail.proof, game)
        with self.assertRaises(ValueError):
            validate_hand_cost_proof_live(replace(tail.proof,
                rewind_anchor=None, rewind_session=None), game)
        restored = self.portable(game)
        self.choose(game)
        self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(game.state.players[1].mana, 9)
        self.assertEqual(sum(row.amount for row in game.state.cost_use_history if row.source_id == source), 1)
        self.assertIsNotNone(game.state.play_history[-1].paid_hand_close)
        self.portable(game)

    def test_action_five_original_window_cannot_erase_action_three_close(self):
        game = self.game(('frost', 'arcane', 'dragon', 'unschooled', 'choice'))
        for card in ('frost', 'arcane', 'dragon', 'unschooled'):
            self.play(game, card)
        prior = game.state.play_history[2]
        self.assertEqual(prior.paid_hand_close.action, 3)
        before = game.snapshot()
        with self.assertRaises(ValueError):
            set_progress(deepcopy(game.state), prior.id,
                close=PaidHandClose(game.state.action_number, len(game.events)))
        with self.assertRaises(ValueError):
            update_play(deepcopy(game.state), prior.id, paid_hand_close=None)
        self.assertEqual(game.snapshot(), before)
        self.play(game, 'choice')
        proof = next(work for work in (*game._frame.prefix, *game._frame.continuation)
            if type(work) is FinishSpellAcceptance)
        self.assertEqual(proof.resolution.state.action_number, 5)
        self.portable(game)
        altered_state = deepcopy(proof.resolution.state)
        altered_state.play_history[2] = replace(altered_state.play_history[2], paid_hand_close=None)
        altered = replace(proof, resolution=replace(proof.resolution, state=altered_state))
        with self.assertRaises(ValueError): _bind_live(game.state, altered, self.r)
        frame = replace(game._frame, continuation=tuple(altered if work is proof else work
            for work in game._frame.continuation))
        saved = game.snapshot()
        saved['resolution_frame'] = FrameCodec(game.mechanics, self.r).encode(frame)
        self.reject(saved)
        self.choose(game)
        self.assertEqual(game.state.play_history[2].paid_hand_close, prior.paid_hand_close)
        self.portable(game)


    def test_same_action_naturally_closed_root_then_empty_paid_waiting_stays_legal(self):
        game = self.game(('review.closed-then-wait', 'review.same-action-inner'))
        self.play(game, 'review.closed-then-wait')
        self.assertIsNotNone(game.state.pending_choice)
        self.portable(game)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        inner = game.state.play_history[-1]
        self.assertEqual((inner.card_id, inner.cost), ('review.same-action-inner', 2))
        self.assertTrue(inner.completed)
        self.assertEqual((inner.action, inner.paid_hand_close.action, game.state.action_number), (2, 2, 2))
        self.assertEqual(game._frame.paid_hand_acceptances, ())
        self.assertEqual(self.tails(game), [])
        boundary = game._frame.paid_hand_choice_boundary
        self.assertIs(type(boundary), PaidHandChoiceBoundaryProof)
        self.assertEqual(boundary.state.play_history[-1].paid_hand_close, inner.paid_hand_close)
        self.assertFalse(any(type(work) is FinishPaidHandAcceptance for work in boundary.work))
        self.assertLess(inner.paid_hand_close.event_cursor, boundary.event.sequence)
        original_close = inner.paid_hand_close
        restored = self.portable(game)
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual(game.state.play_history[-1].paid_hand_close, original_close)
        self.assertEqual(game.state.players[1].mana, 8)
        self.portable(game)


if __name__ == '__main__': unittest.main()
