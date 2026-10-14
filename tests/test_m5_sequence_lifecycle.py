"""Accepted history ownership and per-attempt carrier/controller policies."""
import json
import unittest
from dataclasses import replace
import test_m5_battlecry_sequences as sequences
from hs_sim.engine import (Game, CardDefinition, CardType, PlayCard, EndTurn, BattlecrySequencePolicy,
    RepeatPlayedBattlecrySequence, PlayedBattlecryQuery, PlayedBattlecryFilter, RepeatBattlecry,
    BattlecryHistoryQuery, battlecry_history_candidates, TargetSpec, TargetMode, ResolutionError,
    TriggerBattlecry, RewindSpec, Keyword, BattlecryRepeatSpec)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Transform, ChangeControl, ReturnToHand,
    Silence, Summon, RequestChoice, ChoiceOption, InvokeBehavior, CopyMinion, EquipWeapon, ModifyWeapon, ReplaceHero)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.replay import build_replay,replay


class SequenceLifecycleTests(unittest.TestCase):
    setUp=sequences.BattlecrySequenceTests.setUp
    card=sequences.BattlecrySequenceTests.card
    script=sequences.BattlecrySequenceTests.script
    watch=sequences.BattlecrySequenceTests.watch
    game=sequences.BattlecrySequenceTests.game
    play=sequences.BattlecrySequenceTests.play
    choose=sequences.BattlecrySequenceTests.choose
    armor=sequences.BattlecrySequenceTests.armor
    check=sequences.BattlecrySequenceTests.check
    reject=sequences.BattlecrySequenceTests.reject
    nested=sequences.BattlecrySequenceTests.nested
    sequence=sequences.BattlecrySequenceTests.sequence
    children=sequences.BattlecrySequenceTests.children
    fields=sequences.BattlecrySequenceTests.fields

    def pause(self,c):return RequestChoice(c.player_id,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def mutation(self,name,fn):self.card(name,lambda c:fn(c) if c.battlecry.origin!='hand' else [])
    def scene(self,mutation='change',**game_args):
        g=self.game(hand=(mutation,'cry','sequence'),**game_args)
        self.play(g,mutation);self.play(g);self.play(g,'sequence');return g
    def pending(self,policy=BattlecrySequencePolicy('same_incarnation','current')):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.card('wait',lambda c:[self.pause(c),GainArmor(c.player_id,3)])
        self.sequence(choices='player',policy=policy)
        g=self.game(hand=('change','wait','sequence'));self.play(g,'change');self.play(g,'wait');self.choose(g);self.play(g,'sequence')
        self.assertEqual(g.state.pending_choice.player_id,2 if policy.controller=='current' else 1);return g

    def test_current_controller_executes_next_payload_without_changing_history_owner(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.sequence(policy=BattlecrySequencePolicy('same_incarnation','current'));g=self.scene()
        self.assertEqual((self.armor(g),self.armor(g,2)),(2,2))
        self.assertEqual([(b.player_id,b.history_player_id,b.history_play_id) for b in self.children(g)],[(1,1,1),(2,1,2)]);self.check(g)

    def test_default_policy_keeps_original_execution_player(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)]);self.sequence();g=self.scene()
        self.assertEqual((self.armor(g),self.armor(g,2)),(4,0));self.check(g)

    def test_current_controller_does_not_resample_opponents_history(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.sequence(policy=BattlecrySequencePolicy(controller='current'))
        g=self.game(hand=('change','cry','sequence'));g.apply(EndTurn(1));g.apply(PlayCard(2,g.state.players[2].hand[0]));g.apply(EndTurn(2))
        self.play(g,'change');self.play(g);self.play(g,'sequence')
        self.assertEqual([b.history_play_id for b in self.children(g)],[2,3]);self.assertEqual(self.armor(g,2),4);self.check(g)

    def test_controller_can_change_back_between_attempts(self):
        self.mutation('flip',lambda c:[ChangeControl(c.source_id,3-c.player_id)])
        self.sequence(limit=3,policy=BattlecrySequencePolicy('same_incarnation','current'))
        g=self.game(hand=('flip','flip','cry','sequence'));self.play(g,'flip');self.play(g,'flip');self.play(g);self.play(g,'sequence')
        self.assertEqual([b.player_id for b in self.children(g)],[1,2,1]);self.assertEqual(self.armor(g),4);self.check(g)

    def test_payload_already_started_keeps_captured_player_after_transfer(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2),GainArmor(c.player_id,5)])
        self.sequence(policy=BattlecrySequencePolicy(controller='current'));g=self.scene()
        self.assertEqual((self.armor(g),self.armor(g,2)),(7,2));self.check(g)

    def test_child_start_listener_transfer_only_changes_following_attempt(self):
        self.watch('steal','battlecry_started',lambda c:[ChangeControl(c.event.source_id,2)] if dict(c.event.data)['battlecry_id']==4 else [])
        self.sequence(policy=BattlecrySequencePolicy(controller='current'))
        g=self.game(hand=('cry','cry','sequence'),board=('steal',));self.play(g);self.play(g);self.play(g,'sequence')
        self.assertEqual([b.player_id for b in self.children(g)],[1,2]);self.assertEqual((self.armor(g),self.armor(g,2)),(6,2));self.check(g)

    def test_transferred_payload_is_actual_activation_history_of_its_executor(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.sequence(policy=BattlecrySequencePolicy(controller='current'))
        self.script('again',lambda c:[RepeatBattlecry(2,c.state.players[2].board[0],c.state.battlecry_history[-1].id)])
        g=self.game(hand=('change','cry','sequence','again'));self.play(g,'change');self.play(g);self.play(g,'sequence')
        actual=battlecry_history_candidates(g.state,2,BattlecryHistoryQuery(origins=('played_history',)))
        self.assertEqual(len(actual),1);self.assertEqual(actual[0].history_player_id,1)
        self.play(g,'again');b=g.state.battlecry_history[-1]
        self.assertEqual((b.origin,b.player_id,b.history_player_id),('history',2,2));self.assertEqual(self.armor(g,2),4);self.check(g)

    def test_transferred_choice_belongs_to_new_executor_and_restores(self):
        g=self.pending();self.check(g);saved=Game.from_snapshot(g.snapshot(),self.r)
        self.assertEqual(g.for_player(1).observe()['observation']['pending_choice'],{'player_id':2})
        for match in (g,saved):
            port=match.for_player(2);listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
            self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g,2),3);self.check(g)

    def test_automatic_choice_uses_active_transferred_child(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.card('wait',lambda c:[self.pause(c),GainArmor(c.player_id,3)])
        self.sequence(policy=BattlecrySequencePolicy(controller='current'))
        g=self.game(hand=('change','wait','sequence'));self.play(g,'change');self.play(g,'wait');self.choose(g);self.play(g,'sequence')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.armor(g,2),3);self.check(g)

    def test_enemy_target_domain_tracks_each_new_executor(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.card('hurt',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec(kinds=(CardType.HERO,),relation='enemy'))
        self.sequence(policy=BattlecrySequencePolicy(controller='current'))
        g=self.game(hand=('change','hurt','sequence'));self.play(g,'change');self.play(g,'hurt',g.state.players[2].hero_id);self.play(g,'sequence')
        self.assertEqual(self.children(g)[-1].target_id,g.state.players[1].hero_id);self.check(g)

    def test_guarded_source_death_stops_after_current_payload(self):
        self.mutation('change',lambda c:[Destroy(c.source_id),GainArmor(1,5)])
        self.sequence(policy=BattlecrySequencePolicy(source='in_play'));g=self.scene()
        self.assertEqual((len(self.children(g)),self.armor(g)),(1,7));self.check(g)

    def test_guarded_bounce_stops_remaining_payloads(self):
        self.mutation('change',lambda c:[ReturnToHand(c.source_id)])
        self.sequence(policy=BattlecrySequencePolicy(source='same_incarnation'));g=self.scene()
        self.assertEqual((len(self.children(g)),self.armor(g)),(1,2));self.check(g)

    def test_same_incarnation_stops_even_when_transformed_to_same_card(self):
        self.mutation('change',lambda c:[Transform(c.source_id,'sequence')])
        self.sequence(policy=BattlecrySequencePolicy(source='same_incarnation'));g=self.scene()
        self.assertEqual(len(self.children(g)),1);self.check(g)

    def test_in_play_policy_allows_morph_but_retains_captured_ability_identity(self):
        self.mutation('change',lambda c:[Transform(c.source_id,'body')])
        self.sequence(policy=BattlecrySequencePolicy(source='in_play'));g=self.scene()
        self.assertEqual(len(self.children(g)),2);self.assertTrue(all(b.card_id=='sequence' for b in self.children(g)));self.check(g)

    def test_dormant_carrier_stops_guarded_sequence(self):
        self.mutation('change',lambda c:[MakeDormant(c.source_id,2)])
        self.sequence(policy=BattlecrySequencePolicy(source='in_play'));g=self.scene()
        self.assertEqual(len(self.children(g)),1);self.assertEqual(self.armor(g),2);self.check(g)

    def test_temporary_dormancy_within_payload_is_checked_at_next_attempt(self):
        self.mutation('change',lambda c:[MakeDormant(c.source_id,2),AwakenMinion(c.source_id)])
        self.sequence(policy=BattlecrySequencePolicy(source='same_incarnation'));g=self.scene()
        self.assertEqual(len(self.children(g)),2);self.assertEqual(self.armor(g),4);self.check(g)

    def test_silence_stop_is_explicit_and_independent_of_presence(self):
        self.mutation('change',lambda c:[Silence(c.source_id)])
        self.sequence('stops',policy=BattlecrySequencePolicy(stop_on_silence=True))
        self.sequence('continues',policy=BattlecrySequencePolicy(source='same_incarnation'))
        for name,count in (('stops',1),('continues',2)):
            g=self.game(hand=('change','cry',name));self.play(g,'change');self.play(g);self.play(g,name)
            self.assertEqual(len(self.children(g)),count);self.check(g)

    def test_guard_does_not_cancel_payload_accepted_before_start_listener_death(self):
        self.watch('kill','battlecry_started',lambda c:[Destroy(c.event.source_id)] if dict(c.event.data)['battlecry_id']==4 else [])
        self.sequence(policy=BattlecrySequencePolicy(source='same_incarnation'))
        g=self.game(hand=('cry','cry','sequence'),board=('kill',));self.play(g);self.play(g);self.play(g,'sequence')
        self.assertEqual((len(self.children(g)),self.armor(g)),(1,6));self.check(g)

    def test_guarded_carrier_already_out_of_play_does_not_draw_random_order(self):
        self.card('sequence',lambda c:[ReturnToHand(c.source_id),RepeatPlayedBattlecrySequence(1,c.source_id,2,
            order='random',policy=BattlecrySequencePolicy(source='in_play'))])
        g=self.game(hand=('cry','cry','sequence'));self.play(g);self.play(g);rng=g._rng.getstate();self.play(g,'sequence')
        self.assertFalse(self.children(g));self.assertEqual(g._rng.getstate(),rng);self.check(g)

    def test_captured_policy_continues_after_dormancy(self):
        self.mutation('change',lambda c:[MakeDormant(c.source_id,2)]);self.sequence();g=self.scene()
        self.assertEqual((len(self.children(g)),self.armor(g)),(2,4));self.check(g)

    def test_excluded_source_is_no_target_when_only_friendly_minion_remains(self):
        self.card('target',lambda c:[Destroy(c.source_id),Destroy(c.target_id)] if c.battlecry.origin=='hand' else [GainArmor(1,9)],
            targeting=TargetSpec(kinds=(CardType.MINION,),relation='friendly',exclude_source=False))
        self.sequence(limit=1,policy=BattlecrySequencePolicy(exclude_source_target=True))
        g=self.game(hand=('target','sequence'),board=('body',));target=g.state.players[1].board[0]
        self.play(g,'target',target);self.play(g,'sequence')
        self.assertEqual(self.children(g)[0].failure,'no_target');self.assertEqual(self.armor(g),0);self.check(g)

    def test_target_exclusion_does_not_exclude_separate_copy(self):
        self.card('target',lambda c:[GainArmor(1,1)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='friendly',exclude_source=False))
        self.card('sequence',lambda c:[CopyMinion(c.source_id,1),RepeatPlayedBattlecrySequence(1,c.source_id,1,
            policy=BattlecrySequencePolicy(exclude_source_target=True))])
        self.script('kill',lambda c:[Destroy(i) for i in c.state.players[1].board])
        g=self.game(hand=('target','kill','sequence'),board=('body',));self.play(g,'target',g.state.players[1].board[0]);self.play(g,'kill');source=self.play(g,'sequence')
        b=self.children(g)[0];self.assertNotEqual(b.target_id,source);self.assertEqual(g.state.entities[b.target_id].card_id,'sequence');self.check(g)

    def test_source_target_remains_allowed_under_default_policy(self):
        self.card('target',lambda c:[Destroy(c.source_id),Destroy(c.target_id)] if c.battlecry.origin=='hand' else [GainArmor(1,9)],
            targeting=TargetSpec(kinds=(CardType.MINION,),relation='friendly',exclude_source=False))
        self.sequence(limit=1);g=self.game(hand=('target','sequence'),board=('body',));self.play(g,'target',g.state.players[1].board[0]);source=self.play(g,'sequence')
        self.assertEqual(self.children(g)[0].target_id,source);self.assertEqual(self.armor(g),9);self.check(g)

    def test_invalid_policy_values_are_rejected(self):
        for kw in ({'source':'alive'},{'controller':'opponent'},{'stop_on_silence':1},{'exclude_source_target':'yes'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):BattlecrySequencePolicy(**kw)
        with self.assertRaises(ValueError):RepeatPlayedBattlecrySequence(1,1,20,policy=None)

    def test_restore_rejects_missing_or_wrong_history_owner(self):
        g=self.pending()
        for owner in (None,2,True):
            s=g.snapshot();s['state']['battlecry_history'][-1]['history_player_id']=owner;self.reject(s)
        s=g.snapshot();del s['state']['battlecry_history'][-1]['history_player_id'];self.reject(s)

    def test_restore_rejects_controller_policy_mismatch(self):
        g=self.pending();s=g.snapshot();self.fields(s)['spec']['fields']['policy']['fields']['controller']='captured';self.reject(s)

    def test_restore_rejects_history_owner_on_nonhistorical_activation(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][0]['history_player_id']=1;self.reject(s)

    def test_restore_rejects_missing_future_and_boolean_incarnation(self):
        g=self.pending()
        for epoch in (None,9999,True):
            s=g.snapshot();self.fields(s)['source_epoch']=epoch;self.reject(s)

    def test_restore_rejects_epoch_on_unguarded_sequence(self):
        g=self.pending(BattlecrySequencePolicy(controller='current'));s=g.snapshot();self.fields(s)['source_epoch']=0;self.reject(s)

    def test_restore_rejects_changed_target_exclusion_policy(self):
        g=self.pending();s=g.snapshot();self.fields(s)['spec']['fields']['policy']['fields']['exclude_source_target']=True;self.reject(s)

    def test_restore_after_guard_becomes_false_keeps_valid_pending_payload(self):
        self.mutation('change',lambda c:[ReturnToHand(c.source_id),self.pause(c),GainArmor(1,3)])
        self.sequence(choices='player',policy=BattlecrySequencePolicy(source='same_incarnation'));g=self.scene()
        self.assertIsNotNone(g.state.pending_choice);self.check(g);saved=Game.from_snapshot(g.snapshot(),self.r)
        self.choose(g);self.choose(saved);self.assertEqual(g.snapshot(),saved.snapshot())
        self.assertEqual(len(self.children(g)),1);self.assertEqual(self.armor(g),5);self.check(g)

    def test_post_transfer_resume_failure_rolls_back_to_second_players_choice(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.r.register_behavior('bad',lambda c:[Summon(2,'missing')] if c.battlecry.origin!='hand' else [])
        self.card('wait',lambda c:[self.pause(c),InvokeBehavior('bad',c.source_id,c.player_id)])
        self.sequence(choices='player',policy=BattlecrySequencePolicy(controller='current'))
        g=self.game(hand=('change','wait','sequence'));self.play(g,'change');self.play(g,'wait');self.choose(g);self.play(g,'sequence');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.check(g)

    def test_private_views_do_not_expose_history_owner_or_internal_policies(self):
        g=self.pending()
        for player in (1,2):
            text=json.dumps((g.observe(player),g.player_events(player)))
            for name in ('history_player_id','controller_policy','source_epoch','BattlecrySequencePolicy','history_play_id'):
                self.assertNotIn(name,text)

    def test_weapon_carrier_break_stops_guarded_sequence(self):
        self.mutation('change',lambda c:[ModifyWeapon(c.source_id,durability=-10)])
        self.sequence(policy=BattlecrySequencePolicy(source='in_play'),card_options={'kind':CardType.WEAPON})
        g=self.scene();self.assertEqual(len(self.children(g)),1);self.assertIsNone(g.state.players[1].weapon_id);self.check(g)

    def test_hero_replacement_stops_same_incarnation_sequence(self):
        self.mutation('change',lambda c:[ReplaceHero(1,'hero',hero_power_card_id='power')])
        self.sequence(policy=BattlecrySequencePolicy(source='same_incarnation'),
            card_options={'kind':CardType.HERO,'hero_card':True,'initial_hero_power':'power'})
        g=self.scene();self.assertEqual(len(self.children(g)),1);self.check(g)

    def test_brann_parent_iterations_recheck_source_presence(self):
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        self.mutation('change',lambda c:[ReturnToHand(c.source_id)])
        self.sequence(policy=BattlecrySequencePolicy(source='in_play'));g=self.scene(board=('brann',))
        self.assertEqual(len(self.children(g)),1);self.assertEqual(len([b for b in g.state.battlecry_history if b.card_id=='sequence' and b.origin=='hand']),2);self.check(g)

    def test_manual_rewind_restores_control_and_regenerates_source_owner_records(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.sequence(policy=BattlecrySequencePolicy(controller='current'),card_options={'keywords':(Keyword.REWIND,),'rewind':RewindSpec(1)})
        g=self.scene();self.check(g);self.choose(g,'retry');self.check(g)
        self.assertEqual([(b.player_id,b.history_player_id) for b in self.children(g)],[(1,1),(2,1)])
        self.assertEqual(self.armor(g,2),2)

    def test_retained_rewind_rechecks_controller_with_original_history_owner(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.sequence(policy=BattlecrySequencePolicy(controller='current'),card_options={'keywords':(Keyword.REWIND,),'rewind':RewindSpec(1)})
        g=self.scene(board=('retainer',));self.assertEqual(len(self.children(g)),4)
        self.assertEqual([b.player_id for b in self.children(g)],[1,2,2,2]);self.assertEqual(self.armor(g,2),4);self.check(g)

    def test_nested_sequence_queries_history_for_its_own_captured_executor(self):
        self.mutation('change',lambda c:[ChangeControl(c.source_id,2)])
        self.sequence('inner',limit=1,query=PlayedBattlecryQuery(before_id=2))
        self.sequence('sequence',policy=BattlecrySequencePolicy(controller='current'))
        g=self.game(hand=('change','inner','sequence'));self.play(g,'change');self.play(g,'inner');self.play(g,'sequence')
        # The transferred inner payload executes for P2, who has no played history.
        self.assertEqual([b.history_play_id for b in self.children(g)],[1,1,2]);self.check(g)

    def test_optional_target_runs_without_source_when_exclusion_empties_domain(self):
        self.card('target',lambda c:[Destroy(c.source_id)] if c.battlecry.origin=='hand' else [GainArmor(1,9)],
            targeting=TargetSpec(mode=TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='friendly',exclude_source=False))
        self.sequence(limit=1,policy=BattlecrySequencePolicy(exclude_source_target=True))
        g=self.game(hand=('target','sequence'));self.play(g,'target');self.play(g,'sequence')
        b=self.children(g)[0];self.assertIsNone(b.target_id);self.assertIsNone(b.failure);self.assertEqual(self.armor(g),9);self.check(g)

    def test_restore_rejects_missing_new_execution_policy_fields(self):
        g=self.pending()
        for key in ('controller_policy','exclude_source_target'):
            s=g.snapshot();del s['state']['battlecry_history'][-1][key];self.reject(s)

    def test_restore_rejects_self_target_when_exclusion_was_captured(self):
        g=self.pending();s=g.snapshot();b=s['state']['battlecry_history'][-1]
        b['exclude_source_target']=True;b['target_id']=b['source_id'];self.reject(s)

    def test_restore_rejects_foreign_execution_without_explicit_controller_policy(self):
        g=self.pending();s=g.snapshot();s['state']['battlecry_history'][-1]['controller_policy']='captured';self.reject(s)

    def test_combined_player_transfer_choice_bounce_example(self):
        from examples.battlecry_source_lifecycle import run
        g,s=run();self.assertEqual(len(g.history),6);self.assertEqual(len(g.state.battlecry_history),8)
        self.assertEqual(s['schema_version'],265)

    def test_previous_snapshot_schema_is_rejected(self):
        g=self.pending();s=g.snapshot();self.assertEqual(s['schema_version'],265);s['schema_version']=80;self.reject(s)


if __name__=='__main__':unittest.main()
