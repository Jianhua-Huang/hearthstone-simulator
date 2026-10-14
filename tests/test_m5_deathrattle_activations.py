"""R-136: actual Deathrattle execution identity, captured windows and recovery."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import test_m5_death_causes as foundation
from hs_sim.engine import (CardDefinition,CardType,Game,Scenario,PlayerSetup,Keyword,Zone,Resource,
    ResolutionError,Ruleset,SnapshotError,EndTurn)
from hs_sim.engine.effects import (Damage,DamageBatch,Destroy,GrantDeathrattle,TriggerDeathrattles,
    GainArmor,Draw,RequestChoice,ChoiceOption,Transform,ReturnToHand,Silence,CopyMinion,
    ChangeControl,EquipWeapon,AddToHand,RemoveEnchantment,Summon)
from hs_sim.engine.deathrattles import activated_deathrattles
from hs_sim.engine.model import AbilityInstance


class DeathrattleActivationTests(unittest.TestCase):
    script=foundation.DeathCauseTests.script
    game=foundation.DeathCauseTests.game
    play=foundation.DeathCauseTests.play
    body=foundation.DeathCauseTests.body
    check=foundation.DeathCauseTests.check
    choose=foundation.DeathCauseTests.choose
    reject=foundation.DeathCauseTests.reject
    pause=foundation.DeathCauseTests.pause

    def setUp(self):
        foundation.DeathCauseTests.setUp(self)
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,1)])
        self.minion('rattle','armor')
        self.script('trigger',lambda c:[TriggerDeathrattles(c.target_id,c.source_id)],target=True)

    def minion(self,cid,behavior,**kw):
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=2,deathrattle=behavior,**kw))
    def records(self,g):return g.state.deathrattle_history
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def script_game(self,fn,board=('rattle',),enemy=(),**kw):
        self.script('do',fn);return self.game(hand=('do',),board=board,enemy=enemy,**kw)
    def invoke(self,g):self.play(g,'do');return self.records(g)
    def waiting(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(c.player_id,2))])
        self.minion('waiting','wait')
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0],c.source_id)],board=('waiting',))
        self.invoke(g);return g
    def state_row(self,s):return s['state']
    def frames(self,value,name):
        result=[]
        if isinstance(value,dict):
            if any(v==name for v in value.values() if isinstance(v,str)):result.append(value)
            for v in value.values():result.extend(self.frames(v,name))
        elif isinstance(value,list):
            for v in value:result.extend(self.frames(v,name))
        return result

    def test_natural_death_records_printed_identity_and_completion(self):
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0],c.source_id)])
        d=self.invoke(g)[0];self.assertEqual(d.capture.origin,'death');self.assertEqual(d.capture.death_id,1)
        self.assertEqual(d.capture.ability.deathrattle_card_id,'rattle');self.assertTrue(d.completed)
        self.assertEqual(d.execution_order,1);self.assertEqual(self.armor(g),1);self.check(g)

    def test_effect_trigger_has_source_without_death_or_corpses(self):
        g=self.game(hand=('trigger',),board=('rattle',),enemy=())
        source=self.play(g,'trigger',self.body(g,1));d=self.records(g)[0]
        self.assertEqual(d.capture.origin,'effect');self.assertIsNone(d.capture.death_id)
        self.assertEqual((d.capture.trigger_source_id,d.capture.trigger_source_card_id),(source,'trigger'))
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.assertEqual(len(g.state.players[1].board),1);self.check(g)

    def test_unspecified_trigger_source_stays_unknown(self):
        g=self.script_game(lambda c:[TriggerDeathrattles(c.state.players[1].board[0])]);d=self.invoke(g)[0]
        self.assertIsNone(d.capture.trigger_source_id);self.assertIsNone(d.capture.trigger_source_card_id);self.check(g)

    def test_unknown_trigger_source_rolls_back(self):
        g=self.script_game(lambda c:[TriggerDeathrattles(c.state.players[1].board[0],99999)])
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.invoke(g)
        self.assertEqual(g.snapshot(),before)

    def test_two_same_behavior_grants_have_independent_ability_ids(self):
        def work(c):
            i=c.state.players[1].board[0]
            return [GrantDeathrattle(i,'armor',c.source_id),GrantDeathrattle(i,'armor',c.source_id),Destroy(i,c.source_id)]
        g=self.script_game(work,board=('body',));rows=self.invoke(g)
        self.assertEqual(len(rows),2);self.assertEqual(len({d.capture.ability.id for d in rows}),2)
        self.assertEqual({d.capture.group_id for d in rows},{1});self.assertEqual(self.armor(g),2)
        self.assertTrue(all(d.capture.ability.deathrattle_grant_card_id=='do' for d in rows));self.check(g)

    def test_printed_and_granted_same_behavior_remain_distinct(self):
        g=self.script_game(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor',c.source_id),Destroy(c.state.players[1].board[0])])
        a,b=self.invoke(g);self.assertEqual((a.capture.ability.origin,b.capture.ability.origin),('printed','granted'))
        self.assertEqual(a.capture.ability.deathrattle_card_id,'rattle');self.assertIsNone(b.capture.ability.deathrattle_card_id)
        self.check(g)

    def test_silence_before_death_has_no_invocation(self):
        g=self.script_game(lambda c:[Silence(c.state.players[1].board[0]),Destroy(c.state.players[1].board[0])])
        self.assertFalse(self.invoke(g));self.assertEqual(self.armor(g),0);self.check(g)

    def test_expired_grant_is_not_queued(self):
        self.script('grant',lambda c:[GrantDeathrattle(c.target_id,'armor',c.source_id,expires_turn=1)],target=True)
        g=self.game(hand=('grant','kill'),board=('body',),enemy=());i=self.body(g,1)
        self.play(g,'grant',i);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'kill',i)
        self.assertFalse(self.records(g));self.check(g)

    def test_transform_before_death_uses_new_declaration(self):
        g=self.script_game(lambda c:[Transform(c.state.players[1].board[0],'rattle'),Destroy(c.state.players[1].board[0])],board=('body',))
        d=self.invoke(g)[0];self.assertEqual(d.capture.card_id,'rattle');self.assertEqual(d.capture.ability.deathrattle_card_id,'rattle');self.check(g)

    def test_control_change_uses_death_controller(self):
        g=self.script_game(lambda c:[ChangeControl(c.state.players[1].board[0],2),Destroy(c.state.players[1].board[0])])
        d=self.invoke(g)[0];self.assertEqual(d.capture.player_id,2);self.assertEqual(self.armor(g,2),1);self.check(g)

    def test_current_copy_allocates_ability_identity_and_keeps_declaration(self):
        g=self.script_game(lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        self.invoke(g);ids=g.state.players[1].board
        self.assertNotEqual(g.state.entities[ids[0]].abilities[0].id,g.state.entities[ids[1]].abilities[0].id)
        self.assertEqual(g.state.entities[ids[1]].abilities[0].deathrattle_card_id,'rattle');self.check(g)

    def test_reborn_death_has_one_invocation_and_new_body(self):
        self.minion('reborn_rattle','armor',keywords=(Keyword.REBORN,))
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0])],board=('reborn_rattle',))
        d=self.invoke(g)[0];self.assertNotEqual(self.body(g,1),d.capture.carrier_id)
        self.assertEqual(g.state.entities[self.body(g,1)].health,1);self.assertEqual(self.armor(g),1);self.check(g)

    def test_live_trigger_does_not_consume_reborn(self):
        self.minion('reborn_rattle','armor',keywords=(Keyword.REBORN,))
        g=self.game(hand=('trigger',),board=('reborn_rattle',),enemy=());i=self.body(g,1);self.play(g,'trigger',i)
        self.assertEqual(self.body(g,1),i);self.assertIn(Keyword.REBORN,g.state.entities[i].keywords);self.check(g)

    def test_weapon_replacement_records_old_weapon_payload(self):
        self.r.register_card(CardDefinition('rattle_weapon','rattle_weapon',CardType.WEAPON,attack=1,durability=2,deathrattle='armor'))
        g=self.script_game(lambda c:[EquipWeapon(1,'weapon')],board=(),weapon='rattle_weapon')
        d=self.invoke(g)[0];self.assertEqual(d.capture.kind,CardType.WEAPON);self.assertEqual(d.capture.card_id,'rattle_weapon')
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,'weapon');self.check(g)

    def test_destroyed_location_records_its_deathrattle(self):
        from hs_sim.engine.locations import DestroyLocation
        self.r.register_behavior('location_use',lambda c:[])
        self.r.register_card(CardDefinition('loc','loc',CardType.LOCATION,durability=2,on_use='location_use',deathrattle='armor'))
        g=self.script_game(lambda c:[DestroyLocation(c.state.players[1].board[0])],board=('loc',))
        d=self.invoke(g)[0];self.assertEqual(d.capture.kind,CardType.LOCATION);self.assertEqual(self.armor(g),1);self.check(g)

    def test_noop_deathrattle_still_completes(self):
        self.r.register_behavior('noop',lambda c:[]);self.minion('no','noop')
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0])],board=('no',))
        self.assertTrue(self.invoke(g)[0].completed);self.check(g)

    def test_terminal_before_execution_marks_queued_interrupted(self):
        g=self.script_game(lambda c:[DamageBatch((Damage(c.state.players[1].board[0],5),Damage(c.state.players[2].hero_id,40)))])
        d=self.invoke(g)[0];self.assertIsNone(d.execution_order);self.assertTrue(d.interrupted);self.assertFalse(d.completed)
        self.assertEqual(activated_deathrattles(g.state,1),());self.assertEqual(self.armor(g),0);self.check(g)

    def test_terminal_during_first_skips_second_invocation(self):
        self.r.register_behavior('fatal',lambda c:[Damage(c.state.players[2].hero_id,40)])
        self.minion('fatal_body','fatal')
        g=self.script_game(lambda c:[DamageBatch(tuple(Damage(i,4) for i in c.state.players[1].board))],board=('fatal_body','rattle'))
        a,b=self.invoke(g);self.assertEqual(a.execution_order,1);self.assertTrue(a.interrupted)
        self.assertIsNone(b.execution_order);self.assertTrue(b.interrupted);self.check(g)

    def test_nested_death_executes_before_older_queued_body(self):
        self.r.register_behavior('nested',lambda c:[Destroy(c.state.players[2].board[0])])
        self.minion('nested_body','nested')
        g=self.script_game(lambda c:[DamageBatch(tuple(Damage(i,4) for i in c.state.players[1].board))],board=('nested_body','rattle'),enemy=('rattle',))
        self.invoke(g);self.assertEqual([d.execution_order for d in self.records(g)],[1,3,2])
        self.assertEqual([d.id for d in activated_deathrattles(g.state,1)],[1,2]);self.check(g)

    def test_pending_choice_records_running_without_completion(self):
        g=self.waiting();d=self.records(g)[0];self.assertEqual(d.execution_order,1);self.assertFalse(d.completed)
        self.check(g);self.choose(g);self.assertTrue(self.records(g)[0].completed);self.assertEqual(self.armor(g),2);self.check(g)

    def test_empty_invalid_choice_rolls_back_pending_identity(self):
        from hs_sim.engine import SelectChoice
        g=self.waiting();before=g.snapshot();c=g.state.pending_choice
        with self.assertRaises(ValueError):g.apply(SelectChoice(c.player_id,c.id,()))
        self.assertEqual(g.snapshot(),before)

    def test_behavior_exception_rolls_back_capture_and_execution(self):
        def fail(c):raise ValueError('broken Deathrattle')
        self.r.register_behavior('fail',fail);self.minion('bad','fail')
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0])],board=('bad',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'broken Deathrattle'):self.invoke(g)
        self.assertEqual(g.snapshot(),before)

    def test_suspended_branch_exception_restores_only_current_action(self):
        self.r.register_behavior('badbranch',lambda c:[self.pause(c,Damage(99999,1))]);self.minion('badbranchbody','badbranch')
        # Damage to a stale target is legal; use an explicitly failing handler instead.
        from hs_sim.engine.effects import InvokeBehavior
        def fail(c):raise ValueError('branch failure')
        self.r.register_behavior('branchfail',fail)
        self.r._behaviors['badbranch']=lambda c:[self.pause(c,InvokeBehavior('branchfail',c.source_id,c.player_id))]
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0])],board=('badbranchbody',));self.invoke(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before)

    def test_invalid_history_status_and_execution_order_rejected(self):
        g=self.waiting()
        for values in ({'completed':True},{'interrupted':True},{'execution_order':2},{'execution_order':True}):
            s=g.snapshot();self.state_row(s)['deathrattle_history'][0].update(values)
            with self.subTest(values=values):self.reject(s)

    def test_wrong_death_or_ability_identity_rejected(self):
        g=self.waiting()
        for key,value in (('death_id',999),('carrier_id',999),('player_id',2),('group_id',2),('origin','effect')):
            s=g.snapshot();self.state_row(s)['deathrattle_history'][0]['capture'][key]=value
            with self.subTest(key=key):self.reject(s)

    def test_wrong_declaration_card_rejected(self):
        g=self.waiting();s=g.snapshot();self.state_row(s)['deathrattle_history'][0]['capture']['ability']['deathrattle_card_id']='body';self.reject(s)

    def test_extra_history_field_rejected(self):
        g=self.waiting();s=g.snapshot();self.state_row(s)['deathrattle_history'][0]['unknown']=1;self.reject(s)

    def test_deleted_completed_natural_record_rejected(self):
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0])]);self.invoke(g)
        s=g.snapshot();self.state_row(s)['deathrattle_history']=[];self.reject(s)

    def test_old_snapshot_schema_rejected(self):
        g=self.waiting();s=g.snapshot();self.assertEqual(s['schema_version'],265);s['schema_version']=88;self.reject(s)

    def test_query_filters_and_validation(self):
        g=self.waiting();self.assertEqual(len(activated_deathrattles(g.state,1,completed=False,origin='death',turn=1)),1)
        self.assertEqual(activated_deathrattles(g.state,2),())
        for kw in ({'completed':1},{'origin':'play'},{'turn':False}):
            with self.assertRaises(ValueError):activated_deathrattles(g.state,1,**kw)

    def test_player_observation_does_not_expose_internal_records(self):
        g=self.waiting();text=json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.player_events(1))+json.dumps(g.player_events(2))
        self.assertNotIn('deathrattle_history',text);self.assertNotIn('execution_order',text)
        self.assertNotIn('deathrattle_grant_card_id',text);self.assertNotIn('DeathrattleCapture',text)

    def test_same_batch_callbacks_keep_the_original_captured_board(self):
        self.r.register_behavior('summoner',lambda c:[Summon(c.player_id,'body')]);self.minion('summoner_body','summoner')
        self.r.register_behavior('count',lambda c:[GainArmor(c.player_id,len(c.state.players[1].board))]);self.minion('counter_body','count')
        g=self.script_game(lambda c:[DamageBatch(tuple(Damage(i,4) for i in c.state.players[1].board))],board=('summoner_body','counter_body'))
        self.invoke(g);self.assertEqual(self.armor(g),0);self.assertEqual(len(g.state.players[1].board),1);self.check(g)

    def test_live_trigger_keeps_second_callback_after_transform(self):
        self.r.register_behavior('selftransform',lambda c:[Transform(c.source_id,'body')]);self.minion('transformer','selftransform')
        g=self.script_game(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor',c.source_id),TriggerDeathrattles(c.state.players[1].board[0],c.source_id)],board=('transformer',))
        rows=self.invoke(g);self.assertEqual(len(rows),2);self.assertTrue(all(d.completed for d in rows))
        self.assertEqual(self.armor(g),1);self.assertEqual(g.state.entities[self.body(g,1)].card_id,'body');self.check(g)

    def test_diagnostic_controls_do_not_add_gameplay_checkpoints(self):
        def run(legacy=False):
            self.setUp()
            g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0])])
            if legacy:
                def old(r,carrier,player,abilities,**kw):return [r.call(a.behavior_id,carrier,player,event=kw.get('event'),death=kw.get('death')) for a in abilities]
                with patch('hs_sim.engine.deathrattles.schedule_group',old),patch('hs_sim.engine.deathrattles.validate_boundary',lambda g:None):self.invoke(g)
            else:self.invoke(g)
            return g
        new=run();old=run(True)
        self.assertEqual(new.events,old.events)
        a=new.snapshot()['state'];b=old.snapshot()['state']
        for field in ('deathrattle_history','deathrattle_batches','next_deathrattle_id'):a.pop(field);b.pop(field)
        self.assertEqual(a,b)

    def waiting_group(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))]);self.minion('waiting','wait')
        def work(c):
            i=c.state.players[1].board[0]
            return [GrantDeathrattle(i,'armor',c.source_id),GrantDeathrattle(i,'armor',c.source_id),Destroy(i)]
        g=self.script_game(work,board=('waiting',));self.invoke(g);return g
    def queue(self,s):return s['resolution_frame']['fields']['continuation']['tuple']

    def test_queued_siblings_restore_without_being_counted_as_started(self):
        g=self.waiting_group();self.assertEqual([d.execution_order for d in self.records(g)],[1,None,None])
        self.assertEqual(len(activated_deathrattles(g.state,1)),1);self.check(g)
        restored=g.clone();self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual([d.execution_order for d in self.records(g)],[1,2,3]);self.check(g)

    def test_missing_finish_marker_rejected(self):
        g=self.waiting();s=g.snapshot();self.queue(s).pop(0);self.reject(s)

    def test_duplicate_finish_marker_rejected(self):
        g=self.waiting();s=g.snapshot();self.queue(s).insert(0,deepcopy(self.queue(s)[0]));self.reject(s)

    def test_wrong_finish_identity_rejected(self):
        g=self.waiting();s=g.snapshot();self.queue(s)[0]['fields']['record_id']=999;self.reject(s)

    def test_missing_queued_invocation_rejected(self):
        g=self.waiting_group();s=g.snapshot();self.queue(s).pop(1);self.reject(s)

    def test_duplicate_queued_invocation_rejected(self):
        g=self.waiting_group();s=g.snapshot();self.queue(s).insert(1,deepcopy(self.queue(s)[1]));self.reject(s)

    def test_reordered_sibling_invocations_rejected(self):
        g=self.waiting_group();s=g.snapshot();q=self.queue(s);q[1],q[2]=q[2],q[1];self.reject(s)

    def test_queued_capture_provenance_mismatch_rejected(self):
        g=self.waiting_group();s=g.snapshot();self.state_row(s)['deathrattle_history'][1]['capture']['trigger_source_card_id']='body';self.reject(s)

    def test_duplicate_actual_execution_order_rejected(self):
        g=self.waiting_group();self.choose(g);s=g.snapshot();self.state_row(s)['deathrattle_history'][1]['execution_order']=1;self.reject(s)

    def test_callback_gets_capture_identity_without_live_stage_mutation(self):
        def captured(c):
            self.assertEqual(c.deathrattle.carrier_id,c.source_id)
            self.assertEqual(c.deathrattle.ability.behavior_id,'capture')
            self.assertIsNone(c.state.deathrattle_history[c.deathrattle.id-1].execution_order)
            return [GainArmor(c.player_id,c.deathrattle.id)]
        self.r.register_behavior('capture',captured);self.minion('captured','capture')
        g=self.script_game(lambda c:[Destroy(c.state.players[1].board[0])],board=('captured',))
        self.invoke(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_live_trigger_captured_grant_survives_bounce(self):
        self.r.register_behavior('bounce_self',lambda c:[ReturnToHand(c.source_id)])
        self.minion('bouncer','bounce_self')
        g=self.script_game(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor',c.source_id),TriggerDeathrattles(c.state.players[1].board[0])],board=('bouncer',))
        self.invoke(g);self.assertEqual(self.armor(g),1);self.assertFalse(g.state.players[1].board)
        self.assertTrue(all(d.completed for d in self.records(g)));self.check(g)

    def test_grant_source_card_frozen_before_later_transform(self):
        g=self.script_game(lambda c:[GrantDeathrattle(c.state.players[1].board[1],'armor',c.state.players[1].board[0]),
            Transform(c.state.players[1].board[0],'rattle'),Destroy(c.state.players[1].board[1])],board=('body','body'))
        d=self.invoke(g)[0];self.assertEqual(d.capture.ability.deathrattle_grant_card_id,'body');self.check(g)

    def test_unknown_grant_source_is_explicit_not_carrier(self):
        g=self.script_game(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),Destroy(c.state.players[1].board[0])],board=('body',))
        a=self.invoke(g)[0].capture.ability;self.assertIsNone(a.source_id);self.assertIsNone(a.deathrattle_grant_card_id);self.check(g)

    def test_magnetic_declaration_and_grant_source_remain_separate(self):
        from hs_sim.engine import CardMetadata,CardClass,PlayCard
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.minion('part','armor',keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),metadata=metadata)
        self.r.register_card(CardDefinition('host','host',CardType.MINION,health=4,metadata=metadata))
        g=self.game(hand=('part','kill'),board=('host',),enemy=());part=g.state.players[1].hand[0]
        g.apply(PlayCard(1,part,position=0));self.play(g,'kill',self.body(g,1));c=self.records(g)[0].capture
        self.assertEqual(c.card_id,'host');self.assertEqual(c.ability.deathrattle_card_id,'part')
        self.assertEqual(c.ability.deathrattle_grant_card_id,'part');self.assertEqual(c.ability.source_id,part);self.check(g)

    def test_starship_components_keep_each_printed_declaration(self):
        from examples.build_starship import run
        g,_=run();rows=[d for d in g.state.deathrattle_history if g.state.entities[d.capture.carrier_id].components]
        self.assertTrue(rows)
        self.assertTrue(all(d.capture.ability.deathrattle_card_id in g.state.entities[d.capture.carrier_id].components for d in rows))
        self.assertEqual(len({d.capture.ability.id for d in rows}),len(rows))

    def test_normal_rewind_discards_the_abandoned_activation(self):
        from hs_sim.engine import RewindSpec,SelectChoice
        self.script('rewinder',lambda c:[Destroy(c.state.players[1].board[0])],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewinder',),board=('rattle',),enemy=());self.play(g,'rewinder')
        self.assertEqual(len(self.records(g)),1);self.check(g)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('retry',)))
        self.assertEqual(len(self.records(g)),1);self.assertEqual(self.armor(g),1);self.check(g)

    def test_retained_rewind_records_two_actual_effect_triggers(self):
        from hs_sim.engine import RewindSpec
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.script('rewinder',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewinder',),board=('rattle','retainer'),enemy=());self.play(g,'rewinder')
        self.assertEqual(len(self.records(g)),2);self.assertEqual([d.execution_order for d in self.records(g)],[1,2])
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.death_history);self.check(g)

    def test_same_callback_can_be_triggered_again_as_new_group(self):
        g=self.script_game(lambda c:[TriggerDeathrattles(c.state.players[1].board[0]),TriggerDeathrattles(c.state.players[1].board[0])])
        a,b=self.invoke(g);self.assertEqual(a.capture.ability.id,b.capture.ability.id)
        self.assertNotEqual(a.capture.group_id,b.capture.group_id);self.check(g)

    def test_live_trigger_during_dormancy_does_not_queue(self):
        from hs_sim.engine.dormancy import MakeDormant
        g=self.script_game(lambda c:[MakeDormant(c.state.players[1].board[0],2),TriggerDeathrattles(c.state.players[1].board[0])])
        self.assertFalse(self.invoke(g));self.check(g)

    def test_native_player_example_restores_with_fresh_registry(self):
        from examples.deathrattle_activations import run
        g,s=run();self.assertEqual(s['schema_version'],265)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(len(g.state.deathrattle_history),4)


if __name__=='__main__':unittest.main()
