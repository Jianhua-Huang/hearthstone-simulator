"""Player-held Battlecry budgets, global-turn expiry and retained-result capture."""
import json
import unittest
from dataclasses import replace
import test_m5_battlecry_repeats as repeats
from hs_sim.engine import (AddBattlecryRepeatModifier as Add, RemoveBattlecryRepeatModifier as Remove,
    BattlecryRepeatModifier, BattlecryRepeatPlan, BattlecryRepeatSpec, CardDefinition, CardType,
    EndTurn, Game, PlayCard, UseHeroPower, SelectChoice, RewindSpec, Keyword, TargetSpec,
    IllegalAction, ResolutionError, ResolutionLimitExceeded, SnapshotError, Scenario, PlayerSetup,
    PlayerEffectSpec, AddPlayerEffect, ChooseOneSpec, ChooseBranch, AppendageSpec)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Silence, ReturnToHand, Transform,
    ChangeControl, Summon, CopyMinion, RequestChoice, ChoiceOption, InvokeBehavior, ReplaceHeroPower)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.dormancy import MakeDormant


class BattlecryModifierTests(unittest.TestCase):
    card=repeats.BattlecryRepeatTests.card
    script=repeats.BattlecryRepeatTests.script
    watch=repeats.BattlecryRepeatTests.watch
    game=repeats.BattlecryRepeatTests.game
    play=repeats.BattlecryRepeatTests.play
    choose=repeats.BattlecryRepeatTests.choose
    pause=repeats.BattlecryRepeatTests.pause
    armor=repeats.BattlecryRepeatTests.armor
    check=repeats.BattlecryRepeatTests.check
    reject=repeats.BattlecryRepeatTests.reject
    nested=repeats.BattlecryRepeatTests.nested
    aura=repeats.BattlecryRepeatTests.aura

    def setUp(self):
        repeats.BattlecryRepeatTests.setUp(self)
        self.granter('one',uses=1)
        self.granter('two',uses=2)
        self.granter('forever')
        self.granter('turn',temporary=True)
        self.granter('next_turn',temporary=True,uses=1)

    def granter(self,cid,*,temporary=False,player=1,**kw):
        self.script(cid,lambda c:[Add(player,source_id=c.source_id,expires_turn=c.state.turn if temporary else None,**kw)])
    def mods(self,g,p=1):return g.state.players[p].battlecry_modifiers
    def used(self,g):return [e for e in g.events if e.kind=='battlecry_modifier_used']
    def grant_play(self,name='one',hand=('cry',),board=()):
        g=self.game(hand=(name,*hand),board=board);self.play(g,name);return g

    def test_next_match_consumes_once_and_next_card_is_normal(self):
        g=self.grant_play(hand=('cry','cry'));i=self.mods(g)[0].id;self.play(g)
        self.assertFalse(self.mods(g));self.assertEqual(self.armor(g),4);self.play(g)
        self.assertEqual(self.armor(g),6);self.assertEqual(len(self.used(g)),1)
        self.assertEqual(g.state.battlecry_batches[0].plan.consumable_ids,(i,));self.check(g)

    def test_two_uses_count_plays_not_repetition_iterations(self):
        g=self.grant_play('two',hand=('cry','cry','cry'));self.play(g)
        self.assertEqual(self.mods(g)[0].uses_remaining,1);self.play(g);self.assertFalse(self.mods(g));self.play(g)
        self.assertEqual(self.armor(g),10);self.assertEqual(len(self.used(g)),2);self.check(g)

    def test_unlimited_policy_does_not_consume(self):
        g=self.grant_play('forever',hand=('cry','cry'));self.play(g);self.play(g)
        self.assertEqual(self.armor(g),8);self.assertIsNone(self.mods(g)[0].uses_remaining);self.assertFalse(self.used(g));self.check(g)

    def test_permanent_policy_survives_turns(self):
        g=self.grant_play('forever');g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_turn_policy_repeats_all_matches_then_expires(self):
        g=self.grant_play('turn',hand=('cry','cry','cry'));self.play(g);self.play(g)
        self.assertEqual(self.armor(g),8);g.apply(EndTurn(1));self.assertFalse(self.mods(g));g.apply(EndTurn(2));self.play(g)
        self.assertEqual(self.armor(g),10);self.check(g)

    def test_unused_next_this_turn_expires(self):
        g=self.grant_play('next_turn');g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        self.assertFalse(self.used(g));self.assertEqual(self.armor(g),2);self.check(g)

    def test_expiry_uses_global_turn_not_beneficiary_turn(self):
        self.granter('enemy_turn',player=2,temporary=True)
        g=self.grant_play('enemy_turn',hand=());self.assertEqual(len(self.mods(g,2)),1);g.apply(EndTurn(1))
        self.assertFalse(self.mods(g,2));i=next(i for i in g.state.players[2].hand if g.state.entities[i].card_id=='cry')
        g.apply(PlayCard(2,i));self.assertEqual(self.armor(g,2),2);self.check(g)

    def test_future_absolute_expiry_is_supported(self):
        self.script('future',lambda c:[Add(1,expires_turn=c.state.turn+1)])
        g=self.grant_play('future');g.apply(EndTurn(1));self.assertTrue(self.mods(g));g.apply(EndTurn(2))
        self.assertFalse(self.mods(g));self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_grant_from_end_turn_reaction_expires_same_turn(self):
        self.watch('end','turn_ended',lambda c:[Add(1,source_id=c.source_id,expires_turn=c.state.turn)])
        g=self.game(board=('end',));g.apply(EndTurn(1));self.assertFalse(self.mods(g))
        self.assertTrue(any(e.kind=='battlecry_modifier_expired' for e in g.events));self.check(g)

    def test_expiry_reaction_grant_is_settled_before_next_turn(self):
        # Guard the one-time renewal with a standard once-only trigger ability.
        from hs_sim.engine import LimitedTriggerSpec
        self.r.register_behavior('renew',lambda c:[Add(1,source_id=c.source_id,expires_turn=c.state.turn)])
        self.r.register_card(CardDefinition('limited','limited',CardType.MINION,health=4,
            limited_triggers=(LimitedTriggerSpec('battlecry_modifier_expired','renew',uses=1),)))
        g=self.grant_play('turn',board=('limited',));g.apply(EndTurn(1))
        self.assertFalse(self.mods(g));self.assertEqual(sum(e.kind=='battlecry_modifier_expired' for e in g.events),2);self.check(g)

    def test_source_death_silence_bounce_transform_control_do_not_revoke(self):
        self.card('giver',lambda c:[Add(1,source_id=c.source_id)])
        for name,fn in (('kill',lambda i:Destroy(i)),('silence',lambda i:Silence(i)),
            ('bounce',lambda i:ReturnToHand(i)),('morph',lambda i:Transform(i,'body')),('steal',lambda i:ChangeControl(i,2)),('sleep',lambda i:MakeDormant(i,None))):
            self.script(name,lambda c,fn=fn:[fn(c.state.players[1].board[0])])
        for name in ('kill','silence','bounce','morph','steal','sleep'):
            with self.subTest(name=name):
                g=self.game(hand=('giver',name,'cry'));self.play(g,'giver');self.play(g,name);self.play(g)
                self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g,2));self.check(g)

    def test_copying_giver_does_not_duplicate_player_policy(self):
        self.card('giver',lambda c:[Add(1,source_id=c.source_id)])
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        g=self.game(hand=('giver','copy'));self.play(g,'giver');self.play(g,'copy')
        self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_bounce_replay_giver_adds_new_instances(self):
        self.card('giver',lambda c:[Add(1,source_id=c.source_id,uses=1)])
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('giver','bounce','cry'));self.play(g,'giver');old=self.mods(g)[0].id;self.play(g,'bounce');self.play(g,'giver')
        self.assertEqual(len(self.mods(g)),2);self.assertTrue(all(m.id!=old for m in self.mods(g)));self.play(g)
        self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g));self.check(g)

    def test_duplicate_policies_take_max_and_all_finite_matches_consume(self):
        g=self.game(hand=('one','one','cry'));self.play(g,'one');self.play(g,'one');self.play(g)
        self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g));self.assertEqual(len(self.used(g)),2);self.check(g)

    def test_larger_aura_does_not_preserve_matching_finite_policy(self):
        self.aura('triple',BattlecryRepeatSpec(3));g=self.grant_play(board=('triple',));self.play(g)
        self.assertEqual(self.armor(g),6);self.assertFalse(self.mods(g));self.assertEqual(len(self.used(g)),1);self.check(g)

    def test_permanent_and_finite_share_max_policy(self):
        g=self.game(hand=('forever','one','cry','cry'));self.play(g,'forever');self.play(g,'one');self.play(g);self.play(g)
        self.assertEqual(self.armor(g),8);self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_opponent_policy_does_not_affect_or_consume_on_own_play(self):
        self.granter('enemy',player=2,uses=1);g=self.grant_play('enemy');self.play(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(self.mods(g,2)[0].uses_remaining,1);self.check(g)

    def test_matching_kind_filters_consumption(self):
        self.granter('weapon_only',spec=BattlecryRepeatSpec(kinds=(CardType.WEAPON,)),uses=1)
        self.card('weapon',kind=CardType.WEAPON);g=self.grant_play('weapon_only',hand=('cry','weapon'));self.play(g)
        self.assertEqual(self.mods(g)[0].uses_remaining,1);self.play(g,'weapon');self.assertEqual(self.armor(g),6)
        self.assertFalse(self.mods(g));self.check(g)

    def test_hero_battlecry_is_a_matching_play(self):
        self.card('hero_card',kind=CardType.HERO,hero_card=True,initial_hero_power='power')
        g=self.grant_play(hand=('hero_card',));self.play(g,'hero_card');self.assertFalse(self.mods(g));self.assertEqual(self.armor(g),4);self.check(g)

    def test_generic_and_spell_and_summon_do_not_consume(self):
        self.r.register_card(CardDefinition('generic','generic',CardType.MINION,health=2,on_play='armor'))
        self.script('summon',lambda c:[Summon(1,'cry')]);g=self.grant_play(hand=('generic','summon','cry'))
        self.play(g,'generic');self.play(g,'summon');self.assertEqual(self.mods(g)[0].uses_remaining,1)
        self.play(g);self.assertEqual(self.armor(g),6);self.check(g)

    def test_choose_one_is_not_a_matching_battlecry(self):
        self.r.register_card(CardDefinition('choose','choose',CardType.MINION,health=2,
            choose_one=ChooseOneSpec((ChooseBranch('a','A','armor'),ChooseBranch('b','B','armor')),ChooseBranch('both','Both','armor'))))
        g=self.grant_play(hand=('choose',));self.play(g,'choose',branch='a')
        self.assertEqual(self.mods(g)[0].uses_remaining,1);self.assertEqual(self.armor(g),2);self.check(g)

    def test_illegal_target_does_not_consume(self):
        self.card('target',targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.grant_play(hand=('target',));s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'target')
        self.assertEqual(g.snapshot(),s)

    def test_failed_budget_does_not_consume(self):
        self.granter('huge',spec=BattlecryRepeatSpec(1000000),uses=1);g=self.grant_play('huge');s=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_empty_battlecry_consumes(self):
        self.card('empty',lambda c:[]);g=self.grant_play(hand=('empty',));self.play(g,'empty')
        self.assertFalse(self.mods(g));self.assertEqual(len(g.state.battlecry_history),2);self.check(g)

    def test_granting_battlecry_does_not_consume_its_new_policy(self):
        self.card('giver',lambda c:[Add(1,source_id=c.source_id,uses=1,expires_turn=c.state.turn)])
        g=self.game(hand=('giver','cry'));self.play(g,'giver');self.assertEqual(len(self.mods(g)),1)
        self.assertEqual(len(g.state.battlecry_history),1);self.play(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_aura_doubles_giver_into_two_policies_without_recursive_repeat(self):
        self.card('giver',lambda c:[Add(1,source_id=c.source_id,uses=1)])
        g=self.game(hand=('giver','cry'),board=('repeat',));self.play(g,'giver')
        self.assertEqual(len(self.mods(g)),2);self.assertEqual(len(g.state.battlecry_history),2);self.play(g)
        self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g));self.check(g)

    def test_remove_one_duplicate_by_identity(self):
        self.script('remove',lambda c:[Remove(1,c.state.players[1].battlecry_modifiers[0].id)])
        g=self.game(hand=('one','forever','remove','cry'));self.play(g,'one');self.play(g,'forever');self.play(g,'remove');self.play(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.mods(g)),1);self.assertFalse(self.used(g));self.check(g)

    def test_wrong_owner_removal_does_not_remove_policy(self):
        self.script('remove',lambda c:[Remove(2,c.state.players[1].battlecry_modifiers[0].id)])
        g=self.grant_play(hand=('remove','cry'));self.play(g,'remove');self.play(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_last_removal_stops_future_repetition(self):
        self.script('remove',lambda c:[Remove(1,c.state.players[1].battlecry_modifiers[0].id)])
        g=self.grant_play('forever',hand=('remove','cry'));self.play(g,'remove');self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_capacity_independent_of_filled_objective_area(self):
        self.r.register_player_effect(PlayerEffectSpec('objective','forever',kind='objective',duration=1,tick_event='turn_ended'))
        self.script('fill',lambda c:[*[AddPlayerEffect(1,'objective',c.source_id) for _ in range(5)],Add(1,source_id=c.source_id,uses=1)])
        g=self.grant_play('fill');self.assertEqual(len(g.state.players[1].player_effects),5)
        self.play(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_commit_reaction_pause_precedes_entry_and_consumption(self):
        self.watch('wait','card_committed',lambda c:[self.pause(c)] if c.play.card_id=='cry' else [])
        g=self.grant_play(board=('wait',));self.play(g);self.assertEqual(len(self.mods(g)),1);self.assertFalse(g.state.battlecry_batches)
        self.check(g);self.choose(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_grant_from_commit_reaction_applies_to_accepted_entry(self):
        self.watch('add','card_committed',lambda c:[Add(1,source_id=c.source_id,uses=1)] if c.play.card_id=='cry' else [])
        g=self.game(hand=('cry','cry'),board=('add',));self.play(g);self.assertEqual(self.armor(g),4);self.play(g)
        self.assertEqual(self.armor(g),8);self.assertFalse(self.mods(g));self.check(g)

    def test_removal_before_entry_prevents_capture(self):
        self.watch('remove','card_committed',lambda c:[Remove(1,m.id) for m in c.state.players[1].battlecry_modifiers] if c.play.card_id=='cry' else [])
        g=self.grant_play('forever',board=('remove',));self.play(g)
        self.assertEqual(self.armor(g),2);self.assertFalse(self.mods(g));self.check(g)

    def test_pause_in_consumption_event_restores_frozen_plan(self):
        self.watch('wait','battlecry_modifier_used',lambda c:[self.pause(c)])
        g=self.grant_play(board=('wait',));self.play(g);self.assertFalse(self.mods(g));self.check(g)
        self.choose(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_independent_choices_do_not_consume_again(self):
        self.card('wait',lambda c:[self.pause(c),GainArmor(1,1)])
        g=self.grant_play('two',hand=('wait',));self.play(g,'wait');self.check(g);self.choose(g);self.check(g);self.choose(g)
        self.assertEqual((self.armor(g),self.mods(g)[0].uses_remaining,len(self.used(g))),(2,1,1));self.check(g)

    def test_exception_rolls_back_consumption_with_entire_play(self):
        self.card('bad',lambda c:[Summon(1,'missing')] if c.battlecry.repeat_index==2 else [GainArmor(1,3)])
        g=self.grant_play(hand=('bad',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),s)

    def test_failure_after_pause_keeps_already_consumed_policy(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'missing')])
        self.card('bad',lambda c:[self.pause(c),InvokeBehavior('fail',c.source_id,1)])
        g=self.grant_play(hand=('bad',));self.play(g,'bad');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.assertFalse(self.mods(g));self.check(g)

    def test_rewind_retry_restores_original_budget_then_consumes_once(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.grant_play('two',hand=('rewind',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        # Diagnostic logs retain the abandoned attempt; live budget/history reset.
        self.assertEqual(len(g.state.battlecry_batches),1)
        self.assertEqual((self.armor(g),self.mods(g)[0].uses_remaining,len(self.used(g))),(4,1,2));self.check(g)

    def test_retained_outcomes_do_not_consume_twice(self):
        self.card('rewind',lambda c:[GainArmor(1,1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.grant_play('two',hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.assertEqual((self.armor(g),self.mods(g)[0].uses_remaining,len(self.used(g))),(4,1,1));self.check(g)

    def test_retained_grants_apply_after_all_frozen_outcomes(self):
        self.card('giver',lambda c:[Add(1,source_id=c.source_id,uses=1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('giver','cry'),board=('retainer',));self.play(g,'giver')
        self.assertEqual(len(g.state.battlecry_history),2);self.assertEqual(len(self.mods(g)),2);self.play(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.used(g)),2);self.check(g)

    def test_terminal_before_entry_does_not_consume_or_activate(self):
        self.watch('lethal','card_committed',lambda c:[Damage(c.state.players[2].hero_id,100)] if c.play.card_id=='cry' else [])
        g=self.grant_play(board=('lethal',));self.play(g)
        self.assertEqual(len(self.mods(g)),1);self.assertFalse(g.state.battlecry_history);self.assertEqual(len(self.used(g)),0);self.check(g)

    def test_public_view_has_only_rule_facts_for_both_players(self):
        g=self.grant_play('next_turn');expected=dict(repetitions=2,kinds=['minion','weapon','hero'],uses_remaining=1,expires_turn=1,scope='friendly',match=None)
        for p in (1,2):
            v=next(v for v in g.observe(p)['players'] if v['id']==1)
            self.assertEqual(v['battlecry_modifiers'],[expected])
            for k in ('source_id','source_card_id','id','created_turn'):self.assertNotIn(k,v['battlecry_modifiers'][0])
        self.check(g)

    def test_hidden_source_is_not_exposed_by_modifier_projection_or_event(self):
        self.script('hidden',lambda c:[Add(1,source_id=c.state.players[1].deck[0],uses=1)])
        g=self.grant_play('hidden');log=g.player_events(2)
        event=next(e for e in log if e['kind']=='battlecry_modifier_added')
        self.assertIsNone(event['source']);self.assertNotIn('modifier_id',json.dumps(event));self.assertNotIn('policy_source_id',json.dumps(event));self.check(g)

    def test_snapshot_rejects_modifier_identity_and_lifetime_corruption(self):
        g=self.grant_play('next_turn')
        for changes in ({'id':99999},{'source_id':99999},{'source_card_id':'missing'},{'created_turn':99},{'uses_remaining':0},{'expires_turn':0},{'uses_remaining':True}):
            with self.subTest(changes=changes):
                s=g.snapshot();s['state']['players']['1']['battlecry_modifiers'][0].update(changes);self.reject(s)

    def test_snapshot_rejects_duplicate_and_cross_attachment_identity(self):
        g=self.grant_play('one',board=('repeat',));s=g.snapshot();row=s['state']['players']['1']['battlecry_modifiers']
        row.append(dict(row[0]));self.reject(s)
        s=g.snapshot();ability=g.state.entities[g.state.players[1].board[0]].abilities[0]
        s['state']['players']['1']['battlecry_modifiers'][0]['id']=ability.id;self.reject(s)

    def test_snapshot_rejects_consumables_not_in_contributors(self):
        self.card('wait',lambda c:[self.pause(c)]);g=self.grant_play(hand=('wait',));self.play(g,'wait');s=g.snapshot()
        s['state']['battlecry_batches'][0]['plan']['consumable_ids']=[99999];self.reject(s)

    def test_snapshot_rejects_public_event_forgery(self):
        g=self.grant_play('one')
        for changes in ({'uses_remaining':0},{'repetitions':True},{'kinds':['spell']},{'source_id':9}):
            s=g.snapshot();e=next(e for e in s['information']['players']['1']['events'] if e['kind']=='battlecry_modifier_added')
            e['battlecry_modifier'].update(changes);self.reject(s)

    def test_invalid_effect_fields_and_expired_grant_rejected(self):
        for kw in ({'uses':0},{'uses':True},{'expires_turn':0},{'spec':'twice'},{'player_id':3}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):Add(**{'player_id':1,**kw})
        self.script('old',lambda c:[Add(1,expires_turn=1)])
        g=self.game(hand=('old',));g.apply(EndTurn(1));g.apply(EndTurn(2));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'old')
        self.assertEqual(g.snapshot(),s)

    def test_old_schema_and_information_version_rejected(self):
        g=self.grant_play();s=g.snapshot();s['schema_version']=73
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)
        s=g.snapshot();s['information']['version']='player-view-v43';self.reject(s)

    def test_power_policy_survives_source_power_replacement(self):
        self.r.register_behavior('grant_power',lambda c:[Add(1,source_id=c.source_id,uses=2)])
        self.r.register_card(CardDefinition('grant_power','grant_power',CardType.HERO_POWER,cost=2,on_use='grant_power'))
        self.script('replace',lambda c:[ReplaceHeroPower(1,'power')])
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hero_power_card_id='grant_power',hand=('replace','cry'),mana=10,max_mana=10),PlayerSetup('hero')),seed=75),self.r)
        old=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,old));self.play(g,'replace');self.play(g)
        self.assertEqual(self.mods(g)[0].source_id,old);self.assertEqual(self.mods(g)[0].uses_remaining,1)
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_expiry_paused_reaction_roundtrips(self):
        self.watch('wait','battlecry_modifier_expired',lambda c:[self.pause(c)])
        g=self.grant_play('turn',board=('wait',));g.apply(EndTurn(1));self.assertFalse(self.mods(g));self.check(g)
        self.choose(g);self.assertEqual(g.state.active_player,2);self.check(g)

    def test_consumption_event_renewal_is_not_used_by_current_repeats(self):
        self.watch('renew','battlecry_modifier_used',lambda c:[Add(1,source_id=c.source_id,uses=1)])
        g=self.grant_play(board=('renew',));self.play(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.mods(g)),1);self.assertEqual(len(self.used(g)),1);self.check(g)


class RepresentativeBattlecryModifierTests(unittest.TestCase):
    def test_real_finite_and_turn_combination_restores_and_replays(self):
        from examples.battlecry_player_modifiers import run
        g,s=run();self.assertEqual(len(g.state.battlecry_history),5);self.assertEqual(s['schema_version'],266)

    def test_brann_and_murmuring_create_two_next_policies(self):
        from hs_sim.engine.representative import build_registry
        r=build_registry();g=Game.from_scenario(Scenario((PlayerSetup('HERO_02',board=('LOE_077',),
            hand=('LOOT_517','CS2_203'),mana=10,max_mana=10),PlayerSetup('HERO_08')),seed=75),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));self.assertEqual(len(g.state.players[1].battlecry_modifiers),2)
        target=g.state.players[1].board[0];g.apply(PlayCard(1,g.state.players[1].hand[0],target))
        self.assertFalse(g.state.players[1].battlecry_modifiers);self.assertEqual(len(g.state.battlecry_history),4)
        self.assertTrue(g.state.entities[target].silenced)
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())

    def test_multi_component_ship_consumes_once_per_hand_play(self):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine import LaunchStarship
        from hs_sim.engine.starships import construction
        r=build_registry()
        r.register_behavior('scrap',lambda c:[Destroy(i) for i in c.state.players[1].board])
        r.register_behavior('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0]),Add(1,uses=2,source_id=c.source_id)])
        for cid in ('scrap','bounce'):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('SC_405','SC_405'),hand=('scrap','bounce'),mana=10,max_mana=10),PlayerSetup('HERO_08')),seed=75),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id))
        g.apply(PlayCard(1,g.state.players[1].hand[0]));g.apply(PlayCard(1,ship.id))
        self.assertEqual(len(g.state.battlecry_history),4);self.assertEqual(g.state.players[1].battlecry_modifiers[0].uses_remaining,1)
        self.assertEqual(sum(e.kind=='battlecry_modifier_used' for e in g.events),1)
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
