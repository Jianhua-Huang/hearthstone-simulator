"""Target contracts include original conditional windows and their parameters."""
import unittest
import test_public_body_grants as fixture
from hs_sim.engine import BodyReference, GrantBattlecry
from hs_sim.engine.actions import PlayCard
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Zone


def game(conditions, thresholds):
    r=fixture.registry()
    for name,condition,threshold in zip(('conditional_unit','conditional_donor'),conditions,thresholds):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=3,requires_target=True,
            battlecry='armor3'if name=='conditional_donor'else None,target_condition=condition,
            manathirst=threshold,keywords=(Keyword(condition),)if condition else ()))
    def grant(ctx):
        entity=next(e for e in ctx.state.entities.values()if e.card_id=='conditional_unit'and e.zone==Zone.HAND)
        return (GrantBattlecry(BodyReference.capture(entity),'conditional_donor',ctx.source_id),)
    r.register_behavior('conditional_grant',grant)
    r.register_card(CardDefinition('conditional_grant','Grant',CardType.SPELL,on_play='conditional_grant'))
    return Game.from_scenario(Scenario((PlayerSetup('hero',hand=('conditional_grant','conditional_unit'),mana=10,max_mana=10),
        PlayerSetup('hero',mana=10,max_mana=10))),r)


def play(g,name,target=None):
    s=g.state;eid=next(i for i in s.players[1].hand if s.entities[i].card_id==name)
    g.apply(PlayCard(1,eid,target))


class PublicBodyTargetContractTests(unittest.TestCase):
    def test_distinct_conditional_target_window_is_explicitly_rejected(self):
        g=game((None,'outcast'),(None,None));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'heterogeneous target dispatcher'):play(g,'conditional_grant')
        self.assertEqual(g.snapshot(),before)

    def test_distinct_manathirst_threshold_is_explicitly_rejected(self):
        g=game(('manathirst','manathirst'),(5,10));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'heterogeneous target dispatcher'):play(g,'conditional_grant')
        self.assertEqual(g.snapshot(),before)

    def test_matching_conditional_target_contract_executes_through_real_action(self):
        for condition,threshold in (('outcast',None),('manathirst',5)):
            with self.subTest(condition=condition):
                g=game((condition,condition),(threshold,threshold));play(g,'conditional_grant')
                play(g,'conditional_unit',g.state.players[2].hero_id)
                s=g.state;self.assertEqual(s.entities[s.players[1].hero_id].armor,3)
