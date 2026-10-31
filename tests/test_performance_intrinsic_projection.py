"""Retained fee validation keeps original histories and never copies all state."""
from dataclasses import replace
import unittest
from unittest.mock import patch

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IntrinsicCostSpec,
                           PlayCard, PlayerSetup, Scenario, SpellSchool)
from hs_sim.engine.intrinsic_costs import capture_intrinsic_stage, validate_intrinsic_history_prefix
from hs_sim.engine.model import GameState
from hs_sim.engine.serialization import state_to_dict


def retained(intrinsic):
    r = fixtures.registry()
    r.register_card(CardDefinition('priced', 'Priced', CardType.SPELL, cost=5,
        on_play='nothing', spell_school=SpellSchool.ARCANE, metadata=fixtures.metadata(),
        intrinsic_costs=(IntrinsicCostSpec(delta=-3),) if intrinsic else ()))
    g = Game.from_scenario(Scenario((
        PlayerSetup('hero1', hand=('arcane', 'frost', 'priced'), deck=('empty',)*6,
                    mana=10, max_mana=10),
        PlayerSetup('hero2', deck=('empty',)*6, mana=10, max_mana=10)), seed=17), r)
    arcane = next(i for i in g._state.players[1].hand if g._state.entities[i].card_id=='arcane')
    g.apply(PlayCard(1, arcane))
    g.apply(EndTurn(1))
    g.apply(EndTurn(2))
    fact = capture_intrinsic_stage(g._state, r, 1, 'priced', 5)
    frost = next(i for i in g._state.players[1].hand if g._state.entities[i].card_id=='frost')
    g.apply(PlayCard(1, frost))
    g.apply(EndTurn(1))
    g.apply(EndTurn(2))
    return g, fact


class IntrinsicProjectionPerformanceTests(unittest.TestCase):
    def test_original_prefix_accepts_real_later_progress_without_full_state_copy(self):
        for intrinsic in (False, True):
            with self.subTest(intrinsic=intrinsic):
                g, fact = retained(intrinsic)
                before = state_to_dict(g._state)
                with patch.object(GameState, '__deepcopy__', create=True,
                                  side_effect=AssertionError('entire state copied')):
                    validate_intrinsic_history_prefix(fact, g._state, g.registry)
                self.assertEqual(state_to_dict(g._state), before)

    def test_rejected_future_boundary_does_not_mutate_current_state(self):
        g, fact = retained(True)
        before = state_to_dict(g._state)
        changed = replace(fact, boundary=replace(fact.boundary,
            action=g._state.action_number+1))
        with self.assertRaises(ValueError):
            validate_intrinsic_history_prefix(changed, g._state, g.registry)
        self.assertEqual(state_to_dict(g._state), before)

    def test_rejected_history_omission_preserves_live_lists_and_opening(self):
        g, fact = retained(True)
        original = state_to_dict(g._state)
        # A captured boundary may not claim that genuine earlier plays vanished.
        changed = replace(fact, boundary=replace(fact.boundary, play_history_length=0))
        with self.assertRaises(ValueError):
            validate_intrinsic_history_prefix(changed, g._state, g.registry)
        self.assertEqual(state_to_dict(g._state), original)


if __name__ == '__main__':
    unittest.main()
