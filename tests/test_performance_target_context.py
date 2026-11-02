"""Pure engine targets avoid copying; callback and information isolation remain."""
import unittest
from unittest.mock import patch

from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayerSetup,
                           Registry, Scenario, TargetSpec, Zone)
from hs_sim.engine.target_predicates import TargetPredicateSpec


def registry():
    r = Registry('target-context-performance-test')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=3))
    r.register_card(CardDefinition('weak', 'Weak', CardType.MINION, attack=1, health=2))
    r.register_card(CardDefinition('hidden', 'Hidden', CardType.SPELL))
    return r


def game(r, rule='any_character', spec=None):
    r.register_card(CardDefinition('test', 'Test', CardType.SPELL,
        requires_target=spec is None, target_rule=rule, targeting=spec))
    return Game.from_scenario(Scenario((
        PlayerSetup('hero', hand=('test',), board=('plain',), mana=10, max_mana=10),
        PlayerSetup('hero', hand=('hidden',), board=('weak',))), seed=8), r)


class TargetContextPerformanceTests(unittest.TestCase):
    def test_target_query_resolves_one_domain_and_does_not_cache_live_candidates(self):
        from hs_sim.engine import targeting
        g=game(registry());state=g._state
        source=state.entities[state.players[1].hand[0]]
        definition=g.registry.card(source.card_id)
        before=g.snapshot()
        expected=tuple(i for i in sorted(state.entities)
            if targeting.accepts_target(state,g.registry,source,definition,i))
        with patch.object(targeting,'effective_target_spec',wraps=targeting.effective_target_spec)as spec:
            self.assertEqual(targeting.target_choices(state,g.registry,source,definition),expected)
            self.assertEqual(spec.call_count,1)
        self.assertEqual(g.snapshot(),before)
        removed=state.players[2].board[0]
        state.entities[removed].doomed=True
        self.assertEqual(targeting.target_choices(state,g.registry,source,definition),
            tuple(i for i in expected if i!=removed))

    def test_builtin_targets_avoid_entire_state_copy_without_changing_results(self):
        g = game(registry())
        state = g._state
        source = state.players[1].hand[0]
        expected = {p.hero_id for p in state.players.values()} | {
            i for p in state.players.values() for i in p.board}
        before = g.snapshot()
        with patch('hs_sim.engine.targeting.deepcopy', side_effect=AssertionError('full state copy')):
            self.assertEqual(set(g.legal_targets(source)), expected)
            self.assertTrue(g.legal_actions())
        self.assertEqual(g.snapshot(), before)

    def test_declarative_predicates_keep_complete_filter_without_copy(self):
        r = registry()
        r.register_target_predicate(TargetPredicateSpec('low-health', health_max=2))
        g = game(r, 'low-health', TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        before = g.snapshot()
        with patch('hs_sim.engine.targeting.deepcopy', side_effect=AssertionError('full state copy')):
            self.assertEqual(g.legal_targets(g._state.players[1].hand[0]),
                             (g._state.players[2].board[0],))
        self.assertEqual(g.snapshot(), before)

    def test_omniscient_callback_mutation_is_detached_from_each_query(self):
        r = registry()
        seen, retained = [], []
        def callback(c):
            seen.append(len(c.state.players[1].hand))
            retained.append(c.state)
            c.state.players[1].hand.clear()
            c.state.entities.clear()
            return True
        r.register_target_rule('extension', callback)
        g = game(r, 'extension')
        before = g.snapshot()
        result = g.legal_targets(g._state.players[1].hand[0])
        self.assertGreaterEqual(len(result), 2)
        self.assertEqual(seen, [1] * len(seen))
        self.assertTrue(all(s is not g._state for s in retained))
        self.assertEqual(g.snapshot(), before)

    def test_player_callback_mutation_retains_fresh_private_safe_dtos(self):
        r = registry()
        seen = []
        def callback(c):
            enemy = next(p for p in c.observation['players'] if p['id'] == 2)
            self.assertIsNone(enemy['hand'][0]['card_id'])
            seen.append((len(c.observation['players']), c.source['card_id']))
            c.observation['players'].clear()
            c.source.clear()
            c.target.clear()
            return True
        r.register_target_rule('public-extension', callback, visibility='player')
        g = game(r, 'public-extension')
        before = g.snapshot()
        self.assertGreaterEqual(len(g.legal_targets(g._state.players[1].hand[0])), 2)
        self.assertEqual(seen, [(2, 'test')] * len(seen))
        self.assertEqual(g.snapshot(), before)

    def test_callbacks_cannot_self_declare_builtin_trust(self):
        r = registry()
        with self.assertRaises(ValueError):
            r.register_target_rule('fake-builtin', lambda c: True, visibility='builtin')


if __name__ == '__main__':
    unittest.main()
