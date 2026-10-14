"""Real non-Spell hand roots and their complete original payment tails."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

import test_h2_intrinsic_stage as stages
import test_m5_owner_turn_history as fixtures
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    SelectChoice, SnapshotError, SpellSchool)
from hs_sim.engine.effects import ChoiceOption, Damage, GainArmor, RequestChoice
from hs_sim.engine.interrupts import CounterMinion
from hs_sim.engine.model import RewindSpec, TriggerSpec
from hs_sim.engine.paid_hand_acceptance import FinishPaidHandAcceptance
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class PaidHandAcceptanceTests(unittest.TestCase):
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    end = fixtures.OwnerTurnActionTests.end
    choose = fixtures.OwnerTurnActionTests.choose

    def setUp(self):
        setup = stages.IntrinsicStageTests()
        setup.setUp()
        self.r = setup.r

    def closed_dragon(self, *hand, **kwargs):
        g = self.game(('dragon', *hand), **kwargs)
        self.play(g, 'dragon'); self.end(g); self.end(g)
        return g

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, self.r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), saved)
        return saved

    def reject(self, saved):
        saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, self.r)

    def tail(self, g):
        return next(work for work in (*g._frame.prefix, *g._frame.continuation)
                    if type(work) is FinishPaidHandAcceptance)

    def test_no_battlecry_minion_has_exact_payment_and_clocked_close(self):
        g = self.closed_dragon('intrinsic-minion')
        mana = g.state.players[1].mana
        self.play(g, 'intrinsic-minion')
        play = g.state.play_history[-1]
        self.assertEqual((play.cost, g.state.players[1].mana, play.submitted_cost.quote.intrinsic.amount), (2, mana-2, 2))
        self.assertTrue(play.completed)
        self.assertIsNotNone(play.paid_hand_close)
        self.assertIsNone(play.paid_hand_interrupt)
        self.assertEqual(play.paid_hand_close.action, play.action)
        self.portable(g)

    def test_countered_minion_waiting_preserves_proof_and_rejects_missing_or_borrowed_tail(self):
        def counter(c):
            if c.play is None or c.play.card_id != 'intrinsic-minion': return []
            return [RequestChoice(c.player_id, (ChoiceOption('counter','counter',
                (CounterMinion(dict(c.event.data)['window_id']),)),), source_id=c.source_id)]
        self.r.register_behavior('counter-choice', counter)
        self.r.register_card(CardDefinition('counter-choice', 'counter-choice', CardType.MINION,
            health=8, metadata=fixtures.metadata(), triggers=(TriggerSpec('card_committed','counter-choice'),)))
        g = self.closed_dragon('intrinsic-minion', enemy_board=('counter-choice',))
        self.play(g, 'intrinsic-minion')
        self.assertIsNotNone(g.state.pending_choice)
        saved = self.portable(g)
        del saved['resolution_frame']['fields']['continuation']['tuple'][-1]
        self.reject(saved)
        saved = g.snapshot()
        def tamper(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('PaidHandCostProof'):
                    value['fields']['payment_state']['state']['players']['1']['mana'] += 1
                    return True
                return any(tamper(v) for v in value.values())
            if isinstance(value,list): return any(tamper(v) for v in value)
            return False
        self.assertTrue(tamper(saved['resolution_frame']))
        self.reject(saved)
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id,pending.id,('counter',)))
        play = g.state.play_history[-1]
        self.assertTrue(play.countered and play.completed)
        self.assertIsNotNone(play.paid_hand_close)
        self.assertEqual(play.cost, 2)
        self.portable(g)

    def test_weapon_hero_location_empty_stages_preserve_full_payment(self):
        self.r.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, cost=1, attack=2,
            durability=2, metadata=fixtures.metadata()))
        self.r.register_card(CardDefinition('hero-card', 'hero-card', CardType.HERO, cost=1, health=30,
            hero_card=True, initial_hero_power='power1', metadata=fixtures.metadata()))
        self.r.register_card(CardDefinition('location', 'location', CardType.LOCATION, cost=1,
            durability=2, on_use='power', metadata=fixtures.metadata()))
        g = self.game(('weapon','hero-card','location'))
        for card in ('weapon','hero-card','location'):
            self.play(g, card)
            play = g.state.play_history[-1]
            self.assertEqual((play.cost,play.submitted_cost.quote.intrinsic.rules), (1, ()))
            self.assertIsNotNone(play.paid_hand_close)
            self.portable(g)

    def test_completed_card_played_waiting_still_owes_payment_tail(self):
        def choice(c):
            return ([RequestChoice(c.player_id,(ChoiceOption('ok','ok',(GainArmor(c.player_id,1),)),),
                source_id=c.source_id)] if c.play is not None and c.play.card_id == 'intrinsic-minion' else [])
        self.r.register_behavior('after-choice', choice)
        self.r.register_card(CardDefinition('after-choice','after-choice',CardType.MINION, health=8,
            metadata=fixtures.metadata(), triggers=(TriggerSpec('card_played','after-choice'),)))
        g = self.closed_dragon('intrinsic-minion', board=('after-choice',))
        self.play(g,'intrinsic-minion')
        play = g.state.play_history[-1]
        self.assertTrue(play.completed)
        self.assertIsNone(play.paid_hand_close)
        self.assertEqual(g._frame.paid_hand_acceptances,(play.id,))
        self.portable(g)
        saved = g.snapshot()
        saved['state']['play_history'][-1]['paid_hand_close']={'action':play.action,'event_cursor':len(g.events)}
        self.reject(saved)
        self.choose(g)
        self.assertIsNotNone(g.state.play_history[-1].paid_hand_close)
        self.portable(g)

    def test_battlecry_waiting_original_projection_and_terminal_interruption(self):
        self.r.register_card(replace(self.r.card('intrinsic-minion'), id='choice-minion', name='choice-minion', battlecry='choice'))
        g = self.closed_dragon('choice-minion')
        self.play(g,'choice-minion')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertIsNotNone(self.tail(g).proof.prepared_play.submitted_cost)
        self.portable(g)
        self.choose(g)
        self.portable(g)
        self.r = fixtures.registry()
        self.r.register_card(CardDefinition('lethal-minion','lethal-minion',CardType.MINION,cost=2,
            health=5,battlecry='terminal',metadata=fixtures.metadata()))
        terminal = self.game(('lethal-minion',))
        self.play(terminal,'lethal-minion')
        play = terminal.state.play_history[-1]
        self.assertTrue(play.interrupted)
        self.assertIsNone(play.paid_hand_close)
        self.assertIsNotNone(play.paid_hand_interrupt)
        self.assertEqual(play.cost,2)
        self.portable(terminal)

    def test_real_minion_rewind_preserves_original_quote_and_one_final_payment(self):
        from hs_sim.engine.model import IntrinsicCostSpec
        self.r.register_card(CardDefinition('retry-minion','retry-minion',CardType.MINION,cost=5,
            attack=1,health=5,battlecry='rewind',rewind=RewindSpec(1),keywords=(Keyword.REWIND,),
            metadata=fixtures.metadata(('dragon',)),intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))
        g = self.closed_dragon('retry-minion')
        self.play(g,'retry-minion')
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        self.choose(g,'retry')
        # RewindSpec(1) is exhausted by the actual retry. The default offer
        # automatically keeps the final result; it does not create another choice.
        self.assertIsNone(g.state.pending_choice)
        self.assertIsNone(g._rewind)
        play = g.state.play_history[-1]
        self.assertEqual((play.cost,play.submitted_cost.quote_origin),(2,'rewind_root'))
        self.portable(g)
        self.assertEqual(sum(row.amount for row in g.state.cost_use_history if row.source_id == play.source_id),2)
        self.assertIsNotNone(g.state.play_history[-1].paid_hand_close)
        self.portable(g)

    def test_later_original_window_cannot_erase_already_closed_paid_hand_clock(self):
        from hs_sim.engine.spell_acceptance import FinishSpellAcceptance
        g = self.game(('dragon', 'choice'))
        self.play(g, 'dragon')
        original_close = g.state.play_history[0].paid_hand_close
        self.assertIsNotNone(original_close)
        self.play(g, 'choice')
        self.assertGreater(g.state.action_number, original_close.action)
        self.portable(g)
        proof = next(work for work in (*g._frame.prefix,*g._frame.continuation)
                     if type(work) is FinishSpellAcceptance)
        self.assertIsNotNone(proof.resolution)
        altered_state = deepcopy(proof.resolution.state)
        altered_state.play_history[0] = replace(altered_state.play_history[0], paid_hand_close=None)
        altered_context = replace(proof.resolution, state=altered_state)
        malformed = replace(proof, resolution=altered_context)
        from hs_sim.engine.spell_acceptance import validate_acceptance, _bind_live
        with self.assertRaises(ValueError): _bind_live(g.state, malformed, self.r)
        from hs_sim.engine.continuations import FrameCodec
        changed_frame = replace(g._frame, continuation=tuple(malformed if work is proof else work
                                for work in g._frame.continuation))
        saved = g.snapshot()
        saved['resolution_frame'] = FrameCodec(g.mechanics,self.r).encode(changed_frame)
        self.reject(saved)
        validate_acceptance(proof, self.r)
        self.choose(g)
        self.portable(g)


if __name__ == '__main__': unittest.main()
