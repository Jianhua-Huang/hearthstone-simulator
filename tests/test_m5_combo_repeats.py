"""Combo repetition and distinct commitment/activation policies, provisional R-128."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest
from copy import deepcopy
from dataclasses import replace
import test_m5_combo_activations as foundation
from hs_sim.engine import (Game,CardDefinition,CardType,Keyword,Scenario,PlayerSetup,PlayCard,UseHeroPower,
    EndTurn,SelectChoice,ComboRepeatSpec,ComboRepeatPlan,AddComboRepeatModifier,RemoveComboRepeatModifier,
    GrantComboRepeatAura,BattlecryRepeatSpec,RewindSpec,AppendageSpec,TargetSpec,CounterMinion,
    ResolutionError,ResolutionLimitExceeded,IllegalAction,SnapshotError,Ruleset)
from hs_sim.engine.effects import (GainArmor,Damage,Destroy,Silence,Transform,ChangeControl,ReturnToHand,
    CopyMinion,Summon,InvokeBehavior,RequestChoice,ChoiceOption,RandomDamage)
from hs_sim.engine.dormancy import MakeDormant,AwakenMinion
from hs_sim.engine.replay import build_replay,replay


class ComboRepeatTests(unittest.TestCase):
    card=foundation.ComboActivationTests.card
    script=foundation.ComboActivationTests.script
    watch=foundation.ComboActivationTests.watch
    game=foundation.ComboActivationTests.game
    play=foundation.ComboActivationTests.play
    ready=foundation.ComboActivationTests.ready
    choose=foundation.ComboActivationTests.choose
    pause=foundation.ComboActivationTests.pause
    armor=foundation.ComboActivationTests.armor
    check=foundation.ComboActivationTests.check
    reject=foundation.ComboActivationTests.reject
    nested=foundation.ComboActivationTests.nested
    records=foundation.ComboActivationTests.records

    def setUp(self):
        foundation.ComboActivationTests.setUp(self)
        self.aura('repeat')
        self.power('play_policy',trigger='play')
        self.power('activation_policy',trigger='activation')

    def aura(self,cid,spec=None,**kwargs):
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,combo_repeats=(spec or ComboRepeatSpec(),),**kwargs))

    def power(self,cid,*,trigger='play',uses=1,expires=False,spec=None,extra=()):
        self.r.register_behavior(cid,lambda c:[AddComboRepeatModifier(c.player_id,spec or ComboRepeatSpec(),c.source_id,
            uses,c.state.turn if expires else None,trigger),*extra])
        self.r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,on_use=cid))

    def policy_game(self,power='play_policy',*,hand=('prime','combo'),board=(),enemy=()):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,hero_power_card_id=power,mana=10,max_mana=10,deck=('body',)*4),
            PlayerSetup('hero',board=enemy,deck=('body',)*4)),seed=87),self.r)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));return g

    def modifiers(self,g,p=1):return g.state.players[p].combo_modifiers
    def batch(self,g):return g.state.combo_batches[-1]

    def test_aura_repeats_combo_without_another_payment_or_play(self):
        g=self.ready(board=('repeat',));self.play(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(4,8,2))
        self.assertEqual([b.repeat_index for b in self.records(g)],[1,2])
        self.assertEqual([b.iteration for b in self.records(g)],[1,1]);self.assertTrue(self.batch(g).finished);self.check(g)

    def test_multiple_auras_use_maximum_count(self):
        self.aura('three',ComboRepeatSpec(3));g=self.ready(board=('repeat','repeat','three'));self.play(g)
        self.assertEqual(self.armor(g),6);self.assertEqual(len(self.batch(g).plan.contributors),3);self.check(g)

    def test_opponent_and_dormant_auras_are_inactive(self):
        self.aura('sleep',dormant_turns=2)
        g=self.ready(board=('sleep',),enemy=('repeat',));self.play(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(self.batch(g).plan,ComboRepeatPlan());self.check(g)

    def test_type_scope_distinguishes_minion_weapon_and_hero(self):
        self.card('weapon',kind=CardType.WEAPON);self.card('hero_card',kind=CardType.HERO,hero_card=True,initial_hero_power='power')
        self.aura('all',ComboRepeatSpec(kinds=(CardType.MINION,CardType.WEAPON,CardType.HERO)))
        for name,source,expected in (('weapon','repeat',2),('weapon','all',4),('hero_card','all',4)):
            with self.subTest(kind=name,source=source):
                g=self.ready(name,board=(source,));self.play(g,name);self.assertEqual(self.armor(g),expected);self.check(g)

    def test_generic_battlecry_and_combo_counts_are_separate(self):
        self.r.register_behavior('generic',lambda c:[GainArmor(1,7)])
        self.card('mixed',battlecry='armor',on_play='generic')
        self.aura('both',battlecry_repeats=(BattlecryRepeatSpec(),))
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        g=self.ready('mixed',board=('both','brann'));self.play(g,'mixed')
        self.assertEqual(self.armor(g),15);self.assertEqual(len(self.records(g)),2)
        self.assertEqual(len(g.state.battlecry_history),2);self.check(g)

    def test_aura_does_not_enable_first_card_combo(self):
        g=self.game(hand=('combo',),board=('repeat',));self.play(g)
        self.assertEqual(self.records(g),[]);self.assertEqual(g.state.combo_batches,[]);self.assertEqual(self.armor(g),0);self.check(g)

    def test_normal_summon_and_generic_payload_do_not_use_combo_policy(self):
        self.script('summon',lambda c:[Summon(1,'combo'),GainArmor(1,3)])
        g=self.policy_game(hand=('summon',));self.play(g,'summon')
        self.assertEqual(self.armor(g),3);self.assertEqual(len(self.modifiers(g)),1)
        self.assertEqual(g.state.combo_policy_receipts,[]);self.check(g)

    def test_play_policy_consumes_on_disabled_first_combo(self):
        g=self.policy_game(hand=('combo',));self.play(g)
        self.assertEqual(self.modifiers(g),[]);self.assertEqual(self.records(g),[])
        self.assertEqual([r.phase for r in g.state.combo_policy_receipts if r.modifiers],['play']);self.check(g)

    def test_activation_policy_survives_disabled_first_combo(self):
        g=self.policy_game('activation_policy',hand=('combo','combo'));self.play(g)
        self.assertEqual(len(self.modifiers(g)),1);self.assertEqual([r for r in g.state.combo_policy_receipts if r.modifiers],[])
        self.play(g);self.assertEqual(self.modifiers(g),[]);self.assertEqual(self.armor(g),4);self.check(g)

    def test_enabled_combo_consumes_each_policy_once(self):
        for power in ('play_policy','activation_policy'):
            with self.subTest(power=power):
                g=self.policy_game(power);self.play(g,'prime');self.play(g)
                self.assertEqual(self.modifiers(g),[]);self.assertEqual(self.armor(g),4)
                self.assertEqual(sum(e.kind=='combo_modifier_used' for e in g.events),1);self.check(g)

    def test_two_finite_policies_and_stronger_aura_all_consume_once(self):
        self.power('two',extra=(AddComboRepeatModifier(1,uses=1,trigger='activation'),))
        self.aura('three',ComboRepeatSpec(3));g=self.policy_game('two',board=('three',));self.play(g,'prime');self.play(g)
        self.assertEqual(self.armor(g),6);self.assertEqual(self.modifiers(g),[])
        self.assertEqual(len(self.batch(g).plan.consumable_ids),2)
        self.assertEqual([r.phase for r in g.state.combo_policy_receipts],['play','activation']);self.check(g)

    def test_two_uses_survive_interleaved_noncombo_plays(self):
        self.power('two_uses',uses=2)
        g=self.policy_game('two_uses',hand=('prime','combo','prime','combo'))
        self.play(g,'prime');self.play(g);self.assertEqual(self.modifiers(g)[0].uses_remaining,1)
        self.play(g,'prime');self.assertEqual(self.modifiers(g)[0].uses_remaining,1)
        self.play(g);self.assertEqual(self.modifiers(g),[]);self.assertEqual(self.armor(g),8);self.check(g)

    def test_unlimited_modifier_has_no_consumption_event(self):
        self.power('permanent',uses=None);g=self.policy_game('permanent',hand=('prime','combo','combo'))
        self.play(g,'prime');self.play(g);self.play(g)
        self.assertEqual(len(self.modifiers(g)),1);self.assertEqual(self.armor(g),8)
        self.assertFalse(any(e.kind=='combo_modifier_used' for e in g.events));self.check(g)

    def test_expiry_removes_both_players_policies(self):
        self.power('expires',uses=None,expires=True,extra=(AddComboRepeatModifier(2,expires_turn=1),))
        g=self.policy_game('expires');g.apply(EndTurn(1))
        self.assertEqual((self.modifiers(g),self.modifiers(g,2)),([],[]));self.check(g)

    def test_expiry_reactions_settle_new_same_turn_modifiers(self):
        self.power('expires',expires=True)
        # Use a different trigger for the renewal so the chain is finite.
        self.r.register_behavior('renew_once',lambda c:[AddComboRepeatModifier(1,uses=1,expires_turn=c.state.turn,trigger='activation')]
            if dict(c.event.data)['trigger']=='play' else [])
        from hs_sim.engine import TriggerSpec
        self.r.register_card(CardDefinition('once','once',CardType.MINION,health=2,triggers=(TriggerSpec('combo_modifier_expired','renew_once'),)))
        g=self.policy_game('expires',board=('once',));g.apply(EndTurn(1));self.assertEqual(self.modifiers(g),[])
        self.assertEqual(sum(e.kind=='combo_modifier_expired' for e in g.events),2);self.check(g)

    def test_source_control_change_does_not_transfer_player_modifier(self):
        self.r.register_behavior('grant',lambda c:[AddComboRepeatModifier(1,source_id=c.source_id,uses=1)])
        self.r.register_card(CardDefinition('giver','giver',CardType.MINION,health=4,on_play='grant'))
        self.script('steal',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        g=self.game(hand=('giver','steal','combo'));self.play(g,'giver');self.play(g,'steal');self.play(g)
        self.assertEqual((self.armor(g),self.armor(g,2)),(4,0));self.assertEqual(self.modifiers(g),[]);self.check(g)

    def test_remove_policy_is_player_scoped(self):
        self.script('wrong',lambda c:[RemoveComboRepeatModifier(2,c.state.players[1].combo_modifiers[0].id)])
        self.script('right',lambda c:[RemoveComboRepeatModifier(1,c.state.players[1].combo_modifiers[0].id)])
        g=self.policy_game(hand=('wrong','right','combo'));self.play(g,'wrong');self.assertEqual(len(self.modifiers(g)),1)
        self.play(g,'right');self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_counter_consumes_play_policy_but_not_activation_policy(self):
        self.watch('counter','minion_counter_check',lambda c:[CounterMinion(dict(c.event.data)['window_id'])])
        for power,remaining in (('play_policy',0),('activation_policy',1)):
            g=self.policy_game(power,board=('counter',));self.play(g,'prime');self.play(g)
            self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(len(self.modifiers(g)),remaining)
            self.assertEqual(self.records(g),[]);self.check(g)

    def test_board_full_consumption_follows_policy_window(self):
        self.watch('fill','minion_counter_check',lambda c:[Summon(1,'body') for _ in range(6)])
        for power,remaining in (('play_policy',0),('activation_policy',1)):
            g=self.policy_game(power,board=('fill',));self.play(g,'prime');self.play(g)
            self.assertEqual(g.state.play_history[-1].minion_result,'board_full')
            self.assertEqual(len(self.modifiers(g)),remaining);self.assertEqual(self.records(g),[]);self.check(g)

    def test_magnetic_consumption_follows_policy_window(self):
        from hs_sim.engine.model import CardMetadata,CardClass
        meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.r.register_card(CardDefinition('mech','mech',CardType.MINION,health=4,metadata=meta))
        self.card('magnet',keywords=(Keyword.MAGNETIC,),metadata=meta,magnetic_tribes=('mech',))
        for power,remaining in (('play_policy',0),('activation_policy',1)):
            g=self.policy_game(power,hand=('prime','magnet'),board=('mech',));self.play(g,'prime')
            g.apply(PlayCard(1,g.state.players[1].hand[0],position=0))
            self.assertEqual(g.state.play_history[-1].minion_result,'magnetized')
            self.assertEqual(len(self.modifiers(g)),remaining);self.assertEqual(self.records(g),[]);self.check(g)

    def test_terminal_before_activation_keeps_only_commitment_consumption(self):
        self.power('both',extra=(AddComboRepeatModifier(1,uses=1,trigger='activation'),))
        self.watch('lethal','card_committed',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)] if c.play.kind==CardType.MINION else [])
        g=self.policy_game('both',board=('lethal',));self.play(g,'prime');self.play(g)
        self.assertEqual([m.trigger for m in self.modifiers(g)],['activation'])
        self.assertEqual(self.records(g),[]);self.check(g)

    def test_silence_aura_before_capture_prevents_repetition(self):
        self.watch('silence','card_committed',lambda c:[Silence(c.state.players[1].board[0])] if c.play.kind==CardType.MINION else [])
        g=self.ready(board=('repeat','silence'));self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_silence_aura_after_capture_preserves_repetition(self):
        self.watch('silence','minion_summoned',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.ready(board=('repeat','silence'));self.play(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_commit_listener_cannot_replace_already_captured_play_policy(self):
        self.watch('change','card_committed',lambda c:[AddComboRepeatModifier(1,ComboRepeatSpec(3),uses=1)] if c.play.kind==CardType.MINION else [])
        g=self.policy_game(board=('change',));self.play(g,'prime');self.play(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(self.modifiers(g)[0].spec.repetitions,3);self.check(g)

    def test_commit_listener_can_supply_activation_policy(self):
        self.watch('grant','card_committed',lambda c:[AddComboRepeatModifier(1,ComboRepeatSpec(3),uses=1,trigger='activation')]
            if c.play.kind==CardType.MINION else [])
        g=self.ready(board=('grant',));self.play(g);self.assertEqual(self.armor(g),6);self.assertEqual(self.modifiers(g),[]);self.check(g)

    def test_body_grants_do_not_retroactively_repeat_itself(self):
        self.card('grant',lambda c:[AddComboRepeatModifier(1,uses=1),GainArmor(1,1)])
        g=self.ready('grant',tail=('combo',));self.play(g,'grant')
        self.assertEqual(self.armor(g),1);self.assertEqual(len(self.modifiers(g)),1)
        self.play(g);self.assertEqual(self.armor(g),5);self.check(g)

    def test_granted_aura_copies_and_silences_with_carrier(self):
        self.script('grant_aura',lambda c:[GrantComboRepeatAura(c.state.players[1].board[0],source_id=c.source_id),CopyMinion(c.state.players[1].board[0],1),Silence(c.state.players[1].board[0])])
        g=self.game(hand=('grant_aura','combo'),board=('body',));self.play(g,'grant_aura');self.play(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.batch(g).plan.contributors),1);self.check(g)

    def test_original_target_is_not_reselected_after_death(self):
        self.card('hit',lambda c:[Damage(c.target_id,5,c.source_id)],targeting=TargetSpec())
        g=self.ready('hit',board=('repeat',),enemy=('body','body'));target=g.state.players[2].board[0]
        self.play(g,'hit',target);self.assertEqual(len(self.records(g)),2)
        self.assertEqual(len(g.state.players[2].board),1);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,5);self.check(g)

    def test_each_repeat_captures_current_state_and_own_index(self):
        self.card('grow',lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].armor+c.combo.repeat_index)])
        g=self.ready('grow',board=('repeat',));self.play(g,'grow');self.assertEqual(self.armor(g),4);self.check(g)

    def test_choice_between_repeats_restores_progress_and_does_not_reconsume(self):
        self.card('wait',lambda c:[self.pause(c),GainArmor(1,c.combo.repeat_index)])
        g=self.policy_game(hand=('prime','wait'));self.play(g,'prime');self.play(g,'wait')
        self.assertEqual(self.modifiers(g),[]);self.check(g);self.choose(g);self.check(g)
        self.assertEqual((self.batch(g).completed,self.batch(g).running),(1,True))
        restored=g.clone();self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),3);self.check(g)

    def test_choices_are_independent_without_spell_choice_cache(self):
        self.card('choose',lambda c:[RequestChoice(1,(ChoiceOption('a','A',(GainArmor(1,1),)),ChoiceOption('b','B',(GainArmor(1,4),))),source_id=c.source_id)])
        g=self.ready('choose',board=('repeat',));self.play(g,'choose');self.choose(g,'a');self.choose(g,'b')
        self.assertEqual(self.armor(g),5);self.assertEqual([b.repeat_index for b in self.records(g)],[1,2]);self.check(g)

    def test_pause_in_consumption_listener_restores_frozen_plan(self):
        self.watch('pause','combo_modifier_used',lambda c:[self.pause(c)])
        g=self.policy_game(board=('pause',));self.play(g,'prime');self.play(g);self.assertEqual(self.records(g),[])
        self.check(g);restored=g.clone();self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),4);self.check(g)

    def test_source_mutation_in_first_repeat_preserves_captured_second(self):
        self.card('mutate',lambda c:[Transform(c.source_id,'body'),GainArmor(1,2)])
        g=self.ready('mutate',board=('repeat',));self.play(g,'mutate')
        self.assertEqual(self.armor(g),4);self.assertEqual([b.card_id for b in self.records(g)],['mutate','mutate']);self.check(g)

    def test_colossal_cancellation_preserves_activation_policy(self):
        self.card('giant',colossal=(AppendageSpec('body'),),keywords=(Keyword.COLOSSAL,))
        self.watch('kill','minion_summoned',lambda c:[Destroy(c.event.source_id)] if c.state.entities[c.event.source_id].card_id=='giant' else [])
        g=self.policy_game('activation_policy',hand=('prime','giant'),board=('kill',));self.play(g,'prime');self.play(g,'giant')
        self.assertEqual(len(self.modifiers(g)),1);self.assertEqual(self.records(g),[]);self.check(g)

    def test_retained_outcomes_keep_repeat_and_result_indices_distinct(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(2))
        g=self.policy_game(hand=('prime','rewind'),board=('retainer',));self.play(g,'prime');self.play(g,'rewind')
        self.assertEqual(self.armor(g),12);self.assertEqual([b.repeat_index for b in self.records(g)],[1,2]*3)
        self.assertEqual([b.iteration for b in self.records(g)],[1,1,2,2,3,3])
        self.assertEqual(sum(bool(r.modifiers) for r in g.state.combo_policy_receipts),1);self.assertEqual(self.modifiers(g),[]);self.check(g)

    def test_retained_repeated_choice_restores_each_boundary(self):
        self.card('rewind',lambda c:[self.pause(c),GainArmor(1,1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.policy_game('activation_policy',hand=('prime','rewind'),board=('retainer',));self.play(g,'prime');self.play(g,'rewind')
        for _ in range(4):self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(sum(bool(r.modifiers) for r in g.state.combo_policy_receipts),1);self.check(g)

    def test_normal_rewind_restores_policy_before_retry(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.policy_game(hand=('prime','rewind'));self.play(g,'prime');self.play(g,'rewind');self.check(g)
        self.choose(g,'retry');self.assertEqual(self.armor(g),4);self.assertEqual(len(self.records(g)),2)
        self.assertEqual(sum(bool(r.modifiers) for r in g.state.combo_policy_receipts),1);self.assertEqual(self.modifiers(g),[]);self.check(g)

    def test_terminal_stops_batch_without_inventing_remaining_activations(self):
        self.card('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.ready('lethal',board=('repeat',));self.play(g,'lethal')
        self.assertEqual(len(self.records(g)),1);self.assertTrue(self.records(g)[0].interrupted)
        self.assertTrue(self.batch(g).interrupted);self.assertFalse(self.batch(g).running);self.check(g)

    def test_failure_rolls_back_policies_receipts_randomness_and_payment(self):
        self.card('bad',lambda c:[RandomDamage(tuple(c.state.players[p].hero_id for p in (1,2)),1,c.source_id),Summon(1,'missing')])
        g=self.policy_game(hand=('prime','bad'));self.play(g,'prime');s=g.snapshot()
        with self.assertRaises(ResolutionError) as error:self.play(g,'bad')
        self.assertIn('missing',str(error.exception));self.assertEqual(g.snapshot(),s);self.check(g)

    def test_failure_after_pause_preserves_prior_consumption(self):
        self.r.register_behavior('bad',lambda c:[Summon(1,'missing')])
        self.card('wait',lambda c:[self.pause(c),InvokeBehavior('bad',c.source_id,1)])
        g=self.policy_game(hand=('prime','wait'));self.play(g,'prime');self.play(g,'wait');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.assertEqual(self.modifiers(g),[]);self.check(g)

    def test_invalid_target_does_not_consume_policy(self):
        self.card('hit',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec())
        g=self.policy_game(hand=('prime','hit'));self.play(g,'prime');s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'hit')
        self.assertEqual(g.snapshot(),s)

    def test_budget_error_is_transactional_and_not_a_game_result(self):
        self.aura('huge',ComboRepeatSpec(1000000));g=self.ready(board=('huge',));s=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),s);self.assertEqual(g.state.status,'playing')

    def test_public_modifier_facts_exclude_source_and_receipt_identity(self):
        g=self.policy_game()
        for p in (1,2):
            view=g.observe(p);own=next(x for x in view['players'] if x['id']==1)
            self.assertEqual(own['combo_modifiers'],[dict(repetitions=2,kinds=['minion'],scope='friendly',match=None,uses_remaining=1,expires_turn=None,trigger='play')])
            encoded=json.dumps((view,g.player_events(p)))
            for hidden in ('combo_policy_receipts','modifier_id','source_card_id','consumable_ids'):
                self.assertNotIn(hidden,encoded)
        self.play(g,'prime');self.play(g);self.check(g)

    def test_public_consumption_zero_and_event_schema_restore(self):
        g=self.policy_game();self.play(g,'prime');self.play(g)
        logs=g.player_events(1)
        events=logs['events'] if isinstance(logs,dict) else logs
        used=next(e for e in events if e['kind']=='combo_modifier_used')
        self.assertEqual(used['combo_modifier']['uses_remaining'],0);self.check(g)

    def test_snapshot_rejects_batch_progress_and_plan_corruption(self):
        g=self.ready(board=('repeat',));self.play(g)
        for changes in ({'completed':1},{'running':True},{'player_id':2},{'iteration':2},{'play_id':1}):
            s=g.snapshot();s['state']['combo_batches'][0].update(changes);self.reject(s)
        s=g.snapshot();s['state']['combo_batches'][0]['plan']['repetitions']=3;self.reject(s)

    def test_snapshot_rejects_repeat_order_and_wrong_batch(self):
        g=self.ready(board=('repeat',));self.play(g)
        for changes in ({'repeat_index':3},{'repeat_index':1},{'batch_id':99}):
            s=g.snapshot();s['state']['combo_history'][1].update(changes);self.reject(s)

    def test_snapshot_rejects_receipt_policy_mismatch_and_duplicate(self):
        g=self.policy_game();self.play(g,'prime');self.play(g)
        for changes in ({'phase':'activation'},{'play_id':1},{'id':2}):
            s=g.snapshot();s['state']['combo_policy_receipts'][0].update(changes);self.reject(s)
        s=g.snapshot();s['state']['combo_policy_receipts'].append(deepcopy(s['state']['combo_policy_receipts'][0]));self.reject(s)

    def test_snapshot_rejects_lost_consumption_receipt(self):
        g=self.policy_game();self.play(g,'prime');self.play(g);s=g.snapshot()
        s['state']['combo_policy_receipts']=[];self.reject(s)

    def test_snapshot_rejects_missing_repeat_finish_marker(self):
        self.card('wait',lambda c:[self.pause(c)]);g=self.ready('wait',board=('repeat',));self.play(g,'wait');s=g.snapshot()
        marker=self.nested(s['resolution_frame'],'FinishComboIteration');self.assertIsNotNone(marker)
        marker['fields']['batch_id']=99;self.reject(s)

    def test_snapshot_rejects_retained_plan_disagreement(self):
        self.card('rewind',lambda c:[self.pause(c)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.ready('rewind',board=('repeat','retainer'));self.play(g,'rewind');s=g.snapshot()
        s['state']['rewind_outcomes'][0]['combo_plan']['repetitions']=3;self.reject(s)

    def test_snapshot_rejects_invalid_live_policy_and_public_event(self):
        g=self.policy_game()
        for changes in ({'uses_remaining':0},{'trigger':'unknown'},{'created_turn':99},{'source_id':999}):
            s=g.snapshot();s['state']['players']['1']['combo_modifiers'][0].update(changes);self.reject(s)
        s=g.snapshot();event=next(e for e in s['information']['players']['1']['events'] if e['kind']=='combo_modifier_added')
        event['combo_modifier']['trigger']='unknown';self.reject(s)

    def test_snapshot_rejects_restored_consumed_uses(self):
        self.power('two_uses',uses=2);g=self.policy_game('two_uses',hand=('prime','combo','combo'))
        self.play(g,'prime');self.play(g);s=g.snapshot()
        s['state']['players']['1']['combo_modifiers'][0]['uses_remaining']=2;self.reject(s)
        self.play(g);s=g.snapshot();[r for r in s['state']['combo_policy_receipts'] if r['modifiers']][1]['modifiers'][0]['uses_remaining']=2;self.reject(s)

    def test_invalid_declarations_and_effect_scalars_are_rejected(self):
        for kw in ({'repetitions':True},{'repetitions':1},{'kinds':()},{'kinds':(CardType.SPELL,)},{'kinds':(CardType.MINION,)*2}):
            with self.assertRaises(ValueError):ComboRepeatSpec(**kw)
        for kw in ({'uses':0},{'expires_turn':True},{'trigger':'unknown'},{'spec':BattlecryRepeatSpec()}):
            with self.assertRaises(ValueError):AddComboRepeatModifier(1,**kw)
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.SPELL,combo_repeats=(ComboRepeatSpec(),)))

    def test_old_schema_is_explicitly_rejected(self):
        g=self.ready();s=g.snapshot();s['schema_version']=82
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)

    def test_composite_ship_repeats_each_inherited_combo_and_consumes_once(self):
        from hs_sim.engine import CardClass,LaunchStarship
        from hs_sim.engine.effects import DamageBatch
        from hs_sim.engine.starships import construction
        self.r.register_card(CardDefinition('ship','ship',CardType.MINION,starship_for=(CardClass.NEUTRAL,)))
        self.card('piece',keywords=(Keyword.STARSHIP_PIECE,))
        self.script('scrap',lambda c:[DamageBatch(tuple(Damage(i,100) for i in c.state.players[1].board))])
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.policy_game(hand=('scrap','bounce'),board=('piece','piece'));self.play(g,'scrap')
        ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));self.play(g,'bounce');g.apply(PlayCard(1,ship.id))
        self.assertEqual(self.armor(g),8);self.assertEqual(self.modifiers(g),[])
        self.assertEqual(sum(bool(r.modifiers) for r in g.state.combo_policy_receipts),1)
        self.assertEqual([b.repeat_index for b in self.records(g)],[1,2,1,2])
        self.assertEqual(len({b.payload.ability_id for b in self.records(g)}),2);self.check(g)

    def test_example_mixes_real_cards_with_explicit_mechanism_fixtures(self):
        from examples.combo_repetition import run
        g,s=run();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(len(g.state.combo_history),5);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertEqual(sum(bool(r.modifiers) for r in g.state.combo_policy_receipts),1)


if __name__=='__main__':unittest.main()
