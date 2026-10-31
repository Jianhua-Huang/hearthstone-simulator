"""All four activation carriers retain callback isolation and builtin purity."""
import unittest
from unittest.mock import patch

from hs_sim.engine import (ActivatedAbilitySpec, CardDefinition, CardType, Game,
    HandActionSpec, Keyword, PlayerSetup, Registry, Scenario)
from hs_sim.engine import hero_powers, locations, hand_actions, minion_abilities
from hs_sim.engine.player_api import context_factory


def fixture(callback=None, visibility='omniscient'):
    r = Registry('pure-use-context-test')
    r.register_behavior('nothing', lambda c: ())
    if callback is not None:
        r.register_use_rule('extension', callback, visibility=visibility)
    rule = 'extension' if callback is not None else 'always'
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, cost=2,
        on_use='nothing', use_rule=rule))
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30, initial_hero_power='power'))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=3))
    r.register_card(CardDefinition('location', 'Location', CardType.LOCATION, durability=3,
        on_use='nothing', use_rule=rule))
    r.register_card(CardDefinition('titan', 'Titan', CardType.MINION, attack=1, health=5,
        keywords=(Keyword.TITAN,), activated_abilities=tuple(
            ActivatedAbilitySpec('a'+str(n), 'nothing', use_rule=rule) for n in range(3))))
    r.register_card(CardDefinition('trade', 'Trade', CardType.SPELL, on_play='nothing',
        hand_actions=(HandActionSpec('trade', 'trade', 1, use_rule=rule),)))
    g = Game.from_scenario(Scenario((
        PlayerSetup('hero', hero_power_card_id='power', hand=('trade',), board=('location','titan'), deck=('plain',)*6,
                    mana=10, max_mana=10),
        PlayerSetup('hero', hero_power_card_id='power', hand=('trade',), deck=('plain',)*6)), seed=26), r)
    s=g._state;p=s.players[1];factory=context_factory(g,1)
    by_card={e.card_id:e for e in s.entities.values() if e.controller==1}
    return g, [
        (hero_powers, lambda:hero_powers.use_error(s,r,g.ruleset,p,by_card['power'],context_factory=factory)),
        (locations, lambda:locations.location_error(s,r,g.ruleset,1,by_card['location'].id,context_factory=factory)),
        (hand_actions, lambda:hand_actions.hand_action_error(s,r,p,by_card['trade'],'trade',context_factory=factory)),
        (minion_abilities, lambda:minion_abilities.ability_error(s,r,g.ruleset,1,by_card['titan'].id,'a0',None,context_factory=factory))]


class UseContextPerformanceTests(unittest.TestCase):
    def test_builtin_conditions_do_not_copy_state_for_any_carrier(self):
        g, queries=fixture();before=g.snapshot()
        for module,query in queries:
            with self.subTest(module=module.__name__), patch.object(module,'deepcopy',side_effect=AssertionError('state copy')):
                self.assertIsNone(query())
        self.assertEqual(g.snapshot(),before)

    def test_omniscient_callbacks_each_receive_detached_state(self):
        seen=[]
        def callback(c):
            seen.append(len(c.state.players[1].hand))
            c.state.players[1].hand.clear();c.state.entities.clear()
            return True
        g,queries=fixture(callback);before=g.snapshot()
        for _,query in queries:self.assertIsNone(query())
        self.assertEqual(seen,[1]*4)
        self.assertEqual(g.snapshot(),before)

    def test_player_callbacks_retain_safe_independent_observations(self):
        seen=[]
        def callback(c):
            self.assertFalse(hasattr(c,'state'))
            enemy=next(p for p in c.observation['players']if p['id']==2)
            self.assertIsNone(enemy['hand'][0]['card_id'])
            seen.append(len(c.observation['players']))
            c.observation['players'].clear();c.source.clear()
            return True
        g,queries=fixture(callback,'player');before=g.snapshot()
        for _,query in queries:self.assertIsNone(query())
        self.assertEqual(seen,[2]*4)
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
