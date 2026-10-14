"""R-126 representative composition, not a certificate of CN Shudderwock rules."""
import json
import unittest
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, CardDefinition, CardType, Scenario, PlayerSetup, PlayCard, EndTurn,
    PlayedBattlecryQuery, RepeatPlayedBattlecries, battlecry_play_window, RepeatBattlecry,
    TriggerBattlecry, TargetSpec, TargetMode, BattlecryRepeatSpec, GenerationContext, ResolutionError,
    RewindSpec, Keyword)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Transform, Silence, ChangeControl,
    ReturnToHand, RequestChoice, ChoiceOption, AddToHand, InvokeBehavior, CopyMinion, Summon)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.representative import _shudderwock, _bolner_repeat, build_registry, CARD_LIMITATIONS
from hs_sim.engine.replay import build_replay,replay


class ShudderwockTests(unittest.TestCase):
    card=foundation.BattlecryTests.card
    script=foundation.BattlecryTests.script
    watch=foundation.BattlecryTests.watch
    game=foundation.BattlecryTests.game
    play=foundation.BattlecryTests.play
    choose=foundation.BattlecryTests.choose
    armor=foundation.BattlecryTests.armor
    check=foundation.BattlecryTests.check
    reject=foundation.BattlecryTests.reject
    nested=foundation.BattlecryTests.nested

    def setUp(self):
        foundation.BattlecryTests.setUp(self)
        self.r.register_behavior('m5.shudderwock',_shudderwock)
        self.r.register_card(CardDefinition('shudder','shudder',CardType.MINION,health=6,cost=2,battlecry='m5.shudderwock'))
        self.card('macaw',lambda c:[RepeatPlayedBattlecries(c.player_id,c.source_id,
            PlayedBattlecryQuery(before_id=battlecry_play_window(c.state,c.battlecry),countered='include'))])
    def pause(self,c):return RequestChoice(c.player_id,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def direct(self,g,parent):return [b for b in g.state.battlecry_history if b.parent_id==parent]
    def roots(self,g):return [b for b in g.state.battlecry_history if b.payload.behavior_id=='m5.shudderwock']
    def wait_child(self,fn=None):
        self.watch('wait','battlecry_started',lambda c: (fn(c) if fn else [self.pause(c)])
            if c.battlecry.origin=='played_history' else [])
    def pending(self):
        self.wait_child();g=self.game(hand=('cry','cry','shudder'),board=('wait',))
        self.play(g);self.play(g);self.play(g,'shudder');return g
    def drain(self,g):
        while g.state.pending_choice:self.choose(g)

    def test_empty_history_has_only_its_own_activation(self):
        g=self.game(hand=('shudder',));self.play(g,'shudder');self.assertEqual(len(g.state.battlecry_history),1);self.check(g)
    def test_all_played_declarations_without_duplicate_payments(self):
        g=self.game(hand=('cry','cry','shudder'));self.play(g);self.play(g);self.play(g,'shudder')
        self.assertEqual((self.armor(g),len(g.state.play_history),g.state.players[1].mana),(8,3,4))
        self.assertCountEqual([b.history_play_id for b in self.direct(g,3)],[1,2]);self.check(g)
    def test_excludes_all_own_declarations_including_another_carrier(self):
        self.r.register_card(CardDefinition('borrowed','borrowed',CardType.MINION,health=6,cost=0,battlecry='m5.shudderwock'))
        g=self.game(hand=('cry','shudder','borrowed','shudder'))
        for cid in ('cry','shudder','borrowed','shudder'):self.play(g,cid)
        self.assertEqual(len(self.roots(g)),3);self.assertEqual(self.armor(g),8);self.check(g)
    def test_normal_summons_and_plain_spells_are_not_history(self):
        self.script('create',lambda c:[AddToHand(1,'cry')]);g=self.game(hand=('create','shudder'),board=('cry',))
        self.play(g,'create');self.play(g,'shudder');self.assertEqual(len(g.state.battlecry_history),1);self.check(g)
    def test_brann_repeats_sequence_but_does_not_duplicate_candidates(self):
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        g=self.game(hand=('cry','shudder'),board=('brann',));self.play(g);self.play(g,'shudder')
        self.assertEqual(self.armor(g),8);self.assertEqual([len(self.direct(g,b.id)) for b in self.roots(g)],[1,1]);self.check(g)
    def test_original_window_mixed_shudder_macaw_shudder_terminates(self):
        g=self.game(hand=('cry','shudder','macaw','shudder'))
        for cid in ('cry','shudder','macaw','shudder'):self.play(g,cid)
        self.assertEqual(self.armor(g),10);self.assertEqual(len(g.state.battlecry_history),11)
        root=next(b for b in self.roots(g) if b.play_id==4)
        self.assertCountEqual([b.history_play_id for b in self.direct(g,root.id)],[1,3])
        self.assertTrue(all(b.completed for b in g.state.battlecry_history));self.check(g)
    def test_macaw_before_shudder_has_strictly_older_descendant_history(self):
        g=self.game(hand=('cry','macaw','shudder'));self.play(g);self.play(g,'macaw');self.play(g,'shudder')
        self.assertEqual(self.armor(g),8)
        for b in g.state.battlecry_history:
            if b.parent_id:
                parent=g.state.battlecry_history[b.parent_id-1]
                self.assertLess(b.history_play_id,battlecry_play_window(g.state,parent))
        self.check(g)
    def test_actual_history_copy_preserves_original_shudder_window(self):
        self.card('later',lambda c:[GainArmor(1,7)])
        self.script('actual',lambda c:[RepeatBattlecry(1,c.state.players[1].board[1],2)])
        g=self.game(hand=('cry','shudder','later','actual'))
        for cid in ('cry','shudder','later','actual'):self.play(g,cid)
        self.assertEqual(self.armor(g),13);root=self.roots(g)[-1]
        self.assertEqual((root.origin,root.history_id),('history',2));self.assertEqual([b.history_play_id for b in self.direct(g,root.id)],[1]);self.check(g)
    def test_physical_activation_uses_history_available_at_its_start(self):
        self.card('later',lambda c:[GainArmor(1,7)])
        self.script('actual',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[1]]),c.source_id)])
        g=self.game(hand=('cry','shudder','later','actual'))
        for cid in ('cry','shudder','later','actual'):self.play(g,cid)
        root=self.roots(g)[-1];self.assertEqual(root.origin,'effect')
        self.assertCountEqual([b.history_play_id for b in self.direct(g,root.id)],[1,3]);self.assertEqual(self.armor(g),20);self.check(g)
    def test_bolner_replays_first_shudder_without_new_play_event(self):
        self.watch('bolner','card_played',_bolner_repeat)
        g=self.game(hand=('cry','shudder','macaw'),board=('bolner',));self.play(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'shudder');self.play(g,'macaw')
        self.assertEqual(self.armor(g),12);self.assertEqual(len(g.state.play_history),3)
        self.assertEqual(sum(e.kind=='card_played' for e in g.events),3);self.check(g)
    def test_original_discover_is_manual_and_replay_choice_is_automatic(self):
        self.card('choice',lambda c:[self.pause(c),GainArmor(c.player_id,3)])
        g=self.game(hand=('choice','shudder'));self.play(g,'choice');self.choose(g);self.play(g,'shudder')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.armor(g),6)
        self.assertEqual(sum(e.kind=='battlecry_choice_randomized' for e in g.events),1);self.check(g)
    def test_pause_in_started_listener_restores_frozen_sequence_and_rng(self):
        g=self.pending();self.check(g);saved=Game.from_snapshot(g.snapshot(),self.r)
        self.drain(g);self.drain(saved);self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g),8);self.check(g)
    def test_player_port_can_finish_paused_listener(self):
        g=self.pending()
        while g.state.pending_choice:
            port=g.for_player(g.state.pending_choice.player_id);actions=port.legal_actions()
            action=next(a for a in actions['actions'] if a['type']=='select_choice')
            self.assertTrue(port.submit({'revision':actions['revision'],'action':action})['accepted'])
        self.assertEqual(self.armor(g),8);self.check(g)
    def test_private_view_hides_history_plan_and_source_ids(self):
        g=self.pending()
        for p in (1,2):
            text=json.dumps((g.observe(p),g.player_events(p)))
            for field in ('history_player_id','history_play_id','ContinueBattlecrySequence','exclude_behaviors','source_epoch'):
                self.assertNotIn(field,text)
        self.assertEqual(g.for_player(2).observe()['observation']['pending_choice'],{'player_id':1})
    def test_source_killed_after_child_acceptance_finishes_child_and_stops(self):
        self.wait_child(lambda c:[Destroy(c.event.source_id)])
        g=self.game(hand=('cry','cry','shudder'),board=('wait',));self.play(g);self.play(g);self.play(g,'shudder')
        self.assertEqual(self.armor(g),6);self.assertEqual(len(self.direct(g,3)),1);self.check(g)
    def test_bounce_morph_and_dormancy_stop_later_attempts(self):
        operations=(ReturnToHand,lambda i:Transform(i,'body'),lambda i:Transform(i,'shudder'),lambda i:MakeDormant(i,2))
        for n,op in enumerate(operations):
            self.watch('watch'+str(n),'battlecry_started',lambda c,op=op:[op(c.event.source_id)] if c.battlecry.origin=='played_history' else [])
        for n in range(len(operations)):
            g=self.game(hand=('cry','cry','shudder'),board=('watch'+str(n),));self.play(g);self.play(g);self.play(g,'shudder')
            self.assertEqual(len(self.direct(g,3)),1);self.assertEqual(self.armor(g),6);self.check(g)
    def test_silence_does_not_cancel_accepted_shudder_sequence(self):
        self.wait_child(lambda c:[Silence(c.event.source_id)])
        g=self.game(hand=('cry','cry','shudder'),board=('wait',));self.play(g);self.play(g);self.play(g,'shudder')
        self.assertEqual(len(self.direct(g,3)),2);self.assertEqual(self.armor(g),8);self.check(g)
    def test_transfer_keeps_original_candidates_and_follows_new_executor(self):
        self.wait_child(lambda c:[ChangeControl(c.event.source_id,2)])
        g=self.game(hand=('cry','cry','shudder'),board=('wait',));self.play(g);self.play(g);self.play(g,'shudder')
        self.assertEqual((self.armor(g),self.armor(g,2)),(6,2))
        self.assertEqual([(b.player_id,b.history_player_id) for b in self.direct(g,3)],[(1,1),(2,1)]);self.check(g)
    def test_direct_target_excludes_the_only_remaining_carrier(self):
        self.card('aim',lambda c:[GainArmor(c.player_id,1)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='friendly',exclude_source=False))
        self.script('clear',lambda c:[Destroy(i) for i in c.state.players[1].board])
        g=self.game(hand=('aim','clear','shudder'),board=('body',));self.play(g,'aim',g.state.players[1].board[0]);self.play(g,'clear');self.play(g,'shudder')
        self.assertEqual(self.direct(g,2)[0].failure,'no_target');self.assertEqual(self.armor(g),1);self.check(g)
    def test_no_target_is_counted_without_refill(self):
        self.card('aim',lambda c:[Damage(c.target_id,9,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(hand=('aim','shudder'),enemy=('body',));self.play(g,'aim',g.state.players[2].board[0]);self.play(g,'shudder')
        b=self.direct(g,2)[0];self.assertEqual((b.failure,b.completed,b.payload_started),('no_target',True,False));self.check(g)
    def test_optional_target_absence_still_runs_untargeted_body(self):
        self.card('optional',lambda c:[GainArmor(c.player_id,3)],targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(hand=('optional','shudder'));self.play(g,'optional');self.play(g,'shudder')
        self.assertEqual(self.armor(g),6);self.assertIsNone(self.direct(g,2)[0].target_id);self.check(g)
    def test_callback_condition_is_recomputed_at_replay_time(self):
        self.card('condition',lambda c:[GainArmor(c.player_id,7)] if len(c.state.players[c.player_id].board)>=2 else [])
        g=self.game(hand=('condition','shudder'));self.play(g,'condition');self.assertEqual(self.armor(g),0)
        self.play(g,'shudder');self.assertEqual(self.armor(g),7);self.check(g)
    def test_countered_declaration_is_provisionally_included(self):
        import test_m5_minion_counters as counters
        self.secret=counters.MinionCounterTests.secret.__get__(self);counters.MinionCounterTests.setUp(self)
        self.r.register_behavior('m5.shudderwock',_shudderwock)
        self.r.register_card(CardDefinition('shudder','shudder',CardType.MINION,health=6,battlecry='m5.shudderwock'))
        g=self.game(hand=('arm','cry','shudder'));self.play(g,'arm');self.play(g);self.play(g,'shudder')
        self.assertTrue(g.state.play_history[1].countered);self.assertEqual(self.armor(g),2);self.check(g)
    def test_opponents_and_noncompleted_plays_are_excluded(self):
        g=self.game(hand=('cry','shudder'));g.apply(EndTurn(1));g.apply(PlayCard(2,g.state.players[2].hand[0]));g.apply(EndTurn(2))
        self.play(g);self.play(g,'shudder');root=self.roots(g)[0]
        self.assertEqual([b.history_play_id for b in self.direct(g,root.id)],[2]);self.check(g)
    def test_engine_overflow_remains_transaction_error(self):
        g=self.game(hand=('cry','shudder'));self.play(g);g.ruleset=replace(g.ruleset,max_resolution_steps=1);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'shudder')
        self.assertEqual(g.snapshot(),s)
    def test_error_after_random_schedule_rolls_back_rng_and_play(self):
        self.card('fail',lambda c:[InvokeBehavior('missing')] if c.battlecry.origin=='played_history' else [])
        g=self.game(hand=('cry','fail','shudder'));self.play(g);self.play(g,'fail');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'shudder')
        self.assertEqual(g.snapshot(),s)
    def test_restore_rejects_tampered_source_policy(self):
        g=self.pending();s=g.snapshot();f=self.nested(s['resolution_frame'],'ContinueBattlecrySequence')['fields']
        f['spec']['fields']['policy']['fields']['controller']='captured';self.reject(s)
    def test_restore_rejects_shortened_schedule(self):
        g=self.pending();s=g.snapshot();f=self.nested(s['resolution_frame'],'ContinueBattlecrySequence')['fields']
        f['order']['tuple']=f['order']['tuple'][:-1];self.reject(s)
    def test_exact_thirty_cap_and_distinct_original_play_ids(self):
        def tick(c):
            return [GainArmor(c.player_id,1)]+([Destroy(c.source_id),AddToHand(c.player_id,'tick')] if c.battlecry.origin=='hand' else [])
        self.r.register_behavior('tick',tick);self.r.register_card(CardDefinition('tick','tick',CardType.MINION,health=1,battlecry='tick'))
        g=self.game(hand=('tick','shudder'))
        for _ in range(35):self.play(g,'tick')
        self.play(g,'shudder');children=self.direct(g,self.roots(g)[0].id)
        self.assertEqual((len(children),len({b.history_play_id for b in children}),self.armor(g)),(30,30,65))
        self.assertTrue(all(b.completed for b in children));self.check(g)
    def test_real_adapter_pins_data_and_exposes_experimental_limitations(self):
        r=build_registry();d=r.card('GIL_820')
        self.assertEqual((d.cost,d.attack,d.health,d.battlecry),(9,6,6,'m5.shudderwock'))
        self.assertEqual(r.version,'representative-m5-v64');self.assertIn('R-126',CARD_LIMITATIONS['GIL_820'])
    def test_other_same_card_entity_is_a_legal_target(self):
        self.card('aim',lambda c:[GainArmor(c.player_id,1)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='friendly',exclude_source=False))
        self.script('clear',lambda c:[Destroy(i) for i in c.state.players[1].board]+[Summon(1,'shudder')])
        g=self.game(hand=('aim','clear','shudder'),board=('body',));self.play(g,'aim',g.state.players[1].board[0]);self.play(g,'clear')
        other=g.state.players[1].board[0];carrier=self.play(g,'shudder');b=self.direct(g,2)[0]
        self.assertEqual(b.target_id,other);self.assertNotEqual(b.target_id,carrier);self.assertEqual(self.armor(g),2);self.check(g)
    def test_weapon_and_hero_declarations_share_the_sequence(self):
        self.card('weapon',kind=CardType.WEAPON);self.card('newhero',kind=CardType.HERO,hero_card=True,initial_hero_power='power')
        g=self.game(hand=('weapon','newhero','shudder'));self.play(g,'weapon');self.play(g,'newhero');self.play(g,'shudder')
        self.assertCountEqual([b.payload.card_id for b in self.direct(g,3)],['weapon','newhero']);self.assertEqual(self.armor(g),8);self.check(g)
    def test_nested_shudder_in_macaw_restores_multiple_sequence_closers(self):
        self.wait_child();g=self.game(hand=('cry','shudder','macaw','shudder'),board=('wait',))
        reached_nested=False
        for cid in ('cry','shudder','macaw','shudder'):
            self.play(g,cid)
            while g.state.pending_choice:
                s=g.snapshot();self.check(g)
                if json.dumps(s['resolution_frame']).count('FinishSequenceAttempt')>=2:
                    reached_nested=True;restored=Game.from_snapshot(s,self.r)
                    self.drain(restored);self.drain(g);self.assertEqual(g.snapshot(),restored.snapshot())
                else:self.choose(g)
        self.assertTrue(reached_nested);self.assertEqual(self.armor(g),10);self.check(g)
    def test_terminal_child_interrupts_sequence_without_synthetic_draw(self):
        self.card('lethal',lambda c:[Damage(c.state.players[2].hero_id,40,c.source_id)] if c.battlecry.origin=='played_history' else [])
        g=self.game(hand=('lethal','cry','shudder'));self.play(g,'lethal');self.play(g);self.play(g,'shudder')
        self.assertEqual(g.state.winner,1);self.assertTrue(self.roots(g)[0].interrupted);self.check(g)
    def test_rewind_replaces_previous_random_attempt_and_history(self):
        self.r.register_card(CardDefinition('rewinder','rewinder',CardType.MINION,health=6,cost=2,battlecry='m5.shudderwock',keywords=(Keyword.REWIND,),rewind=RewindSpec()))
        g=self.game(hand=('cry','rewinder'));self.play(g);self.play(g,'rewinder')
        self.assertEqual(self.armor(g),4);self.choose(g,'retry');self.assertEqual(self.armor(g),4)
        self.assertEqual(len(self.roots(g)),1);self.assertEqual(len(g.state.play_history),2);self.check(g)
    def test_retained_rewind_results_get_separate_bounded_sequences(self):
        self.r.register_card(CardDefinition('rewinder','rewinder',CardType.MINION,health=6,cost=2,battlecry='m5.shudderwock',keywords=(Keyword.REWIND,),rewind=RewindSpec()))
        g=self.game(hand=('cry','rewinder'),board=('retainer',));self.play(g);self.play(g,'rewinder')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.armor(g),6);self.assertEqual([len(self.direct(g,b.id)) for b in self.roots(g)],[1,1]);self.check(g)
    def test_borrowed_self_copy_uses_present_carrier_and_does_not_add_play(self):
        self.card('copy',lambda c:[CopyMinion(c.source_id,c.player_id)])
        g=self.game(hand=('copy','shudder'));self.play(g,'copy');self.play(g,'shudder')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['copy','copy','shudder','shudder'])
        self.assertEqual(len(g.state.play_history),2);self.check(g)
    def test_real_representative_example_replays(self):
        from examples.shudderwock_history import run
        g,s=run();self.assertEqual(replay(build_replay(g),build_registry()).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
