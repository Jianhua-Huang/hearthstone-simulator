import unittest
from hs_sim.cards.presence_cost_cards import load_batch
from hs_sim.engine import EndTurn,Game,PlayCard,PlayerSetup,Scenario,UseHandAction
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import Silence
from hs_sim.engine.model import PaymentType,Resource
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.replay import build_replay,replay
from test_cost_presence import registry
from hs_sim.targets import canonical_digest


class ConstructedPresenceCostCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy_hand=(),corpses=0,weapon=None):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=('k09.small',)*3,
            mana=30,max_mana=30,mana_cap=30,corpses=corpses,weapon_card_id=weapon),
            PlayerSetup('test.hero',hand=enemy_hand)),seed=91),self.r)
    def eid(self,g,cid,p=1):return next(e for e in g.state.players[p].hand if g.state.entities[e].card_id==cid)
    def price(self,g,cid,p=1):return quote_cost(g.state,g.registry,g.state.entities[self.eid(g,cid,p)]).amount
    def play(self,g,cid):g.apply(PlayCard(1,self.eid(g,cid)))
    def portable(self,g):
        s=g.snapshot()
        for other in (g.clone(),Game.from_snapshot(s,registry()),replay(build_replay(g),registry())):
            self.assertEqual(other.snapshot(),s)

    def test_all_seven_complete_pinned_roots_pay_using_declared_accounts(self):
        batch=load_batch();self.assertEqual(len(batch['cards']),7)
        for row in batch['cards']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            with self.subTest(card=cid):
                g=self.game((cid,),corpses=5);self.play(g,cid)
                self.assertEqual(g.state.play_history[-1].cost,row['record']['cost'])
                self.assertEqual(g.state.play_history[-1].payment,PaymentType.CORPSES if cid=='TLC_436' else PaymentType.MANA)

    def test_dread_corsair_reuses_current_equipped_weapon_attack(self):
        g=self.game(('CORE_NEW1_022',),weapon='CS2_106')
        self.assertEqual(self.price(g,'CORE_NEW1_022'),1);self.play(g,'CORE_NEW1_022')
        self.assertEqual(g.state.play_history[-1].cost,1);self.portable(g)

    def test_gronn_giant_uses_latest_actual_pre_self_hand_cost(self):
        g=self.game(('CATA_616','k09.dragon'))
        self.assertEqual(self.price(g,'CATA_616'),9);self.play(g,'k09.dragon')
        self.assertEqual(self.price(g,'CATA_616'),8);self.play(g,'CATA_616')
        self.assertEqual(g.state.play_history[-1].cost,8);self.portable(g)

    def test_reanimated_pterrordax_pays_corpses_without_spending_mana(self):
        g=self.game(('TLC_436',),corpses=5);self.play(g,'TLC_436')
        self.assertEqual((g.state.players[1].mana,g.state.players[1].resources[Resource.CORPSES]),(30,0));self.portable(g)
        g=self.game(('TLC_436',),corpses=4);s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'TLC_436')
        self.assertEqual(g.snapshot(),s)

    def test_captured_nathrezim_aura_affects_both_players_minions_but_not_spells(self):
        g=self.game(('JAIL_890','k09.dragon','k09.holy'),enemy_hand=('k09.dragon','k09.holy'))
        self.play(g,'JAIL_890')
        self.assertEqual([self.price(g,'k09.dragon',p) for p in (1,2)],[3,3])
        self.assertEqual([self.price(g,'k09.holy',p) for p in (1,2)],[0,0]);self.portable(g)

    def test_nathrezim_prepare_preserves_the_existing_lock_and_investment(self):
        g=self.game(('JAIL_890',));e=self.eid(g,'JAIL_890');g.apply(UseHandAction(1,e,'prepare'))
        self.assertEqual(self.price(g,'JAIL_890'),0)
        self.assertFalse(any(isinstance(a,PlayCard)and a.entity_id==e for a in g.legal_actions()))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'JAIL_890')
        self.assertEqual(g.state.play_history[-1].cost,0);self.portable(g)


if __name__=='__main__':unittest.main()
