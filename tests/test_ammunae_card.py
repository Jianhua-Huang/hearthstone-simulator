"""Ammunae's actual player program copies only the original paid residence."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry as assembled
from hs_sim.cards.ammunae_card import CARD, PROGRAM, load_batch, register_ammunae_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy, DestroyBatch,
    GainArmor, GrantDeathrattle, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, Rarity, SummonQuantitySpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest
from tools.card_batch import check_face

P='fixture.ammunae.';OP=P+'op.'
DR,PLAIN,DIE,SLEEP,INSTALLER,DOUBLE,WATCH=(P+x for x in ('dr','plain','die','sleep','installer','double','watch'))
META=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in ('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_ammunae_card(r)
    r.register_behavior(P+'death',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(P+'die',lambda c:(Destroy(c.source_id,c.source_id),))
    r.register_behavior(P+'self_install',lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),))
    for cid,options in ((DR,dict(deathrattle=P+'death')),(PLAIN,{}),
            (DIE,dict(deathrattle=P+'death',battlecry=P+'die')),
            (SLEEP,dict(deathrattle=P+'death',dormant_turns=2)),
            (INSTALLER,dict(deathrattle=P+'death',battlecry=P+'self_install')),
            (DOUBLE,dict(summon_quantities=(SummonQuantitySpec(2,(CardType.MINION,)),)))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=2,health=6,metadata=META,**options))
    def fail(c):raise ResolutionError('Ammunae deliberate failure')
    r.register_behavior(P+'fail',fail)
    operations={
        'summon':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(DR),),SummonCause.capture(c)),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'sweep':lambda c:(DestroyBatch(tuple(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==DR),c.source_id),),
        'return':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,PLAIN),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
    }
    for name,body in operations.items():
        key=OP+name;r.register_behavior(key,body)
        r.register_card(CardDefinition(key,key,CardType.SPELL,on_play=key,metadata=META,
            targeting=None if name in('summon','sweep')else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    if mode:
        def watch(c):
            if mode in('copy_wait','copy_fail'):
                e=c.state.entities.get(c.event.target_id or c.event.source_id)
                if e is None or e.origin_entity_id is None:return()
                if mode=='copy_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
                return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                    ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
            if mode=='install_wait':
                if dict(c.event.data).get('effect_key')!=PROGRAM:return()
                return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),),source_id=c.source_id),)
            row=play_record(c.state,dict(c.event.data)['play_id'])
            if row.card_id not in(DR,PLAIN):return()
            eid=row.source_id
            def bounce():return(ReturnToHand(eid),SummonFromZone(row.player_id,zone=Zone.HAND,
                query=PoolQuery(card_ids=(row.card_id,)),selection='first'))
            if mode=='before_wait':
                return(RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                    ChoiceOption('bounce','Return and summon',effects=bounce()),
                    ChoiceOption('fail','Fail',effects=(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),)
            if mode=='bounce':return bounce()
            if mode=='transform':return(Transform(eid,PLAIN),)
            if mode=='silence':return(Silence(eid),)
            if mode=='grant':return(GrantDeathrattle(eid,P+'death',c.source_id),)
            if mode=='grow':return(Buff(eid,3,4,c.source_id),Damage(eid,2,c.source_id))
            if mode=='free_slot':
                other=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==PLAIN)
                return(Destroy(other,c.source_id),)
            if mode=='control':return(ChangeControl(eid,3-row.player_id),)
            return()
        r.register_behavior(P+'watch',watch)
        event='minion_summoned'if mode in('copy_wait','copy_fail')else'player_effect_added'if mode=='install_wait'else'card_played'
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            triggers=(TriggerSpec(event,P+'watch'),)))
    return r


class AmmunaeTests(unittest.TestCase):
    def game(self,*,hand=(CARD,DR),board=(),enemy=(),enemy_hand=(),seat=1,mode=None):
        self.mode=mode;self.seat=seat
        if mode:board=(WATCH,*board)
        own=PlayerSetup('HERO_08',hand=hand,board=board,deck=(PLAIN,)*6,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',hand=enemy_hand,board=enemy,deck=(PLAIN,)*6,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=364),fixture(mode))
    def eid(self,g,cid,pid=None,zone='board'):
        return next(i for i in getattr(g.state.players[self.seat if pid is None else pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,target=None):
        pid=g.state.active_player;i=self.eid(g,cid,pid,'hand');g.apply(PlayCard(pid,i,target));return i
    def op(self,g,name,target=None):return self.play(g,OP+name,target)
    def copies(self,g,eid):return[e for e in g.state.entities.values()if e.origin_entity_id==eid and e.zone==Zone.BOARD]
    def programs(self,g):return[e for e in g.state.players[self.seat].player_effects if e.spec_id==PROGRAM]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original program/play/residence/copy/quantity must restore')
        return Game.from_snapshot(s,r)

    def test_full_raw_two_primary_faces_druid_legendary_body_and_central_player_program(self):
        data=load_batch();raw=data['cards'][0]['record'];self.assertEqual(raw['dbf_id'],129842)
        self.assertEqual(canonical_digest(raw),data['cards'][0]['record_sha256'])
        self.assertEqual({o['locale']for o in data['official_observations']},{'zh_CN','en_US'})
        for o in data['official_observations']:check_face(raw,o['face'],o['locale'])
        r=assembled();card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health,card.metadata.classes,card.metadata.rarity),
            (8,6,6,(CardClass.DRUID,),Rarity.LEGENDARY))
        self.assertEqual(card,fixture().card(CARD));self.assertEqual(r.pool_card(CARD),fixture().pool_card(CARD))
        self.assertEqual(r.player_effect(PROGRAM),fixture().player_effect(PROGRAM))

    def test_actual_eight_mana_install_and_paid_deathrattle_copy_are_two_distinct_ordinary_summons(self):
        g=self.game();root=self.play(g);self.assertEqual(g.state.players[1].mana,2);i=self.play(g,DR)
        self.assertEqual(g.state.players[1].mana,1);copies=self.copies(g,i);self.assertEqual(len(copies),1)
        self.assertEqual((copies[0].card_id,copies[0].attack,copies[0].max_health),(DR,2,6));self.assertNotEqual(copies[0].id,i)
        self.assertEqual(len(g.state.play_history),2);self.assertEqual(len(self.programs(g)),1)
        row=g.state.card_summon_history[-1];self.assertEqual(row.request.cause.source.entity_id,root)
        self.portable(g)

    def test_copy_is_summon_not_play_and_does_not_recursively_trigger_program(self):
        g=self.game();self.play(g);i=self.play(g,DR)
        self.assertEqual(len(self.copies(g,i)),1);self.assertEqual(sum(p.card_id==DR for p in g.state.play_history),1)
        self.assertEqual(len(g.state.players[1].board),3)

    def test_plain_minion_spell_and_effect_summon_do_not_qualify(self):
        g=self.game(hand=(CARD,PLAIN,OP+'summon'));self.play(g);i=self.play(g,PLAIN);self.assertFalse(self.copies(g,i))
        self.op(g,'summon');self.assertEqual(sum(g.state.entities[j].card_id==DR for j in g.state.players[1].board),1)

    def test_opponent_paid_deathrattle_does_not_use_owners_program(self):
        g=self.game(enemy_hand=(DR,));self.play(g);g.apply(EndTurn(1));i=self.play(g,DR)
        self.assertFalse(self.copies(g,i));self.assertEqual(len(g.state.players[2].board),1)

    def test_source_death_and_following_owner_turn_do_not_retire_persistent_effect(self):
        g=self.game(hand=(CARD,OP+'kill',DR));root=self.play(g);self.op(g,'kill',root)
        g.apply(EndTurn(1));g.apply(EndTurn(2));i=self.play(g,DR);self.assertEqual(len(self.copies(g,i)),1)
        self.assertEqual(g.state.entities[root].zone,Zone.GRAVEYARD);self.portable(g)

    def test_source_transformation_and_control_do_not_change_program_beneficiary(self):
        for op in('transform','give'):
            with self.subTest(op=op):
                g=self.game(hand=(CARD,OP+op,DR));root=self.play(g);self.op(g,op,root);i=self.play(g,DR)
                self.assertEqual(len(self.copies(g,i)),1);self.assertEqual(self.copies(g,i)[0].controller,1)

    def test_original_submitted_deathrattle_qualifies_after_current_body_is_transformed(self):
        g=self.game(mode='transform');self.play(g);i=self.play(g,DR);copies=self.copies(g,i)
        self.assertEqual(g.state.entities[i].card_id,PLAIN);self.assertEqual([e.card_id for e in copies],[PLAIN])
        self.assertFalse(any(a.kind=='deathrattle'for a in copies[0].abilities))

    def test_original_submitted_deathrattle_qualifies_after_silence_and_copies_current_silenced_material(self):
        g=self.game(mode='silence');self.play(g);i=self.play(g,DR);copy=self.copies(g,i)[0]
        self.assertTrue(copy.silenced);self.assertFalse(any(a.kind=='deathrattle'for a in copy.abilities))

    def test_deathrattle_granted_only_after_play_does_not_change_original_qualification(self):
        g=self.game(mode='grant',hand=(CARD,PLAIN));self.play(g);i=self.play(g,PLAIN)
        self.assertTrue(any(a.kind=='deathrattle'for a in g.state.entities[i].abilities));self.assertFalse(self.copies(g,i))

    def test_current_enchantments_and_damage_use_existing_copy_material_with_independent_attachments(self):
        g=self.game(mode='grow');self.play(g);i=self.play(g,DR);copy=self.copies(g,i)[0];original=g.state.entities[i]
        self.assertEqual((copy.attack,copy.max_health,copy.damage),(5,10,2))
        self.assertTrue({a.id for a in copy.enchantments}.isdisjoint(a.id for a in original.enchantments));self.portable(g)

    def test_source_body_dead_before_after_play_cannot_be_replaced_with_a_base_copy(self):
        g=self.game(hand=(CARD,DIE));self.play(g);i=self.play(g,DIE)
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD);self.assertFalse(self.copies(g,i))

    def test_earlier_return_and_resummon_same_physical_id_cannot_receive_prior_play_copy(self):
        g=self.game(mode='bounce');self.play(g);i=self.play(g,DR)
        self.assertEqual(g.state.entities[i].zone,Zone.BOARD);self.assertFalse(self.copies(g,i));self.portable(g)

    def test_current_body_control_change_keeps_original_residence_and_copy_goes_to_effect_owner(self):
        g=self.game(mode='control');self.play(g);i=self.play(g,DR)
        self.assertEqual(g.state.entities[i].controller,2);self.assertEqual([e.controller for e in self.copies(g,i)],[1])

    def test_dormant_original_has_explicit_nontargeted_copy_permission(self):
        g=self.game(hand=(CARD,SLEEP));self.play(g);i=self.play(g,SLEEP);copy=self.copies(g,i)[0]
        self.assertIsNotNone(g.state.entities[i].dormancy);self.assertIsNotNone(copy.dormancy)
        self.assertFalse(copy.active);self.portable(g)

    def test_full_board_uses_actual_capacity_and_does_not_invent_delayed_copy(self):
        g=self.game(board=(PLAIN,)*5,hand=(CARD,DR,OP+'kill'));self.play(g);i=self.play(g,DR)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.copies(g,i))
        self.op(g,'kill',self.eid(g,PLAIN));self.assertFalse(self.copies(g,i));self.portable(g)

    def test_earlier_after_play_reaction_frees_capacity_before_actual_copy(self):
        g=self.game(mode='free_slot',board=(PLAIN,)*4);self.play(g);i=self.play(g,DR)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(self.copies(g,i)),1)

    def test_two_real_installs_each_deliver_one_copy_without_collapsing_duplicate_programs(self):
        g=self.game(hand=(CARD,CARD,DR));self.play(g);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g);i=self.play(g,DR)
        self.assertEqual(len(self.programs(g)),2);self.assertEqual(len(self.copies(g,i)),2);self.portable(g)

    def test_native_quantity_doubles_copy_deliveries_without_replaying_paid_minion(self):
        g=self.game(board=(DOUBLE,));self.play(g);i=self.play(g,DR)
        self.assertEqual(len(self.copies(g,i)),2);self.assertEqual(sum(p.card_id==DR for p in g.state.play_history),1)

    def test_player_program_does_not_apply_live_listener_self_exclusion(self):
        g=self.game(hand=(INSTALLER,));i=self.play(g,INSTALLER)
        self.assertEqual(len(self.copies(g,i)),1);self.assertEqual(len(self.programs(g)),1)

    def test_original_and_copy_have_independent_actual_deathrattles(self):
        g=self.game(hand=(CARD,DR,OP+'sweep'));self.play(g);self.play(g,DR);self.op(g,'sweep')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(sum(row.card_id==DR for row in g.state.death_history),2)

    def test_wait_before_copy_restores_original_entry_and_bounce_invalidates_it(self):
        g=self.game(mode='before_wait');self.play(g);i=self.play(g,DR);self.assertFalse(self.copies(g,i));other=self.portable(g)
        self.choose(g,'bounce');self.choose(other,'bounce');self.assertTrue(g.snapshot()==other.snapshot());self.assertFalse(self.copies(g,i))

    def test_waiting_quantity_copy_restores_each_delivery_without_resampling_or_new_play(self):
        g=self.game(mode='copy_wait',board=(DOUBLE,));self.play(g);i=self.play(g,DR);waits=0
        while g.state.pending_choice:
            other=self.portable(g);self.choose(g);self.choose(other);self.assertTrue(g.snapshot()==other.snapshot());waits+=1
        self.assertEqual(waits,2);self.assertEqual(len(self.copies(g,i)),2);self.portable(g)

    def test_failed_copy_notification_and_waiting_choice_preserve_original_transaction(self):
        g=self.game(mode='copy_fail');self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,DR)
        self.assertTrue(g.snapshot()==before)
        g=self.game(mode='copy_wait');self.play(g);self.play(g,DR);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before);self.choose(g)

    def test_second_seat_install_wait_and_queries_hide_original_work_and_copy_proofs(self):
        g=self.game(mode='install_wait',seat=2);self.play(g);self.assertEqual(g.state.pending_choice.player_id,1)
        before=g.snapshot();other=self.portable(g)
        for pid in(1,2):
            visible=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in('resolution_frame','presence_id','copy_material','before_state','rng_state'):
                self.assertNotIn('"'+key+'"',visible)
        self.assertTrue(g.snapshot()==before);self.choose(g);self.choose(other);i=self.play(g,DR);self.play(other,DR)
        self.assertTrue(g.snapshot()==other.snapshot());self.assertEqual([e.controller for e in self.copies(g,i)],[2])
