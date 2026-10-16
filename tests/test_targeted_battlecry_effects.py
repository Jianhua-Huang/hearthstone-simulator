"""Original-destruction continuations and current physical cheapest minion copy."""
import unittest
from _targeted_battlecry_support import TargetHelpers
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Zone
from hs_sim.engine.zones import CopyLowestCostMinion


class TargetedEffectTests(TargetHelpers,unittest.TestCase):
    def test_old_victim_cycle_does_not_destroy_same_id_new_incarnation_or_reward(self):
        g=self.game(('k24.wait_destroy',),board=('k24.plain',));target=self.body(g,'k24.plain').id
        entered=g.state.entities[target].entered_order;self.play(g,'k24.wait_destroy',target)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIn(target,g.state.players[1].board)
        self.assertNotEqual(g.state.entities[target].entered_order,entered)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_original_source_death_does_not_cancel_victim_destruction_or_revive_source(self):
        g=self.game(('k24.dead_beneficiary',),board=('CORE_EX1_198',),enemy=('k24.plain',))
        source=self.body(g,'CORE_EX1_198').id;target=self.body(g,'k24.plain',2).id
        self.play(g,'k24.dead_beneficiary',target)
        self.assertEqual((g.state.entities[source].zone,g.state.entities[target].zone),(Zone.GRAVEYARD,Zone.GRAVEYARD))

    def test_queued_control_does_not_take_same_id_new_residence(self):
        g=self.game(('k24.wait_control',),board=('k24.plain',));target=self.body(g,'k24.plain').id
        entered=g.state.entities[target].entered_order;self.play(g,'k24.wait_control',target)
        self.assertIn('TakeCapturedMinion',str(g.snapshot()));other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIn(target,g.state.players[1].board)
        self.assertNotEqual(g.state.entities[target].entered_order,entered)

    def test_paid_original_target_proof_survives_queued_choice_and_reentry(self):
        g=self.game(('k24.paid_take',),enemy=('CORE_EX1_008',));target=self.body(g,'CORE_EX1_008',2).id
        entered=g.state.entities[target].entered_order;self.play(g,'k24.paid_take',target)
        self.assertIn('TakeCapturedMinion',str(g.snapshot()));self.assertIsNotNone(g.state.pending_choice)
        other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIn(target,g.state.players[2].board)
        self.assertNotEqual(g.state.entities[target].entered_order,entered)

    def test_invalid_destroy_source_rolls_back_original_state(self):
        g=self.game(('k24.invalid_source',),board=('k24.plain',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k24.invalid_source',self.body(g,'k24.plain').id)
        self.assertEqual(g.snapshot(),before)

    def test_copy_request_queued_across_choice_keeps_original_codec_and_rng(self):
        g=self.game(('k24.wait_copy','k24.beast2','k24.beast2'));self.play(g,'k24.wait_copy')
        saved=g.snapshot();self.assertIn('CopyLowestCostMinion',str(saved))
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.players[1].hand),3)

    def test_copy_empty_or_unique_lowest_does_not_consume_rng(self):
        for hand in (('FIR_960',),('FIR_960','k24.beast2','k24.beast5')):
            g=self.game(hand);before=g.snapshot()['rng_state'];self.play(g,'FIR_960')
            self.assertEqual(g.snapshot()['rng_state'],before)

    def test_copy_unknown_current_tribes_explicit_and_shapes_validated(self):
        g=self.game(('FIR_960','k24.unknown'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Unknown current tribe'):self.play(g,'FIR_960')
        self.assertEqual(g.snapshot(),before)
        for args in ((0,('beast',)),(1,(1,)),(1,('beast',),0)):
            with self.assertRaises(ValueError):CopyLowestCostMinion(*args)
