"""Generated card faces have their full playable bodies, not placeholder tokens."""
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario


class ConditionalDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=build_registry()

    def game(self,hand,board=(),mana=30,deck=('CORE_CS2_182',)*3):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,
            deck=deck,mana=mana,max_mana=mana,mana_cap=max(10,mana)),PlayerSetup('test.hero'),)),self.registry)
    def play(self,g,cid,target=None):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,source,target_id=target));return source

    def test_all_six_plain_dependencies_have_real_stats_and_keywords(self):
        expected=[('AT_037t',1,1,()),('EX1_160t',3,2,()),('TSC_650t',6,6,(Keyword.TAUNT,)),
            ('TSC_650t4',1,1,(Keyword.RUSH,)),('UNG_809t1',1,2,()),('UNG_999t2t1',1,1,())]
        g=self.game(tuple(cid for cid,_,_,_ in expected))
        for cid,attack,health,keywords in expected:
            eid=self.play(g,cid);e=g.state.entities[eid]
            self.assertEqual((e.attack,e.health),(attack,health));self.assertEqual(e.keywords,set(keywords))

    def test_banana_and_detective_suit_buff_the_selected_minion_completely(self):
        g=self.game(('EX1_014t','JAIL_447t'),board=('CORE_CS2_182',));target=g.state.players[1].board[0]
        self.play(g,'EX1_014t',target);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(5,6))
        self.play(g,'JAIL_447t',target);e=g.state.entities[target]
        self.assertEqual((e.attack,e.health),(9,10));self.assertIn(Keyword.RUSH,e.keywords)

    def test_coin_deathrattle_reuses_the_real_temporary_mana_card(self):
        g=self.game(('JAIL_720','CORE_EX1_309'));eid=self.play(g,'JAIL_720')
        self.play(g,'CORE_EX1_309',eid)
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].hand],['GAME_005'])
        before=g.state.players[1].mana;self.play(g,'GAME_005')
        self.assertEqual(g.state.players[1].mana,before+1);self.assertEqual(g.state.players[1].max_mana,30)

    def test_empty_hand_quick_shot_draws_exactly_one_real_card(self):
        g=self.game(('CORE_BRM_013',));self.play(g,'CORE_BRM_013',g.state.players[2].hero_id)
        self.assertEqual(len(g.state.players[1].hand),1);self.assertEqual(len(g.state.draw_history),1)

    def test_zero_unused_mana_does_not_activate_crystal_merchant(self):
        g=self.game(('CORE_ULD_133',),mana=2);self.play(g,'CORE_ULD_133');g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand,[])
