"""A real accepted adjacent spell must tolerate its target dying before text."""
from functools import lru_cache
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario, TriggerSpec
from hs_sim.engine.effects import Destroy

CARDS = ('EX1_275','UNG_955','DEEP_032')
OBSERVER = 'k602.prebody_observer'


@lru_cache(None)
def registry():
    r = build_registry()
    def kill(c):
        return (Destroy(c.event.target_id,c.source_id),)if c.state.entities[c.event.source_id].card_id in CARDS else()
    r.register_behavior(OBSERVER,kill)
    r.register_card(CardDefinition(OBSERVER,OBSERVER,CardType.MINION,health=3,
        triggers=(TriggerSpec('card_committed',OBSERVER),)))
    return r


class PastMagePrebodyTargetTests(unittest.TestCase):
    def test_paid_original_target_removed_before_adjacent_text_does_not_refund_or_reselect(self):
        for cid in CARDS:
            with self.subTest(card=cid):
                g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),board=(OBSERVER,),mana=10,max_mana=10),
                    PlayerSetup('HERO_08',board=('CS2_033',))),seed=602),registry())
                source=g.state.players[1].hand[0];target=g.state.players[2].board[0]
                g.apply(PlayCard(1,source,target))
                self.assertEqual(g.state.players[1].mana,10-g.registry.card(cid).cost)
                self.assertNotIn(target,g.state.players[2].board)
                self.assertFalse(g.state.damage_history)
                self.assertTrue(g.state.play_history[-1].completed)
                self.assertIsNone(g.state.pending_choice)
