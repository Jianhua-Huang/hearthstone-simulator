"""Frozen paid/generated facts for independent public Battlecry/Combo bodies."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BodyReference,GrantBattlecry,GrantCombo,BodyPlayReference,
    BodyPlayConditions,IfBodyCondition,body_play_conditions,CardDefinition,CardType,Keyword,
    Zone,TriggerSpec,Game,Scenario,PlayerSetup,PlayCard,SelectChoice,SnapshotError,ResolutionError)
from hs_sim.engine.effects import (GainArmor,ChangeManaCrystals,RequestChoice,ChoiceOption,
    RandomDamage,Transform,ChangeControl,Draw)
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.generated_combo_repeats import PROFILE


def registry(mode='normal'):
    r=Registry('body-condition-fixtures-'+mode+'-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('plain','Plain',CardType.MINION,health=5))
    r.register_card(CardDefinition('unit','Unit',CardType.MINION,cost=1,health=5,
        keywords=(Keyword.MANATHIRST,),manathirst=3))
    def body(c,family):
        ref=BodyPlayReference.capture(c,family)
        positive=5 if family=='battlecry'else 3
        effect=IfBodyCondition(ref,'manathirst',(GainArmor(c.player_id,positive),),(GainArmor(c.player_id,1),))
        if mode=='wait':
            return (ChangeManaCrystals(c.player_id,-5),
                RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),effect)
        if mode=='bad':return (RandomDamage((c.state.players[2].hero_id,),1),replace(effect,body=replace(ref,activation_id=999999)))
        if mode=='branch_fail':
            from hs_sim.engine.effects import Summon
            return (RandomDamage((c.state.players[2].hero_id,),1),replace(effect,when_true=(Summon(c.player_id,'missing'),)))
        if mode=='transform'and ref.declaration_card_id=='threshold5'and family=='battlecry':
            return (Transform(c.source_id,'plain'),effect)
        if mode=='control'and ref.declaration_card_id=='threshold5'and family=='battlecry':
            return (ChangeControl(c.source_id,2),effect)
        if mode=='generated_late'and c.physical is not None and ref.declaration_card_id=='threshold5'and family=='battlecry':
            return (ChangeManaCrystals(c.player_id,-5),effect)
        if mode=='nested':
            return (replace(effect,when_false=(IfBodyCondition(ref,'combo',(GainArmor(c.player_id,2),),(GainArmor(c.player_id,1),)),)),)
        return (effect,)
    r.register_behavior('bc',lambda c:body(c,'battlecry'))
    r.register_behavior('combo',lambda c:body(c,'combo'))
    for t in (5,9):
        r.register_card(CardDefinition('threshold'+str(t),'Threshold',CardType.MINION,health=5,
            battlecry='bc',combo='combo',keywords=(Keyword.MANATHIRST,Keyword.COMBO),manathirst=t))
    def grant(c,entity=None):
        e=entity or next(e for e in c.state.entities.values()if e.card_id=='unit'and e.zone==Zone.HAND)
        ref=BodyReference.capture(e)
        return tuple(kind(ref,'threshold'+str(t),c.source_id)for kind in (GrantBattlecry,GrantCombo)for t in (5,9))
    r.register_behavior('grant',grant)
    r.register_card(CardDefinition('grant','Grant',CardType.SPELL,on_play='grant'))
    r.register_behavior('draw',lambda c:(Draw(c.player_id),))
    r.register_card(CardDefinition('draw','Draw',CardType.SPELL,on_play='draw'))
    def watch(c):
        target=c.state.entities[c.event.target_id]
        return grant(c,target)if target.card_id=='unit'else ()
    r.register_behavior('watch',watch)
    r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=5,
        triggers=(TriggerSpec('minion_summoned','watch'),)))
    r.register_behavior('replay',lambda c:(ReplayWholeCards(c.player_id,c.source_id,
        WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,kinds=(CardType.MINION,)),
        physical_profile=PROFILE,choices='player'),))
    r.register_card(CardDefinition('replay','Replay',CardType.SPELL,cost=0,on_play='replay'))
    return r


class BodyPlayConditionTests(unittest.TestCase):
    def game(self,mode='normal',hand=('grant','unit'),board=(),deck=('plain',)*3,mana=6):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=deck,max_mana=mana,mana=mana),
            PlayerSetup('hero',deck=('plain',)*3,max_mana=mana,mana=mana)),seed=246),registry(mode))

    def play(self,g,name):
        s=g.state;i=next(i for i in s.players[1].hand if s.entities[i].card_id==name);g.apply(PlayCard(1,i))

    def populated(self,mode='normal',**kw):
        g=self.game(mode,**kw);self.play(g,'grant');self.play(g,'unit');return g

    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor

    def checks(self,g):return [dict(e.data)for e in g.events if e.kind=='body_condition_checked']

    def portable(self,g,mode='normal'):
        for branch in (g.clone(),Game.from_snapshot(json.loads(json.dumps(g.snapshot())),registry(mode)),replay(build_replay(g),registry(mode))):
            self.assertEqual(branch.snapshot(),g.snapshot())
            for seat in (1,2):self.assertEqual(branch.for_player(seat).observe(),g.for_player(seat).observe())

    def test_independent_paid_bodies_use_thresholds_not_physical_carrier_boolean(self):
        g=self.populated();self.assertTrue(g.state.play_history[-1].manathirst)
        self.assertEqual([c['result']for c in self.checks(g)],[True,False,True,False]);self.assertEqual(self.armor(g),10)
        self.portable(g)

    def test_completed_query_preserves_physical_hand_conditions_and_own_threshold(self):
        g=self.populated();s=g.state
        ref=BodyPlayReference.from_record(s.battlecry_history[1],'battlecry');facts=body_play_conditions(s,g.registry,ref)
        play=s.play_history[-1]
        self.assertEqual((facts.combo,facts.outcast,facts.finale,facts.quickdraw),(play.combo,play.outcast,play.finale,play.quickdraw))
        self.assertEqual((facts.mana_crystals,facts.manathirst_threshold,facts.manathirst),(6,9,False))
        self.assertEqual(play.manathirst_threshold,3)

    def test_crystal_changes_and_real_wait_do_not_recompute_original_conditions(self):
        g=self.populated('wait');self.assertIsNotNone(g.state.pending_choice);self.portable(g,'wait')
        self.assertEqual(g.state.players[1].max_mana,1)
        while g.state.pending_choice:
            g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)))
            if g.state.pending_choice:self.portable(g,'wait')
        self.assertEqual([c['result']for c in self.checks(g)],[True,False,True,False]);self.assertEqual(self.armor(g),10)
        self.portable(g,'wait')

    def test_source_transform_does_not_replace_the_captured_body_declaration(self):
        g=self.populated('transform');self.assertEqual(self.armor(g),10)
        self.assertEqual([c['declaration_card_id']for c in self.checks(g)],['threshold5','threshold9','threshold5','threshold9'])
        self.portable(g,'transform')

    def test_source_control_change_does_not_replace_the_accepted_execution_seat(self):
        g=self.populated('control');self.assertEqual(self.armor(g),10)
        self.assertEqual(g.state.players[2].board[-1],g.state.play_history[-1].source_id);self.portable(g,'control')

    def test_bad_identity_after_actual_random_damage_rolls_back_whole_paid_root(self):
        g=self.game('bad');self.play(g,'grant');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'unit')
        self.assertEqual(g.snapshot(),before)

    def test_selected_branch_failure_after_random_damage_rolls_back_whole_paid_root(self):
        g=self.game('branch_fail');self.play(g,'grant');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'unit')
        self.assertEqual(g.snapshot(),before)

    def test_nested_condition_effects_are_serializable_public_composition(self):
        g=self.populated('nested');self.assertEqual(self.armor(g),12);self.portable(g,'nested')

    def test_generated_roots_use_own_acceptance_without_fake_paid_conditions(self):
        g=self.game(hand=('unit','replay'),board=('watcher',));self.play(g,'unit');self.play(g,'replay')
        s=g.state;self.assertEqual(len(s.play_history),2);self.assertEqual(len(s.battlecry_history),2);self.assertEqual(len(s.combo_history),2)
        self.assertEqual(self.armor(g),10)
        for family,records in (('battlecry',s.battlecry_history),('combo',s.combo_history)):
            for record in records:
                self.assertIsNone(record.play_id)
                facts=body_play_conditions(s,g.registry,BodyPlayReference.from_record(record,family))
                self.assertEqual((facts.combo,facts.outcast,facts.finale,facts.quickdraw),(True,False,False,False))
                self.assertEqual(facts.mana_crystals,6)
        self.portable(g)

    def test_generated_late_crystal_change_keeps_both_body_threshold_decisions(self):
        g=self.game('generated_late',hand=('unit','replay'),board=('watcher',));self.play(g,'unit');self.play(g,'replay')
        self.assertEqual(g.state.players[1].max_mana,1);self.assertEqual(self.armor(g),10)
        self.assertEqual([c['result']for c in self.checks(g)],[True,False,True,False]);self.portable(g,'generated_late')

    def test_players_receive_no_private_condition_receipt_or_branch_marker(self):
        g=self.populated()
        for seat in (1,2):
            wire=json.dumps(g.for_player(seat).observe())+json.dumps(g.player_events(seat))
            for private in ('body_condition_checked','activation_id','physical_child_id','mana_crystals','BodyPlayReference','submitted_cost'):
                self.assertNotIn(private,wire)

    def test_rehashed_waiting_reference_cannot_change_declaration_or_invocation(self):
        g=self.populated('wait')
        def refs(value):
            if isinstance(value,dict):
                if str(value.get('type','')).endswith('.BodyPlayReference'):yield value
                for item in value.values():yield from refs(item)
            elif isinstance(value,list):
                for item in value:yield from refs(item)
        snapshot=g.snapshot();nodes=list(refs(snapshot['resolution_frame']));self.assertTrue(nodes)
        for field,value in (('activation_id',999999),('declaration_card_id','threshold9')):
            bad=g.snapshot();node=next(refs(bad['resolution_frame']));node['fields'][field]=value
            bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry('wait'))

    def test_reference_and_branch_inputs_are_strict(self):
        g=self.populated();ref=BodyPlayReference.from_record(g.state.battlecry_history[0],'battlecry')
        for f in (lambda:replace(ref,activation_id=True),lambda:replace(ref,family='deathrattle'),
                  lambda:replace(ref,physical_child_id=1),lambda:IfBodyCondition(ref,'unknown'),
                  lambda:IfBodyCondition(ref,'combo',[GainArmor(1,1)]),lambda:BodyPlayConditions(True,False,False,False,True,6,9)):
            with self.assertRaises(ValueError):f()

    def test_completed_invocation_cannot_be_used_as_an_active_condition_effect(self):
        g=self.populated();ref=BodyPlayReference.from_record(g.state.battlecry_history[0],'battlecry')
        from hs_sim.engine.body_conditions import invocation
        with self.assertRaises(ValueError):invocation(g.state,g.registry,ref,active=True)
