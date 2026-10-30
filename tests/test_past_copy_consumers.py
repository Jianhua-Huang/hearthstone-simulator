"""Real copy consumers, frozen recipes, capacity and continuation boundaries."""
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_copy_consumers as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (Buff,ChoiceOption,Destroy,Draw,GainArmor,InvokeBehavior,ModifyCost,
    RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.zones import CardReference
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.registry import Registry
from hs_sim.local_pool_format import build_cn37_local_pool_format

VOONE,LADY,ZAI,PIP,VORAZJ,FREYA,ARUGAL,DORIAN,NEW_DORIAN,ROCK=native.ROOTS
P='k700.';A=P+'beast';B=P+'dragon';C=P+'plain';DUAL=P+'dual';ALL=P+'all';BOTH=P+'both'
FROST=P+'frost';FIRE=P+'fire';DRAW=P+'draw';KILL=P+'kill';BUFF=P+'buff';ONE=P+'one';TWO=P+'two';HUSH=P+'hush'
WATCH=P+'watch';S_WATCH=P+'summon_watch';FAIL=P+'fail'
HELPERS=(A,B,C,DUAL,ALL,BOTH,FROST,FIRE,DRAW,KILL,BUFF,ONE,TWO,HUSH,WATCH,S_WATCH)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    r.register_behavior(P+'unit',lambda c:(GainArmor(c.player_id,7),))
    for cid,tribes in((A,('beast',)),(B,('dragon',)),(C,()),(DUAL,('beast','dragon')),(ALL,('all',)),(BOTH,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=4,health=6,battlecry=P+'unit',
            choose_both=cid==BOTH,metadata=replace(meta,tribes=tribes)))
    for cid,school in((FROST,SpellSchool.FROST),(FIRE,SpellSchool.FIRE)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,spell_school=school,metadata=meta))
    bodies={DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        BUFF:lambda c:((BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,3,c.source_id),)
            if c.state.entities[c.target_id].zone==Zone.HAND else(Buff(c.target_id,2,3,c.source_id),)),
        ONE:lambda c:(ModifyCost(c.target_id,CostSpec(set_to=1),c.source_id),),
        TWO:lambda c:(ModifyCost(c.target_id,CostSpec(set_to=2),c.source_id),),HUSH:lambda c:(Silence(c.target_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0,on_play=cid,metadata=meta,
            targeting=None if cid==DRAW else TargetSpec(zones=(Zone.BOARD,Zone.HAND),kinds=(CardType.MINION,CardType.SPELL,))))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K700 deliberate copy continuation failure')))
    def waiting(c):
        source=c.state.entities.get(c.event.source_id)
        board_copy=c.event.kind=='minion_summoned'and 'copied_from'in dict(c.event.data)
        if source is None or (not board_copy if c.event.kind=='minion_summoned'else source.card_id not in native.ROOTS):return()
        original=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==B and i<c.event.source_id),None)
        move=()if original is None else(ChoiceOption('move','Return original dragon',(ReturnToHand(original),)),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),*move),c.source_id),)
    r.register_behavior(WATCH,waiting)
    for cid,event in((WATCH,'card_created'),(S_WATCH,'minion_summoned')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k700-past-copy-consumers-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in ('HERO_08','HERO_08bp','TIME_013',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_copy_consumers(r);r.validate();return r


class PastCopyConsumerTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(),enemy_hand=(),watch=None,real_host=False):
        self.mode='host'if real_host else'small';h=host('writer')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp',weapon_card_id=watch),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp')),
            seed=700,generation_context=h.context if real_host else None),h.registry if real_host else fixture('writer'))
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def freya(self,g,branch):
        eid=self.entity(g,FREYA,1,'hand').id;g.apply(PlayCard(1,eid,branch_id=branch));return eid
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_original_records_and_real_choice_roles(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),22)
        for row in d['cards']+d['dependencies']:
            self.assertEqual(r.card(row['record']['id']),native.make_definition(row['record']))
        for cid in native.DEPENDENCIES:
            self.assertTrue(r.card(cid).choice_only);self.assertNotIn(cid,r.pool_cards)
        self.assertEqual([x.id for x in r.card(FREYA).choose_one.branches],[native.HAND_OPTION,native.BOARD_OPTION])

    def test_voone_copies_only_current_dragons_and_all_types_in_original_order(self):
        g=self.game((VOONE,A,B,C,ALL));self.play(g,VOONE)
        self.assertEqual(self.hand(g),[A,B,C,ALL,B,ALL]);self.assertEqual(self.hero(g).armor,0)
        self.assertEqual(g.state.players[1].mana,30-g.registry.card(VOONE).cost)

    def test_hand_copy_preserves_current_buff_and_discount_without_copying_source(self):
        g=self.game((BUFF,ONE,VOONE,B));original=self.entity(g,B,1,'hand').id
        self.play(g,BUFF,original);self.play(g,ONE,original);self.play(g,VOONE)
        copied=g.state.entities[g.state.players[1].hand[-1]]
        self.assertNotEqual(copied.id,original);self.assertEqual((copied.attack,copied.max_health,copied.cost),(6,9,1));self.portable(g)

    def test_passive_and_deathrattle_roots_have_real_paid_hand_entries(self):
        for cid in(LADY,ARUGAL,DORIAN,NEW_DORIAN):
            g=self.game((cid,));source=self.play(g,cid)
            self.assertEqual(g.state.entities[source].card_id,cid)
            self.assertEqual(g.state.players[1].mana,30-g.registry.card(cid).cost)
            self.assertEqual(len(g.state.play_history),1)

    def test_lady_natural_death_copies_only_frost_spells_from_own_hand(self):
        g=self.game((KILL,FROST,FIRE,A),board=(LADY,),enemy_hand=(FROST,));self.play(g,KILL,self.unit(g,LADY).id)
        self.assertEqual(self.hand(g),[FROST,FIRE,A,FROST]);self.assertEqual(self.hand(g,2),[FROST]);self.portable(g)

    def test_lady_accepted_hand_material_survives_wait_and_fault(self):
        g=self.game((KILL,FROST,FROST),board=(LADY,),watch=WATCH);self.play(g,KILL,self.unit(g,LADY).id)
        self.assertEqual(self.hand(g).count(FROST),3);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.hand(g).count(FROST),4);self.portable(g)

    def test_zai_freezes_two_original_edges_excluding_middle(self):
        g=self.game((A,ZAI,B,C));self.play(g,ZAI)
        self.assertEqual(self.hand(g),[A,B,C,A,C])

    def test_zai_single_physical_card_local_dedup_and_empty_hand(self):
        g=self.game((ZAI,A));self.play(g,ZAI);self.assertEqual(self.hand(g),[A,A])
        g=self.game((ZAI,));self.play(g,ZAI);self.assertEqual(self.hand(g),[])

    def test_pip_uses_current_quote_instead_of_printed_cost(self):
        g=self.game((ONE,TWO,PIP,A,FROST));a=self.entity(g,A,1,'hand').id;f=self.entity(g,FROST,1,'hand').id
        self.play(g,ONE,a);self.play(g,TWO,f);self.play(g,PIP)
        self.assertEqual(self.hand(g),[A,FROST,A]);self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].cost,1)

    def test_hand_copy_overflow_is_ordinary_creation_and_never_draws(self):
        g=self.game((VOONE,)+(B,)*9);self.play(g,VOONE)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual(self.hand(g).count(B),10)
        self.assertEqual(g.state.draw_history,[]);self.portable(g)

    def test_vorazj_summons_one_one_copies_without_new_battlecries(self):
        g=self.game((VORAZJ,),board=(A,B));self.play(g,VORAZJ)
        self.assertEqual(self.board(g),[A,B,VORAZJ,A,B]);self.assertEqual(self.hero(g).armor,0)
        copies=[g.state.entities[i]for i in g.state.players[1].board[-2:]]
        self.assertEqual([(e.attack,e.max_health)for e in copies],[(1,1),(1,1)]);self.portable(g)

    def test_remembered_board_override_keeps_strict_hand_and_mode_boundaries(self):
        g=self.game(board=(A,));material=native.CopyEntryMaterial.capture(g.state,self.unit(g,A),
            'remembered_copy','current',native.SummonStats(1,1),registry=g.registry,player_id=1)
        with self.assertRaises(ValueError):replace(material,mode='base')
        with self.assertRaises(ValueError):replace(material,profile='remembered_hand_copy',origin=replace(material.origin,zone=Zone.HAND))
        with self.assertRaises(ValueError):replace(material,stats={'attack':1,'health':1})

    def test_vorazj_frozen_group_restores_across_first_copy_wait(self):
        g=self.game((VORAZJ,),board=(A,B),watch=S_WATCH);self.play(g,VORAZJ)
        g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.board(g),[A,B,VORAZJ,A,B]);self.portable(g)

    def test_board_copy_uses_current_stats_and_excludes_enemy_and_self(self):
        g=self.game((BUFF,FREYA),board=(A,),enemy=(B,));self.play(g,BUFF,self.unit(g,A).id);self.freya(g,native.BOARD_OPTION)
        self.assertEqual(self.board(g),[A,FREYA,A]);last=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((last.attack,last.max_health),(6,9));self.assertEqual(self.board(g,2),[B])

    def test_freya_actual_hand_option_duplicates_frozen_hand_and_pays_once(self):
        g=self.game((A,FREYA,B));self.freya(g,native.HAND_OPTION)
        self.assertEqual(self.hand(g),[A,B,A,B]);self.assertEqual(self.board(g),[FREYA]);self.portable(g)

    def test_freya_later_original_leaving_does_not_rewrite_frozen_copy_group(self):
        g=self.game((FREYA,),board=(A,B),watch=S_WATCH);original=self.unit(g,B).id
        self.freya(g,native.BOARD_OPTION);g=self.portable(g);self.choose(g,'move');self.finish(g)
        self.assertIn(original,g.state.players[1].hand);copy=self.unit(g,B)
        self.assertNotEqual(copy.id,original);self.assertEqual((copy.attack,copy.max_health),(4,6));self.portable(g)

    def test_freya_choose_both_uses_existing_real_branch_and_original_groups(self):
        g=self.game((FREYA,B),board=(BOTH,A));self.freya(g,'both')
        self.assertEqual(self.hand(g),[B,B]);self.assertEqual(self.board(g),[BOTH,A,FREYA,BOTH,A]);self.portable(g)

    def test_freya_unknown_branch_rolls_back_before_payment(self):
        g=self.game((FREYA,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.freya(g,'invented')
        self.assertEqual(g.snapshot(),before)

    def test_arugal_actual_draw_keeps_original_and_copies_minion_once(self):
        g=self.game((DRAW,),board=(ARUGAL,),deck=(A,));self.play(g,DRAW)
        self.assertEqual(self.hand(g),[A,A]);self.assertEqual(self.board(g),[ARUGAL]);self.assertEqual(len(g.state.draw_history),1)
        self.assertEqual(len(set(g.state.players[1].hand)),2);self.portable(g)

    def test_draw_consumers_ignore_spells_and_opponent_draws(self):
        for source in(ARUGAL,DORIAN,NEW_DORIAN):
            g=self.game((DRAW,),board=(source,),deck=(FROST,),enemy_hand=(DRAW,));self.play(g,DRAW)
            self.assertEqual(self.hand(g),[FROST]);self.assertEqual(self.board(g),[source])
            g.apply(EndTurn(1));self.play(g,DRAW,player=2);self.assertEqual(self.hand(g),[FROST])

    def test_dorian_draw_summons_one_one_and_keeps_original_in_hand(self):
        g=self.game((DRAW,),board=(DORIAN,),deck=(A,));self.play(g,DRAW)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(self.board(g),[DORIAN,A])
        self.assertEqual((self.unit(g,A).attack,self.unit(g,A).max_health),(1,1));self.assertEqual(self.hero(g).armor,0);self.portable(g)

    def test_new_dorian_copies_as_one_one_cost_one_without_altering_original(self):
        g=self.game((DRAW,),board=(NEW_DORIAN,),deck=(A,));self.play(g,DRAW)
        first,last=(g.state.entities[i]for i in g.state.players[1].hand)
        self.assertEqual((first.attack,first.max_health,first.cost),(4,6,2));self.assertEqual((last.attack,last.max_health,last.cost),(1,1,1))
        self.assertEqual(self.board(g),[NEW_DORIAN]);self.portable(g)

    def test_draw_copy_wait_and_failure_preserve_original_draw_receipt(self):
        g=self.game((DRAW,),board=(ARUGAL,),deck=(A,),watch=WATCH);self.play(g,DRAW)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.hand(g),[A,A]);self.portable(g)

    def test_dorian_full_board_keeps_draw_without_summoning(self):
        g=self.game((DRAW,),board=(DORIAN,)+(C,)*6,deck=(A,));self.play(g,DRAW)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(len(g.state.players[1].board),7)

    def test_silenced_draw_source_does_not_copy_later_draw(self):
        g=self.game((HUSH,DRAW),board=(ARUGAL,),deck=(A,));self.play(g,HUSH,self.unit(g,ARUGAL).id);self.play(g,DRAW)
        self.assertEqual(self.hand(g),[A])

    def test_rock_uses_existing_one_physical_card_per_type_matching(self):
        g=self.game((ROCK,A,A,DUAL,ALL,C));self.play(g,ROCK)
        self.assertEqual(self.hand(g),[A,A,DUAL,ALL,C,A,DUAL,ALL]);self.portable(g)

    def test_one_amalgam_is_never_copied_once_per_each_of_twelve_types(self):
        g=self.game((ROCK,ALL));before=g.snapshot()['rng_state'];self.play(g,ROCK)
        self.assertEqual(self.hand(g),[ALL,ALL]);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_complete_standard_host_runs_hand_board_draw_and_real_choice_roles(self):
        g=self.game((VOONE,B),real_host=True);self.play(g,VOONE);self.assertEqual(self.hand(g),[B,B])
        g=self.game((FREYA,),board=(A,),real_host=True);self.freya(g,native.BOARD_OPTION);self.assertEqual(self.board(g),[A,FREYA,A])
        g=self.game((DRAW,),board=(NEW_DORIAN,),deck=(A,),real_host=True);self.play(g,DRAW)
        self.assertEqual(self.hand(g),[A,A]);self.portable(g)


if __name__=='__main__':unittest.main()
