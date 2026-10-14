"""Real indirect grants and invocation windows, including physical lifecycle."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import (BodyPlayReference, BodyReference, BodyTargetBinding, BodyTargetProfile,
    CardDefinition, CardType, Game, GrantBattlecry, IfBodyCondition, IndirectBattlecryBinding,
    Keyword, PlayCard, PlayerSetup, PlayerTargetRuleSpec, Scenario, SelectChoice, TargetPredicateSpec,
    TargetSpec, TriggerSpec, Zone, body_play_conditions, ConsumeGrantedBody, RemoveGrantedBody)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import (Buff, ChangeControl, ChangeManaCrystals, ChoiceOption, CopyMinion,
    Damage, Destroy, GainArmor, RandomDamage, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash


def registry(mode='normal', policy='random', variant='complete'):
    r=Registry('indirect-body-'+mode+'-'+policy+'-'+variant+'-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    for name,hp in (('tiny',3),('big',6),('hidden',2)):
        r.register_card(CardDefinition(name,name,CardType.MINION,attack=1,health=hp))
    r.register_target_predicate(TargetPredicateSpec('low',health_min=2,health_max=4))
    if mode.startswith('player'):
        def predicate(ctx):
            own=ctx.observation['players'][ctx.player_id-1]
            return ctx.target['health']<=own['max_mana']
        r.register_player_target_rule(PlayerTargetRuleSpec('low_player','v1'),predicate)
    target_rule='low_player' if mode.startswith('player') else 'low'
    enemy=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,),relation='enemy')
    friend=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,),relation='friendly',exclude_source=True)

    def body(ctx):
        ref=BodyPlayReference.capture(ctx,'battlecry')
        first=ref.declaration_card_id=='unit'
        effects=[]
        if first:
            if mode=='conditions': effects.append(ChangeManaCrystals(ctx.player_id,-7))
            elif mode=='change': effects.append(Buff(ctx.target_id,health=3,source_id=ctx.source_id))
            elif mode=='silence': effects.append(Silence(ctx.source_id))
            elif mode=='transform': effects.append(Transform(ctx.source_id,'big'))
            elif mode=='death': effects.append(Destroy(ctx.source_id))
            elif mode in ('control','player_control'): effects.append(ChangeControl(ctx.source_id,2))
            elif mode=='late': effects.append(GrantBattlecry(BodyReference.capture(ctx.source),'donor',ctx.source_id))
            elif mode in ('consume','remove'):
                donor=next(a for a in ctx.source.abilities if a.kind=='battlecry' and a.origin=='granted')
                mutation=ConsumeGrantedBody if mode=='consume' else RemoveGrantedBody
                effects.append(mutation(BodyReference.capture(ctx.source),donor.id,'battlecry',ctx.source_id))
            elif mode=='nested' and len(ctx.state.indirect_body_sequences)==1:
                effects.append(TriggerBattlecry(MinionReference.capture(ctx.source),ctx.source_id,profile_id='indirect'))
            elif mode=='terminal': effects.append(Damage(ctx.state.players[2].hero_id,50,source_id=ctx.source_id))
            elif mode=='fail': effects.append(RandomDamage((ctx.state.players[2].hero_id,),1,source_id=ctx.source_id))
        elif mode=='fail': effects.append(Summon(ctx.player_id,'unknown.indirect.body'))
        if mode in ('wait','player_wait'): effects.append(RequestChoice(ctx.player_id,(ChoiceOption('go','Go'),),ctx.source_id))
        if mode=='conditions':
            effects.append(IfBodyCondition(ref,'manathirst',(GainArmor(ctx.player_id,5),),(GainArmor(ctx.player_id,1),)))
        else:
            effects.append(GainArmor(ctx.player_id,1 if first else 2))
        return tuple(effects)
    r.register_behavior('body',body)
    r.register_behavior('combo_body',lambda c:(GainArmor(c.player_id,100),))
    def start_listener(ctx):
        if ctx.event.source_id != ctx.source_id: return ()
        return (RequestChoice(ctx.player_id,(ChoiceOption('go','Go'),),ctx.source_id),
                ChangeManaCrystals(ctx.player_id,-1))
    r.register_behavior('start_listener',start_listener)
    condition='manathirst' if mode=='conditions' else None
    r.register_card(CardDefinition('unit','Unit',CardType.MINION,attack=2,health=8,
        battlecry='body',combo='combo_body',targeting=enemy,target_rule=target_rule,
        target_condition=condition,manathirst=9 if mode=='conditions' else None,
        triggers=(TriggerSpec('battlecry_started','start_listener'),) if mode=='start_wait' else (),
        keywords=(Keyword.COMBO,Keyword.MANATHIRST) if mode=='conditions' else (Keyword.COMBO,)))
    r.register_card(CardDefinition('donor','Donor',CardType.MINION,health=5,
        battlecry='body',targeting=enemy if mode in ('change','conditions') or mode.startswith('player') else friend,
        target_rule=target_rule,target_condition=condition,manathirst=4 if mode=='conditions' else None,
        keywords=(Keyword.MANATHIRST,) if mode=='conditions' else ()))

    def unit(ctx):
        return next((e for e in reversed(tuple(ctx.state.entities.values())) if e.card_id=='unit' and e.zone==Zone.BOARD),None)
    def setup(ctx):
        entity=unit(ctx)
        return (GrantBattlecry(BodyReference.capture(entity),'donor',ctx.source_id,
            expires_turn=ctx.state.turn if mode=='expiry' else None),)
    def invoke(ctx):
        entity=unit(ctx)
        target=next(i for i in ctx.state.players[2].board if ctx.state.entities[i].card_id=='tiny') if policy=='explicit' else None
        return (TriggerBattlecry(MinionReference.capture(entity),ctx.source_id,target,policy,
            'player',None if variant=='unselected' else 'indirect'),)
    def tool(ctx):
        entity=unit(ctx)
        if mode=='whole':
            from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
            from hs_sim.engine.whole_card_replays import ReplayWholeCards
            from hs_sim.engine.whole_card_physical import PROFILE
            return (ReplayWholeCards(ctx.player_id,ctx.source_id,
                WholeCardHistoryQuery(ctx.player_id,len(ctx.state.play_history)+1,kinds=(CardType.MINION,)),physical_profile=PROFILE),)
        if mode=='base_copy': return (CopyMinion(entity.id,ctx.player_id,mode='base'),)
        if mode=='bounce': return (ReturnToHand(entity.id),)
        if mode=='pre_control': return (ChangeControl(entity.id,2),)
        if mode=='empty': return (Silence(entity.id),)
        return (CopyMinion(entity.id,ctx.player_id,mode='current'),)
    for name,handler in (('setup',setup),('invoke',invoke),('tool',tool)):
        r.register_behavior(name,handler)
        r.register_card(CardDefinition(name,name,CardType.SPELL,cost=0,on_play=name))
    r.register_body_target_profile(BodyTargetProfile('indirect',
        'paid_hand' if variant=='wrong_origin' else 'indirect_battlecry',
        'manual' if variant=='wrong_origin' else policy,
        'pre_payment' if variant=='wrong_origin' else 'indirect_invocation'))
    for name,origins in (('unit',('printed',)),('donor',('granted',))):
        if variant=='missing' and name=='donor': continue
        r.register_body_target_binding(BodyTargetBinding(name,'battlecry','indirect',origins=origins,
            carrier_kinds=(CardType.MINION,),carrier_card_ids=('unit',)))
    r.register_indirect_battlecry_binding(IndirectBattlecryBinding('unit','indirect'))
    return r


class IndirectBodyTargetTests(unittest.TestCase):
    def game(self,mode='normal',policy='random',variant='complete', *, setup=True, enemy='hidden'):
        g=Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=('setup','invoke','invoke','tool'),board=('unit','tiny'),mana=10,max_mana=10),
            PlayerSetup('hero',board=('tiny','big'),hand=(enemy,),mana=10,max_mana=10)),seed=37),
            registry(mode,policy,variant))
        if setup: self.play(g,'setup')
        return g

    def play(self,g,name):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(1,source))

    def armor(self,g,player=1): return g.state.entities[g.state.players[player].hero_id].armor
    def root(self,g): return g.state.indirect_body_sequences[-1]
    def roundtrip(self,g,mode='normal',policy='random'):
        snapshot=g.snapshot(); observations=[g.for_player(i).observe() for i in (1,2)]
        copies=(Game.from_snapshot(snapshot,registry(mode,policy)),g.clone(),replay(build_replay(g),registry(mode,policy)))
        for other in copies:
            self.assertEqual(other.snapshot(),snapshot)
            self.assertEqual([other.for_player(i).observe() for i in (1,2)],observations)
        return copies
    def rehash(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_actual_grants_have_independent_domains_without_combo_or_extra_payment(self):
        g=self.game(); mana=g.state.players[1].mana; self.play(g,'invoke'); root=self.root(g)
        self.assertTrue(root.finished); self.assertEqual(root.cursor,2); self.assertEqual(self.armor(g),3)
        self.assertEqual(g.state.players[1].mana,mana)
        self.assertEqual([r.origin for r in g.state.battlecry_history],['effect','effect'])
        self.assertFalse(g.state.combo_history)
        self.assertIn(root.receipts[0].selection.target_id,g.state.players[2].board)
        self.assertEqual(root.receipts[1].selection.target_id,g.state.players[1].board[1])
        self.assertEqual(len(g.state.play_history),2); self.roundtrip(g)

    def test_structural_grant_and_source_acceptance_do_not_run_predicates(self):
        g=self.game(setup=False)
        with patch('hs_sim.engine.targeting.accepts_target',side_effect=AssertionError('target query')):
            self.play(g,'setup')
        self.assertEqual(len([a for a in g.state.entities[g.state.players[1].board[0]].abilities if a.kind=='battlecry']),2)

    def test_structural_indirect_authority_is_pure_and_does_not_select_or_quote(self):
        from hs_sim.engine.indirect_body_targets import authorities
        g=self.game(); snapshot=g.snapshot(); source=g._state.entities[g.state.players[1].board[0]]
        with (patch('hs_sim.engine.targeting.target_choices',side_effect=AssertionError('target query')),
              patch('hs_sim.engine.costs.quote_cost',side_effect=AssertionError('quote'))):
            rows=authorities(g._state,g.registry,source,'indirect')
        self.assertEqual(len(rows),2); self.assertEqual(g.snapshot(),snapshot)

    def test_paid_and_generated_producers_cannot_inherit_indirect_permission(self):
        from hs_sim.engine.indirect_body_targets import require_legacy_paid_scope
        g=self.game(); source=g.state.entities[g.state.players[1].board[0]]
        stored_copy=replace(source,zone=Zone.HAND)
        with self.assertRaisesRegex(IllegalAction,'own connected paid'): require_legacy_paid_scope(g.registry,stored_copy)
        # Use a real paid printed carrier to put the selected physical card in
        # whole-card history, then exercise the actual generated dispatcher.
        r=registry('whole')
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('unit','tool'),board=('tiny',),mana=10,max_mana=10),
            PlayerSetup('hero',board=('tiny',),mana=10,max_mana=10)),seed=37),r)
        source=g.state.players[1].hand[0]; g.apply(PlayCard(1,source,g.state.players[2].board[0]))
        before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'own generated origin'): self.play(g,'tool')
        self.assertEqual(g.snapshot(),before)

    def test_missing_binding_rejects_real_grant_and_rolls_back(self):
        g=self.game(variant='missing',setup=False); before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'complete connected'): self.play(g,'setup')
        self.assertEqual(g.snapshot(),before)

    def test_indirect_binding_cannot_borrow_manual_origin(self):
        with self.assertRaisesRegex(ValueError,'own origin'): registry(variant='wrong_origin')

    def test_bound_carrier_requires_explicit_indirect_producer(self):
        g=self.game(variant='unselected'); before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'own indirect origin'): self.play(g,'invoke')
        self.assertEqual(g.snapshot(),before)

    def test_each_actual_body_has_new_conditions_but_first_keeps_accepted_threshold(self):
        g=self.game('conditions'); self.play(g,'invoke'); root=self.root(g)
        self.assertEqual([r.conditions.mana_crystals for r in root.receipts],[10,3])
        self.assertEqual([r.conditions.manathirst for r in root.receipts],[True,False])
        self.assertTrue(all(r.conditions.combo for r in root.receipts)); self.assertEqual(self.armor(g),6)
        self.assertIsNone(root.receipts[1].selection.target_id)
        self.assertIsNone(root.receipts[1].selection.partition.mode)
        self.assertEqual(root.receipts[1].selection.rng_before,root.receipts[1].selection.rng_after)
        for record in g.state.battlecry_history:
            facts=body_play_conditions(g.state,g.registry,BodyPlayReference.from_record(record,'battlecry'))
            self.assertEqual(facts,root.receipts[record.id-1].conditions)
            self.assertFalse(facts.outcast or facts.finale or facts.quickdraw)
        self.roundtrip(g,'conditions')

    def test_later_target_partition_uses_changed_stats_and_empty_pool_consumes_no_rng(self):
        g=self.game('change'); self.play(g,'invoke'); root=self.root(g)
        self.assertEqual([len(r.selection.partition.legal_ids) for r in root.receipts],[1,0])
        self.assertEqual(root.receipts[1].selection.failure,'no_target')
        self.assertEqual(root.receipts[1].selection.rng_before,root.receipts[1].selection.rng_after)
        self.assertEqual(self.armor(g),1); self.roundtrip(g,'change')

    def test_explicit_target_failure_is_per_body_and_consumes_no_rng(self):
        g=self.game(policy='explicit'); before=g._rng.getstate(); self.play(g,'invoke')
        root=self.root(g); self.assertEqual(g._rng.getstate(),before)
        self.assertEqual([r.selection.failure for r in root.receipts],[None,'invalid_target'])
        self.assertEqual(self.armor(g),1); self.roundtrip(g,policy='explicit')

    def test_explicit_target_does_not_suppress_a_conditionally_untargeted_body(self):
        g=self.game('conditions',policy='explicit'); before=g._rng.getstate(); self.play(g,'invoke')
        receipts=self.root(g).receipts
        self.assertEqual([r.conditions.manathirst for r in receipts],[True,False])
        self.assertIsNotNone(receipts[0].selection.target_id)
        self.assertIsNone(receipts[1].selection.partition.mode)
        self.assertIsNone(receipts[1].selection.target_id)
        self.assertEqual([r.selection.failure for r in receipts],[None,None])
        self.assertEqual(g._rng.getstate(),before); self.assertEqual(self.armor(g),6)
        self.roundtrip(g,'conditions',policy='explicit')

    def test_late_grant_does_not_extend_accepted_sequence_and_next_trigger_captures_it(self):
        g=self.game('late'); self.play(g,'invoke'); self.assertEqual(self.root(g).cursor,2)
        self.play(g,'invoke'); self.assertEqual(self.root(g).cursor,3)
        self.assertEqual(len(g.state.battlecry_history),5); self.roundtrip(g,'late')

    def test_silence_transform_and_death_do_not_substitute_accepted_remaining_body(self):
        for mode in ('silence','transform','death'):
            with self.subTest(mode=mode):
                g=self.game(mode); self.play(g,'invoke'); self.assertEqual(self.armor(g),3)
                self.assertEqual([r.payload.card_id for r in g.state.battlecry_history],['unit','donor'])
                self.assertTrue(self.root(g).finished); self.roundtrip(g,mode)

    def test_control_change_preserves_captured_executor_and_later_friendly_domain(self):
        g=self.game('control'); self.play(g,'invoke'); root=self.root(g)
        self.assertEqual([r.player_id for r in root.receipts],[1,1]); self.assertEqual(self.armor(g),3)
        self.assertEqual(self.armor(g,2),0)
        self.assertEqual(g.state.entities[root.receipts[0].source_id].controller,2)
        self.assertEqual(root.receipts[1].selection.target_id,g.state.players[1].board[0])
        self.roundtrip(g,'control')

    def test_current_copy_has_fresh_physical_body_references(self):
        g=self.game(); original=g.state.entities[g.state.players[1].board[0]]; self.play(g,'tool'); self.play(g,'invoke')
        refs=self.root(g).origin.bodies; self.assertNotEqual(refs[0].carrier.entity_id,original.id)
        self.assertTrue(set(r.ability_id for r in refs).isdisjoint(a.id for a in original.abilities))
        self.assertEqual([r.origin for r in refs],['printed','granted']); self.roundtrip(g)

    def test_base_copy_reinstalls_only_printed_body(self):
        g=self.game('base_copy'); self.play(g,'tool'); self.play(g,'invoke')
        self.assertEqual(self.root(g).cursor,1); self.assertEqual(self.armor(g),1); self.roundtrip(g,'base_copy')

    def test_bounce_resets_grant_and_retires_original_captured_source(self):
        g=self.game('bounce'); source=g.state.players[1].board[0]; self.play(g,'tool')
        entity=g.state.entities[source]
        self.assertEqual(entity.zone,Zone.HAND)
        self.assertEqual([a.origin for a in entity.abilities if a.kind=='battlecry'],['printed'])
        self.assertFalse(g.state.indirect_body_sequences); self.roundtrip(g,'bounce')

    def test_expiry_removes_grant_before_the_next_actual_trigger(self):
        g=self.game('expiry'); from hs_sim.engine import EndTurn as TurnAction
        g.apply(TurnAction(1)); g.apply(TurnAction(2)); self.play(g,'invoke')
        self.assertEqual(self.root(g).cursor,1); self.roundtrip(g,'expiry')

    def test_each_wait_restores_clones_and_replays_then_resumes_same_original_selection(self):
        g=self.game('wait'); self.play(g,'invoke'); count=0
        while g.state.pending_choice is not None:
            count+=1; copies=self.roundtrip(g,'wait'); accepted=self.root(g).receipts[-1].selection
            choice=g.state.pending_choice; action=SelectChoice(choice.player_id,choice.id,('go',))
            g.apply(action)
            for other in copies:
                other.apply(action); self.assertEqual(other.snapshot(),g.snapshot())
            self.assertEqual(g.state.indirect_body_sequences[0].receipts[count-1].selection,accepted)
        self.assertEqual(count,2); self.assertEqual(self.armor(g),3); self.roundtrip(g,'wait')

    def test_second_body_failure_rolls_back_first_body_rng_payment_and_information(self):
        g=self.game('fail'); before=g.snapshot(); history=g.history
        with self.assertRaisesRegex(ResolutionError,'unknown.indirect.body'): self.play(g,'invoke')
        self.assertEqual(g.snapshot(),before); self.assertEqual(g.history,history)

    def test_nested_real_producers_keep_separate_sequences_and_actual_ids(self):
        g=self.game('nested'); self.play(g,'invoke'); roots=g.state.indirect_body_sequences
        self.assertEqual(len(roots),2); self.assertTrue(all(r.finished and r.cursor==2 for r in roots))
        self.assertEqual([[r.record_id for r in root.receipts] for root in roots],[[1,4],[2,3]])
        self.assertEqual(self.armor(g),6); self.roundtrip(g,'nested')

    def test_terminal_game_interrupts_whole_accepted_sequence_without_extra_body(self):
        g=self.game('terminal'); self.play(g,'invoke'); root=self.root(g)
        self.assertEqual(g.state.status,'finished'); self.assertTrue(root.interrupted); self.assertFalse(root.finished)
        self.assertEqual(root.cursor,1); self.assertIsNone(root.active_battlecry_id)
        self.assertEqual(len(g.state.battlecry_history),1); self.roundtrip(g,'terminal')

    def test_consumed_or_removed_future_body_still_executes_accepted_payload(self):
        for mode in ('consume','remove'):
            with self.subTest(mode=mode):
                g=self.game(mode); self.play(g,'invoke'); self.assertEqual(self.root(g).cursor,2)
                self.assertEqual(self.armor(g),3)
                # The first body will not find an active donor on the next root;
                # only verify the current complete accepted sequence here.
                self.roundtrip(g,mode)

    def test_empty_actual_source_saves_empty_root_without_targets_or_rng(self):
        g=self.game('empty'); self.play(g,'tool'); before=g._rng.getstate(); self.play(g,'invoke')
        root=self.root(g); self.assertTrue(root.finished); self.assertEqual(root.cursor,0)
        self.assertFalse(root.origin.bodies); self.assertFalse(g.state.battlecry_history)
        self.assertEqual(g._rng.getstate(),before); self.roundtrip(g,'empty')

    def test_transfer_before_trigger_accepts_new_controller_without_invented_combo(self):
        g=self.game('pre_control'); self.play(g,'tool'); self.play(g,'invoke'); root=self.root(g)
        self.assertEqual([r.player_id for r in root.receipts],[2,2])
        self.assertTrue(all(not r.conditions.combo and r.combo_play_ids==() for r in root.receipts))
        self.assertEqual(self.armor(g),0); self.assertEqual(self.armor(g,2),3)
        self.roundtrip(g,'pre_control')

    def test_player_predicate_original_dto_is_hidden_face_independent(self):
        first=self.game('player',enemy='hidden'); second=self.game('player',enemy='big')
        self.assertEqual(first.for_player(1).observe(),second.for_player(1).observe())
        self.play(first,'invoke'); self.play(second,'invoke')
        self.assertEqual(first.for_player(1).observe(),second.for_player(1).observe())
        receipts=self.root(first).receipts
        self.assertTrue(all(r.observation is not None for r in receipts))
        self.assertEqual([r.observation.observation_json for r in receipts],
                         [r.observation.observation_json for r in self.root(second).receipts])
        raw=json.dumps(first.for_player(1).observe())+json.dumps(first.for_player(1).events())
        for private in ('indirect_body_sequences','source_json','rng_before','combo_play_ids','profile_id'):
            self.assertNotIn(private,raw)
        self.roundtrip(first,'player')

    def test_settled_target_receipts_do_not_store_recursive_old_states(self):
        g=self.game('player'); self.play(g,'invoke'); raw=json.dumps(g.snapshot()['state']['indirect_body_sequences'])
        for key in ('before_state','play_history','events_hash','information_json'):
            self.assertNotIn(key,raw)

    def test_player_wait_restores_original_observation_before_both_resume_windows(self):
        g=self.game('player_wait'); self.play(g,'invoke'); count=0
        while g.state.pending_choice is not None:
            count+=1; copies=self.roundtrip(g,'player_wait')
            choice=g.state.pending_choice; action=SelectChoice(choice.player_id,choice.id,('go',))
            g.apply(action)
            for other in copies:
                other.apply(action); self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual(count,2); self.roundtrip(g,'player_wait')

    def test_player_condition_after_source_transfer_uses_captured_executor_observation(self):
        g=self.game('player_control'); self.play(g,'invoke'); root=self.root(g)
        self.assertEqual([json.loads(r.observation.observation_json)['viewer'] for r in root.receipts],[1,1])
        self.assertEqual(self.armor(g),3); self.assertEqual(self.armor(g,2),0)
        self.roundtrip(g,'player_control')

    def test_pending_producer_and_original_target_proof_cannot_be_cut_or_rewritten(self):
        g=self.game('wait'); self.play(g,'invoke'); original=g.snapshot()
        for kind in ('invocation_finish','producer_finish','advance','original_health','original_conditions'):
            with self.subTest(kind=kind):
                snapshot=deepcopy(original); queue=snapshot['resolution_frame']['fields']['continuation']['tuple']
                marker=next(w for w in queue if w['type'].endswith('.FinishIndirectInvocation'))
                if kind in ('invocation_finish','producer_finish','advance'):
                    suffix={'invocation_finish':'.FinishIndirectInvocation','producer_finish':'.FinishIndirectBodies',
                            'advance':'.AdvanceIndirectBodies'}[kind]
                    queue[:]=[w for w in queue if not w['type'].endswith(suffix)]
                else:
                    proof=marker['fields']['proof']['fields']
                    before=proof['before_state']['state']
                    if kind=='original_health':
                        target=str(snapshot['state']['indirect_body_sequences'][0]['receipts'][0]['selection']['target_id'])
                        before['entities'][target]['damage']=2
                    else:
                        before['players']['1']['max_mana']=9
                self.rehash(snapshot)
                with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot,registry('wait'))

    def test_closed_player_observation_cannot_lose_or_borrow_visibility(self):
        g=self.game('player'); self.play(g,'invoke'); original=g.snapshot()
        for kind in ('missing','viewer','turn','array'):
            with self.subTest(kind=kind):
                snapshot=deepcopy(original); receipt=snapshot['state']['indirect_body_sequences'][0]['receipts'][0]
                if kind=='missing': receipt['observation']=None
                elif kind=='array': receipt['combo_play_ids']={}
                else:
                    value=json.loads(receipt['observation']['observation_json'])
                    value[kind]=2 if kind=='viewer' else value[kind]+1
                    receipt['observation']['observation_json']=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                self.rehash(snapshot)
                with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot,registry('player'))

    def test_start_listener_wait_precedes_payload_and_does_not_rewrite_accepted_conditions(self):
        g=self.game('start_wait'); self.play(g,'invoke'); count=0
        while g.state.pending_choice is not None:
            count+=1; receipt=self.root(g).receipts[-1]
            record=g.state.battlecry_history[-1]
            self.assertFalse(record.payload_started); self.assertFalse(record.completed)
            self.assertEqual(receipt.conditions.mana_crystals,11-count)
            copies=self.roundtrip(g,'start_wait'); choice=g.state.pending_choice
            action=SelectChoice(choice.player_id,choice.id,('go',)); g.apply(action)
            for other in copies:
                other.apply(action); self.assertEqual(other.snapshot(),g.snapshot())
            self.assertEqual(g.state.indirect_body_sequences[0].receipts[count-1],receipt)
        self.assertEqual(count,2); self.assertEqual(g.state.players[1].max_mana,8)
        self.assertEqual(self.armor(g),3); self.roundtrip(g,'start_wait')

    def test_source_vector_and_target_receipts_reject_real_rehashed_corruption(self):
        g=self.game(); self.play(g,'invoke'); original=g.snapshot()
        for kind in ('trim','duplicate','family','payload','rng','prefix','source','slot'):
            with self.subTest(kind=kind):
                snapshot=deepcopy(original); root=snapshot['state']['indirect_body_sequences'][0]
                if kind=='trim': root['origin']['bodies'].pop()
                elif kind=='duplicate': root['origin']['bodies'][1]=deepcopy(root['origin']['bodies'][0])
                elif kind=='family': root['origin']['bodies'][1]['family']='combo'
                elif kind=='payload': root['receipts'][1]['payload']['card_id']='unit'
                elif kind=='rng': root['receipts'][0]['selection']['rng_after']=root['receipts'][0]['selection']['rng_before']
                elif kind=='prefix': root['receipts'][1]['combo_play_ids']=[]
                elif kind=='source': root['origin']['bodies'][1]['carrier']['zone_epoch']+=1
                elif kind=='slot': root['receipts'][1]['slot']=0
                self.rehash(snapshot)
                with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot,registry())

    def test_new_schema_rejects_old_134_and_missing_indirect_history(self):
        g=self.game(); snapshot=g.snapshot(); self.assertEqual(snapshot['schema_version'],266)
        old=deepcopy(snapshot); old['schema_version']=134
        with self.assertRaises(SnapshotError): Game.from_snapshot(old,registry())
        del snapshot['state']['indirect_body_sequences']; self.rehash(snapshot)
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot,registry())


if __name__=='__main__': unittest.main()
