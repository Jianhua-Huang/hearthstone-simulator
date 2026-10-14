"""Existing logical turn-cap behavior; no new mechanism or official profile claim."""
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction,
    PlayerSetup, Registry, ResolutionError, Ruleset, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.replay import build_replay, replay


def registry():
    r = Registry('logical-turn-limit-basics-v1')
    # A finite large health value keeps the existing fatigue path alive during
    # the actual 89-turn traversal; no immunity or other combination is installed.
    r.register_card(CardDefinition('limit.hero', 'Finite traversal hero', CardType.HERO, health=2000))
    r.register_card(CardDefinition('limit.hidden', 'Hidden card', CardType.MINION, health=1))
    def fail(c): raise ResolutionError('Deliberate end-boundary continuation failure')
    def wait(c):
        if c.event.player_id != c.player_id: return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('bad', 'Fail', (InvokeBehavior('limit.fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('limit.fail', fail)
    r.register_behavior('limit.wait', wait)
    r.register_card(CardDefinition('limit.waiter', 'End-boundary probe', CardType.MINION,
        health=1, triggers=(TriggerSpec('turn_ended', 'limit.wait'),)))
    return r


class LogicalTurnLimitTests(unittest.TestCase):
    def game(self, rules, *, first=1, waiting=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('limit.hero', board=('limit.waiter',) if waiting else (), max_mana=10, mana=10),
            PlayerSetup('limit.hero', hand=('limit.hidden',) if waiting else (), max_mana=10, mana=10),
        ), active_player=first, seed=887), registry(), ruleset=rules)
    def check(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, registry()).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snapshot)
    def choose(self, g, option='ok'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def test_actual_89_turn_configuration_stops_before_the_90th_start(self):
        g = self.game(Ruleset(draw_after_turn=89))
        self.assertEqual(g.ruleset.max_turns, 200)
        self.assertIsNone(Ruleset().draw_after_turn)
        for number in range(1, 89):
            self.assertEqual((g.state.status, g.state.turn), ('playing', number))
            g.apply(EndTurn(g.state.active_player))
        before = g.state
        self.assertEqual((before.turn, before.active_player), (89, 1))
        self.assertEqual([sum(r.player_id == p for r in before.owner_turn_history) for p in (1, 2)], [45, 44])
        draw_count = len(before.draw_history)
        result = g.apply(EndTurn(1)); after = g.state
        self.assertEqual((after.status, after.winner, after.turn, after.active_player), ('draw', None, 89, 1))
        self.assertEqual((len(after.owner_turn_history), len(after.draw_history)), (89, draw_count))
        self.assertTrue(after.owner_turn_history[-1].closed)
        self.assertEqual([e.kind for e in result.events if e.kind in ('turn_started', 'fatigue', 'card_drawn')], [])
        terminal = [e for e in result.events if e.kind == 'game_ended']
        self.assertEqual(len(terminal), 1)
        self.assertEqual(dict(terminal[0].data), {'reason': 'configured_draw_turn', 'result': 'draw'})
        for p in (1, 2): self.assertGreater(after.entities[after.players[p].hero_id].health, 0)
        self.assertEqual(g.legal_actions(), ())
        with self.assertRaises(IllegalAction): g.apply(EndTurn(1))
        self.check(g)

    def test_pending_natural_end_must_resume_before_the_configured_draw(self):
        g = self.game(Ruleset(max_turns=1, draw_after_turn=1), waiting=True)
        g.apply(EndTurn(1))
        self.assertEqual((g.state.status, g.state.turn), ('playing', 1))
        self.assertFalse(g.state.owner_turn_history[-1].closed)
        self.assertFalse(any(e.kind == 'game_ended' for e in g.events))
        self.assertNotIn('limit.hidden', json.dumps(g.for_player(1).observe()))
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry()); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual((g.state.status, g.state.winner, g.state.turn), ('draw', None, 1))
        self.assertTrue(g.state.owner_turn_history[-1].closed)
        self.assertEqual(g.state.draw_history, [])
        self.assertEqual(g.for_player(1).legal_actions()['actions'], [])
        self.check(g)
