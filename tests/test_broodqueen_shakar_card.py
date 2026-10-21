"""Actual Sha'kar death gate and the finite current-Rush player aura."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.broodqueen_shakar_card import CARD, PROGRAM, load_batch, register_broodqueen_shakar_card
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, DestroyBatch,
    GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, KeywordAuraSpec, PlayerEffectSpec,
    PlayerKeywordAuraSpec, PlayerKeywordConditionAuraSpec, Rarity)
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='fixture.shakar.'
OP=P+'op.'
TOKEN,RUSH,PLAIN,MECH,UNKNOWN,NATIVE,WATCH=(P+x for x in ('token','rush','plain','mech','unknown','native','watch'))
TRIBAL=OP+'tribal'
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in ('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_broodqueen_shakar_card(r)
    for cid,kw,meta in ((TOKEN,(),META),(RUSH,(Keyword.RUSH,),META),(PLAIN,(),META),
            (MECH,(),replace(META,tribes=('mech',))),(UNKNOWN,(Keyword.RUSH,),replace(META,tribes=None))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=0 if cid==TOKEN else 1,attack=2,
            health=1 if cid==TOKEN else 6,keywords=kw,metadata=meta))
    r.register_card(CardDefinition(NATIVE,NATIVE,CardType.MINION,attack=1,health=7,metadata=META,
        keyword_auras=(KeywordAuraSpec(Keyword.RUSH,target='friendly_minions'),)))
    r.register_player_effect(PlayerEffectSpec(TRIBAL,CARD,keyword_auras=(PlayerKeywordAuraSpec(Keyword.RUSH,('mech',)),)))
    def fail(c):raise ResolutionError('Sha\'kar deliberate failure')
    r.register_behavior(P+'fail',fail)
    def remove(c,program):
        row=next(e for e in c.state.players[c.player_id].player_effects if e.spec_id==program)
        return(RemovePlayerEffect(c.player_id,row.id),)
    operations={
        'sweep':lambda c:(DestroyBatch(tuple(i for p in(1,2)for i in c.state.players[p].board
            if c.state.entities[i].card_id==TOKEN),c.source_id),),
        'install':lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),),
        'tribal':lambda c:(AddPlayerEffect(c.player_id,TRIBAL,c.source_id),),
        'remove':lambda c:remove(c,PROGRAM),
        'remove_tribal':lambda c:remove(c,TRIBAL),
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'steal':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'plain':lambda c:(Transform(c.target_id,PLAIN),),
        'rush':lambda c:(Transform(c.target_id,RUSH),),
        'grant':lambda c:(GrantKeyword(c.target_id,Keyword.RUSH,c.source_id),),
        'grant_turn':lambda c:(GrantKeyword(c.target_id,Keyword.RUSH,c.source_id,expires_turn=c.state.turn),),
        'return':lambda c:(ReturnToHand(c.target_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'copy_base':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'copy_enemy':lambda c:(CopyMinion(c.target_id,3-c.player_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].dormancy is not None),c.source_id),),
    }
    for name,body in operations.items():
        key=OP+name;r.register_behavior(key,body)
        untargeted=name in ('sweep','install','tribal','remove','remove_tribal','wake')
        r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,metadata=META,
            targeting=None if untargeted else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    if mode:
        def watch(c):
            if dict(c.event.data).get('effect_key')!=PROGRAM:return()
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=META,
            triggers=(TriggerSpec('player_effect_added',P+'watch'),)))
    return r


class BroodqueenSourceTests(unittest.TestCase):
    def test_all_three_original_progress_forms_and_full_primary_initial_count_are_strict(self):
        data=load_batch();raw=data['cards'][0]['record'];self.assertEqual(raw['tags']['1724'],1)
        self.assertEqual(canonical_digest(raw),data['cards'][0]['record_sha256'])
        self.assertEqual(len(raw['text'].split('@')),3);self.assertEqual(len(raw['text_en'].split('@')),3)
        self.assertEqual({o['locale']for o in data['official_observations']},{'zh_CN','en_US'})
        for o in data['official_observations']:
            check_face(raw,o['face'],o['locale'],data['display_normalizations'])
            with self.assertRaises(ValueError):check_face(raw,o['face'],o['locale'])

    def test_changed_raw_identity_body_hidden_progress_tag_or_stats_cannot_borrow_exception(self):
        data=load_batch();original=data['cards'][0]['record']
        for key,value in (('id','other'),('text',original['text']+'抽牌。'),('cost',4),('health',4),
                ('text_en',original['text_en'].replace('(Ready)','(Draw)'))):
            raw=deepcopy(original);raw[key]=value
            for o in data['official_observations']:
                with self.subTest(key=key,locale=o['locale']),self.assertRaises(ValueError):
                    check_face(raw,o['face'],o['locale'],data['display_normalizations'])
        raw=deepcopy(original);raw['tags']['1724']=2
        for o in data['official_observations']:
            with self.assertRaises(ValueError):check_face(raw,o['face'],o['locale'],data['display_normalizations'])

    def test_primary_rule_threshold_and_all_metadata_remain_strict(self):
        data=load_batch();raw=data['cards'][0]['record']
        for o in data['official_observations']:
            for key,value in (('text',o['face']['text'].replace('5','4')),('text',o['face']['text']+' Draw a card.'),
                    ('manaCost',4),('attack',4),('health',4),('classId',3),('minionTypeId',18)):
                face=deepcopy(o['face']);face[key]=value
                with self.subTest(key=key,locale=o['locale']),self.assertRaises(ValueError):
                    check_face(raw,face,o['locale'],data['display_normalizations'])

    def test_unreviewed_marker_empty_count_and_other_initial_values_are_rejected(self):
        data=load_batch();raw=data['cards'][0]['record']
        for o in data['official_observations']:
            for decl in ({'{0}':''},{'{0}':'4'},{'@':'','{0}':'5'},{'{1}':'5'}):
                with self.assertRaises(ValueError):check_face(raw,o['face'],o['locale'],decl)


class BroodqueenShakarTests(unittest.TestCase):
    def game(self,*,hand=(),board=(),enemy=(),seat=1,mode=None):
        self.mode=mode;self.seat=seat
        if mode:board=(*board,WATCH)
        own=PlayerSetup('HERO_08',hand=hand,board=board,deck=(PLAIN,)*6,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',board=enemy,deck=(PLAIN,)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=363),fixture(mode))
    def eid(self,g,cid,pid=None,zone='board'):
        return next(i for i in getattr(g.state.players[self.seat if pid is None else pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,target=None):
        pid=g.state.active_player;i=self.eid(g,cid,pid,'hand');g.apply(PlayCard(pid,i,target));return i
    def op(self,g,name,target=None):return self.play(g,OP+name,target)
    def programs(self,g):return[e for e in g.state.players[self.seat].player_effects if e.spec_id==PROGRAM]
    def hero(self,g,pid=None):return g.state.players[3-self.seat if pid is None else pid].hero_id
    def charge(self,g,eid):return Keyword.CHARGE in g.state.entities[eid].keywords
    def hero_attack(self,g,eid):return Attack(self.seat,eid,self.hero(g))in g.legal_actions()
    def activate(self,g):self.op(g,'sweep');return self.play(g)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original player effect/current predicate/remaining work must restore')
        return Game.from_snapshot(s,r)

    def test_central_original_legendary_demon_hunter_beast_body_and_only_finite_player_declaration(self):
        r=assembled();card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.classes,card.metadata.rarity,card.metadata.tribes),
            (5,3,5,(CardClass.DEMON_HUNTER,),Rarity.LEGENDARY,('beast',)))
        self.assertEqual(card,fixture().card(CARD));self.assertEqual(r.pool_card(CARD),fixture().pool_card(CARD))
        self.assertEqual(r.player_effect(PROGRAM).keyword_auras,(PlayerKeywordConditionAuraSpec(Keyword.CHARGE,Keyword.RUSH),))

    def test_exact_five_actual_deaths_enable_real_paid_effect_and_newborn_rush_hero_attack(self):
        g=self.game(hand=(OP+'sweep',CARD,RUSH),board=(TOKEN,)*5);root=self.activate(g);self.assertEqual(g.state.players[1].mana,5)
        self.assertEqual(len(self.programs(g)),1);i=self.play(g,RUSH);self.assertTrue(self.hero_attack(g,i))
        self.assertFalse(self.charge(g,root));g.apply(Attack(1,i,self.hero(g)));self.assertEqual(g.state.entities[self.hero(g)].damage,2)
        self.assertEqual(g.state.entities[i].attacks_this_turn,1);self.portable(g)

    def test_four_friendly_deaths_do_not_install_and_six_are_not_required_to_equal_five(self):
        for count in(4,6):
            with self.subTest(count=count):
                g=self.game(hand=(OP+'sweep',CARD),board=(TOKEN,)*count);self.activate(g)
                self.assertEqual(len(self.programs(g)),int(count>=5))

    def test_opponent_deaths_and_previous_turn_deaths_do_not_satisfy_current_friendly_gate(self):
        g=self.game(hand=(OP+'sweep',CARD),enemy=(TOKEN,)*5);self.activate(g);self.assertFalse(self.programs(g))
        g=self.game(hand=(OP+'sweep',CARD),board=(TOKEN,)*5);self.op(g,'sweep')
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g);self.assertFalse(self.programs(g))

    def test_gate_uses_original_controller_at_death_instead_of_card_owner(self):
        g=self.game(hand=(OP+'give',OP+'sweep',CARD),board=(TOKEN,)*5);self.op(g,'give',self.eid(g,TOKEN));self.activate(g)
        self.assertFalse(self.programs(g))
        g=self.game(hand=(OP+'steal',OP+'sweep',CARD),board=(TOKEN,)*4,enemy=(TOKEN,));self.op(g,'steal',self.eid(g,TOKEN,2));self.activate(g)
        self.assertEqual(len(self.programs(g)),1)

    def test_persistent_real_effect_survives_source_death_and_following_turns(self):
        g=self.game(hand=(OP+'sweep',CARD,OP+'kill',RUSH),board=(TOKEN,)*5);root=self.activate(g);self.op(g,'kill',root)
        g.apply(EndTurn(1));g.apply(EndTurn(2));i=self.play(g,RUSH)
        self.assertEqual(len(self.programs(g)),1);self.assertTrue(self.hero_attack(g,i));self.portable(g)

    def test_silence_removes_local_rush_and_derived_charge_in_same_action(self):
        g=self.game(hand=(OP+'install',RUSH,OP+'silence'));self.op(g,'install');i=self.play(g,RUSH);self.assertTrue(self.hero_attack(g,i))
        self.op(g,'silence',i);self.assertNotIn(Keyword.RUSH,g.state.entities[i].keywords);self.assertFalse(self.charge(g,i))
        self.assertFalse(self.hero_attack(g,i));self.assertEqual(len(self.programs(g)),1)

    def test_native_external_rush_is_read_fresh_and_its_removal_cannot_leave_cached_charge(self):
        g=self.game(hand=(OP+'install',PLAIN,OP+'kill'),board=(NATIVE,));aura=self.eid(g,NATIVE);self.op(g,'install');i=self.play(g,PLAIN)
        self.assertTrue(self.hero_attack(g,i));self.op(g,'kill',aura)
        self.assertNotIn(Keyword.RUSH,g.state.entities[i].keywords);self.assertFalse(self.charge(g,i));self.assertFalse(self.hero_attack(g,i))

    def test_fresh_old_player_tribal_rush_contributes_and_removal_clears_charge_without_second_pass(self):
        g=self.game(hand=(OP+'install',OP+'tribal',MECH,OP+'remove_tribal'));self.op(g,'install');self.op(g,'tribal');i=self.play(g,MECH)
        self.assertTrue(self.hero_attack(g,i));self.op(g,'remove_tribal');self.assertNotIn(Keyword.RUSH,g.state.entities[i].keywords)
        self.assertFalse(self.charge(g,i));self.portable(g)

    def test_local_granted_rush_qualifies_and_absolute_expiry_removes_both_flags(self):
        g=self.game(hand=(OP+'install',PLAIN,OP+'grant_turn'));self.op(g,'install');i=self.play(g,PLAIN);self.assertFalse(self.charge(g,i))
        self.op(g,'grant_turn',i);self.assertTrue(self.hero_attack(g,i));g.apply(EndTurn(1))
        self.assertNotIn(Keyword.RUSH,g.state.entities[i].keywords);self.assertFalse(self.charge(g,i))

    def test_control_roundtrip_recomputes_against_receiving_players_program(self):
        g=self.game(hand=(OP+'install',OP+'give',OP+'steal'),board=(RUSH,));i=self.eid(g,RUSH);self.op(g,'install');self.op(g,'give',i)
        self.assertFalse(self.charge(g,i));self.assertIn(Keyword.RUSH,g.state.entities[i].keywords)
        self.op(g,'steal',i);self.assertTrue(self.charge(g,i))

    def test_transform_away_and_back_recomputes_current_rush_qualification(self):
        g=self.game(hand=(OP+'install',OP+'plain',OP+'rush'),board=(RUSH,));i=self.eid(g,RUSH);self.op(g,'install')
        self.op(g,'plain',i);self.assertFalse(self.charge(g,i));self.op(g,'rush',i);self.assertTrue(self.charge(g,i))

    def test_copy_to_other_player_does_not_bake_derived_charge_into_native_rush(self):
        g=self.game(hand=(OP+'install',OP+'copy',OP+'copy_enemy'),board=(RUSH,));i=self.eid(g,RUSH);self.op(g,'install')
        self.op(g,'copy',i);self.assertTrue(all(self.charge(g,j)for j in g.state.players[1].board))
        self.op(g,'copy_enemy',i);other=self.eid(g,RUSH,2);self.assertIn(Keyword.RUSH,g.state.entities[other].keywords)
        self.assertFalse(self.charge(g,other));self.assertFalse(any(a.kind=='keyword'and a.keyword==Keyword.CHARGE for a in g.state.entities[i].abilities))

    def test_current_and_base_copies_separate_local_granted_rush_and_external_charge(self):
        g=self.game(hand=(OP+'install',OP+'grant',OP+'copy',OP+'copy_base'),board=(PLAIN,));i=self.eid(g,PLAIN);self.op(g,'install');self.op(g,'grant',i)
        self.op(g,'copy',i);current=g.state.players[1].board[-1];self.op(g,'copy_base',i);base=g.state.players[1].board[-1]
        self.assertTrue(self.charge(g,current));self.assertFalse(self.charge(g,base));self.assertNotIn(Keyword.RUSH,g.state.entities[base].keywords)

    def test_return_to_hand_clears_derived_charge_and_actual_replay_receives_it_again(self):
        g=self.game(hand=(OP+'install',RUSH,OP+'return'));self.op(g,'install');i=self.play(g,RUSH);self.op(g,'return',i)
        self.assertFalse(self.charge(g,i));self.assertIn(Keyword.RUSH,g.state.entities[i].keywords);self.play(g,RUSH)
        self.assertTrue(self.hero_attack(g,i));self.portable(g)

    def test_dormancy_removes_qualification_and_waking_restores_ordinary_flags(self):
        g=self.game(hand=(OP+'install',OP+'sleep',OP+'wake'),board=(RUSH,));i=self.eid(g,RUSH);self.op(g,'install');self.op(g,'sleep',i)
        self.assertFalse(self.charge(g,i));self.op(g,'wake');self.assertTrue(self.charge(g,i))

    def test_unknown_tribe_is_irrelevant_to_known_current_keyword_predicate(self):
        g=self.game(hand=(OP+'install',),board=(UNKNOWN,));self.op(g,'install');self.assertTrue(self.charge(g,self.eid(g,UNKNOWN)))

    def test_duplicate_programs_union_and_removing_last_leaves_original_rush(self):
        g=self.game(hand=(OP+'install',OP+'install',OP+'remove',OP+'remove'),board=(RUSH,));i=self.eid(g,RUSH)
        self.op(g,'install');self.op(g,'install');self.assertEqual(len(self.programs(g)),2);self.op(g,'remove');self.assertTrue(self.charge(g,i))
        self.op(g,'remove');self.assertFalse(self.charge(g,i));self.assertIn(Keyword.RUSH,g.state.entities[i].keywords)

    def test_removal_and_reinstallation_do_not_refund_used_attack(self):
        g=self.game(hand=(OP+'install',RUSH,OP+'remove',OP+'install'));self.op(g,'install');i=self.play(g,RUSH);g.apply(Attack(1,i,self.hero(g)))
        self.op(g,'remove');self.op(g,'install');self.assertEqual(g.state.entities[i].attacks_this_turn,1);self.assertFalse(self.hero_attack(g,i))

    def test_player_effect_added_wait_restores_real_paid_gate_and_private_projection(self):
        g=self.game(hand=(OP+'sweep',CARD),board=(TOKEN,)*5,mode='wait',seat=2);self.activate(g)
        self.assertEqual(g.state.pending_choice.player_id,1);self.assertEqual(len(self.programs(g)),1);other=self.portable(g);before=g.snapshot()
        for pid in(1,2):
            view=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in ('required_keyword','PlayerKeywordConditionAuraSpec','resolution_frame','rng_state','instance_id'):
                self.assertNotIn('"'+key+'"',view)
        self.assertTrue(g.snapshot()==before);self.choose(g);self.choose(other);self.assertTrue(g.snapshot()==other.snapshot())

    def test_install_notification_failure_and_failed_choice_roll_back_atomically(self):
        g=self.game(hand=(OP+'sweep',CARD),board=(TOKEN,)*5,mode='fail');self.op(g,'sweep');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertTrue(g.snapshot()==before)
        g=self.game(hand=(OP+'sweep',CARD),board=(TOKEN,)*5,mode='wait');self.activate(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before);self.choose(g)

    def test_only_real_finite_predicate_and_original_tribal_declaration_are_accepted(self):
        for kw,required in((Keyword.RUSH,Keyword.CHARGE),(Keyword.CHARGE,Keyword.CHARGE),('charge',Keyword.RUSH)):
            with self.assertRaises(ValueError):PlayerKeywordConditionAuraSpec(kw,required)
        with self.assertRaises(ValueError):PlayerKeywordAuraSpec(Keyword.CHARGE,('mech',))
        with self.assertRaises(ValueError):PlayerEffectSpec('bad',CARD,kind='aura',duration=2,tick_event='turn_ended',
            keyword_auras=(PlayerKeywordConditionAuraSpec(Keyword.CHARGE,Keyword.RUSH),))
        self.assertEqual(asdict(PlayerKeywordAuraSpec(Keyword.RUSH,('mech',))),{'keyword':Keyword.RUSH,'tribes_any':('mech',)})
