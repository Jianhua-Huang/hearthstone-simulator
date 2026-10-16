"""Actual generated physical sources, independent bodies and original windows."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import (BodyPlayReference, BodyReference, BodyTargetBinding, BodyTargetProfile,
    CardDefinition, CardType, Game, GeneratedWholeTargetBinding, GrantBattlecry, GrantCombo,
    IfBodyCondition, Keyword, PlayCard, PlayerSetup, PlayerTargetRuleSpec, Scenario, SelectChoice,
    TargetPredicateSpec, TargetSpec, TriggerSpec, Zone, body_play_conditions)
from hs_sim.engine.effects import (Buff, ChangeControl, ChangeManaCrystals, ChoiceOption, Damage,
    Destroy, GainArmor, RequestChoice, Silence, Summon, Transform, ReturnToHand)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.registry import Registry
from hs_sim.engine.generated_combo_repeats import PROFILE
from hs_sim.engine.generated_activation_receipts import RETAINED_PROFILE
from hs_sim.engine.model import BattlecryRepeatSpec, ComboRepeatSpec, RewindSpec
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards


def registry(mode='normal',policy='random',kind=CardType.MINION,variant='complete'):
    r=Registry('generated-target-'+mode+'-'+policy+'-'+kind.value+'-'+variant+'-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('power','Power',CardType.HERO_POWER,on_use='armor'))
    r.register_behavior('armor',lambda c:(GainArmor(c.player_id,1),))
    for name,hp in (('tiny',3),('big',8)):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=hp))
    r.register_card(CardDefinition('holder','Holder',CardType.MINION,health=5,retain_rewind_outcomes=True))
    enemy=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,),relation='enemy')
    friend=TargetSpec(kinds=(CardType.MINION,),zones=(Zone.BOARD,),relation='friendly',exclude_source=True)
    r.register_target_predicate(TargetPredicateSpec('small',health_max=4))
    if mode.startswith('player'):
        def predicate(c):
            own=c.observation['players'][c.player_id-1]
            return c.target['health']<=own['max_mana'] and len(own['hand'])>=1
        r.register_player_target_rule(PlayerTargetRuleSpec('player_small','v1'),predicate)
    rule='player_small' if mode.startswith('player') else 'small'
    conditional=mode in ('conditions','inactive')
    def body(c):
        actual=c.battlecry if c.battlecry is not None else c.combo
        if actual is None or actual.physical_child_id is None: return ()
        family='battlecry' if c.battlecry is not None else 'combo'
        first=actual.payload.card_id=='unit' and family=='battlecry'
        work=[]
        if first:
            if mode=='conditions': work.append(ChangeManaCrystals(c.player_id,-8))
            elif mode=='player_resources': work.append(ChangeManaCrystals(c.player_id,-8))
            elif mode=='stale': work.append(Destroy(c.target_id))
            elif mode=='silence': work.append(Silence(c.source_id))
            elif mode=='transform': work.append(Transform(c.source_id,'big'))
            elif mode=='death': work.append(Destroy(c.source_id))
            elif mode=='bounce': work.append(ReturnToHand(c.source_id))
            elif mode=='control': work.append(ChangeControl(c.source_id,2))
            elif mode=='late': work.append(GrantBattlecry(BodyReference.capture(c.source),'donor',c.source_id))
            elif mode=='terminal': work.append(Damage(c.state.players[2].hero_id,80))
            elif mode=='fail': work.append(Damage(c.target_id,1))
        if mode=='fail' and not first: work.append(Summon(c.player_id,'unregistered.generated.target'))
        if mode in ('wait','player_wait'): work.append(RequestChoice(c.player_id,(ChoiceOption('go','Go'),),c.source_id))
        if conditional:
            ref=BodyPlayReference.capture(c,family)
            work.append(IfBodyCondition(ref,'manathirst',(GainArmor(c.player_id,5),),(GainArmor(c.player_id,1),)))
        else: work.append(GainArmor(c.player_id,1 if first else 2))
        return tuple(work)
    r.register_behavior('body',body)
    def ordinary(c):
        return (GainArmor(c.player_id,10),) if c.physical is not None else ()
    r.register_behavior('ordinary',ordinary)
    root_mode=mode in ('root','root_empty','root_silenced')
    keywords=(Keyword.COMBO,Keyword.MANATHIRST) if conditional else (Keyword.COMBO,)
    if mode=='retained': keywords=(*keywords,Keyword.REWIND)
    fields=dict(attack=2,health=8) if kind==CardType.MINION else dict(attack=2,durability=4) if kind==CardType.WEAPON else dict(
        health=30,hero_card=True,initial_hero_power='power')
    r.register_card(CardDefinition('unit','Unit',kind,cost=1,battlecry='body',combo='body',
        targeting=enemy,target_rule=rule,on_play='ordinary' if root_mode else None,
        target_condition='manathirst' if conditional else None,manathirst=9 if conditional else None,
        keywords=keywords,rewind=RewindSpec() if mode=='retained' else None,**fields))
    r.register_card(CardDefinition('donor','Donor',CardType.MINION,health=6,battlecry='body',combo='body',
        targeting=enemy if conditional else friend,target_rule=rule,
        target_condition='manathirst' if conditional else None,manathirst=4 if conditional else None,
        keywords=(Keyword.COMBO,Keyword.MANATHIRST) if conditional else (Keyword.COMBO,)))
    def install(c):
        ledger=c.state.whole_card_replay_ledger
        if not ledger.stack or c.event.target_id is None: return ()
        entity=c.state.entities[c.event.target_id]
        if entity.card_id!='unit': return ()
        ref=BodyReference.capture(entity)
        if mode in ('empty_body','root_silenced'): return (Silence(entity.id),)
        result=[GrantBattlecry(ref,'donor',c.source_id),GrantCombo(ref,'donor',c.source_id)]
        if mode=='empty_target': result.append(Destroy(next(i for i in c.state.players[2].board if c.state.entities[i].card_id=='tiny')))
        if mode=='entry_wait': result.append(RequestChoice(c.player_id,(ChoiceOption('go','Go'),),c.source_id))
        return tuple(result)
    r.register_behavior('install',install)
    r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=6,triggers=(
        TriggerSpec('minion_summoned','install'),TriggerSpec('weapon_equipped','install'),TriggerSpec('hero_replaced','install'))))
    def replay_body(c):
        player=2 if mode=='player_other' else c.player_id
        target=next((i for i in c.state.players[2].board if c.state.entities[i].card_id=='tiny'),None) if policy=='explicit' else None
        return (ReplayWholeCards(player,c.source_id,WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,kinds=(kind,)),
            physical_profile='generated_after_install_v1' if variant=='legacy' else
                'generated_battlecry_repeat_after_install_v1' if variant=='legacy_bc' else
                RETAINED_PROFILE if mode=='retained' else PROFILE,choices='player',
            body_target_profile_id=None if variant=='unselected' else 'generated',body_target_id=target),)
    r.register_behavior('repeat',replay_body)
    r.register_card(CardDefinition('repeat','Repeat',CardType.SPELL,cost=1,on_play='repeat'))
    def policies(c):
        return (AddBattlecryRepeatModifier(c.player_id,BattlecryRepeatSpec(2,(kind,)),c.source_id,uses=1),
            AddComboRepeatModifier(c.player_id,ComboRepeatSpec(3,(kind,)),c.source_id,uses=1,trigger='activation'))
    r.register_behavior('policies',policies)
    r.register_card(CardDefinition('policies','Policies',CardType.SPELL,on_play='policies'))
    r.register_body_target_profile(BodyTargetProfile('generated','generated_whole',policy,'generated_acceptance'))
    for name,origins in (('unit',('printed',)),('donor',('granted',))):
        for family in ('battlecry','combo'):
            if variant=='missing' and name=='donor' and family=='combo': continue
            r.register_body_target_binding(BodyTargetBinding(name,family,'generated',origins=origins,carrier_kinds=(kind,),carrier_card_ids=('unit',)))
    if root_mode:
        r.register_generated_whole_target_binding(GeneratedWholeTargetBinding('unit','generated','explicit_root',
            targeting=TargetSpec(kinds=(CardType.HERO,),zones=(Zone.HERO,),relation='friendly') if mode in ('root','root_silenced') else
                TargetSpec(kinds=(CardType.LOCATION,),zones=(Zone.BOARD,))))
    else: r.register_generated_whole_target_binding(GeneratedWholeTargetBinding('unit','generated',
        'preserve_root' if mode=='preserve_no_root' else 'body_only'))
    return r


class GeneratedBodyTargetTests(unittest.TestCase):
    def game(self,mode='normal',policy='random',kind=CardType.MINION,variant='complete', *, policies=False):
        r=registry(mode,policy,kind,variant)
        crystals=5 if mode=='inactive' else 10
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('unit','policies','repeat','tiny'),
            board=('watch','tiny')+(('holder',) if mode=='retained' else ()),mana=crystals,max_mana=crystals,hero_power_card_id='power'),
            PlayerSetup('hero',board=('tiny','big'),hand=('tiny',),mana=10,max_mana=10,hero_power_card_id='power')),seed=46),r)
        self.play(g,'unit',None if mode=='inactive' else next(i for i in g.state.players[2].board if g.state.entities[i].card_id=='tiny'))
        if policies: self.play(g,'policies')
        return g

    def play(self,g,name,target=None):
        entity=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,entity,target))

    def generated(self,g):
        return [c.physical for c in g.state.whole_card_replay_ledger.children if c.physical is not None][-1]

    def portable(self,g,mode='normal',policy='random',kind=CardType.MINION):
        value=json.loads(json.dumps(g.snapshot()))
        branches=(Game.from_snapshot(value,registry(mode,policy,kind)),g.clone(),replay(build_replay(g),registry(mode,policy,kind)))
        for b in branches:
            self.assertEqual(b.snapshot(),value)
            for seat in (1,2): self.assertEqual(b.observe(seat),g.observe(seat))
        return branches

    def settled(self,mode='normal',policy='random',kind=CardType.MINION,**kw):
        g=self.game(mode,policy,kind,**kw);self.play(g,'repeat');return g

    def test_each_physical_family_has_independent_domain(self):
        g=self.settled();p=self.generated(g)
        self.assertEqual([(s.reference.family,s.reference.declaration_card_id) for s in p.body_targets.slots],
            [('battlecry','unit'),('battlecry','donor'),('combo','unit'),('combo','donor')])
        self.assertEqual(p.selection.target_id,None)
        bc=[b for b in g.state.battlecry_history if b.physical_child_id==p.child_id]
        self.assertEqual(bc[0].target_id,next(i for i in g.state.players[2].board if g.state.entities[i].card_id=='tiny'))
        self.assertIn(bc[1].target_id,g.state.players[1].board)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7)
        self.assertEqual(len(g.state.play_history),2)
        self.portable(g)

    def test_explicit_target_checks_each_body_and_uses_no_body_rng(self):
        g=self.settled(policy='explicit');p=self.generated(g)
        self.assertEqual([s.selected.failure for s in p.body_targets.slots],[None,'invalid_target',None,'invalid_target'])
        self.assertTrue(all(s.selected.rng_before==s.selected.rng_after for s in p.body_targets.slots))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3)
        self.portable(g,policy='explicit')

    def test_own_conditions_frozen_before_any_body_changes_crystals(self):
        g=self.settled('conditions');p=self.generated(g)
        self.assertEqual([s.conditions.manathirst_threshold for s in p.body_targets.slots],[9,4,9,4])
        self.assertTrue(all(s.conditions.manathirst for s in p.body_targets.slots))
        self.assertEqual(g.state.players[1].max_mana,2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,20)
        for b in g.state.battlecry_history:
            if b.physical_child_id: self.assertTrue(body_play_conditions(g.state,g.registry,BodyPlayReference.from_record(b,'battlecry')).manathirst)
        self.portable(g,'conditions')

    def test_unavailable_accepted_target_skips_only_its_later_body(self):
        g=self.settled('stale');p=self.generated(g)
        row=next(c for c in g.state.combo_history if c.physical_child_id==p.child_id and c.payload.card_id=='unit')
        self.assertEqual(row.failure,'invalid_target')
        self.assertEqual(row.target_id,p.body_targets.slots[2].selected.target_id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        self.portable(g,'stale')

    def test_separate_ordinary_root_target(self):
        g=self.settled('root');p=self.generated(g)
        self.assertEqual(p.selection.target_id,g.state.players[1].hero_id)
        self.assertNotEqual(p.selection.target_id,p.body_targets.slots[0].selected.target_id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,17)
        self.portable(g,'root')

    def test_empty_ordinary_root_does_not_erase_other_body_families(self):
        g=self.settled('root_empty');p=self.generated(g)
        self.assertEqual(p.selection.failure,'no_target');self.assertIsNone(p.failure)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7)
        self.portable(g,'root_empty')

    def test_silence_after_acceptance_preserves_remaining_granted_vector(self): self.portable(self.settled('silence'),'silence')
    def test_transform_after_acceptance_preserves_original_identity(self): self.portable(self.settled('transform'),'transform')
    def test_death_after_acceptance_preserves_remaining_bodies(self): self.portable(self.settled('death'),'death')
    def test_bounce_after_acceptance_preserves_original_body_vector(self): self.portable(self.settled('bounce'),'bounce')
    def test_control_after_acceptance_keeps_captured_executor(self):
        g=self.settled('control');self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7)
        self.portable(g,'control')

    def test_late_grant_does_not_extend_accepted_vector(self):
        g=self.settled('late');p=self.generated(g)
        self.assertEqual(len(p.body_targets.slots),4);self.assertEqual(len(p.battlecries),2)
        self.assertEqual(len([a for a in g.state.entities[p.source.entity_id].abilities if a.kind=='battlecry']),3)
        self.portable(g,'late')

    def test_repetition_reuses_each_body_selection_and_finite_policy_once(self):
        g=self.settled(policies=True);p=self.generated(g)
        self.assertEqual(len(p.battlecry_ids),4);self.assertEqual(len(p.combo_ids),6)
        for family,rows in (('battlecry',g.state.battlecry_history),('combo',g.state.combo_history)):
            for b in rows:
                if b.physical_child_id==p.child_id:
                    s=next(s for s in p.body_targets.slots if s.reference.ability_id==b.payload.ability_id)
                    self.assertEqual(b.target_id,s.selected.target_id)
        self.assertEqual(g.state.players[1].battlecry_modifiers,[])
        self.assertEqual(g.state.players[1].combo_modifiers,[])
        self.assertEqual(len([p for p in g.state.battlecry_policy_uses if p.origin=='generated_body']),1)
        self.assertEqual(len([p for p in g.state.combo_policy_receipts if p.origin=='generated_body']),1)
        self.portable(g)

    def test_retained_result_groups_keep_each_selection(self):
        g=self.settled('retained',policies=True);p=self.generated(g)
        self.assertIsNotNone(p.outcome_id);self.assertGreater(len(p.battlecry_ids),4)
        self.assertEqual(len(p.body_targets.slots),4)
        self.portable(g,'retained')

    def test_every_body_wait_restores_and_replays_before_resume(self):
        g=self.settled('wait');waits=0
        while g.state.pending_choice is not None:
            branches=self.portable(g,'wait');choice=g.state.pending_choice
            action=SelectChoice(choice.player_id,choice.id,('go',))
            g.apply(action)
            for b in branches: b.apply(action);self.assertEqual(b.snapshot(),g.snapshot())
            waits+=1
        self.assertEqual(waits,4)

    def test_player_original_projection_and_hidden_information(self):
        g=self.settled('player');p=self.generated(g)
        self.assertIsNotNone(p.body_targets.origin.observation)
        for seat in (1,2):
            public=json.dumps(g.observe(seat));self.assertNotIn('original_state_hash',public);self.assertNotIn('source_json',public)
        self.portable(g,'player')

    def test_other_executor_observation_does_not_borrow_active_player(self):
        g=self.settled('player_other');p=self.generated(g)
        self.assertEqual(p.player_id,2)
        self.assertEqual(json.loads(p.body_targets.origin.observation.observation_json)['viewer'],2)
        self.assertEqual(g.state.active_player,1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,3)
        self.assertFalse(any(s.active for s in p.body_targets.slots if s.reference.family=='combo'))
        self.portable(g,'player_other')

    def test_entry_choice_precedes_body_acceptance_and_grants(self):
        g=self.settled('entry_wait');p=self.generated(g)
        self.assertEqual(p.phase,'installing');self.assertIsNone(p.body_targets)
        branches=self.portable(g,'entry_wait');c=g.state.pending_choice;action=SelectChoice(c.player_id,c.id,('go',))
        g.apply(action)
        for b in branches: b.apply(action);self.assertEqual(b.snapshot(),g.snapshot())
        self.assertEqual(len(self.generated(g).body_targets.slots),4)

    def test_missing_complete_authority_rolls_back_installation_and_payment(self):
        g=self.game(variant='missing');before=g.snapshot()
        with self.assertRaises((IllegalAction,ResolutionError,ValueError)): self.play(g,'repeat')
        self.assertEqual(g.snapshot(),before)

    def test_unselected_generated_profile_refuses_instead_of_common_target(self):
        g=self.game(variant='unselected');before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'repeat')
        self.assertEqual(g.snapshot(),before)

    def test_later_unknown_body_rolls_back_earlier_effects_and_rng(self):
        g=self.game('fail');before=g.snapshot()
        with self.assertRaises((IllegalAction,ResolutionError)): self.play(g,'repeat')
        self.assertEqual(g.snapshot(),before)

    def reject(self,g,mutate,mode='normal'):
        value=deepcopy(g.snapshot());mutate(value)
        value['state_hash']=canonical_hash({k:value[k] for k in ('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame','rewind_session','match_setup','generation_context','information')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(value,registry(mode))

    def test_complete_source_and_vector_cannot_be_trimmed_after_rehash(self):
        g=self.settled()
        self.reject(g,lambda s:s['state']['whole_card_replay_ledger']['children'][0]['physical']['body_targets']['slots'].pop())

    def test_original_target_universe_recomputed_after_rehash(self):
        g=self.settled()
        def corrupt(s):
            accepted=s['state']['whole_card_replay_ledger']['children'][0]['physical']['body_targets']
            target=accepted['slots'][0]['selected']['target_id']
            fact=next(f for f in accepted['origin']['entities'] if f['id']==target)
            fact['health']=7;fact['max_health']=7
        self.reject(g,corrupt)

    def test_current_version_and_old_schema_rejected(self):
        g=self.settled();s=g.snapshot();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        s['schema_version']=135
        with self.assertRaises(SnapshotError): Game.from_snapshot(s,registry())

    def test_weapon_generated_installation_uses_same_independent_module(self):
        g=self.settled(kind=CardType.WEAPON);self.assertEqual(len(self.generated(g).body_targets.slots),4)
        self.portable(g,kind=CardType.WEAPON)

    def test_hero_generated_installation_uses_same_independent_module(self):
        g=self.settled(kind=CardType.HERO);self.assertEqual(len(self.generated(g).body_targets.slots),4)
        self.portable(g,kind=CardType.HERO)

    def test_empty_physical_vector_is_preserved_without_rng(self):
        g=self.game('empty_body');rng=g.snapshot()['rng_state'];self.play(g,'repeat');p=self.generated(g)
        self.assertEqual(p.body_targets.slots,());self.assertEqual(p.cursor,0)
        self.assertEqual(g.snapshot()['rng_state'],rng)
        self.portable(g,'empty_body')

    def test_empty_required_pool_skips_only_that_body_and_no_selection_rng(self):
        g=self.settled('empty_target');p=self.generated(g)
        for s in (p.body_targets.slots[0],p.body_targets.slots[2]):
            self.assertEqual(s.selected.failure,'no_target');self.assertEqual(s.selected.rng_before,s.selected.rng_after)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4)
        self.portable(g,'empty_target')

    def test_explicit_request_does_not_suppress_inactive_untargeted_body(self):
        g=self.settled('inactive','explicit');p=self.generated(g)
        self.assertEqual([s.conditions.manathirst for s in p.body_targets.slots],[False,True,False,True])
        self.assertIsNone(p.body_targets.slots[0].selected.failure)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,12)
        self.portable(g,'inactive','explicit')

    def test_player_live_eligibility_does_not_rewrite_original_projection(self):
        g=self.settled('player_resources');p=self.generated(g)
        own=json.loads(p.body_targets.origin.observation.observation_json)['players'][0]
        self.assertEqual(own['max_mana'],10);self.assertEqual(g.state.players[1].max_mana,2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.portable(g,'player_resources')

    def test_nonactive_observation_value_does_not_authorize_paid_window(self):
        from hs_sim.engine.player_target_inputs import decode
        g=self.settled('player_other');observation=self.generated(g).body_targets.origin.observation
        with self.assertRaises(ValueError): decode(observation)
        self.assertEqual(decode(observation,require_active_player=False)['viewer'],2)

    def test_terminal_interrupt_does_not_start_remaining_bodies(self):
        g=self.settled('terminal');p=self.generated(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual(len(p.battlecry_ids),1)
        self.assertEqual(len(p.combo_ids),0);self.assertEqual(len(p.body_targets.slots),4)
        self.portable(g,'terminal')

    def test_storing_body_authority_does_not_run_predicate_or_select(self):
        from hs_sim.engine.generated_body_targets import grant_authority
        g=self.game('player');source=next(e for e in g.state.entities.values() if e.card_id=='unit')
        ability=replace(next(a for a in source.abilities if a.kind=='battlecry'),id=g.state.next_attachment_id,
            origin='granted',battlecry_card_id='donor')
        before=g.snapshot()
        def fail(*args,**kwargs): raise AssertionError('Pure authority ran a target producer')
        with patch.object(g.registry,'target_rule',return_value=fail),patch('hs_sim.engine.automatic_targets.select_automatic_target',side_effect=fail):
            self.assertEqual(grant_authority(g.state,g.registry,source,ability),('generated',))
        self.assertEqual(g.snapshot(),before)

    def test_original_body_condition_cannot_be_rewritten_after_rehash(self):
        g=self.settled('conditions')
        def corrupt(s):
            row=s['state']['whole_card_replay_ledger']['children'][0]['physical']['body_targets']['slots'][1]['conditions']
            row['mana_crystals']=2;row['manathirst']=False
        self.reject(g,corrupt,'conditions')

    def test_binding_cannot_be_borrowed_from_a_different_separation_mode(self):
        g=self.settled()
        self.reject(g,lambda s:s['state']['whole_card_replay_ledger']['children'][0]['physical']['body_targets']['binding'].__setitem__('mode','preserve_root'))

    def test_single_profile_has_actual_combo_origin_and_independent_targets(self):
        g=self.game(variant='legacy');self.play(g,'repeat');p=self.generated(g)
        self.assertEqual(p.combo_repeat_acceptance.plan.repetitions,1)
        self.assertEqual(len(p.combo_ids),2)
        self.assertEqual(len(p.body_targets.slots),4)
        self.assertTrue(all(g.state.combo_history[i-1].completed for i in p.combo_ids))

    def test_preserving_root_without_ordinary_body_consumes_no_root_rng(self):
        g=self.settled('preserve_no_root');p=self.generated(g)
        self.assertEqual(p.on_play,());self.assertIsNone(p.selection.partition.mode)
        self.assertEqual(p.selection.rng_before,p.selection.rng_after)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,7)
        self.portable(g,'preserve_no_root')

    def test_entry_silence_removes_root_target_window_before_acceptance(self):
        g=self.game('root_silenced');rng=g.snapshot()['rng_state'];self.play(g,'repeat');p=self.generated(g)
        self.assertEqual(p.on_play,());self.assertEqual(p.body_targets.slots,())
        self.assertIsNone(p.selection.partition.mode);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.portable(g,'root_silenced')
