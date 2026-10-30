"""Actual physical inventories, current copy recipes and original delivery tails."""
from dataclasses import replace
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_physical_inventory as native
from hs_sim.engine import (Attack,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SnapshotError)
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,GainArmor,InvokeBehavior,RandomDamage,
    RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (BattlecryRepeatSpec,CardDefinition,CardType,Keyword,SummonQuantitySpec,
    SummonStats,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.resolver import Resolution
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck,CardReference,MoveCard,zone_candidates
from hs_sim.local_pool_format import build_cn37_local_pool_format

BLACKTHORN,BOOM,TRON,GOYA=native.ROOTS
P='k716.'
A,R,HIGH,MECH,VANILLA_MECH,ALL,BC,RBC,Q,REPEAT=(P+x for x in ('plain','rattle','high','mech','vanilla_mech','all','bc','rattle_bc','quantity','repeat'))
KILL,HUSH,BUFF_DECK,NOOP=(P+x for x in ('kill','hush','buff_deck','noop'))
WATCH,FAIL,REENTER=(P+x for x in ('watch','fail','reenter'))
WATCHED=(A,R,HIGH,MECH,VANILLA_MECH,ALL,BC,RBC)


@lru_cache(None)
def fixture(role='writer',real_host=False):
    h=build_cn37_local_pool_format() if real_host else None;r=h.registry if h else defaults()
    if not real_host:native.register_past_physical_inventory(r)
    meta=metadata(collectible=False,tribes=())
    r.register_behavior(P+'rattle',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(P+'battlecry',lambda c:(GainArmor(c.player_id,100),))
    for cid in (*WATCHED,Q,REPEAT):
        fields=dict(metadata=meta)
        if cid in (R,HIGH,MECH,ALL,RBC):fields['deathrattle']=P+'rattle'
        if cid in (MECH,VANILLA_MECH):fields['metadata']=metadata(collectible=False,tribes=('mech',))
        if cid==ALL:fields['metadata']=metadata(collectible=False,tribes=('all',))
        if cid in (BC,RBC):fields['battlecry']=P+'battlecry'
        if cid==Q:fields['summon_quantities']=(SummonQuantitySpec(),)
        if cid==REPEAT:fields['battlecry_repeats']=(BattlecryRepeatSpec(2),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=6 if cid==HIGH else 5 if cid==RBC else 3,
            attack=2,health=5,**fields))
    def buff_deck(c):return tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),4,4,c.source_id)
        for i in c.state.players[c.player_id].deck if c.state.entities[i].kind==CardType.MINION)
    for cid,body in ((KILL,lambda c:(Destroy(c.target_id,c.source_id),)),(HUSH,lambda c:(Silence(c.target_id),)),
            (BUFF_DECK,buff_deck),(NOOP,lambda c:())):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=meta,targeting=TargetSpec() if cid in (KILL,HUSH) else None))
    def fail(c):raise ResolutionError('K716 deliberate accepted continuation failure')
    def reenter(c):
        entity=c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(entity),c.player_id,cause=SummonCause.capture(c)),)
    r.register_behavior(FAIL,fail);r.register_behavior(REENTER,reenter)
    def wait(c):
        target=c.state.entities[c.event.target_id]
        if target.card_id not in WATCHED:return ()
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after RNG',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),
            ChoiceOption('kill','Destroy original delivery',(Destroy(target.id,c.source_id),)),
            ChoiceOption('take','Transfer original delivery',(ChangeControl(target.id,2),)),
            ChoiceOption('bounce','Return and reenter original delivery',(ReturnToHand(target.id),
                InvokeBehavior(REENTER,c.source_id,c.player_id,target.id))),
            ChoiceOption('insert','Insert a new plain copy',(AddToDeck(c.player_id,A,position='bottom',source_id=c.source_id),)))
        parent=next((i for i in c.state.players[1].board if c.state.entities[i].card_id in native.ROOTS),None)
        if parent is not None:options+=(ChoiceOption('source_control','Transfer original source',(ChangeControl(parent,2),)),
            ChoiceOption('source_die','Destroy original source',(Destroy(parent,c.source_id),)))
        original=next((c.state.entities[i]for i in c.state.players[1].deck if c.state.entities[i].kind==CardType.MINION),None)
        if original is not None:
            ref=CardReference.capture(original)
            options+=(ChoiceOption('mutate_origin','Buff original deck body',(BuffStoredCard(ref,4,4,c.source_id),)),
                ChoiceOption('pull_tail','Move original deck body to hand',(MoveCard(ref,1,Zone.HAND,source_id=c.source_id),)))
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
        triggers=(TriggerSpec('minion_summoned',WATCH),)))
    r.validate();return r,None if h is None else h.context


class PhysicalInventoryTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,deck=(),board=(),enemy=(),real_host=False):
        self.mode='host' if real_host else 'small';r,context=fixture('writer',real_host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',deck=(A,)*12,board=enemy,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),
            seed=716,generation_context=context),r)
    def units(self,g,cid,p=1):return [g.state.entities[i]for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def face(self,g,cid,p=1):return self.units(g,cid,p)[0]
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:n+=1;self.assertLess(n,40);self.choose(g)
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_four_faces_full_source_and_original_evidence_only(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),10);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['cards']),4);self.assertFalse(d['dependencies']);r,_=fixture()
        self.assertTrue(all(cid not in r.cards for cid in native.EVIDENCE))

    def test_Blackthorn_actual_paid_recruits_three_original_eligible_cards(self):
        g=self.game((BLACKTHORN,),deck=(R,RBC,R,HIGH,A,NOOP));original=set(g.state.players[1].deck)
        self.play(g,BLACKTHORN);actual={e.id for cid in (R,RBC)for e in self.units(g,cid)}
        self.assertEqual(len(actual),3);self.assertTrue(actual<=original);self.assertEqual(self.armor(g),0)
        self.assertEqual(g.state.players[1].mana,33);self.assertFalse(g.state.draw_history)

    def test_printed_Deathrattle_fact_is_supplied_for_both_zone_query_polarities(self):
        g=self.game(deck=(R,A,HIGH,NOOP));r=Resolution(g);query=PoolQuery(kinds=(CardType.MINION,),deathrattle=False)
        rows=zone_candidates(r,1,Zone.DECK,query,1);self.assertEqual([x.card_id for x in rows],[A])
        rows=zone_candidates(r,1,Zone.DECK,native.DEATHRATTLES,1);self.assertEqual([x.card_id for x in rows],[R])

    def test_Blackthorn_keeps_current_stored_buffs_and_does_not_execute_battlecry(self):
        g=self.game((BUFF_DECK,BLACKTHORN),deck=(RBC,));original=g.state.players[1].deck[0]
        self.play(g,BUFF_DECK);self.play(g,BLACKTHORN);self.assertEqual(self.face(g,RBC).id,original)
        self.assertEqual((self.face(g,RBC).attack,self.face(g,RBC).health),(6,9));self.assertEqual(self.armor(g),0)

    def test_Blackthorn_empty_and_last_slot_skip_without_RNG_or_hidden_movement(self):
        for deck,board in (((A,HIGH,NOOP),()),((R,R,R),(A,)*6)):
            g=self.game((BLACKTHORN,),deck=deck,board=board);before=g.snapshot()['rng_state'];original=list(g.state.players[1].deck)
            self.play(g,BLACKTHORN);self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(g.state.players[1].deck,original)

    def test_Blackthorn_child_quantity_and_real_Battlecry_repeat_pay_only_once(self):
        g=self.game((BLACKTHORN,),deck=(R,)*4,board=(Q,));self.play(g,BLACKTHORN)
        self.assertEqual(len(self.units(g,R)),5);self.assertEqual(len(g.state.players[1].deck),1)
        g=self.game((BLACKTHORN,),deck=(R,)*6,board=(REPEAT,));self.play(g,BLACKTHORN)
        self.assertEqual(len(self.units(g,R)),5);self.assertEqual(g.state.players[1].mana,33)

    def test_Blackthorn_wait_restores_remaining_original_recruits_and_failed_choice(self):
        g=self.game((BLACKTHORN,),deck=(R,R,R),board=(WATCH,));self.play(g,BLACKTHORN)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(len(self.units(g,R)),3);self.portable(g)

    def test_Blackthorn_remaining_recipient_does_not_follow_later_source_control(self):
        g=self.game((BLACKTHORN,),deck=(R,R,R),board=(WATCH,));source=self.play(g,BLACKTHORN)
        self.choose(g,'source_control');self.finish(g);self.assertEqual(g.state.entities[source].controller,2)
        self.assertEqual(len(self.units(g,R)),3);self.assertEqual(self.units(g,R,2),[]);self.portable(g)

    def test_Goya_actual_target_kept_and_all_original_exact_copies_moved(self):
        g=self.game((GOYA,),deck=(A,R,A,A),board=(A,));target=self.face(g,A).id
        originals=[i for i in g.state.players[1].deck if g.state.entities[i].card_id==A]
        self.play(g,GOYA,target);self.assertIn(target,g.state.players[1].board)
        self.assertTrue(set(originals)<=set(g.state.players[1].board));self.assertEqual(len(self.units(g,A)),4)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[R]);self.assertEqual(g.state.players[1].mana,34)

    def test_Goya_no_target_no_copies_or_full_board_are_ordinary_paid_whiffs(self):
        for deck,board in (((A,),()),((R,),(A,)),((A,A),(A,)*6)):
            g=self.game((GOYA,),deck=deck,board=board);rng=g.snapshot()['rng_state'];original=list(g.state.players[1].deck)
            self.play(g,GOYA,self.face(g,A).id if board else None)
            self.assertEqual(g.state.players[1].deck,original);self.assertEqual(g.snapshot()['rng_state'],rng)
            self.assertEqual(g.state.players[1].mana,34)

    def test_Goya_illegal_enemy_and_hero_targets_reject_before_payment(self):
        g=self.game((GOYA,),board=(A,),enemy=(A,));before=g.snapshot()
        for target in (self.face(g,A,2).id,g.state.players[1].hero_id):
            with self.assertRaises(IllegalAction):self.play(g,GOYA,target)
            self.assertEqual(g.snapshot(),before)

    def test_Goya_captured_all_inventory_excludes_later_inserted_copy(self):
        g=self.game((GOYA,),deck=(A,A),board=(A,WATCH));original=set(g.state.players[1].deck)
        self.play(g,GOYA,self.face(g,A).id);g=self.portable(g);self.choose(g,'insert');self.finish(g)
        self.assertTrue(original<=set(g.state.players[1].board));self.assertEqual(len(g.state.players[1].deck),1)
        self.assertNotIn(g.state.players[1].deck[0],original);self.assertEqual(len(self.units(g,A)),3);self.portable(g)

    def test_Goya_stale_original_tail_does_not_retarget_its_later_hand_lifetime(self):
        g=self.game((GOYA,),deck=(A,A),board=(A,WATCH));original=list(g.state.players[1].deck)
        self.play(g,GOYA,self.face(g,A).id);self.choose(g,'pull_tail');self.finish(g)
        self.assertIn(original[1],g.state.players[1].hand);self.assertNotIn(original[1],g.state.players[1].board)
        self.assertEqual(len(self.units(g,A)),2);self.portable(g)

    def test_Goya_each_original_physical_card_uses_existing_quantity_delivery(self):
        g=self.game((GOYA,),deck=(A,A),board=(A,Q));self.play(g,GOYA,self.face(g,A).id)
        self.assertEqual(len(self.units(g,A)),5);self.assertEqual(g.state.players[1].deck,[])

    def test_Boom_current_deck_copy_preserves_original_body_without_its_Battlecry(self):
        g=self.game((BUFF_DECK,BOOM),deck=(BC,));origin=g.state.players[1].deck[0]
        self.play(g,BUFF_DECK);self.play(g,BOOM);copy=self.face(g,BC)
        self.assertNotEqual(copy.id,origin);self.assertEqual(g.state.players[1].deck,[origin])
        self.assertEqual((copy.attack,copy.health),(6,9));self.assertIn(Keyword.RUSH,copy.keywords);self.assertEqual(self.armor(g),0)
        self.assertNotIn(Keyword.RUSH,g.state.entities[origin].keywords);self.assertEqual(g.state.players[1].mana,30)

    def test_Boom_Rush_is_real_immediate_minion_attack_and_does_not_allow_face(self):
        g=self.game((BOOM,),deck=(R,),enemy=(A,));self.play(g,BOOM);copy=self.face(g,R)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,copy.id,g.state.players[2].hero_id))
        target=self.face(g,A,2).id;g.apply(Attack(1,copy.id,target));self.assertEqual(g.state.entities[target].health,3)

    def test_Boom_complete_physical_candidates_keep_duplicate_faces_as_separate_weights(self):
        g=self.game((BOOM,),deck=(A,R,R,NOOP));original=g.state.players[1].deck;self.play(g,BOOM)
        root=g.state.card_summon_history[0];materials=root.request.materials
        self.assertEqual(len(materials),3);self.assertEqual({x.origin.entity_id for x in materials},set(original[:3]))
        self.assertEqual([x.card_id for x in materials],[A,R,R]);self.portable(g)

    def test_Boom_quantity_copies_each_get_independent_Rush_and_keep_deck_source(self):
        g=self.game((BOOM,),deck=(R,),board=(Q,));origin=g.state.players[1].deck[0];self.play(g,BOOM)
        copies=self.units(g,R);self.assertEqual(len(copies),2);self.assertEqual(g.state.players[1].deck,[origin])
        grants=[{a.id for a in e.abilities if a.kind=='keyword' and a.keyword==Keyword.RUSH}for e in copies]
        self.assertTrue(all(grants));self.assertFalse(grants[0]&grants[1]);self.portable(g)

    def test_Boom_empty_or_full_board_does_not_draw_RNG_or_move_deck_cards(self):
        for deck,board in (((NOOP,),()),((R,),(A,)*6)):
            g=self.game((BOOM,),deck=deck,board=board);before=g.snapshot()['rng_state'];original=list(g.state.players[1].deck)
            self.play(g,BOOM);self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(g.state.players[1].deck,original)

    def test_Boom_wait_is_before_Rush_then_restores_original_selected_tail_once(self):
        g=self.game((BOOM,),deck=(R,),board=(WATCH,));self.play(g,BOOM);self.assertNotIn(Keyword.RUSH,self.face(g,R).keywords)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertIn(Keyword.RUSH,self.face(g,R).keywords);self.portable(g)

    def test_Boom_source_deck_mutation_after_copy_does_not_change_accepted_material(self):
        g=self.game((BOOM,),deck=(R,),board=(WATCH,));origin=g.state.players[1].deck[0];self.play(g,BOOM)
        self.choose(g,'mutate_origin');self.finish(g);self.assertEqual(g.state.entities[origin].attack,6)
        self.assertEqual(self.face(g,R).attack,2);self.assertIn(Keyword.RUSH,self.face(g,R).keywords);self.portable(g)

    def test_Boom_origin_can_leave_deck_after_acceptance_without_losing_copy_tail(self):
        g=self.game((BOOM,),deck=(R,),board=(WATCH,));origin=g.state.players[1].deck[0];self.play(g,BOOM)
        self.choose(g,'pull_tail');self.finish(g);self.assertIn(origin,g.state.players[1].hand)
        self.assertIn(Keyword.RUSH,self.face(g,R).keywords);self.portable(g)

    def test_Boom_departed_and_reentered_copy_does_not_receive_old_Rush_tail(self):
        g=self.game((BOOM,),deck=(R,),board=(WATCH,));self.play(g,BOOM);copy=self.face(g,R).id
        self.choose(g,'bounce');self.finish(g);self.assertEqual(self.face(g,R).id,copy)
        self.assertNotIn(Keyword.RUSH,self.face(g,R).keywords);self.portable(g)

    def test_Boom_accepted_copy_tail_survives_original_source_death(self):
        g=self.game((BOOM,),deck=(R,),board=(WATCH,));source=self.play(g,BOOM)
        self.choose(g,'source_die');self.finish(g);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertIn(Keyword.RUSH,self.face(g,R).keywords);self.portable(g)

    def test_new_copy_followup_shape_remains_only_plain_current_deck_material(self):
        g=self.game(deck=(R,));entity=g.state.entities[g.state.players[1].deck[0]]
        material=CopyEntryMaterial.capture(g.state,entity,'stored_copy','current',registry=g.registry,player_id=1,on_summon=native.PREFIX+'rush')
        for changes in ({'stats':SummonStats(1,1)},{'mode':'base','local':None},
                {'origin':replace(material.origin,zone=Zone.HAND)},
                {'minion_grant':CreatedMinionGrant(attack=1),'grant_source_id':g.state.players[1].hero_id}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(material,**changes)

    def test_Oblivitron_moves_real_hand_Mech_then_triggers_without_killing_it(self):
        g=self.game((TRON,MECH,KILL));source=self.play(g,TRON);original=self.entity(g,MECH).id;self.play(g,KILL,source)
        self.assertEqual(self.face(g,MECH).id,original);self.assertEqual(self.armor(g),1)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(g.state.players[1].mana,34);self.portable(g)

    def test_Oblivitron_has_no_Deathrattle_candidate_filter_and_accepts_all_tribe(self):
        for cid,armor in ((VANILLA_MECH,0),(ALL,1)):
            g=self.game((TRON,cid,KILL,A));source=self.play(g,TRON);self.play(g,KILL,source)
            self.assertEqual(len(self.units(g,cid)),1);self.assertEqual(self.armor(g),armor);self.assertEqual(self.units(g,A),[])

    def test_Oblivitron_quantity_has_one_real_tail_per_actual_delivered_body(self):
        g=self.game((TRON,MECH,KILL),board=(Q,));source=self.play(g,TRON);self.play(g,KILL,source)
        self.assertEqual(len(self.units(g,MECH)),2);self.assertEqual(self.armor(g),2);self.portable(g)

    def test_Oblivitron_reactive_target_death_skips_old_tail_after_natural_Deathrattle(self):
        g=self.game((TRON,MECH,KILL),board=(WATCH,));source=self.play(g,TRON);self.play(g,KILL,source)
        g=self.portable(g);self.fault(g);self.choose(g,'kill');self.finish(g)
        self.assertEqual(self.units(g,MECH),[]);self.assertEqual(self.armor(g),1);self.portable(g)

    def test_Oblivitron_new_lifetime_after_return_is_not_old_recruit_beneficiary(self):
        g=self.game((TRON,MECH,KILL),board=(WATCH,));source=self.play(g,TRON);self.play(g,KILL,source)
        self.choose(g,'bounce');self.finish(g);self.assertEqual(len(self.units(g,MECH)),1);self.assertEqual(self.armor(g),0);self.portable(g)

    def test_Oblivitron_silence_and_control_use_existing_actual_source_lifecycle(self):
        g=self.game((TRON,MECH,HUSH,KILL));source=self.play(g,TRON);self.play(g,HUSH,source);self.play(g,KILL,source)
        self.assertEqual(self.units(g,MECH),[]);self.assertIsNotNone(self.entity(g,MECH))

    def test_current_schema_rejects_old_future_and_boolean_versions(self):
        g=self.game();saved=g.snapshot()
        for version in (661,663,True):
            changed=dict(saved,schema_version=version)
            with self.subTest(version=version),self.assertRaises(SnapshotError):Game.from_snapshot(changed,g.registry)

    def test_actual_host_all_four_native_entries_use_original_physical_inventories(self):
        g=self.game((BLACKTHORN,),deck=(R,R,R),real_host=True);self.play(g,BLACKTHORN);self.assertEqual(len(self.units(g,R)),3)
        g=self.game((BOOM,),deck=(BC,),real_host=True);self.play(g,BOOM);self.assertIn(Keyword.RUSH,self.face(g,BC).keywords);self.assertEqual(self.armor(g),0)
        g=self.game((GOYA,),deck=(A,A),board=(A,),real_host=True);self.play(g,GOYA,self.face(g,A).id);self.assertEqual(len(self.units(g,A)),3)
        g=self.game((TRON,MECH,KILL),real_host=True);source=self.play(g,TRON);self.play(g,KILL,source);self.assertEqual(self.armor(g),1);self.portable(g)


if __name__=='__main__':unittest.main()
