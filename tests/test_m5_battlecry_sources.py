"""Indirect payload provenance, history selection, persistence and composition."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, CardDefinition, CardType, BattlecryRepeatSpec, BattlecryRepeatPlan,
    BattlecryHistoryQuery, battlecry_history_candidates, TriggerBattlecry, RepeatBattlecry,
    RepeatBattlecries, ResolutionError, SnapshotError, TargetSpec, TargetMode, EndTurn,
    Keyword, RewindSpec, AddBattlecryRepeatModifier, SelectChoice, Ruleset)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Transform, ChangeControl,
    Silence, ReturnToHand, RequestChoice, ChoiceOption, Summon, GrantDeathrattle, InvokeBehavior)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.battlecry_sources import BeginIndirectBattlecry, ResolveIndirectBattlecry
from hs_sim.engine.serialization import canonical_hash


class BattlecrySourceTests(unittest.TestCase):
    setUp=foundation.BattlecryTests.setUp
    card=foundation.BattlecryTests.card
    script=foundation.BattlecryTests.script
    watch=foundation.BattlecryTests.watch
    game=foundation.BattlecryTests.game
    play=foundation.BattlecryTests.play
    choose=foundation.BattlecryTests.choose
    pause=foundation.BattlecryTests.pause
    armor=foundation.BattlecryTests.armor
    check=foundation.BattlecryTests.check
    reject=foundation.BattlecryTests.reject
    nested=foundation.BattlecryTests.nested

    def trigger_card(self,**kw):
        self.script('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(
            c.state.entities[c.state.players[1].board[0]]),c.source_id,**kw)])

    def repeater(self,name='repeat',**kw):
        self.card(name,lambda c:[RepeatBattlecries(c.player_id,c.source_id,**kw)])

    def records(self,g): return g.state.battlecry_history
    def last(self,g): return self.records(g)[-1]

    def test_effect_activation_has_independent_history_and_no_minion_play(self):
        self.trigger_card();g=self.game(hand=('trigger',),board=('cry',));caster=self.play(g,'trigger');b=self.last(g)
        self.assertEqual((b.origin,b.play_id,b.batch_id,b.caster_id),('effect',None,None,caster))
        self.assertEqual((self.armor(g),len(g.state.play_history),len(g.state.battlecry_batches)),(2,1,0))
        self.assertTrue(b.completed and b.payload_started);self.check(g)

    def test_history_borrows_payload_on_new_carrier_without_copying_attachments(self):
        self.r.register_behavior('death',lambda c:[GainArmor(1,9)])
        self.card('original',deathrattle='death');self.repeater()
        g=self.game(hand=('original','repeat'));old=self.play(g,'original');new=self.play(g,'repeat');b=self.last(g)
        self.assertEqual((b.source_id,b.card_id,b.payload.card_id,b.history_id,b.parent_id),(new,'repeat','original',1,2))
        self.assertFalse(any(a.kind=='deathrattle' for a in g.state.entities[new].abilities))
        self.assertEqual((self.armor(g),len(g.state.play_history),g.state.players[1].mana),(4,2,6));self.check(g)

    def test_source_context_is_current_carrier_and_no_fabricated_play(self):
        self.card('context',lambda c:[GainArmor(1,2 if c.battlecry.origin=='hand' or
            c.play is None and c.battlecry.source_id==c.source_id and c.source.card_id=='repeat' else 99)])
        self.repeater();g=self.game(hand=('context','repeat'));self.play(g,'context');self.play(g,'repeat')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_history_survives_original_death(self):
        self.repeater();self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('cry','kill','repeat'));self.play(g);self.play(g,'kill');self.play(g,'repeat')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_history_survives_original_morph(self):
        self.repeater();self.script('morph',lambda c:[Transform(c.state.players[1].board[0],'body')])
        g=self.game(hand=('cry','morph','repeat'));self.play(g);self.play(g,'morph');self.play(g,'repeat')
        self.assertEqual(self.last(g).payload.card_id,'cry');self.assertEqual(self.armor(g),4);self.check(g)

    def test_history_keeps_original_player_after_control_change(self):
        self.repeater();self.script('steal',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        g=self.game(hand=('cry','steal','repeat'));self.play(g);self.play(g,'steal');self.play(g,'repeat')
        self.assertEqual((self.armor(g),self.armor(g,2)),(4,0));self.check(g)

    def test_effect_on_enemy_subject_uses_its_controller(self):
        self.script('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[2].board[0]]),c.source_id)])
        g=self.game(hand=('trigger',),enemy=('cry',));self.play(g,'trigger')
        self.assertEqual((self.armor(g),self.armor(g,2)),(0,2));self.check(g)

    def test_stale_physical_reference_is_skipped_after_bounce(self):
        self.script('trigger',lambda c:[ReturnToHand(c.state.players[1].board[0]),
            TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[0]]),c.source_id)])
        g=self.game(hand=('trigger',),board=('cry',));self.play(g,'trigger')
        self.assertEqual(self.records(g),[]);self.assertEqual(self.armor(g),0);self.check(g)

    def test_silenced_subject_has_no_payload(self):
        self.script('trigger',lambda c:[Silence(c.state.players[1].board[0]),
            TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[0]]),c.source_id)])
        g=self.game(hand=('trigger',),board=('cry',));self.play(g,'trigger');self.assertEqual(self.records(g),[]);self.check(g)

    def test_start_reaction_can_kill_accepted_subject(self):
        self.trigger_card();self.watch('kill','battlecry_started',lambda c:[Destroy(c.event.source_id)])
        g=self.game(hand=('trigger',),board=('cry','kill'));self.play(g,'trigger')
        self.assertEqual(self.armor(g),2);self.assertTrue(self.last(g).completed);self.check(g)

    def test_start_reaction_can_morph_accepted_subject(self):
        self.trigger_card();self.watch('morph','battlecry_started',lambda c:[Transform(c.event.source_id,'body')])
        g=self.game(hand=('trigger',),board=('cry','morph'));self.play(g,'trigger')
        self.assertEqual(self.armor(g),2);self.assertEqual(self.last(g).payload.card_id,'cry');self.check(g)

    def test_required_no_target_is_recorded_without_payload(self):
        self.card('target',targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.trigger_card();g=self.game(hand=('trigger',),board=('target',));self.play(g,'trigger');b=self.last(g)
        self.assertEqual((b.failure,b.payload_started,b.completed),('no_target',False,True))
        self.assertEqual(self.armor(g),0);self.check(g)

    def test_if_available_no_target_runs_payload(self):
        self.card('target',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='enemy'))
        self.trigger_card();g=self.game(hand=('trigger',),board=('target',));self.play(g,'trigger')
        self.assertIsNone(self.last(g).failure);self.assertEqual(self.armor(g),2);self.check(g)

    def test_explicit_invalid_target_has_failure(self):
        self.card('target',targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.trigger_card(targeting='explicit',target_id=1);g=self.game(hand=('trigger',),board=('target',))
        self.play(g,'trigger');self.assertEqual(self.last(g).failure,'invalid_target');self.check(g)

    def test_random_retarget_uses_original_definition_not_carrier(self):
        self.card('damage',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.repeater();g=self.game(hand=('damage','repeat'),enemy=('body',));target=g.state.players[2].board[0]
        self.play(g,'damage',target);self.play(g,'repeat')
        self.assertEqual((self.last(g).target_id,g.state.entities[target].health),(target,3));self.check(g)

    def test_random_target_uses_captured_player_after_carrier_stolen(self):
        self.card('damage',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.card('repeat',lambda c:[ChangeControl(c.source_id,2),RepeatBattlecry(1,c.source_id,1)])
        g=self.game(hand=('damage','repeat'),enemy=('body',));target=g.state.players[2].board[0]
        self.play(g,'damage',target);self.play(g,'repeat');self.assertEqual(self.last(g).player_id,1)
        self.assertEqual(g.state.entities[self.last(g).target_id].controller,2);self.check(g)

    def test_player_choice_pauses_and_restores_nested_record(self):
        self.card('choose',lambda c:[self.pause(c),GainArmor(1,3)]);self.repeater(choices='player')
        g=self.game(hand=('choose','repeat'));self.play(g,'choose');self.choose(g);self.play(g,'repeat');self.check(g)
        self.assertEqual(len([b for b in self.records(g) if not b.completed]),2)
        restored=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),6);self.check(g)

    def test_random_choice_does_not_suspend_and_preserves_rng(self):
        self.card('choose',lambda c:[RequestChoice(c.player_id,(ChoiceOption('a','A',(GainArmor(1,2),)),
            ChoiceOption('b','B',(GainArmor(1,5),))),source_id=c.source_id)])
        self.trigger_card();g=self.game(hand=('trigger',),board=('choose',));self.play(g,'trigger')
        self.assertIsNone(g.state.pending_choice);self.assertIn(self.armor(g),(2,5));self.check(g)
        self.assertEqual(sum(e.kind=='battlecry_choice_randomized' for e in g.events),1)

    def test_start_reaction_pause_retains_typed_unstarted_payload(self):
        self.trigger_card();self.watch('watch','battlecry_started',lambda c:[self.pause(c)])
        g=self.game(hand=('trigger',),board=('cry','watch'));self.play(g,'trigger')
        self.assertFalse(self.last(g).payload_started);self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),2);self.check(g)

    def test_finish_reaction_pause_has_completed_history(self):
        self.trigger_card();self.watch('watch','battlecry_finished',lambda c:[self.pause(c)])
        g=self.game(hand=('trigger',),board=('cry','watch'));self.play(g,'trigger');self.assertTrue(self.last(g).completed)
        self.check(g);self.choose(g);self.check(g)

    def test_direct_effect_does_not_consume_or_multiply_player_policies(self):
        self.script('trigger',lambda c:[AddBattlecryRepeatModifier(1,BattlecryRepeatSpec(3),uses=1),
            TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[0]]),c.source_id)])
        g=self.game(hand=('trigger',),board=('cry',));self.play(g,'trigger');self.assertEqual(self.armor(g),2)
        self.assertEqual(g.state.players[1].battlecry_modifiers[0].uses_remaining,1);self.check(g)

    def test_outer_repeat_policy_does_not_multiply_indirect_child_again(self):
        self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        self.repeater(query=BattlecryHistoryQuery(before_play_id=2));g=self.game(hand=('cry','repeat'),board=('aura',))
        self.play(g);self.play(g,'repeat');self.assertEqual(self.armor(g),8)
        self.assertEqual([b.origin for b in self.records(g)],['hand','hand','hand','history','hand','history']);self.check(g)

    def test_history_query_deduplicates_hand_play_payloads(self):
        self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        g=self.game(board=('aura',));self.play(g)
        self.assertEqual(len(battlecry_history_candidates(g.state,1)),2)
        self.assertEqual([b.id for b in battlecry_history_candidates(g.state,1,BattlecryHistoryQuery(distinct='play_payload'))],[1])

    def test_query_excludes_pending_current_activation(self):
        self.repeater();g=self.game(hand=('repeat',));self.play(g,'repeat');self.assertEqual(len(self.records(g)),1);self.check(g)

    def test_query_bounds_origins_exclusions_and_player(self):
        self.repeater();g=self.game(hand=('cry','repeat'));self.play(g);self.play(g,'repeat')
        self.assertEqual([b.id for b in battlecry_history_candidates(g.state,1,BattlecryHistoryQuery(origins=('history',)))],[3])
        self.assertEqual(battlecry_history_candidates(g.state,2),())
        self.assertEqual(battlecry_history_candidates(g.state,1,BattlecryHistoryQuery(turn=99)),())
        self.assertEqual(battlecry_history_candidates(g.state,1,BattlecryHistoryQuery(before_id=2,exclude_ids=(1,))),())
        self.assertEqual([b.id for b in battlecry_history_candidates(g.state,1,BattlecryHistoryQuery(before_play_id=2))],[1])

    def test_failed_attempt_is_not_history_candidate(self):
        self.card('target',targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'));self.trigger_card()
        g=self.game(hand=('trigger',),board=('target',));self.play(g,'trigger')
        self.assertEqual(battlecry_history_candidates(g.state,1,BattlecryHistoryQuery(origins=('effect',))),())

    def test_first_and_last_selection_are_distinct(self):
        self.card('five',lambda c:[GainArmor(1,5)]);self.repeater('first',selection='first');self.repeater('last',query=BattlecryHistoryQuery(before_play_id=3))
        g=self.game(hand=('cry','five','first','last'));self.play(g);self.play(g,'five');self.play(g,'first');self.play(g,'last')
        self.assertEqual(self.armor(g),14);self.check(g)

    def test_all_sequence_is_frozen_not_extended_by_new_history(self):
        self.repeater(selection='all',query=BattlecryHistoryQuery(origins=('hand','history')))
        g=self.game(hand=('cry','cry','repeat'));self.play(g);self.play(g);self.play(g,'repeat')
        self.assertEqual(self.armor(g),8);self.assertEqual(len(self.records(g)),5);self.check(g)

    def test_random_sequence_round_trip_is_deterministic(self):
        self.card('five',lambda c:[GainArmor(1,5)]);self.repeater(selection='all',order='random')
        g=self.game(hand=('cry','five','repeat'));self.play(g);self.play(g,'five');self.play(g,'repeat')
        self.assertEqual(self.armor(g),14);self.assertEqual({b.history_id for b in self.records(g) if b.origin=='history'},{1,2});self.check(g)

    def test_nested_history_is_explicit_and_acyclic(self):
        self.card('repeat',lambda c:[RepeatBattlecry(1,c.source_id,1)])
        self.card('nested',lambda c:[RepeatBattlecry(1,c.source_id,2)])
        g=self.game(hand=('cry','repeat','nested'));self.play(g);self.play(g,'repeat');self.play(g,'nested')
        self.assertEqual(self.armor(g),6);self.assertEqual([(b.id,b.parent_id) for b in self.records(g)],[(1,None),(2,None),(3,2),(4,None),(5,4),(6,5)]);self.check(g)

    def test_rewind_restores_history_and_indirect_attempt_stays_zero(self):
        self.card('attempt',lambda c:[GainArmor(1,c.rewind_attempt+2)])
        self.card('repeat',lambda c:[RepeatBattlecry(1,c.source_id,1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('attempt','repeat'));self.play(g,'attempt');self.play(g,'repeat');self.check(g)
        self.choose(g,'retry');self.assertEqual(self.armor(g),4);self.check(g)

    def test_retained_rewind_reexecutes_indirect_without_fake_outcome(self):
        self.card('attempt',lambda c:[GainArmor(1,c.rewind_attempt+2)])
        self.card('repeat',lambda c:[RepeatBattlecry(1,c.source_id,1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('attempt','repeat'),board=('retainer',));self.play(g,'attempt');self.play(g,'repeat')
        self.assertEqual(self.armor(g),6);self.assertTrue(all(b.outcome_id is None and b.iteration==1 for b in self.records(g) if b.origin=='history'));self.check(g)

    def test_lethal_child_interrupts_both_records_and_stops_tail(self):
        self.card('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id),GainArmor(1,99)])
        self.trigger_card();g=self.game(hand=('trigger',),board=('lethal',));self.play(g,'trigger')
        self.assertTrue(self.last(g).interrupted);self.assertFalse(self.last(g).completed);self.assertEqual(self.armor(g),0);self.check(g)

    def test_start_lethal_interrupts_before_payload(self):
        self.trigger_card();self.watch('lethal','battlecry_started',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.game(hand=('trigger',),board=('cry','lethal'));self.play(g,'trigger')
        self.assertTrue(self.last(g).interrupted);self.assertFalse(self.last(g).payload_started);self.assertEqual(self.armor(g),0);self.check(g)

    def test_bad_payload_rolls_back_history_rng_payment_and_events(self):
        self.card('bad',lambda c:[GainArmor(1,3),Summon(1,'unknown')]);self.trigger_card()
        g=self.game(hand=('trigger',),board=('bad',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'trigger')
        self.assertEqual(g.snapshot(),s)

    def test_bad_payload_after_choice_rolls_back_choice_submission(self):
        self.r.register_behavior('fail_later',lambda c:[Summon(1,'unknown')])
        self.card('bad',lambda c:[self.pause(c),InvokeBehavior('fail_later',c.source_id,1)]);self.trigger_card(choices='player')
        g=self.game(hand=('trigger',),board=('bad',));self.play(g,'trigger');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.check(g)

    def test_unfinished_or_other_player_history_cannot_be_repeated(self):
        self.card('repeat',lambda c:[RepeatBattlecry(1,c.source_id,1)])
        self.card('other',lambda c:[RepeatBattlecry(2,c.source_id,1)])
        g=self.game(hand=('repeat',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'repeat')
        self.assertEqual(g.snapshot(),s)
        g=self.game(hand=('cry','other'));self.play(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'other')
        self.assertEqual(g.snapshot(),s)

    def pending(self):
        self.card('pause',lambda c:[self.pause(c)]);self.repeater(choices='player')
        g=self.game(hand=('pause','repeat'));self.play(g,'pause');self.choose(g);self.play(g,'repeat');return g

    def test_restore_rejects_history_source_changed(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['history_id']=2;self.reject(s)

    def test_restore_rejects_fabricated_play_in_indirect_record(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['play_id']=2;self.reject(s)

    def test_restore_rejects_self_parent(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['parent_id']=3;self.reject(s)

    def test_restore_rejects_payload_changed(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['payload']['ability_id']=999999;self.reject(s)

    def test_restore_rejects_missing_completion_marker(self):
        g=self.pending();s=g.snapshot();self.nested(s,'FinishBattlecry')['fields']['record_id']=1;self.reject(s)

    def test_restore_rejects_duplicate_resolve_after_payload_started(self):
        g=self.pending();s=g.snapshot();node=self.nested(s,'FinishBattlecry');node['type']='hs_sim.engine.battlecry_sources.ResolveIndirectBattlecry';self.reject(s)

    def test_restore_rejects_removed_resolve_before_payload(self):
        self.trigger_card();self.watch('watch','battlecry_started',lambda c:[self.pause(c)])
        g=self.game(hand=('trigger',),board=('cry','watch'));self.play(g,'trigger');s=g.snapshot()
        node=self.nested(s,'ResolveIndirectBattlecry');node['fields']['record_id']=99;self.reject(s)

    def test_player_observation_does_not_expose_host_history_or_random_choices(self):
        self.card('choose',lambda c:[self.pause(c)]);self.trigger_card();g=self.game(hand=('trigger',),board=('choose',))
        self.play(g,'trigger')
        for p in (1,2):
            encoded=json.dumps((g.observe(p),g.player_events(p)))
            for private in ('history_id','battlecry_history','battlecry_choice_randomized','payload_started'):
                self.assertNotIn(private,encoded)

    def test_query_validation_rejects_ambiguous_play_counting(self):
        for kw in ({'origins':()}, {'origins':('hand','hand')}, {'origins':['hand']},
            {'origins':('history',),'distinct':'play_payload'}, {'origins':('effect',),'before_play_id':2},
            {'turn':True}, {'before_id':0}, {'exclude_ids':(1,1)}, {'distinct':'card'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):BattlecryHistoryQuery(**kw)

    def test_countered_play_does_not_fabricate_successful_history(self):
        import test_m5_minion_counters as counters
        self.secret=counters.MinionCounterTests.secret.__get__(self)
        counters.MinionCounterTests.setUp(self)
        self.repeater();g=self.game(hand=('arm','cry','repeat'));self.play(g,'arm');self.play(g);self.play(g,'repeat')
        self.assertTrue(g.state.play_history[1].countered)
        self.assertEqual([b.card_id for b in self.records(g)],['repeat']);self.assertEqual(self.armor(g),0);self.check(g)

    def test_explicit_valid_target_uses_shared_damage_and_target_record(self):
        self.card('damage',lambda c:[Damage(c.target_id,2,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.script('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[0]]),
            c.source_id,c.state.players[2].board[0],'explicit')])
        g=self.game(hand=('trigger',),board=('damage',),enemy=('body',));target=g.state.players[2].board[0]
        self.play(g,'trigger');self.assertEqual((self.last(g).target_id,g.state.entities[target].health),(target,3));self.check(g)

    def test_history_carrier_captures_identity_before_it_morphs(self):
        self.card('repeat',lambda c:[Transform(c.source_id,'body'),RepeatBattlecry(1,c.source_id,1)])
        g=self.game(hand=('cry','repeat'));self.play(g);i=self.play(g,'repeat')
        self.assertEqual(g.state.entities[i].card_id,'body');self.assertEqual(self.last(g).card_id,'repeat');self.check(g)

    def test_frozen_all_sequence_survives_choice_and_does_not_requery(self):
        self.card('choose',lambda c:[self.pause(c),GainArmor(1,3)])
        self.repeater(selection='all',choices='player',query=BattlecryHistoryQuery(origins=('hand','history')))
        g=self.game(hand=('choose','cry','repeat'));self.play(g,'choose');self.choose(g);self.play(g);self.play(g,'repeat')
        self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(self.armor(g),10);self.assertEqual([b.history_id for b in self.records(g) if b.origin=='history'],[1,2]);self.check(g)

    def test_queued_history_repeat_rejects_tampered_original(self):
        self.card('choose',lambda c:[self.pause(c)])
        self.repeater(selection='all',choices='player')
        g=self.game(hand=('choose','cry','repeat'));self.play(g,'choose');self.choose(g);self.play(g);self.play(g,'repeat')
        s=g.snapshot();node=self.nested(s['resolution_frame'],'RepeatBattlecry');self.assertIsNotNone(node)
        node['fields']['history_id']=4;self.reject(s)

    def test_player_command_resumes_indirect_discovery(self):
        g=self.pending();port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='select_choice')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertTrue(self.last(g).completed);self.check(g)

    def test_engine_budget_does_not_become_a_game_result(self):
        self.card('loop',lambda c:[TriggerBattlecry(MinionReference.capture(c.source))])
        g=self.game(hand=('loop',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'loop')
        self.assertEqual(g.snapshot(),s);self.assertEqual(g.state.status,'playing')

    def test_effect_validation_rejects_ambiguous_policies(self):
        for make in (lambda:RepeatBattlecry(1,1,True),lambda:RepeatBattlecry(1,1,1,target_id=2),
            lambda:RepeatBattlecries(1,1,selection='random'),lambda:RepeatBattlecries(1,1,choices='unknown'),
            lambda:TriggerBattlecry(1)):
            with self.subTest(make=make),self.assertRaises(ValueError):make()


if __name__=='__main__': unittest.main()
