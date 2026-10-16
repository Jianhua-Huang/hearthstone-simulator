"""Physical current Attack draw, original draw results and serializable waiting."""
import json
import unittest
from _conditional_battlecry_support import CardHelpers
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Zone
from hs_sim.engine.zones import DrawMinionWithAttack


class AttackFilteredDrawTests(CardHelpers,unittest.TestCase):
    def test_current_buffed_duplicate_face_selects_correct_physical_card(self):
        g=self.game(('k23.deck_lower','k23.draw'),deck=('k23.one','k23.one','k23.noop'))
        original=list(g.state.players[1].deck);self.play(g,'k23.deck_lower');self.play(g,'k23.draw')
        self.assertEqual(g.state.draw_history[0].entity_id,original[0])
        self.assertEqual(g.state.entities[original[0]].attack,0)
        self.assertEqual(g.state.players[1].deck,original[1:]);self.portable(g)

    def test_empty_deck_or_no_match_skip_without_fatigue_or_rng(self):
        for deck in ((),('k23.one','k23.noop')):
            g=self.game(('k23.draw',),deck=deck);before=g.snapshot()['rng_state'];self.play(g,'k23.draw')
            self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(g.state.draw_history)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_random_physical_selection_waiting_and_independent_replay(self):
        g=self.game(('k23.draw',),deck=('k23.zero','k23.zero'),board=('k23.watch',),mode='draw')
        candidates=set(g.state.players[1].deck);before=g.snapshot()['rng_state'];self.play(g,'k23.draw')
        self.assertIsNotNone(g.state.pending_choice);selected=g.state.draw_history[0].entity_id
        self.assertIn(selected,candidates);self.assertNotEqual(g.snapshot()['rng_state'],before)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);other=self.portable(g,'draw')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.draw_history[0].entity_id,selected)
        public=json.dumps(g.observe(2));self.assertNotIn('k23.zero',public);self.assertNotIn('rng_state',public)

    def test_request_itself_queued_across_choice_uses_original_codec(self):
        g=self.game(('k23.wait_draw',),deck=('k23.zero',));self.play(g,'k23.wait_draw')
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.draw_history)
        self.assertIn('DrawMinionWithAttack',json.dumps(g.snapshot()))
        other=self.portable(g)
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),1)

    def test_full_hand_retains_actual_draw_burn_and_no_replacement(self):
        g=self.game(('k23.burn_draw',),deck=('k23.zero','k23.one'))
        self.play(g,'k23.burn_draw')
        self.assertEqual(len(g.state.draw_history),1)
        self.assertEqual(g.state.draw_history[0].card_id,'k23.zero')
        self.assertEqual(g.state.entities[g.state.draw_history[0].entity_id].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len(g.state.players[1].deck),1)

    def test_unknown_source_rolls_back_and_request_rejects_invalid_shapes(self):
        g=self.game(('k23.invalid_source',),deck=('k23.zero',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k23.invalid_source')
        self.assertEqual(g.snapshot(),before)
        for args in ((0,0),(1,-1),(1,True),(1,0,0)):
            with self.assertRaises(ValueError):DrawMinionWithAttack(*args)
