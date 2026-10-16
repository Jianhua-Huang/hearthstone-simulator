"""Real payment, Hero Power targeting, disguised intrinsic cost and named Holy spell."""
from dataclasses import asdict
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.one_cost_basic_cards import load_batch
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,UseHeroPower,Keyword,PlayCard,PlayerSetup,Scenario,SpellSchool,Zone
from hs_sim.engine.effects import Damage,Destroy,RefreshMana,Silence,SpendMana
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import canonical_digest

CUB='CATA_130';CHAMELEON='FIR_908';DETECTIVE='JAIL_452';ECOLOGIST='TLC_820';VINES='TLC_813';YETI='CORE_CS2_182'


def registry():
    r=build_registry()
    for key,cost,body in [('one',1,lambda c:()),('zero',0,lambda c:()),
        ('spend',0,lambda c:(SpendMana(c.player_id,None,c.source_id),)),
        ('spend_zero',0,lambda c:(SpendMana(c.player_id,0,c.source_id),)),
        ('refresh',0,lambda c:(RefreshMana(c.player_id,1),)),
        ('kill',0,lambda c:(Destroy(c.target_id,c.source_id),)),
        ('silence',0,lambda c:(Silence(c.target_id),)),
        ('damage',0,lambda c:(Damage(c.target_id,2,c.source_id),)),
        ('summon',0,lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(DETECTIVE),),SummonCause.capture(c)),)),
        ('fail',1,lambda c:(_ for _ in ()).throw(ResolutionError('intentional failed root')))]:
        r.register_behavior('k57.'+key,body);r.register_card(CardDefinition('k57.'+key,key,CardType.SPELL,cost=cost,on_play='k57.'+key,requires_target=key in ('kill','silence','damage')))
    return r


class OneCostBasicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mana=20):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=hand,board=board,deck=(YETI,)*8,mana=mana,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_03',hand=enemy_hand,board=enemy,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20)),seed=1057),self.r)
    def find(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1,side=None):
        eid=self.find(g,cid,p).id;g.apply(PlayCard(p,eid,target,board_player_id=side));return eid
    def power(self,g):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,target_id=g.state.players[2].hero_id))
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def test_complete_five_pinned_faces_and_named_holy_dependency(self):
        data=load_batch();self.assertEqual([x['record']['id']for x in data['cards']],[CUB,CHAMELEON,DETECTIVE,ECOLOGIST])
        for x in data['cards']+data['dependencies']:self.assertEqual(canonical_digest(x['record']),x['record_sha256']);self.assertEqual(self.r.card(x['record']['id']).cost,1)
        self.assertEqual(self.r.card(VINES).spell_school,SpellSchool.HOLY);self.assertFalse(self.r.card(VINES).metadata.collectible)
        self.assertIsNone(self.r.card(DETECTIVE).battlecry);self.assertIsNotNone(self.r.card(DETECTIVE).on_play)
    def test_cub_grows_once_when_a_paid_card_spends_last_mana(self):
        g=self.game(('k57.one',),board=(CUB,),mana=1);self.play(g,'k57.one');e=self.find(g,CUB,zone='board');self.assertEqual((e.attack,e.health),(2,2));self.portable(g)
    def test_cub_does_not_grow_when_mana_remains(self):
        g=self.game(('k57.one',),board=(CUB,),mana=2);self.play(g,'k57.one');self.assertEqual(self.find(g,CUB,zone='board').attack,1)
    def test_zero_cost_at_zero_mana_is_not_spending_last_crystal(self):
        g=self.game(('k57.zero',),board=(CUB,),mana=0);self.play(g,'k57.zero');self.assertEqual(self.find(g,CUB,zone='board').attack,1)
    def test_cub_own_hand_payment_precedes_its_board_listener(self):
        g=self.game((CUB,),mana=1);eid=self.play(g,CUB);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,1))
    def test_two_cubs_each_receive_one_original_debit(self):
        g=self.game(('k57.one',),board=(CUB,CUB),mana=1);self.play(g,'k57.one');self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board],[2,2])
    def test_opponent_debit_does_not_grow_cub(self):
        g=self.game(board=(CUB,),enemy_hand=('k57.one',));g.apply(EndTurn(1));self.play(g,'k57.one',p=2);self.assertEqual(self.find(g,CUB,zone='board').attack,1)
    def test_hero_power_payment_can_spend_last_crystal(self):
        g=self.game(board=(CUB,),mana=2);self.power(g);self.assertEqual(self.find(g,CUB,zone='board').attack,2)
    def test_explicit_positive_mana_consumption_is_one_real_debit(self):
        g=self.game(('k57.spend',),board=(CUB,),mana=3);self.play(g,'k57.spend');self.assertEqual(self.find(g,CUB,zone='board').attack,2);self.assertEqual(len(g.state.mana_consumption_history),1)
    def test_zero_explicit_consumption_does_not_grow_cub(self):
        g=self.game(('k57.spend_zero',),board=(CUB,),mana=0);self.play(g,'k57.spend_zero');self.assertEqual(self.find(g,CUB,zone='board').attack,1)
    def test_refreshed_crystal_can_be_spent_again(self):
        g=self.game(('k57.one','k57.refresh','k57.one'),board=(CUB,),mana=1);self.play(g,'k57.one');self.play(g,'k57.refresh');self.play(g,'k57.one');self.assertEqual(self.find(g,CUB,zone='board').attack,3)
    def test_silenced_cub_no_longer_listens(self):
        g=self.game(('k57.silence','k57.one'),board=(CUB,),mana=1);self.play(g,'k57.silence',self.find(g,CUB,zone='board').id);self.play(g,'k57.one');self.assertEqual(self.find(g,CUB,zone='board').attack,1)
    def test_failure_after_payment_rolls_back_cub_and_original_accounts(self):
        g=self.game(('k57.fail',),board=(CUB,),mana=1);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k57.fail')
        self.assertEqual(g.snapshot(),before)
    def test_chameleon_without_power_has_no_target_and_no_reward(self):
        g=self.game((CHAMELEON,),board=(YETI,));self.play(g,CHAMELEON);e=self.find(g,YETI,zone='board');self.assertEqual((e.attack,e.health),(4,5));self.assertNotIn(Keyword.RUSH,e.keywords)
    def test_chameleon_cannot_invent_target_before_power_used(self):
        g=self.game((CHAMELEON,),board=(YETI,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CHAMELEON,self.find(g,YETI,zone='board').id)
        self.assertEqual(g.snapshot(),before)
    def test_chameleon_uses_real_current_turn_power_and_friendly_target(self):
        g=self.game((CHAMELEON,),board=(YETI,));self.power(g);self.play(g,CHAMELEON,self.find(g,YETI,zone='board').id);e=self.find(g,YETI,zone='board');self.assertEqual((e.attack,e.health),(5,7));self.assertIn(Keyword.RUSH,e.keywords);self.portable(g)
    def test_chameleon_cannot_target_enemy_after_power_used(self):
        g=self.game((CHAMELEON,),enemy=(YETI,));self.power(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CHAMELEON,self.find(g,YETI,2,'board').id)
        self.assertEqual(g.snapshot(),before)
    def test_chameleon_empty_board_remains_playable_after_power(self):
        g=self.game((CHAMELEON,));self.power(g);eid=self.play(g,CHAMELEON);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,2))
    def test_prior_turn_power_does_not_enable_chameleon(self):
        g=self.game((CHAMELEON,),board=(YETI,));self.power(g);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,CHAMELEON);self.assertEqual(self.find(g,YETI,zone='board').attack,4)
    def test_disguised_detective_own_side_overloads_actor(self):
        g=self.game((DETECTIVE,));eid=self.play(g,DETECTIVE);self.assertEqual((g.state.entities[eid].controller,g.state.players[1].overload_owed,g.state.players[2].overload_owed),(1,2,0))
    def test_disguised_detective_enemy_side_keeps_actor_payment_and_destination_debt(self):
        g=self.game((DETECTIVE,));eid=self.play(g,DETECTIVE,side=2);s=g.state;self.assertEqual((s.entities[eid].owner,s.entities[eid].controller,s.players[1].mana,s.players[1].overload_owed,s.players[2].overload_owed),(1,2,19,0,2));self.assertEqual((s.play_history[-1].player_id,s.play_history[-1].board_player_id),(1,2));self.portable(g)
    def test_selected_recipient_locks_crystals_at_its_next_start(self):
        g=self.game((DETECTIVE,));self.play(g,DETECTIVE,side=2);g.apply(EndTurn(1));self.assertEqual((g.state.players[2].overload_locked,g.state.players[2].overload_owed),(2,0))
    def test_direct_summon_does_not_execute_detective_intrinsic_play_body(self):
        g=self.game(('k57.summon',));self.play(g,'k57.summon');self.assertEqual(g.state.players[1].overload_owed,0)
    def test_ecologist_death_produces_exact_complete_holy_spell(self):
        g=self.game(('k57.kill',),board=(ECOLOGIST,));self.play(g,'k57.kill',self.find(g,ECOLOGIST,zone='board').id);self.assertEqual(self.find(g,VINES).base_cost,1);self.portable(g)
    def test_silenced_ecologist_does_not_produce_spell(self):
        g=self.game(('k57.silence','k57.kill'),board=(ECOLOGIST,));eid=self.find(g,ECOLOGIST,zone='board').id;self.play(g,'k57.silence',eid);self.play(g,'k57.kill',eid);self.assertFalse(any(e.card_id==VINES and e.zone==Zone.HAND for e in g.state.entities.values()))
    def test_vines_friendly_target_increases_max_and_current_health(self):
        g=self.game((VINES,),board=(YETI,));eid=self.find(g,YETI,zone='board').id;self.play(g,VINES,eid);e=g.state.entities[eid];self.assertEqual((e.attack,e.health,e.max_health),(4,7,7));self.portable(g)
    def test_vines_enemy_target_reduces_health_without_damage(self):
        g=self.game((VINES,),enemy=(YETI,));eid=self.find(g,YETI,2,'board').id;self.play(g,VINES,eid);e=g.state.entities[eid];self.assertEqual((e.attack,e.health,e.max_health),(4,3,3));self.assertFalse(any(x.kind=='damage'and x.target_id==eid for x in g.events))
    def test_vines_health_reduction_can_kill_through_divine_shield(self):
        g=self.game((VINES,),enemy=('CORE_EX1_008',));eid=self.find(g,'CORE_EX1_008',2,'board').id;self.play(g,VINES,eid);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertFalse(any(x.kind=='shield_lost'and x.target_id==eid for x in g.events))
    def test_vines_cannot_target_hero(self):
        g=self.game((VINES,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,VINES,g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),before)
    def test_public_queries_do_not_change_target_condition_or_snapshot(self):
        g=self.game((CHAMELEON,DETECTIVE,VINES),board=(YETI,));self.power(g);before=g.snapshot()
        for _ in range(2):g.for_player(1).observe();g.for_player(2).observe();g.legal_actions()
        self.assertEqual(g.snapshot(),before)


if __name__=='__main__':unittest.main()
