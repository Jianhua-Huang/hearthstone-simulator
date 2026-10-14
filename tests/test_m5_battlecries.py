"""Battlecry identity and hand-play provenance, provisional R-113."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from hs_sim.engine import (Game, Registry, CardDefinition, CardType, Scenario, PlayerSetup,
    PlayCard, SelectChoice, EndTurn, TargetSpec, TargetMode, TriggerSpec, Keyword,
    RewindSpec, AppendageSpec, BattlecryRecord, BattlecryPayload, activated_battlecries,
    IllegalAction, ResolutionError, SnapshotError, ChooseOneSpec, ChooseBranch)
from hs_sim.engine.effects import (GainArmor, Damage, Summon, EquipWeapon, Silence,
    Destroy, Transform, ChangeControl, CopyMinion, ReturnToHand, RequestChoice,
    ChoiceOption, InvokeBehavior)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.battlecries import BeginBattlecry, FinishBattlecry


class BattlecryTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('battlecry-foundation-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,health=5))
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,2)])
        self.r.register_card(CardDefinition('power','power',CardType.HERO_POWER,on_use='armor'))
        self.r.register_card(CardDefinition('cry','cry',CardType.MINION,cost=2,health=4,battlecry='armor'))
    def card(self,cid,fn=None,kind=CardType.MINION,**kw):
        if fn is not None:self.r.register_behavior(cid,fn)
        if kind in (CardType.MINION,CardType.HERO):kw.setdefault('health',4 if kind==CardType.MINION else 30)
        if kind==CardType.WEAPON:kw.setdefault('attack',2);kw.setdefault('durability',2)
        self.r.register_card(CardDefinition(cid,cid,kind,cost=2,battlecry=cid if fn else 'armor',**kw))
    def script(self,cid,fn):
        self.r.register_behavior(cid,fn);self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    def watch(self,cid,event,fn):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),)))
    def game(self,hand=('cry',),board=(),enemy=(),mana=10):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('body',)*4,mana=mana,max_mana=10),
            PlayerSetup('hero',hand=('cry',),board=enemy,deck=('body',)*4,mana=10,max_mana=10)),seed=73),self.r)
    def play(self,g,cid='cry',target=None,branch=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,i,target,branch_id=branch));return i
    def choose(self,g,option='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option,)))
    def pause(self,c):return RequestChoice(1,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))
    def nested(self,value,suffix):
        if isinstance(value,dict):
            if value.get('type','').endswith('.'+suffix):return value
            for v in value.values():
                if (found:=self.nested(v,suffix)) is not None:return found
        elif isinstance(value,list):
            for v in value:
                if (found:=self.nested(v,suffix)) is not None:return found
        return None

    def test_hand_play_has_one_payment_and_independent_completed_record(self):
        g=self.game();i=self.play(g);b=g.state.battlecry_history[0]
        self.assertEqual((b.source_id,b.card_id,b.play_id,b.player_id,b.origin),(i,'cry',1,1,'hand'))
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(2,8,1))
        self.assertTrue(b.completed);self.assertFalse(b.interrupted);self.assertEqual(g.state.cast_history,[]);self.check(g)
    def test_normal_on_play_does_not_become_battlecry(self):
        self.r.register_card(CardDefinition('generic','generic',CardType.MINION,health=2,on_play='armor'))
        g=self.game(hand=('generic',));self.play(g,'generic');self.assertEqual(self.armor(g),2)
        self.assertEqual(g.state.battlecry_history,[]);self.check(g)
    def test_spell_payload_is_not_battlecry(self):
        self.script('spell',lambda c:[GainArmor(1,3)])
        g=self.game(hand=('spell',));self.play(g,'spell');self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.battlecry_history,[]);self.check(g)
    def test_choose_one_minion_remains_separate(self):
        spec=ChooseOneSpec((ChooseBranch('a','A','armor'),ChooseBranch('b','B','armor')),ChooseBranch('both','Both','armor'))
        self.r.register_card(CardDefinition('choose','choose',CardType.MINION,health=3,choose_one=spec))
        g=self.game(hand=('choose',));self.play(g,'choose',branch='a')
        self.assertEqual(self.armor(g),2);self.assertEqual(g.state.battlecry_history,[]);self.check(g)
    def test_generic_then_battlecry_have_explicit_order(self):
        self.r.register_behavior('first',lambda c:[GainArmor(1,5)])
        self.card('mixed',lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].armor)],on_play='first')
        g=self.game(hand=('mixed',));self.play(g,'mixed');self.assertEqual(self.armor(g),10);self.check(g)
    def test_normal_summon_never_activates_battlecry(self):
        self.script('summon',lambda c:[Summon(1,'cry')])
        g=self.game(hand=('summon',));self.play(g,'summon')
        self.assertEqual(self.armor(g),0);self.assertEqual(g.state.battlecry_history,[]);self.check(g)
    def test_weapon_hand_play_activates_after_equip(self):
        self.card('weapon',lambda c:[GainArmor(1,3 if c.state.players[1].weapon_id==c.source_id else 99)],kind=CardType.WEAPON)
        g=self.game(hand=('weapon',));i=self.play(g,'weapon')
        self.assertEqual(self.armor(g),3);self.assertEqual(g.state.players[1].weapon_id,i);self.check(g)
    def test_effect_equipping_weapon_does_not_activate(self):
        self.card('weapon',kind=CardType.WEAPON)
        self.script('equip',lambda c:[EquipWeapon(1,'weapon')])
        g=self.game(hand=('equip',));self.play(g,'equip')
        self.assertEqual(self.armor(g),0);self.assertEqual(g.state.battlecry_history,[]);self.check(g)
    def test_hero_card_activates_without_duplicate_replacement(self):
        self.card('hero_card',lambda c:[GainArmor(1,7)],kind=CardType.HERO,hero_card=True,hero_armor=5,initial_hero_power='power')
        g=self.game(hand=('hero_card',));i=self.play(g,'hero_card')
        self.assertEqual(self.armor(g),12);self.assertEqual(g.state.players[1].hero_id,i)
        self.assertEqual(sum(e.kind=='hero_replaced' for e in g.events),1);self.check(g)
    def test_required_target_validation_precedes_payment(self):
        self.card('target',targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(hand=('target',));s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'target')
        self.assertEqual(g.snapshot(),s)
    def test_if_available_can_play_with_no_target(self):
        self.card('target',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(hand=('target',));self.play(g,'target')
        self.assertIsNone(g.state.battlecry_history[0].target_id);self.assertEqual(self.armor(g),2);self.check(g)
    def test_target_is_recorded_and_resolved_by_common_damage(self):
        self.card('damage',lambda c:[Damage(c.target_id,3,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(hand=('damage',),enemy=('body',));target=g.state.players[2].board[0];self.play(g,'damage',target)
        self.assertEqual(g.state.battlecry_history[0].target_id,target);self.assertEqual(g.state.entities[target].health,2);self.check(g)
    def test_no_effect_battlecry_still_has_completed_activation(self):
        self.card('empty',lambda c:[]);g=self.game(hand=('empty',));self.play(g,'empty')
        self.assertTrue(g.state.battlecry_history[0].completed);self.assertEqual(self.armor(g),0);self.check(g)
    def test_context_has_original_play_and_current_battlecry(self):
        self.card('context',lambda c:[GainArmor(1,5 if c.battlecry and c.battlecry.play_id==c.play.id and
            c.battlecry.source_id==c.source_id and not c.battlecry.completed else 99)])
        g=self.game(hand=('context',));self.play(g,'context');self.assertEqual(self.armor(g),5);self.check(g)
    def test_start_and_finish_listeners_read_captured_history(self):
        self.watch('start','battlecry_started',lambda c:[GainArmor(1,3 if c.battlecry and not c.battlecry.completed else 99)])
        self.watch('finish','battlecry_finished',lambda c:[GainArmor(1,5 if c.battlecry and c.battlecry.completed else 99)])
        g=self.game(board=('start','finish'));self.play(g);self.assertEqual(self.armor(g),10);self.check(g)
    def test_death_in_entry_reaction_keeps_accepted_battlecry(self):
        self.watch('kill','minion_summoned',lambda c:[Destroy(c.event.source_id)])
        g=self.game(board=('kill',));i=self.play(g)
        self.assertNotIn(i,g.state.players[1].board);self.assertEqual(self.armor(g),2);self.check(g)
    def test_silence_in_entry_reaction_does_not_erase_captured_activation(self):
        self.watch('silence','minion_summoned',lambda c:[Silence(c.event.source_id)])
        g=self.game(board=('silence',));i=self.play(g)
        self.assertTrue(g.state.entities[i].silenced);self.assertEqual(self.armor(g),2);self.check(g)
    def test_control_change_preserves_captured_player(self):
        self.watch('steal','minion_summoned',lambda c:[ChangeControl(c.event.source_id,2)])
        g=self.game(board=('steal',));i=self.play(g)
        self.assertEqual(g.state.entities[i].controller,2);self.assertEqual((self.armor(g),self.armor(g,2)),(2,0));self.check(g)
    def test_transformation_preserves_original_record_and_payload(self):
        self.watch('morph','minion_summoned',lambda c:[Transform(c.event.source_id,'body')])
        g=self.game(board=('morph',));i=self.play(g)
        self.assertEqual(g.state.entities[i].card_id,'body');self.assertEqual(g.state.battlecry_history[0].card_id,'cry')
        self.assertEqual(self.armor(g),2);self.check(g)
    def test_return_to_hand_preserves_accepted_payload(self):
        self.watch('bounce','minion_summoned',lambda c:[ReturnToHand(c.event.source_id)])
        g=self.game(board=('bounce',));i=self.play(g)
        self.assertIn(i,g.state.players[1].hand);self.assertEqual(self.armor(g),2);self.check(g)
    def test_copy_carries_identity_without_triggering(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        g=self.game(hand=('copy',),board=('cry',));self.play(g,'copy')
        self.assertEqual(g.state.battlecry_history,[]);self.assertEqual(self.armor(g),0)
        ids=[next(a.id for a in g.state.entities[i].abilities if a.kind=='battlecry') for i in g.state.players[1].board]
        self.assertEqual(len(set(ids)),2);self.check(g)
    def test_silence_removes_passive_battlecry_identity(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(hand=('silence',),board=('cry',));self.play(g,'silence')
        self.assertFalse(any(a.kind=='battlecry' for a in g.state.entities[g.state.players[1].board[0]].abilities));self.check(g)
    def test_bounce_and_replay_install_fresh_ability_identity(self):
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('cry','bounce'));self.play(g);self.play(g,'bounce');self.play(g)
        self.assertEqual(self.armor(g),4);self.assertNotEqual(*[b.payload.ability_id for b in g.state.battlecry_history]);self.check(g)
    def test_dormant_hand_play_can_activate_battlecry(self):
        self.card('sleep',dormant_turns=2);g=self.game(hand=('sleep',));i=self.play(g,'sleep')
        self.assertIsNotNone(g.state.entities[i].dormancy);self.assertEqual(self.armor(g),2);self.check(g)
    def test_colossal_battlecry_runs_after_appendages(self):
        self.card('giant',lambda c:[GainArmor(1,len(c.state.players[1].board))],colossal=(AppendageSpec('body'),),keywords=(Keyword.COLOSSAL,))
        g=self.game(hand=('giant',));self.play(g,'giant')
        self.assertEqual(self.armor(g),2);self.assertTrue(g.state.colossal_history[0].completed);self.check(g)
    def test_colossal_summon_does_not_activate_battlecry(self):
        self.card('giant',colossal=(AppendageSpec('body'),),keywords=(Keyword.COLOSSAL,));self.script('summon',lambda c:[Summon(1,'giant')])
        g=self.game(hand=('summon',));self.play(g,'summon')
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual(g.state.battlecry_history,[]);self.check(g)
    def test_pause_inside_battlecry_restores_and_finishes_once(self):
        self.card('pause',lambda c:[self.pause(c),GainArmor(1,3)])
        g=self.game(hand=('pause',));self.play(g,'pause');self.assertFalse(g.state.battlecry_history[0].completed);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),3);self.check(g)
    def test_pause_before_begin_preserves_queued_identity(self):
        self.watch('pause','card_committed',lambda c:[self.pause(c)])
        g=self.game(board=('pause',));self.play(g);self.assertEqual(g.state.battlecry_history,[]);self.check(g)
        self.choose(g);self.assertTrue(g.state.battlecry_history[0].completed);self.check(g)
    def test_completion_reaction_pause_has_completed_record(self):
        self.watch('pause','battlecry_finished',lambda c:[self.pause(c)])
        g=self.game(board=('pause',));self.play(g);self.assertTrue(g.state.battlecry_history[0].completed);self.check(g)
        self.choose(g);self.check(g)
    def test_terminal_payload_marks_interruption_not_completion(self):
        self.card('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id),GainArmor(1,99)])
        g=self.game(hand=('lethal',));self.play(g,'lethal')
        self.assertTrue(g.state.battlecry_history[0].interrupted);self.assertFalse(g.state.battlecry_history[0].completed)
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.play_history[0].interrupted);self.check(g)
    def test_terminal_before_begin_does_not_invent_activation(self):
        self.watch('lethal','card_committed',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.game(board=('lethal',));self.play(g);self.assertEqual(g.state.battlecry_history,[]);self.check(g)
    def test_failure_before_pause_rolls_back_everything(self):
        self.card('bad',lambda c:[GainArmor(1,3),Summon(1,'unknown')])
        g=self.game(hand=('bad',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),s)
    def test_failure_after_pause_rolls_back_to_pending_battlecry(self):
        self.r.register_behavior('bad',lambda c:[Summon(1,'unknown')])
        self.card('pause',lambda c:[self.pause(c),InvokeBehavior('bad',c.source_id,1)])
        g=self.game(hand=('pause',));self.play(g,'pause');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.check(g)
    def test_rewind_retry_replaces_history_without_double_payment(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history),len(g.state.battlecry_history)),(3,8,1,1));self.check(g)
    def test_retained_outcomes_record_each_actual_execution(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(2))
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(9,8,1))
        self.assertEqual([b.iteration for b in g.state.battlecry_history],[1,2,3])
        self.assertEqual({b.outcome_id for b in g.state.battlecry_history},{1});self.check(g)
    def test_retained_battlecry_pause_restores_between_outcomes(self):
        self.card('rewind',lambda c:[self.pause(c),GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind');self.check(g);self.choose(g);self.check(g)
        self.assertEqual([b.completed for b in g.state.battlecry_history],[True,False]);self.choose(g)
        self.assertEqual(self.armor(g),3);self.check(g)
    def test_retained_payload_survives_source_transformation(self):
        self.card('rewind',lambda c:[Transform(c.source_id,'body'),GainArmor(1,2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('retainer',));i=self.play(g,'rewind')
        self.assertEqual(g.state.entities[i].card_id,'body');self.assertEqual(self.armor(g),4)
        self.assertEqual([b.card_id for b in g.state.battlecry_history],['rewind','rewind']);self.check(g)
    def test_retained_lethal_stops_further_activations(self):
        self.card('rewind',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(2))
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.assertEqual(len(g.state.battlecry_history),1);self.assertTrue(g.state.battlecry_history[0].interrupted);self.check(g)
    def test_history_query_filters_and_input_validation(self):
        g=self.game(hand=('cry','cry'));self.play(g);self.play(g)
        self.assertEqual(len(activated_battlecries(g.state,1,successful=True)),2)
        self.assertEqual(len(activated_battlecries(g.state,1,before_id=2)),1)
        self.assertEqual(activated_battlecries(g.state,2),())
        for kw in ({'successful':1},{'before_id':True},{'turn':-1}):
            with self.assertRaises(ValueError):activated_battlecries(g.state,1,**kw)
    def test_host_diagnostic_events_and_records_are_private(self):
        g=self.game();self.play(g)
        self.assertEqual(sum(e.kind.startswith('battlecry_') for e in g.events),2)
        for p in (1,2):
            public=json.dumps((g.observe(p),g.player_events(p)),ensure_ascii=False)
            self.assertNotIn('battlecry_history',public);self.assertNotIn('battlecry_id',public)
            self.assertNotIn('battlecry_started',public);self.assertNotIn('behavior_id',public)
        self.check(g)
    def test_player_command_uses_existing_shared_legality(self):
        g=self.game();p=g.for_player(1);listing=p.legal_actions()
        a=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(p.submit({'revision':listing['revision'],'action':a})['accepted'])
        self.assertEqual(len(g.state.battlecry_history),1);self.check(g)
    def test_snapshot_rejects_wrong_record_provenance(self):
        g=self.game();self.play(g)
        for changes in ({'play_id':99},{'card_id':'body'},{'target_id':999},{'origin':'effect'},{'id':2},{'iteration':2},{'completed':False},{'player_id':2}):
            s=g.snapshot();s['state']['battlecry_history'][0].update(changes);self.reject(s)
    def test_snapshot_rejects_unknown_and_mismatched_payload(self):
        g=self.game();self.play(g)
        for changes in ({'behavior_id':'missing'},{'ability_id':999999},{'ability_id':True},{'card_id':'body'}):
            s=g.snapshot();s['state']['battlecry_history'][0]['payload'].update(changes);self.reject(s)
    def test_snapshot_rejects_duplicate_activation(self):
        g=self.game();self.play(g);s=g.snapshot();b=deepcopy(s['state']['battlecry_history'][0]);b['id']=2
        s['state']['battlecry_history'].append(b);self.reject(s)
    def test_snapshot_rejects_missing_finish_marker(self):
        self.card('pause',lambda c:[self.pause(c)]);g=self.game(hand=('pause',));self.play(g,'pause');s=g.snapshot()
        marker=self.nested(s['resolution_frame'],'FinishBattlecry');self.assertIsNotNone(marker)
        marker['fields']['record_id']=99;self.reject(s)
    def test_snapshot_rejects_corrupt_queued_begin(self):
        self.watch('pause','minion_summoned',lambda c:[self.pause(c)]);g=self.game(board=('pause',));self.play(g);s=g.snapshot()
        marker=self.nested(s['resolution_frame'],'BeginBattlecryBatch');self.assertIsNotNone(marker)
        marker['fields']['play_id']=99;self.reject(s)
    def test_snapshot_rejects_corrupt_retained_payload(self):
        self.card('rewind',lambda c:[self.pause(c)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind');s=g.snapshot()
        s['state']['rewind_outcomes'][0]['battlecries'][0]['behavior_id']='armor';self.reject(s)
    def test_old_snapshot_and_missing_history_are_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=71
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)
        s=g.snapshot();del s['state']['battlecry_history'];self.reject(s)
    def test_invalid_definitions_and_unregistered_behavior_rejected(self):
        for kind in (CardType.SPELL,CardType.HERO_POWER,CardType.LOCATION):
            with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',kind,battlecry='armor'))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,battlecry=''))
        self.card('unknown',lambda c:[]);r=Registry('bad')
        r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,battlecry='missing'))
        with self.assertRaises(ValueError):r.freeze()
    def test_record_scalar_types_and_invalid_progress_rejected(self):
        g=self.game();self.play(g);record=g.state.battlecry_history[0]
        for changes in ({'player_id':True},{'iteration':0},{'interrupted':True},{'payload':'bad'},{'play_id':0}):
            with self.assertRaises(ValueError):replace(record,**changes)
    def test_snapshot_rejects_mismatched_ability_declaration(self):
        g=self.game(board=('cry',));s=g.snapshot()
        entity=s['state']['entities'][str(g.state.players[1].board[0])]
        next(a for a in entity['abilities'] if a['kind']=='battlecry')['battlecry_card_id']='body'
        self.reject(s)
    def test_printed_battlecry_and_choose_one_composition_rejected_explicitly(self):
        spec=ChooseOneSpec((ChooseBranch('a','A','armor'),ChooseBranch('b','B','armor')),ChooseBranch('both','Both','armor'))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,battlecry='armor',choose_one=spec))


class RepresentativeBattlecryTests(unittest.TestCase):
    def composed_ship(self,count):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine import LaunchStarship
        from hs_sim.engine.effects import DamageBatch
        from hs_sim.engine.starships import construction
        r=build_registry()
        r.register_behavior('scrap',lambda c:[DamageBatch(tuple(Damage(i,100) for i in c.state.players[1].board))])
        r.register_behavior('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        for cid in ('scrap','bounce'):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('SC_405',)*count,hand=('scrap','bounce'),mana=10,max_mana=10),PlayerSetup('HERO_08')),seed=73),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));ship=construction(g.state,1)
        g.apply(LaunchStarship(1,ship.id));self.assertEqual(g.state.battlecry_history,[])
        g.apply(PlayCard(1,g.state.players[1].hand[0]));g.apply(PlayCard(1,ship.id))
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())
        return g,ship.id
    def test_composed_ship_replay_retains_component_declaration(self):
        g,ship=self.composed_ship(1);b=g.state.battlecry_history[0]
        self.assertEqual(b.source_id,ship);self.assertEqual(b.card_id,g.state.entities[ship].card_id)
        self.assertEqual(b.payload.card_id,'SC_405');self.assertTrue(b.completed)
    def test_repeated_ship_components_execute_distinct_printed_abilities(self):
        g,_=self.composed_ship(2);records=g.state.battlecry_history
        self.assertEqual(len(records),2);self.assertEqual({b.payload.card_id for b in records},{'SC_405'})
        self.assertEqual(len({b.payload.ability_id for b in records}),2)
    def test_all_44_reviewed_declarations_are_explicit_without_generic_payload(self):
        from hs_sim.engine.representative import build_registry
        registry=build_registry();root=Path(__file__).resolve().parents[1]
        rows=json.loads((root/'outputs/m5-13d-battlecry-candidates.json').read_text(encoding='utf-8'))['current_representatives_with_battlecry_tag']
        self.assertEqual(len(rows),44)
        for row in rows:
            c=registry.card(row['id']);self.assertIsNotNone(c.battlecry,row['id']);self.assertIsNone(c.on_play,row['id'])
        self.assertIsNotNone(registry.card('EX1_178').choose_one)
        self.assertIsNone(registry.card('EX1_178').battlecry)
    def test_real_discovery_battlecry_has_pause_restore_and_single_payment(self):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine import GenerationContext
        r=build_registry();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('LOE_029',),mana=10,max_mana=10),
            PlayerSetup('HERO_01')),seed=73,generation_context=GenerationContext('local-2026-09-23','experimental')),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));self.assertIsNotNone(g.state.pending_choice)
        saved=Game.from_snapshot(g.snapshot(),r)
        for game in (g,saved):
            c=game.state.pending_choice;game.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(g.state.players[1].mana,8)
        self.assertEqual(len(g.state.play_history),1);self.assertTrue(g.state.battlecry_history[0].completed)
        self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
