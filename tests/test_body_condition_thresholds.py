"""The documented physical-root Manathirst query is insufficient for grants."""
import unittest
import hs_sim.engine as engine
from hs_sim.engine import (BodyReference,GrantBattlecry,GrantCombo,CardDefinition,CardType,
    Keyword,Zone,Game,Scenario,PlayerSetup,PlayCard)
from hs_sim.engine.effects import GainArmor
from hs_sim.engine.registry import Registry


def registry(family):
    r=Registry('body-threshold-boundary-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('unit','Unit',CardType.MINION,health=5))
    def body(c):
        # The first branch demonstrates the existing documented query, without
        # inventing an internal attachment or silently omitting an effect.
        if not hasattr(engine,'BodyPlayReference'):
            return (GainArmor(c.player_id,5 if c.play.manathirst else 1),)
        ref=engine.BodyPlayReference.capture(c,family)
        return (engine.IfBodyCondition(ref,'manathirst',(GainArmor(c.player_id,5),),(GainArmor(c.player_id,1),)),)
    r.register_behavior('body',body)
    for threshold in (5,9):
        r.register_card(CardDefinition('threshold'+str(threshold),'Threshold',CardType.MINION,health=5,
            keywords=(Keyword.MANATHIRST,Keyword.COMBO)if family=='combo'else (Keyword.MANATHIRST,),
            manathirst=threshold,**{family:'body'}))
    def grant(c):
        e=next(e for e in c.state.entities.values()if e.card_id=='unit'and e.zone==Zone.HAND)
        kind=GrantBattlecry if family=='battlecry'else GrantCombo
        return tuple(kind(BodyReference.capture(e),'threshold'+str(t),c.source_id)for t in (5,9))
    r.register_behavior('grant',grant)
    r.register_card(CardDefinition('grant','Grant',CardType.SPELL,on_play='grant'))
    return r


class BodyThresholdBoundaryTests(unittest.TestCase):
    def check(self,family):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('grant','unit'),mana=6,max_mana=6),
            PlayerSetup('hero',mana=6,max_mana=6))),registry(family))
        for name in ('grant','unit'):
            s=g.state;e=next(i for i in s.players[1].hand if s.entities[i].card_id==name);g.apply(PlayCard(1,e))
        s=g.state
        self.assertFalse(s.play_history[-1].manathirst)
        self.assertEqual(s.entities[s.players[1].hero_id].armor,6)

    def test_granted_battlecries_use_their_own_distinct_manathirst_thresholds(self):self.check('battlecry')
    def test_granted_combos_use_their_own_distinct_manathirst_thresholds(self):self.check('combo')
