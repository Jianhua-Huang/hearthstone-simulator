"""Real historical producers: distinct authorization and per-invocation inputs."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BodyPlayReference,BodyTargetProfile,HistoricalBattlecryBinding,CardDefinition,CardType,
    Game,IfBodyCondition,Keyword,PlayCard,PlayerSetup,PlayerTargetRuleSpec,Scenario,SelectChoice,
    TargetSpec,TriggerSpec,Zone,body_play_conditions)
from hs_sim.engine.battlecry_sources import BattlecryHistoryQuery,RepeatBattlecry,RepeatBattlecries
from hs_sim.engine.played_battlecries import RepeatPlayedBattlecry,RepeatPlayedBattlecries,PlayedBattlecryQuery
from hs_sim.engine.battlecry_sequences import RepeatPlayedBattlecrySequence,BattlecrySequencePolicy
from hs_sim.engine.effects import (Buff,ChangeControl,ChangeManaCrystals,ChoiceOption,Damage,Destroy,
    GainArmor,RandomDamage,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


def registry(mode='normal',route='sequence',policy='random',scope='complete'):
    r=Registry('historical-body-'+mode+'-'+route+'-'+policy+'-'+scope+'-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('tiny','Tiny',CardType.MINION,health=20))
    if mode in ('player','player_control'):
        r.register_player_target_rule(PlayerTargetRuleSpec('visible','v1'),
            lambda c:c.target['health']<=c.observation['players'][c.player_id-1]['max_mana']+20)
    target_rule='visible' if mode in ('player','player_control') else 'any_entity'
    enemy=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,),relation='enemy')
    all_minions=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,))

    def body(c):
        if c.battlecry.origin=='hand': return (GainArmor(c.player_id,1),)
        ref=BodyPlayReference.capture(c,'battlecry'); low=ref.declaration_card_id=='low'
        effects=[]
        if low:
            if mode=='crystals': effects.append(ChangeManaCrystals(c.player_id,-7))
            elif mode=='transform':effects.append(Transform(c.source_id,'tiny'))
            elif mode in ('control','player_control'):effects.append(ChangeControl(c.source_id,2))
            elif mode in ('bounce','stop_on_leave'):effects.append(ReturnToHand(c.source_id))
            elif mode=='death':effects.append(Destroy(c.source_id))
            elif mode=='silence':effects.append(Silence(c.source_id))
            elif mode=='target_change' and c.target_id is not None:effects.append(Buff(c.target_id,health=3))
            elif mode=='nested' and len(c.state.historical_body_invocations)==1:
                effects.append(RepeatBattlecry(c.player_id,c.source_id,1,choices='player',profile_id='history'))
            elif mode=='terminal':effects.append(Damage(c.state.players[2].hero_id,80))
            elif mode=='fail':effects.extend((RandomDamage(tuple(c.state.players[2].board),1),Summon(c.player_id,'unknown.history.body')))
        if mode=='body_wait': effects.append(RequestChoice(c.player_id,(ChoiceOption('go','Go'),),c.source_id))
        effects.append(IfBodyCondition(ref,'manathirst',(GainArmor(c.player_id,5),),(GainArmor(c.player_id,1),)))
        if c.target_id is not None:effects.append(Damage(c.target_id,1))
        return tuple(effects)
    r.register_behavior('body',body)
    for card,threshold in (('low',6),('high',10)):
        r.register_card(CardDefinition(card,card,CardType.MINION,health=6,battlecry='body',
            targeting=all_minions if mode=='exclude_self' else enemy,target_rule=target_rule,
            keywords=(Keyword.MANATHIRST,),manathirst=threshold,
            target_condition=None if mode in ('unconditional','exclude_self','player_control') else 'manathirst'))
    def watch(c):
        if not c.state.historical_body_invocations or c.event.source_id != next(i for i in c.state.entities
                if c.state.entities[i].card_id=='carrier'): return ()
        if c.event.kind=='battlecry_started':
            return (ChangeManaCrystals(1,-1),RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id))
        return (RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id),)
    r.register_behavior('watch',watch)
    event='battlecry_finished' if mode=='finish_wait' else 'battlecry_started'
    r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=20,
        triggers=(TriggerSpec(event,'watch'),) if mode in ('start_wait','finish_wait') else ()))
    def invoke(c):
        carrier=next(i for i in c.state.entities if c.state.entities[i].card_id=='carrier')
        profile=None if scope=='omitted' else 'history'
        target=c.state.players[2].board[0] if policy=='explicit' and c.state.players[2].board else None
        work=[]
        if mode=='empty':work.extend(Destroy(i) for i in c.state.players[2].board)
        if route=='activation':work.append(RepeatBattlecry(1,carrier,1,target_id=target,targeting=policy,choices='player',profile_id=profile))
        elif route=='activations':work.append(RepeatBattlecries(1,carrier,selection='all',choices='player',profile_id=profile))
        elif route=='played':work.append(RepeatPlayedBattlecry(1,carrier,1,target_id=target,targeting=policy,choices='player',profile_id=profile))
        elif route=='plays':work.append(RepeatPlayedBattlecries(1,carrier,selection='all',choices='player',profile_id=profile))
        else:
            source_policy='in_play' if mode=='stop_on_leave' else 'captured'
            work.append(RepeatPlayedBattlecrySequence(1,carrier,5,choices='player',profile_id=profile,
                policy=BattlecrySequencePolicy(source=source_policy,controller='current' if mode in ('control','player_control') else 'captured',
                    exclude_source_target=mode=='exclude_self')))
        return tuple(work)
    r.register_behavior('invoke',invoke)
    r.register_card(CardDefinition('carrier','Carrier',CardType.MINION,health=20,
        cost=1 if mode=='paid_parent' else 0,battlecry='invoke' if mode=='paid_parent' else None))
    r.register_card(CardDefinition('invoke','Invoke',CardType.SPELL,cost=1,on_play='invoke'))
    r.register_body_target_profile(BodyTargetProfile('history','historical_battlecry',policy,'historical_invocation'))
    if scope!='no_binding':
        declarations=('low',) if scope=='partial' else ('low','high')
        r.register_historical_battlecry_binding(HistoricalBattlecryBinding('carrier','history',declarations,
            ('history',) if scope=='activation_only' else ('history','played_history')))
    return r


class HistoricalBodyTargetTests(unittest.TestCase):
    def game(self,mode='normal',route='sequence',policy='random',scope='complete'):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('low','high','invoke')+(('carrier',) if mode=='paid_parent' else ()),
            board=('watch',) if mode=='paid_parent' else ('carrier','watch'),mana=7,max_mana=7),
            PlayerSetup('hero',board=('tiny','tiny'),hand=('tiny',),mana=7,max_mana=7)),seed=37),registry(mode,route,policy,scope))
        self.play(g,'low',g.state.players[2].board[0])
        self.play(g,'high',g.state.players[2].board[0] if mode in ('unconditional','exclude_self','player_control') else None)
        return g

    def play(self,g,card,target=None):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==card)
        return g.apply(PlayCard(1,source,target))

    def settled(self,*args):
        g=self.game(*args);self.play(g,'invoke');return g

    def choose(self,g):
        choice=g.state.pending_choice
        return g.apply(SelectChoice(choice.player_id,choice.id,('go',)))

    def portable(self,g,mode='normal',route='sequence',policy='random',scope='complete'):
        snapshot=json.loads(json.dumps(g.snapshot()))
        copies=(Game.from_snapshot(snapshot,registry(mode,route,policy,scope)),g.clone(),
            replay(build_replay(g),registry(mode,route,policy,scope)))
        for copy in copies:
            self.assertEqual(copy.snapshot(),snapshot)
            for seat in (1,2):self.assertEqual(copy.observe(seat),g.observe(seat))
        return copies

    def reject(self,g,mutate,mode='normal'):
        snapshot=deepcopy(g.snapshot());mutate(snapshot)
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(snapshot,registry(mode))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_all_five_actual_history_producers_capture_own_conditions(self):
        for route in ('activation','activations','played','plays','sequence'):
            with self.subTest(route=route):
                g=self.settled('normal',route);rows=g.state.historical_body_invocations
                self.assertEqual(len(rows),1 if route in ('activation','played') else 2)
                self.assertTrue(all(row.completed for row in rows))
                self.assertEqual(rows[0].conditions.manathirst_threshold,6)
                self.assertTrue(rows[0].conditions.manathirst)
                self.assertEqual(len(g.state.play_history),3)
                self.assertFalse(g.state.combo_history)
                self.assertTrue(all(b.play_id is None for b in g.state.battlecry_history[2:]))
                self.portable(g,route=route)

    def test_next_body_accepts_new_crystals_without_rewriting_first(self):
        g=self.settled('crystals');low,high=g.state.historical_body_invocations
        self.assertEqual((low.conditions.mana_crystals,high.conditions.mana_crystals),(7,0))
        self.assertTrue(low.conditions.manathirst);self.assertFalse(high.conditions.manathirst)
        self.assertEqual(high.selection.partition.mode,None)
        self.assertEqual(high.selection.rng_before,high.selection.rng_after)
        self.portable(g,'crystals')

    def test_explicit_target_uses_selected_body_domain_and_no_rng(self):
        g=self.settled('normal','played','explicit');row=g.state.historical_body_invocations[-1]
        self.assertEqual(row.selection.target_id,g.state.players[2].board[0])
        self.assertEqual(row.selection.rng_before,row.selection.rng_after)
        self.portable(g,route='played',policy='explicit')

    def test_random_empty_required_target_records_failure_without_branch_or_rng(self):
        g=self.settled('empty');rows=g.state.historical_body_invocations
        self.assertEqual(rows[0].selection.failure,'no_target')
        self.assertFalse(g.state.battlecry_history[2].payload_started)
        self.assertEqual(rows[0].selection.rng_before,rows[0].selection.rng_after)
        self.assertEqual(rows[1].selection.failure,None)
        self.portable(g,'empty')

    def test_current_execution_conditions_do_not_restore_original_hand_position(self):
        g=self.settled()
        for record in g.state.battlecry_history[2:]:
            facts=body_play_conditions(g.state,g.registry,BodyPlayReference.from_record(record,'battlecry'))
            self.assertTrue(facts.combo)
            self.assertEqual((facts.outcast,facts.finale,facts.quickdraw),(False,False,False))

    def test_body_wait_restores_original_finish_and_resumes_without_recapture(self):
        g=self.settled('body_wait');self.assertIsNotNone(g.state.pending_choice)
        for match in (g,*self.portable(g,'body_wait')):
            while match.state.pending_choice is not None:
                self.choose(match)
            self.assertEqual(match.snapshot(),g.snapshot())
            self.assertTrue(all(row.completed for row in match.state.historical_body_invocations))

    def test_start_wait_changes_live_crystals_but_preserves_prior_acceptance(self):
        g=self.settled('start_wait');self.assertIsNotNone(g.state.pending_choice)
        first=g.state.historical_body_invocations[0];self.assertEqual(first.conditions.mana_crystals,7)
        self.assertEqual(g.state.players[1].max_mana,6)
        for match in (g,*self.portable(g,'start_wait')):
            while match.state.pending_choice is not None:self.choose(match)
            self.assertEqual(match.snapshot(),g.snapshot())

    def test_completed_body_finish_listener_keeps_pending_original_proof(self):
        g=self.settled('finish_wait');self.assertTrue(g.state.battlecry_history[-1].completed)
        self.assertFalse(g.state.historical_body_invocations[-1].completed)
        for match in (g,*self.portable(g,'finish_wait')):
            while match.state.pending_choice is not None:self.choose(match)
            self.assertEqual(match.snapshot(),g.snapshot())

    def test_captured_sequence_survives_carrier_transform(self):
        g=self.settled('transform');self.assertEqual(len(g.state.historical_body_invocations),2)
        self.assertEqual([b.card_id for b in g.state.battlecry_history[2:]],['carrier','carrier'])
        self.portable(g,'transform')

    def test_current_controller_sequence_retains_old_history_owner(self):
        g=self.settled('control');records=g.state.battlecry_history[2:]
        self.assertEqual([b.player_id for b in records],[1,2])
        self.assertEqual([b.history_player_id for b in records],[1,1])
        self.assertFalse(g.state.historical_body_invocations[-1].conditions.combo)
        self.portable(g,'control')

    def test_captured_sequence_survives_carrier_return_to_hand(self):
        g=self.settled('bounce');self.assertEqual(len(g.state.historical_body_invocations),2)
        self.assertEqual(g.state.entities[g.state.battlecry_history[-1].source_id].zone,Zone.HAND)
        self.portable(g,'bounce')

    def test_in_play_source_policy_stops_later_attempt_after_return(self):
        g=self.settled('stop_on_leave')
        self.assertEqual(len(g.state.historical_body_invocations),1)
        self.assertTrue(g.state.historical_body_invocations[0].completed)
        self.portable(g,'stop_on_leave')

    def test_captured_sequence_survives_carrier_death(self):
        g=self.settled('death');self.assertEqual(len(g.state.historical_body_invocations),2)
        self.portable(g,'death')

    def test_captured_sequence_survives_carrier_silence(self):
        g=self.settled('silence');self.assertEqual(len(g.state.historical_body_invocations),2)
        self.portable(g,'silence')

    def test_sequence_self_exclusion_is_its_own_accepted_policy(self):
        g=self.settled('exclude_self')
        for row in g.state.historical_body_invocations:
            self.assertEqual(row.selection.partition.excluded_ids,(row.request.source_id,))
            self.assertNotIn(row.request.source_id,row.selection.partition.legal_ids)
        self.portable(g,'exclude_self')

    def test_nested_history_roots_keep_distinct_receipts_and_parent(self):
        g=self.settled('nested');self.assertEqual(len(g.state.historical_body_invocations),3)
        self.assertEqual([row.record_id for row in g.state.historical_body_invocations],[3,4,5])
        self.assertEqual(g.state.battlecry_history[3].parent_id,3)
        self.portable(g,'nested')

    def test_paid_outer_battlecry_retains_child_proofs_and_pays_only_its_root(self):
        g=self.game('paid_parent');mana=g.state.players[1].mana;self.play(g,'carrier')
        self.assertEqual(g.state.players[1].mana,mana-1)
        self.assertEqual(len(g.state.play_history),3)
        self.assertEqual([b.parent_id for b in g.state.battlecry_history[3:]],[3,3])
        self.assertTrue(g.state.battlecry_history[2].completed)
        self.assertTrue(all(row.completed for row in g.state.historical_body_invocations))
        self.portable(g,'paid_parent')

    def test_registered_player_condition_uses_own_original_observation(self):
        g=self.settled('player');row=g.state.historical_body_invocations[0]
        self.assertIsNotNone(row.observation)
        self.portable(g,'player')

    def test_player_condition_after_control_change_uses_nonactive_executor_view(self):
        g=self.settled('player_control');rows=g.state.historical_body_invocations
        self.assertEqual([row.request.player_id for row in rows],[1,2])
        self.assertEqual([json.loads(row.observation.observation_json)['viewer'] for row in rows],[1,2])
        self.assertEqual(g.state.active_player,1)
        self.assertFalse(rows[1].conditions.combo)
        self.portable(g,'player_control')

    def test_closed_player_inputs_cannot_borrow_seat_turn_or_future_reference(self):
        g=self.settled('player_control')
        def wrong_seat(s):
            rows=s['state']['historical_body_invocations']
            rows[1]['observation']=deepcopy(rows[0]['observation'])
        def wrong_turn(s):
            observed=s['state']['historical_body_invocations'][1]['observation']
            value=json.loads(observed['observation_json']);value['turn']+=1
            observed['observation_json']=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        def future_reference(s):
            row=s['state']['historical_body_invocations'][1]
            row['observation']['references'][0][0]=row['next_entity_id']
        for mutate in (wrong_seat,wrong_turn,future_reference):
            with self.subTest(mutation=mutate.__name__):self.reject(g,mutate,'player_control')

    def test_unbound_profile_and_partial_declaration_scope_fail_atomically(self):
        for scope in ('no_binding','partial','activation_only','omitted'):
            with self.subTest(scope=scope):
                g=self.game(scope=scope);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,'invoke')
                self.assertEqual(g.snapshot(),before)

    def test_unknown_selected_body_rolls_back_history_carrier_payment_and_rng(self):
        g=self.game('fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'invoke')
        self.assertEqual(g.snapshot(),before)

    def test_terminal_interrupts_only_started_historical_body(self):
        g=self.settled('terminal');self.assertNotEqual(g.state.status,'playing')
        self.assertEqual(len(g.state.historical_body_invocations),1)
        self.assertTrue(g.state.historical_body_invocations[0].interrupted)
        self.portable(g,'terminal')

    def test_closed_receipt_cannot_erase_or_borrow_actual_record(self):
        g=self.settled()
        self.reject(g,lambda s:s['state']['historical_body_invocations'].clear())
        self.reject(g,lambda s:s['state']['battlecry_history'][2].__setitem__('historical_body_id',None))
        self.reject(g,lambda s:s['state']['historical_body_invocations'][0].__setitem__('record_id',4))

    def test_closed_condition_prefix_and_declaring_threshold_cannot_change(self):
        g=self.settled()
        self.reject(g,lambda s:s['state']['historical_body_invocations'][0].__setitem__('combo_play_ids',[]))
        self.reject(g,lambda s:s['state']['historical_body_invocations'][0]['conditions'].__setitem__('manathirst_threshold',5))

    def test_closed_random_domain_or_selected_target_cannot_change(self):
        g=self.settled()
        self.reject(g,lambda s:s['state']['historical_body_invocations'][0]['selection'].__setitem__('target_id',999999))
        self.reject(g,lambda s:s['state']['historical_body_invocations'][0]['selection']['partition'].__setitem__('excluded_ids',[999999]))

    def test_pending_finish_cannot_be_removed_even_after_rehash(self):
        g=self.settled('body_wait')
        def mutate(s):
            removed=[]
            def walk(value):
                if type(value) is dict:
                    if type(value.get('tuple')) is list:
                        original=value['tuple']
                        value['tuple']=[item for item in original if not
                            (type(item) is dict and str(item.get('type','')).endswith('.FinishHistoricalBody'))]
                        removed.extend(range(len(original)-len(value['tuple'])))
                    for item in value.values():walk(item)
                elif type(value) is list:
                    for item in value:walk(item)
            walk(s['resolution_frame'])
            self.assertTrue(removed)
        self.reject(g,mutate,'body_wait')

    def test_pending_history_cannot_erase_its_outer_sequence_attempt(self):
        g=self.settled('body_wait')
        def mutate(s):
            removed=[]
            def walk(value):
                if type(value) is dict:
                    if type(value.get('tuple')) is list:
                        original=value['tuple']
                        value['tuple']=[item for item in original if not
                            (type(item) is dict and str(item.get('type','')).endswith('.FinishSequenceAttempt'))]
                        removed.extend(range(len(original)-len(value['tuple'])))
                    for item in value.values():walk(item)
                elif type(value) is list:
                    for item in value:walk(item)
            walk(s['resolution_frame']);self.assertTrue(removed)
        self.reject(g,mutate,'body_wait')

    def test_original_activity_conditions_cannot_be_changed_with_closed_copy(self):
        g=self.settled('body_wait')
        def mutate(s):
            def walk(value):
                if type(value) is dict:
                    if str(value.get('type','')).endswith('.HistoricalBodyReceipt'):
                        value['fields']['conditions']['fields']['mana_crystals']=9
                    if 'conditions' in value and type(value['conditions']) is dict and 'mana_crystals' in value['conditions']:
                        value['conditions']['mana_crystals']=9
                    for item in value.values():walk(item)
                elif type(value) is list:
                    for item in value:walk(item)
            walk(s)
        self.reject(g,mutate,'body_wait')

    def test_both_players_receive_no_host_receipt_source_json_or_rng(self):
        g=self.settled('body_wait')
        for seat in (1,2):
            text=json.dumps(g.for_player(seat).observe(),ensure_ascii=False)
            for private in ('historical_body_invocations','source_json','rng_before','HistoricalBodyProof'):
                self.assertNotIn(private,text)

    def test_origin_registration_cannot_reuse_paid_or_live_indirect_profile(self):
        r=registry()
        r.register_body_target_profile(BodyTargetProfile('live','indirect_battlecry','random','indirect_invocation'))
        with self.assertRaises(ValueError):r.register_historical_battlecry_binding(HistoricalBattlecryBinding('carrier','live',('low',)))

    def test_current_format_refuses_previous_schema_without_historical_receipts(self):
        g=self.settled();snapshot=g.snapshot();self.assertEqual(snapshot['schema_version'],266)
        snapshot['schema_version']=138
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,registry())
