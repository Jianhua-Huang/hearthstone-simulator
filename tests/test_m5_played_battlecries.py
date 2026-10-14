"""Committed declarations, explicit counter/window policy and borrowed plays."""
import json
import unittest
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, CardDefinition, CardType, Scenario, PlayerSetup, PlayCard,
    PlayedBattlecryQuery, played_battlecry_candidates, RepeatPlayedBattlecry,
    RepeatPlayedBattlecries, battlecry_play_window, TriggerBattlecry, RepeatBattlecry,
    BattlecryRepeatSpec, AddBattlecryRepeatModifier, RewindSpec, Keyword, EndTurn,
    TargetSpec, ResolutionError, SnapshotError, GenerationContext, SelectChoice,
    BattlecryHistoryQuery, battlecry_history_candidates, LaunchStarship)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Transform, ChangeControl,
    ReturnToHand, Silence, Summon, RequestChoice, ChoiceOption, InvokeBehavior, DamageBatch)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry


class PlayedBattlecryTests(unittest.TestCase):
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

    def macaw(self,name='macaw',choices='random',**kw):
        self.card(name,lambda c:[RepeatPlayedBattlecries(c.player_id,c.source_id,
            PlayedBattlecryQuery(before_id=battlecry_play_window(c.state,c.battlecry),countered='include'),choices=choices)],**kw)

    def last(self,g):return g.state.battlecry_history[-1]

    def test_committed_declaration_and_activation_are_distinct_records(self):
        g=self.game();self.play(g);p=g.state.play_history[0];b=self.last(g)
        self.assertEqual(p.battlecries,(b.payload,));self.assertEqual([p.id for p in played_battlecry_candidates(g.state,1)],[1]);self.check(g)

    def test_nonbattlecry_and_normal_summons_are_not_candidates(self):
        self.script('summon',lambda c:[Summon(1,'cry')]);g=self.game(hand=('summon','body'));self.play(g,'summon');self.play(g,'body')
        self.assertEqual(played_battlecry_candidates(g.state,1),());self.assertTrue(all(p.battlecries==() for p in g.state.play_history));self.check(g)

    def test_capture_precedes_paid_minion_counter_window(self):
        self.watch('wait','card_committed',lambda c:[self.pause(c)])
        g=self.game(board=('wait',));self.play(g)
        self.assertEqual(len(g.state.play_history[0].battlecries),1);self.assertEqual(g.state.battlecry_history,[])
        self.assertEqual(played_battlecry_candidates(g.state,1),());self.check(g);self.choose(g);self.check(g)

    def test_first_macaw_without_prior_play_has_no_child(self):
        self.macaw();g=self.game(hand=('macaw',));self.play(g,'macaw')
        self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(self.armor(g),0);self.check(g)

    def test_repeat_uses_new_carrier_and_original_declaration_without_payment(self):
        self.macaw();g=self.game(hand=('cry','macaw'));self.play(g);source=self.play(g,'macaw');b=self.last(g)
        self.assertEqual((b.origin,b.source_id,b.history_play_id,b.history_id,b.play_id),('played_history',source,1,None,None))
        self.assertEqual((b.card_id,b.payload.card_id,b.parent_id),('macaw','cry',2))
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(4,6,2));self.check(g)

    def test_consecutive_macaws_follow_decreasing_original_windows(self):
        self.macaw();g=self.game(hand=('cry','macaw','macaw'));self.play(g);self.play(g,'macaw');self.play(g,'macaw')
        self.assertEqual(self.armor(g),6)
        self.assertEqual([b.history_play_id for b in g.state.battlecry_history],[None,None,1,None,2,1]);self.check(g)

    def test_repeated_macaw_with_no_older_battlecry_terminates(self):
        self.macaw();g=self.game(hand=('macaw','macaw'));self.play(g,'macaw');self.play(g,'macaw')
        self.assertEqual(len(g.state.battlecry_history),3);self.assertEqual(self.armor(g),0);self.check(g)

    def test_brann_does_not_turn_second_iteration_into_a_new_history_sample(self):
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        self.macaw();g=self.game(hand=('cry','macaw'),board=('brann',));self.play(g);self.play(g,'macaw')
        self.assertEqual(self.armor(g),8);self.assertEqual([b.history_play_id for b in g.state.battlecry_history if b.origin=='played_history'],[1,1])
        self.assertEqual(len(played_battlecry_candidates(g.state,1)),2);self.check(g)

    def test_copy_does_not_gain_original_deathrattle(self):
        self.r.register_behavior('death',lambda c:[GainArmor(1,99)]);self.card('original',deathrattle='death');self.macaw()
        g=self.game(hand=('original','macaw'));self.play(g,'original');i=self.play(g,'macaw')
        self.assertFalse(any(a.kind=='deathrattle' for a in g.state.entities[i].abilities));self.assertEqual(self.armor(g),4);self.check(g)

    def test_declared_history_survives_silence_then_morph(self):
        self.macaw();self.script('morph',lambda c:[Silence(c.state.players[1].board[0]),Transform(c.state.players[1].board[0],'body')])
        g=self.game(hand=('cry','morph','macaw'));self.play(g);self.play(g,'morph');self.play(g,'macaw')
        self.assertEqual(self.last(g).payload.card_id,'cry');self.assertEqual(self.armor(g),4);self.check(g)

    def test_declared_history_survives_death(self):
        self.macaw();self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('cry','kill','macaw'));self.play(g);self.play(g,'kill');self.play(g,'macaw')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_declared_history_keeps_original_player_after_transfer(self):
        self.macaw();self.script('steal',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        g=self.game(hand=('cry','steal','macaw'));self.play(g);self.play(g,'steal');self.play(g,'macaw')
        self.assertEqual((self.armor(g),self.armor(g,2)),(4,0));self.assertEqual(played_battlecry_candidates(g.state,2),());self.check(g)

    def test_entry_morph_does_not_rewrite_committed_declaration(self):
        self.macaw();self.watch('morph','minion_summoned',lambda c:[Transform(c.event.source_id,'body')])
        g=self.game(hand=('cry','macaw'),board=('morph',));self.play(g);self.play(g,'macaw')
        self.assertEqual([p.card_id for p in g.state.play_history],['cry','macaw']);self.assertEqual(self.armor(g),4);self.check(g)

    def test_bounce_replay_records_two_independent_played_declarations(self):
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])]);g=self.game(hand=('cry','bounce'))
        self.play(g);self.play(g,'bounce');self.play(g);candidates=played_battlecry_candidates(g.state,1)
        self.assertEqual([p.id for p in candidates],[1,3]);self.assertNotEqual(candidates[0].battlecries[0].ability_id,candidates[1].battlecries[0].ability_id);self.check(g)

    def arm_counter(self):
        import test_m5_minion_counters as counters
        self.secret=counters.MinionCounterTests.secret.__get__(self)
        counters.MinionCounterTests.setUp(self)

    def test_countered_play_keeps_declarations_without_actual_activation(self):
        self.arm_counter();g=self.game(hand=('arm','cry'));self.play(g,'arm');self.play(g)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(g.state.battlecry_history,[])
        self.assertEqual(played_battlecry_candidates(g.state,1),())
        self.assertEqual([p.id for p in played_battlecry_candidates(g.state,1,PlayedBattlecryQuery(countered='include'))],[2])
        self.assertEqual([p.id for p in played_battlecry_candidates(g.state,1,PlayedBattlecryQuery(countered='only'))],[2]);self.check(g)

    def test_explicit_include_policy_can_repeat_countered_payload(self):
        self.arm_counter();self.macaw();g=self.game(hand=('arm','cry','macaw'));self.play(g,'arm');self.play(g);self.play(g,'macaw')
        self.assertEqual(self.armor(g),2);self.assertEqual(self.last(g).history_play_id,2)
        self.assertEqual([b.origin for b in g.state.battlecry_history],['hand','played_history']);self.check(g)

    def test_board_full_failure_retains_played_declaration_without_activation(self):
        self.watch('fill','minion_counter_check',lambda c:[Summon(1,'body') for _ in range(6)])
        g=self.game(board=('fill',));self.play(g)
        self.assertEqual(g.state.play_history[0].minion_result,'board_full');self.assertEqual(g.state.battlecry_history,[])
        self.assertEqual([p.id for p in played_battlecry_candidates(g.state,1)],[1]);self.check(g)

    def test_magnetic_commit_keeps_original_payload_identity(self):
        from hs_sim.engine.model import CardMetadata, CardClass
        meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.r.register_card(CardDefinition('mech','mech',CardType.MINION,health=4,metadata=meta))
        self.card('magnet',keywords=(Keyword.MAGNETIC,),metadata=meta,magnetic_tribes=('mech',));self.macaw()
        g=self.game(hand=('magnet','macaw'),board=('mech',));source=g.state.players[1].hand[0]
        g.apply(PlayCard(1,source,position=0));original=g.state.play_history[0].battlecries
        self.assertEqual(g.state.play_history[0].minion_result,'magnetized');self.assertFalse(g.state.battlecry_history)
        self.play(g,'macaw');self.assertEqual(self.last(g).payload,original[0]);self.assertEqual(self.armor(g),2);self.check(g)

    def test_exclude_policy_falls_back_to_earlier_completed_play(self):
        self.arm_counter();self.card('five',lambda c:[GainArmor(1,5)])
        self.card('last',lambda c:[RepeatPlayedBattlecries(1,c.source_id)])
        g=self.game(hand=('cry','arm','five','last'));self.play(g);self.play(g,'arm');self.play(g,'five');self.play(g,'last')
        self.assertEqual(self.armor(g),4);self.assertEqual(self.last(g).history_play_id,1);self.check(g)

    def test_physical_trigger_macaw_has_no_new_play_and_follows_older_window(self):
        self.macaw();self.script('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[1]]),c.source_id)])
        g=self.game(hand=('cry','macaw','trigger'));self.play(g);self.play(g,'macaw');self.play(g,'trigger')
        self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.play_history),3)
        self.assertEqual([b.history_play_id for b in g.state.battlecry_history if b.origin=='played_history'],[1,2,1]);self.check(g)

    def test_summoned_macaw_physical_trigger_uses_completed_play_history(self):
        self.macaw();self.script('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[0]]),c.source_id)])
        g=self.game(hand=('cry','trigger'),board=('macaw',));self.play(g);self.play(g,'trigger')
        self.assertEqual(self.armor(g),4);self.assertEqual(self.last(g).history_play_id,1);self.check(g)

    def test_actual_activation_history_can_repeat_a_played_history_payload(self):
        self.macaw();self.card('actual',lambda c:[RepeatBattlecry(1,c.source_id,3)])
        g=self.game(hand=('cry','macaw','actual'));self.play(g);self.play(g,'macaw');self.play(g,'actual')
        self.assertEqual(self.armor(g),6);self.assertEqual(self.last(g).origin,'history')
        self.assertEqual([b.id for b in battlecry_history_candidates(g.state,1,BattlecryHistoryQuery(origins=('played_history',)))],[3]);self.check(g)

    def test_historical_macaw_activation_recovers_its_original_play_window(self):
        self.macaw();self.card('actual',lambda c:[RepeatBattlecry(1,c.source_id,2)])
        g=self.game(hand=('cry','macaw','actual'));self.play(g);self.play(g,'macaw');self.play(g,'actual')
        self.assertEqual(self.armor(g),6);self.assertEqual(self.last(g).history_play_id,1);self.check(g)

    def test_whole_play_query_has_bounds_kind_owner_and_exclusions(self):
        self.card('weapon',kind=CardType.WEAPON);g=self.game(hand=('cry','weapon'));self.play(g);self.play(g,'weapon')
        self.assertEqual([p.id for p in played_battlecry_candidates(g.state,1,PlayedBattlecryQuery(kinds=(CardType.WEAPON,)))],[2])
        self.assertEqual(played_battlecry_candidates(g.state,1,PlayedBattlecryQuery(before_id=2,exclude_ids=(1,))),())
        self.assertEqual(played_battlecry_candidates(g.state,1,PlayedBattlecryQuery(turn=99)),());self.check(g)

    def test_weapon_and_hero_play_are_valid_borrowed_sources(self):
        self.card('weapon',kind=CardType.WEAPON);self.card('hero_card',kind=CardType.HERO,hero_card=True,initial_hero_power='power');self.macaw()
        g=self.game(hand=('weapon','macaw','hero_card','macaw'));self.play(g,'weapon');self.play(g,'macaw');self.play(g,'hero_card');self.play(g,'macaw')
        self.assertEqual(self.armor(g),8);self.assertEqual([b.payload.card_id for b in g.state.battlecry_history if b.origin=='played_history'],['weapon','hero_card']);self.check(g)

    def test_random_target_uses_original_domain_and_current_board(self):
        self.card('damage',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'));self.macaw()
        g=self.game(hand=('damage','macaw'),enemy=('body',));target=g.state.players[2].board[0]
        self.play(g,'damage',target);self.play(g,'macaw');self.assertEqual(g.state.entities[target].health,3);self.assertEqual(self.last(g).target_id,target);self.check(g)

    def test_missing_current_target_records_failed_repeat(self):
        self.card('damage',lambda c:[Damage(c.target_id,10,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'));self.macaw()
        g=self.game(hand=('damage','macaw'),enemy=('body',));self.play(g,'damage',g.state.players[2].board[0]);self.play(g,'macaw')
        self.assertEqual((self.last(g).failure,self.last(g).completed),('no_target',True));self.check(g)

    def test_targeted_direct_play_repeat_can_prescribe_a_new_target(self):
        self.card('damage',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.card('direct',lambda c:[RepeatPlayedBattlecry(1,c.source_id,1,c.state.players[2].board[1],'explicit')])
        g=self.game(hand=('damage','direct'),enemy=('body','body'));a,b=g.state.players[2].board;self.play(g,'damage',a);self.play(g,'direct')
        self.assertEqual((g.state.entities[a].health,g.state.entities[b].health),(4,4));self.check(g)

    def test_player_choice_inside_borrowed_play_restores_nested_closers(self):
        self.card('choose',lambda c:[self.pause(c),GainArmor(1,3)]);self.macaw(choices='player')
        g=self.game(hand=('choose','macaw'));self.play(g,'choose');self.choose(g);self.play(g,'macaw');self.check(g)
        saved=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(saved)
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g),6);self.check(g)

    def test_random_choice_replay_does_not_request_player_input(self):
        self.card('choose',lambda c:[self.pause(c),GainArmor(1,3)]);self.macaw()
        g=self.game(hand=('choose','macaw'));self.play(g,'choose');self.choose(g);self.play(g,'macaw')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.armor(g),6);self.check(g)

    def test_all_plays_sequence_is_frozen_across_pause(self):
        self.card('choose',lambda c:[self.pause(c),GainArmor(1,3)])
        self.card('all',lambda c:[RepeatPlayedBattlecries(1,c.source_id,selection='all',choices='player')])
        g=self.game(hand=('choose','cry','all'));self.play(g,'choose');self.choose(g);self.play(g);self.play(g,'all');self.check(g)
        self.choose(g);self.assertEqual(self.armor(g),10);self.assertEqual([b.history_play_id for b in g.state.battlecry_history if b.origin=='played_history'],[1,2]);self.check(g)

    def test_first_and_random_all_selection_are_deterministic(self):
        self.card('five',lambda c:[GainArmor(1,5)])
        self.card('first',lambda c:[RepeatPlayedBattlecries(1,c.source_id,selection='first')])
        self.card('all',lambda c:[RepeatPlayedBattlecries(1,c.source_id,PlayedBattlecryQuery(before_id=3),selection='all',order='random')])
        g=self.game(hand=('cry','five','first','all'));self.play(g);self.play(g,'five');self.play(g,'first');self.play(g,'all')
        self.assertEqual(self.armor(g),16);self.check(g)

    def test_current_carrier_morph_preserves_history_window_and_identity(self):
        self.card('macaw',lambda c:[Transform(c.source_id,'body'),RepeatPlayedBattlecries(1,c.source_id,
            PlayedBattlecryQuery(before_id=battlecry_play_window(c.state,c.battlecry)))])
        g=self.game(hand=('cry','macaw'));self.play(g);i=self.play(g,'macaw')
        self.assertEqual((g.state.entities[i].card_id,self.last(g).card_id),('body','macaw'));self.assertEqual(self.armor(g),4);self.check(g)

    def test_new_carrier_controller_does_not_change_execution_owner(self):
        self.card('macaw',lambda c:[ChangeControl(c.source_id,2),RepeatPlayedBattlecry(1,c.source_id,1)])
        g=self.game(hand=('cry','macaw'));self.play(g);self.play(g,'macaw');self.assertEqual((self.armor(g),self.armor(g,2)),(4,0));self.check(g)

    def test_borrowed_context_has_history_reference_but_no_original_play(self):
        self.card('context',lambda c:[GainArmor(1,2 if c.battlecry.origin=='hand' or c.play is None and c.battlecry.history_play_id==1 else 99)])
        self.macaw();g=self.game(hand=('context','macaw'));self.play(g,'context');self.play(g,'macaw');self.assertEqual(self.armor(g),4);self.check(g)

    def test_finite_policy_only_consumed_by_outer_play(self):
        self.script('grant',lambda c:[AddBattlecryRepeatModifier(1,BattlecryRepeatSpec(3),uses=1)]);self.macaw()
        g=self.game(hand=('cry','grant','macaw'));self.play(g);self.play(g,'grant');self.play(g,'macaw')
        self.assertEqual(self.armor(g),8);self.assertEqual(len([b for b in g.state.battlecry_history if b.origin=='played_history']),3)
        self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_manual_rewind_replaces_child_history_and_preserves_declaration(self):
        self.macaw(keywords=(Keyword.REWIND,),rewind=RewindSpec(1));g=self.game(hand=('cry','macaw'))
        self.play(g);self.play(g,'macaw');self.check(g);self.choose(g,'retry')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.play_history),2);self.assertEqual(len(g.state.battlecry_history),3);self.check(g)

    def test_retained_rewind_keeps_one_play_candidate_with_multiple_children(self):
        self.macaw(keywords=(Keyword.REWIND,),rewind=RewindSpec(1));g=self.game(hand=('cry','macaw'),board=('retainer',))
        self.play(g);self.play(g,'macaw');self.assertEqual(self.armor(g),6)
        self.assertEqual(len(played_battlecry_candidates(g.state,1)),2);self.assertEqual([b.history_play_id for b in g.state.battlecry_history if b.origin=='played_history'],[1,1]);self.check(g)

    def test_lethal_borrowed_body_interrupts_outer_battlecry(self):
        self.card('hurt',lambda c:[Damage(c.state.players[2].hero_id,20,c.source_id)]);self.macaw()
        g=self.game(hand=('hurt','macaw'));self.play(g,'hurt');self.play(g,'macaw')
        self.assertEqual(g.state.status,'finished');self.assertTrue(self.last(g).interrupted);self.assertTrue(g.state.battlecry_history[-2].interrupted);self.check(g)

    def test_error_after_pause_rolls_back_only_current_choice(self):
        self.r.register_behavior('later',lambda c:[Summon(1,'missing')] if c.battlecry.origin!='hand' else [])
        self.card('bad',lambda c:[self.pause(c),InvokeBehavior('later',c.source_id,1)]);self.macaw(choices='player')
        g=self.game(hand=('bad','macaw'));self.play(g,'bad');self.choose(g);self.play(g,'macaw');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.check(g)

    def test_foreign_or_pending_play_source_is_rejected_atomically(self):
        self.card('pending',lambda c:[RepeatPlayedBattlecry(1,c.source_id,1)])
        self.card('foreign',lambda c:[RepeatPlayedBattlecry(2,c.source_id,1)])
        g=self.game(hand=('pending',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'pending')
        self.assertEqual(g.snapshot(),s)
        g=self.game(hand=('cry','foreign'));self.play(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'foreign')
        self.assertEqual(g.snapshot(),s)

    def pending(self):
        self.card('wait',lambda c:[self.pause(c)]);self.macaw(choices='player');g=self.game(hand=('wait','macaw'))
        self.play(g,'wait');self.choose(g);self.play(g,'macaw');return g

    def test_restore_rejects_missing_played_declarations(self):
        g=self.pending();s=g.snapshot();del s['state']['play_history'][0]['battlecries'];self.reject(s)

    def test_restore_rejects_invalid_declaration_identity(self):
        g=self.pending();s=g.snapshot();s['state']['play_history'][0]['battlecries'][0]['ability_id']=999999;self.reject(s)

    def test_restore_rejects_duplicate_played_payload(self):
        g=self.pending();s=g.snapshot();s['state']['play_history'][0]['battlecries']*=2;self.reject(s)

    def test_restore_rejects_mismatched_declaration_behavior(self):
        g=self.pending();s=g.snapshot();s['state']['play_history'][0]['battlecries'][0]['behavior_id']='armor';self.reject(s)

    def test_restore_rejects_mismatched_history_play_source(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['history_play_id']=2;self.reject(s)

    def test_restore_rejects_two_different_history_origins(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['history_id']=1;self.reject(s)

    def test_restore_rejects_removed_history_play_reference(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['history_play_id']=None;self.reject(s)

    def test_restore_rejects_queued_repeat_of_pending_play(self):
        self.card('wait',lambda c:[self.pause(c)])
        self.card('all',lambda c:[RepeatPlayedBattlecries(1,c.source_id,selection='all',choices='player')])
        g=self.game(hand=('wait','cry','all'));self.play(g,'wait');self.choose(g);self.play(g);self.play(g,'all');s=g.snapshot()
        self.nested(s['resolution_frame'],'RepeatPlayedBattlecry')['fields']['play_id']=3;self.reject(s)

    def test_player_port_can_resume_borrowed_play(self):
        g=self.pending();p=g.for_player(1);listing=p.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
        self.assertTrue(p.submit({'revision':listing['revision'],'action':action})['accepted']);self.assertTrue(self.last(g).completed);self.check(g)

    def test_player_observation_hides_played_payload_and_history_link(self):
        g=self.pending()
        for p in (1,2):
            text=json.dumps((g.observe(p),g.player_events(p)))
            for name in ('history_play_id','play_history','behavior_id','battlecry_id'):self.assertNotIn(name,text)

    def test_invalid_query_policy_is_rejected(self):
        for kw in ({'countered':'unknown'},{'before_id':True},{'exclude_ids':(1,1)},{'kinds':()},
            {'kinds':(CardType.SPELL,)},{'kinds':('MINION',)},{'kinds':[CardType.MINION]}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):PlayedBattlecryQuery(**kw)

    def test_invalid_effect_and_window_are_rejected(self):
        for make in (lambda:RepeatPlayedBattlecry(1,1,0),lambda:RepeatPlayedBattlecry(1,1,1,target_id=2),
            lambda:RepeatPlayedBattlecries(1,1,selection='random'),lambda:RepeatPlayedBattlecries(1,1,query=None),
            lambda:battlecry_play_window(self.game().state,None)):
            with self.subTest(make=make),self.assertRaises(ValueError):make()


class MacawRepresentativeTests(unittest.TestCase):
    def test_brann_snapdragon_macaw_chain_buff_uses_one_play_per_history_candidate(self):
        from examples.battlecry_activations import submit
        r=build_registry();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',board=('LOE_077',),
            hand=('TID_710','DED_509','DED_509'),deck=('LOE_029','CS2_182'),mana=10,max_mana=10),PlayerSetup('HERO_01')),
            generation_context=GenerationContext('local-2026-09-23','experimental')),r)
        for cid in ('TID_710','DED_509','DED_509'):submit(g,'play_card',cid)
        cards=[g.state.entities[i] for i in g.state.players[1].deck]
        self.assertEqual([(c.attack,c.health) for c in cards],[(7,7),(4,5)])
        self.assertEqual((len(g.state.play_history),len(g.state.battlecry_history)),(3,12))
        self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot());self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot())

    def test_scarab_and_two_macaws_have_random_repeated_discoveries(self):
        from examples.battlecry_activations import submit
        r=build_registry();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('LOE_029','DED_509','DED_509'),mana=10,max_mana=10),
            PlayerSetup('HERO_01')),seed=81,generation_context=GenerationContext('local-2026-09-23','experimental')),r)
        submit(g,'play_card','LOE_029');saved=Game.from_snapshot(g.snapshot(),r)
        for match in (g,saved):
            submit(match,'select_choice');submit(match,'play_card','DED_509');submit(match,'play_card','DED_509')
            self.assertIsNone(match.state.pending_choice);self.assertEqual(len(match.state.players[1].hand),3)
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())

    def test_composed_starship_keeps_two_distinct_played_payloads(self):
        from hs_sim.engine.starships import construction
        r=build_registry();r.register_behavior('scrap',lambda c:[DamageBatch(tuple(Damage(i,100) for i in c.state.players[1].board))])
        r.register_behavior('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        for cid in ('scrap','bounce'):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('SC_405','SC_405'),hand=('scrap','bounce','DED_509'),
            deck=('CS2_182',)*6,mana=10,max_mana=10),PlayerSetup('HERO_08',deck=('CS2_182',)*6)),seed=81),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id))
        g.apply(PlayCard(1,g.state.players[1].hand[0]));g.apply(PlayCard(1,ship.id))
        g.apply(EndTurn(1));g.apply(EndTurn(2));macaw=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='DED_509')
        g.apply(PlayCard(1,macaw));play=g.state.play_history[-2]
        self.assertEqual(len(play.battlecries),2);self.assertEqual(len({b.ability_id for b in play.battlecries}),2)
        children=[b for b in g.state.battlecry_history if b.history_play_id==play.id]
        self.assertEqual([b.payload for b in children],list(play.battlecries))
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
