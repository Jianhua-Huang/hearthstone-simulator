"""Prepared independent P1 closing/window probes; execute only after source freeze.

Use real card_played reaction -> RequestChoice -> PlayFromHand(child) -> child
ordinary Spell body RequestChoice. Parent is physically completed but still
owes its original payment tail. No custom dispatcher or direct state setup.
"""
from copy import deepcopy
import json
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import (CardDefinition, CardType, Game, IntrinsicCostSpec,
    PlayCard, SnapshotError, SpellSchool)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice
from hs_sim.engine.model import TriggerSpec
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash

OBSERVATIONS = []

def walk(value):
    if type(value) is dict:
        yield value
        for item in value.values(): yield from walk(item)
    elif type(value) is list:
        for item in value: yield from walk(item)


def live_work(frame):
    # The required boundary stores a second complete original work snapshot.
    # These negatives target the current live Spell control, not that proof.
    fields = frame['fields']
    return [*fields['prefix']['tuple'], *fields['continuation']['tuple']]


class IndependentPaidTailClosingTests(unittest.TestCase):
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    end = fixtures.OwnerTurnActionTests.end
    choose = fixtures.OwnerTurnActionTests.choose

    def build_registry(self):
        result = fixtures.registry()
        result.register_card(CardDefinition('independent-parent', 'independent-parent', CardType.MINION,
            cost=5, attack=1, health=5, metadata=fixtures.metadata(('dragon',)),
            intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))
        result.register_card(CardDefinition('independent-child', 'independent-child', CardType.SPELL,
            on_play='choice', spell_school=SpellSchool.ARCANE, metadata=fixtures.metadata()))

        def later_child(context):
            if context.play is None or context.play.card_id != 'independent-parent': return []
            child = next(identity for identity in context.state.players[context.player_id].hand
                         if context.state.entities[identity].card_id == 'independent-child')
            return [RequestChoice(context.player_id,
                (ChoiceOption('child', 'child', (PlayFromHand(PlayCard(context.player_id, child)),)),),
                source_id=context.source_id)]

        result.register_behavior('independent-later-child', later_child)
        result.register_card(CardDefinition('independent-watch', 'independent-watch', CardType.MINION,
            health=8, metadata=fixtures.metadata(),
            triggers=(TriggerSpec('card_played', 'independent-later-child'),)))

        result.register_card(CardDefinition('independent-plain', 'independent-plain', CardType.MINION,
            cost=2, health=5, metadata=fixtures.metadata()))
        def plain_wait(context):
            if context.play is None or context.play.card_id != 'independent-plain': return []
            return [RequestChoice(context.player_id,
                (ChoiceOption('ok', 'Complete ordinary callback',
                    (GainArmor(context.player_id, 1),)),), source_id=context.source_id)]
        result.register_behavior('independent-plain-watch', plain_wait)
        result.register_card(CardDefinition('independent-plain-watch', 'independent-plain-watch',
            CardType.MINION, health=8, metadata=fixtures.metadata(),
            triggers=(TriggerSpec('card_played', 'independent-plain-watch'),)))
        return result

    def completed_parent_then_later_paid_child(self):
        self.r = self.build_registry()
        game = self.game(('dragon', 'independent-parent', 'independent-child'), board=('independent-watch',))
        self.play(game, 'dragon'); self.end(game); self.end(game)
        self.play(game, 'independent-parent')
        parent = game.state.play_history[-1]
        self.assertTrue(parent.completed)
        self.assertIsNone(parent.paid_hand_close)
        self.assertEqual(parent.cost, 2)
        self.assertIsNotNone(game.state.pending_choice)
        self.portable(game)
        self.choose(game, 'child')
        parent, child = game.state.play_history[-2:]
        self.assertTrue(parent.completed)
        self.assertFalse(child.completed)
        self.assertEqual((parent.card_id, child.card_id), ('independent-parent', 'independent-child'))
        self.assertIsNone(parent.paid_hand_close)
        self.assertEqual(game._frame.paid_hand_acceptances, (parent.id,))
        self.assertIsNotNone(game.state.pending_choice)
        saved = self.portable(game)
        controls = [node for node in walk(live_work(saved['resolution_frame']))
            if node.get('type') == 'hs_sim.engine.spell_acceptance.FinishSpellAcceptance'
            and node['fields']['submission']['fields']['play']['fields']['id'] == child.id]
        self.assertEqual(len(controls), 1)
        for context_name in ('submission', 'resolution'):
            previous = controls[0]['fields'][context_name]['fields']['state']['state']['play_history'][parent.id-1]
            self.assertTrue(previous['completed'])
            self.assertIsNone(previous['paid_hand_close'])
            self.assertEqual(previous['submitted_cost'], saved['state']['play_history'][parent.id-1]['submitted_cost'])
        OBSERVATIONS.append({'case': 'legal-completed-parent-later-child-waiting', 'snapshot': saved,
            'parent_play_id': parent.id, 'child_play_id': child.id})
        return game, parent, child, saved

    def portable(self, game):
        saved = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, self.build_registry()).snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), self.build_registry()).snapshot(), saved)
        return saved

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({key:value for key,value in saved.items()
            if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        OBSERVATIONS.append({'case': 'freshrestore-negative-input', 'snapshot': deepcopy(saved)})
        with self.assertRaises(SnapshotError) as raised:
            accepted = Game.from_snapshot(saved, self.build_registry())
            OBSERVATIONS.append({'case': 'unexpected-negative-accepted', 'snapshot': accepted.snapshot()})
        self.assertNotIn('digest mismatch', str(raised.exception))
        return str(raised.exception)

    def finish_legal(self, game, parent, child):
        self.choose(game, 'ok')
        current_parent = game.state.play_history[parent.id-1]
        current_child = game.state.play_history[child.id-1]
        self.assertTrue(current_parent.completed and current_child.completed)
        self.assertIsNotNone(current_parent.paid_hand_close)
        self.assertIsNone(current_parent.paid_hand_interrupt)
        self.assertIsNone(game.state.pending_choice)
        self.assertIsNone(game._frame)
        self.portable(game)

    def test_completed_parent_with_later_spell_waiting_rejects_cut_tail_and_forged_close(self):
        game, parent, child, saved = self.completed_parent_then_later_paid_child()
        bad = deepcopy(saved)
        removed = 0
        for name in ('prefix', 'continuation'):
            work = bad['resolution_frame']['fields'][name]['tuple']
            selected = [item for item in work
                if item.get('type') == 'hs_sim.engine.paid_hand_acceptance.FinishPaidHandAcceptance'
                and item['fields']['proof']['fields']['prepared_play']['fields']['id'] == parent.id]
            removed += len(selected)
            bad['resolution_frame']['fields'][name]['tuple'] = [item for item in work if item not in selected]
        self.assertEqual(removed, 1)
        self.assertEqual(bad['resolution_frame']['fields']['paid_hand_acceptances']['tuple'], [parent.id])
        bad['resolution_frame']['fields']['paid_hand_acceptances']['tuple'] = []
        bad['state']['play_history'][parent.id-1]['paid_hand_close'] = {
            'action': game.state.action_number, 'event_cursor': len(game.events)}
        # Child original typed windows remain untouched and still show the
        # same parent with its genuinely unclosed original payment obligation.
        rejected = self.reject(bad)
        OBSERVATIONS.append({'case':'cut-parent-tail-and-forge-close', 'snapshot':bad,'rejection':rejected})
        self.assertEqual(game.snapshot(), saved)
        self.finish_legal(game, parent, child)

    def test_later_spell_original_cannot_forge_active_completed_parent_close(self):
        game, parent, child, saved = self.completed_parent_then_later_paid_child()
        bad = deepcopy(saved)
        controls = [node for node in walk(live_work(bad['resolution_frame']))
            if node.get('type') == 'hs_sim.engine.spell_acceptance.FinishSpellAcceptance'
            and node['fields']['submission']['fields']['play']['fields']['id'] == child.id]
        self.assertEqual(len(controls), 1)
        control = controls[0]['fields']
        originals = (
            control['cost_proof']['fields']['payment_state']['state'],
            control['submission']['fields']['state']['state'],
            control['resolution']['fields']['state']['state'],
        )
        for original in originals:
            record = original['play_history'][parent.id-1]
            self.assertTrue(record['completed'])
            self.assertIsNone(record['paid_hand_close'])
            record['paid_hand_close'] = {'action':game.state.action_number, 'event_cursor':len(game.events)}
        # The child's own prepay -> submission projection carries this same
        # change in all three originals; current parent and its actual tail
        # stay unchanged. This checks foreign provenance, not a broken quote.
        self.assertEqual(bad['state'], saved['state'])
        rejected = self.reject(bad)
        OBSERVATIONS.append({'case':'later-child-originals-forge-parent-close','snapshot':bad,'rejection':rejected})
        self.assertEqual(game.snapshot(), saved)
        self.finish_legal(game, parent, child)

    def test_plain_completed_waiting_cannot_forge_close_cut_tail_and_clear_obligations(self):
        self.r = self.build_registry()
        game = self.game(('independent-plain',), board=('independent-plain-watch',))
        self.play(game, 'independent-plain')
        parent = game.state.play_history[-1]
        self.assertTrue(parent.completed)
        self.assertIsNone(parent.paid_hand_close)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game._frame.paid_hand_acceptances, (parent.id,))
        saved = self.portable(game)
        original_action, original_cursor = game.state.action_number, len(game.events)
        restored = Game.from_snapshot(saved, self.build_registry())
        self.choose(game)
        self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertIsNotNone(game.state.play_history[-1].paid_hand_close)
        self.assertGreater(game.state.play_history[-1].paid_hand_close.action, original_action)
        self.portable(game)
        bad = deepcopy(saved)
        removed = 0
        for name in ('prefix', 'continuation'):
            queue = bad['resolution_frame']['fields'][name]['tuple']
            selected = [work for work in queue
                if work.get('type') == 'hs_sim.engine.paid_hand_acceptance.FinishPaidHandAcceptance'
                and work['fields']['proof']['fields']['prepared_play']['fields']['id'] == parent.id]
            removed += len(selected)
            bad['resolution_frame']['fields'][name]['tuple'] = [work for work in queue if work not in selected]
        self.assertEqual(removed, 1)
        self.assertEqual(bad['resolution_frame']['fields']['paid_hand_acceptances']['tuple'], [parent.id])
        bad['resolution_frame']['fields']['paid_hand_acceptances']['tuple'] = []
        bad['state']['play_history'][parent.id-1]['paid_hand_close'] = {
            'action': original_action, 'event_cursor': original_cursor}
        self.assertIsNotNone(bad['state']['pending_choice'])
        self.assertEqual(bad['state']['play_history'][parent.id-1]['submitted_cost'],
                         saved['state']['play_history'][parent.id-1]['submitted_cost'])
        OBSERVATIONS.append({'case': 'legal-plain-completed-waiting-before-tamper', 'snapshot': saved})
        self.reject(bad)
        self.assertEqual(game.snapshot(), restored.snapshot())

