"""R-139: explicit trigger rounds, source repetitions and frozen continuation."""
import json
import unittest
from dataclasses import replace
import test_m5_deathrattle_repeats as base
from hs_sim.engine import (Game,Scenario,PlayerSetup,CardDefinition,CardType,Keyword,Resource,
    EndTurn,SelectChoice,RewindSpec,ResolutionError,Ruleset,TargetSpec,TargetMode,
    BattlecryRepeatSpec,PlayerEffectSpec,DeathrattleRepeatSpec,AddPlayerEffect,RemovePlayerEffect)
from hs_sim.engine.effects import (TriggerDeathrattles,GainArmor,Damage,Destroy,Transform,Silence,
    ReturnToHand,ChangeControl,GrantDeathrattle,Summon,RandomDamage)


class FixedDeathrattleTests(unittest.TestCase):
    script=base.DeathrattleRepeatTests.script
    play=base.DeathrattleRepeatTests.play
    body=base.DeathrattleRepeatTests.body
    check=base.DeathrattleRepeatTests.check
    choose=base.DeathrattleRepeatTests.choose
    reject=base.DeathrattleRepeatTests.reject
    pause=base.DeathrattleRepeatTests.pause
    minion=base.DeathrattleRepeatTests.minion
    records=base.DeathrattleRepeatTests.records
    armor=base.DeathrattleRepeatTests.armor
    frames=base.DeathrattleRepeatTests.frames
    batch=base.DeathrattleRepeatTests.batch

    def setUp(self):
        base.DeathrattleRepeatTests.setUp(self)
        self.script('twice',lambda c:[TriggerDeathrattles(c.target_id,c.source_id,times=2)],target=True)
        self.script('thrice',lambda c:[TriggerDeathrattles(c.target_id,c.source_id,times=3)],target=True)
        self.script('policy',lambda c:[AddPlayerEffect(1,'policy',c.source_id)])
        self.r.register_player_effect(PlayerEffectSpec('policy','policy',deathrattle_repeats=(DeathrattleRepeatSpec(),)))

    def game(self,hand=('twice',),board=('rattle',),enemy=(),rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('body',)*12,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('body',)*12,mana=10,max_mana=10)),seed=98),self.r,ruleset=rules)
    def invoke(self,g,card='twice'):return self.play(g,card,self.body(g,1))
    def custom(self,fn,board=('rattle',),enemy=()):
        self.script('do',fn);return self.game(hand=('do',),board=board,enemy=enemy)
    def waiting(self,board=('waiter','baron')):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))]);self.minion('waiter','wait')
        g=self.game(board=board);self.invoke(g);return g

    def test_fixed_twice_has_two_rounds_and_one_batch_without_death(self):
        g=self.game();self.invoke(g);rows=self.records(g)
        self.assertEqual([(d.capture.trigger_index,d.capture.repeat_index) for d in rows],[(1,1),(2,1)])
        self.assertEqual(self.armor(g),2);self.assertEqual(self.batch(g).trigger_count,2);self.assertFalse(g.state.death_history)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.check(g)

    def test_fixed_rounds_multiply_board_repeat_count(self):
        g=self.game(board=('rattle','baron'));self.invoke(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(self.batch(g).plan.repetitions,2)
        self.assertEqual([(d.capture.trigger_index,d.capture.repeat_index) for d in self.records(g)],[(1,1),(1,2),(2,1),(2,2)]);self.check(g)

    def test_fixed_rounds_multiply_player_repeat_count(self):
        g=self.game(hand=('policy','twice'));self.play(g,'policy');self.invoke(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.batch(g).plan.contributors),1);self.check(g)

    def test_mixed_set_count_sources_still_use_max_before_fixed_rounds(self):
        g=self.game(hand=('policy','twice'),board=('rattle','baron'));self.play(g,'policy');self.invoke(g)
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.batch(g).plan.contributors),2);self.check(g)

    def test_three_rounds_and_triple_source_keep_separate_axes(self):
        g=self.game(hand=('thrice',),board=('rattle','triple'));self.invoke(g,'thrice')
        self.assertEqual(self.armor(g),9);self.assertEqual([d.capture.trigger_index for d in self.records(g)],[1]*3+[2]*3+[3]*3);self.check(g)

    def test_round_ability_repeat_order_and_fresh_extra_contexts(self):
        self.r.register_behavior('grow',lambda c:[GainArmor(1,self.armor_proxy(c)+1)])
        self.r.register_behavior('ten',lambda c:[GainArmor(1,10)]);self.minion('grower','grow')
        g=self.custom(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'ten'),TriggerDeathrattles(c.state.players[1].board[0],times=2)],('grower','baron'))
        self.play(g,'do');self.assertEqual(self.armor(g),115)
        self.assertEqual([(d.capture.trigger_index,d.capture.ability.behavior_id,d.capture.repeat_index) for d in self.records(g)],
            [(t,a,r) for t in (1,2) for a in ('grow','ten') for r in (1,2)]);self.check(g)

    @staticmethod
    def armor_proxy(c):return c.state.entities[c.state.players[1].hero_id].armor

    def test_later_round_reads_world_when_source_repeat_is_one(self):
        self.r.register_behavior('grow',lambda c:[GainArmor(1,self.armor_proxy(c)+1)]);self.minion('grower','grow')
        g=self.game(board=('grower',));self.invoke(g);self.assertEqual(self.armor(g),3);self.check(g)

    def test_identical_grants_remain_two_abilities_in_each_round(self):
        g=self.custom(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),GrantDeathrattle(c.state.players[1].board[0],'armor'),
            TriggerDeathrattles(c.state.players[1].board[0],times=2)],('body',));self.play(g,'do')
        self.assertEqual(self.armor(g),4);self.assertEqual(len({d.capture.ability.id for d in self.records(g)}),2);self.check(g)

    def test_each_position_gets_independent_choice_and_restore(self):
        g=self.waiting()
        for expected in range(4):
            self.assertEqual(self.armor(g),expected);self.assertIsNotNone(g.state.pending_choice);self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),4);self.assertIsNone(g.state.pending_choice);self.check(g)

    def pending_effect(self):
        g=self.custom(lambda c:[self.pause(c,GainArmor(1,1)),TriggerDeathrattles(c.state.players[1].board[0],c.source_id,times=2)],('rattle','baron'))
        self.play(g,'do');return g

    def test_pending_effect_retains_requested_count_before_batch_creation(self):
        g=self.pending_effect();self.assertFalse(g.state.deathrattle_batches)
        work=self.frames(g.snapshot(),'hs_sim.engine.effects.TriggerDeathrattles')[0]
        self.assertEqual(work['fields']['times'],2);self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),5);self.assertEqual(self.batch(g).trigger_count,2);self.check(g)

    def test_invalid_pending_effect_count_is_rejected(self):
        g=self.pending_effect();s=g.snapshot();self.frames(s,'hs_sim.engine.effects.TriggerDeathrattles')[0]['fields']['times']=True;self.reject(s)

    def test_later_round_failure_rolls_back_entire_action(self):
        def fail(c):
            if c.deathrattle.trigger_index==2:raise ValueError('later round')
            return [GainArmor(1,1)]
        self.r.register_behavior('fail',fail);self.minion('bad','fail');g=self.game(board=('bad',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'later round'):self.invoke(g)
        self.assertEqual(g.snapshot(),before)

    def test_terminal_preserves_unstarted_rounds(self):
        self.r.register_behavior('fatal',lambda c:[Damage(c.state.players[2].hero_id,40)]);self.minion('fatalbody','fatal')
        g=self.game(board=('fatalbody','baron'));self.invoke(g)
        self.assertEqual([d.execution_order for d in self.records(g)],[1,None,None,None]);self.assertTrue(all(d.interrupted for d in self.records(g)));self.check(g)

    def test_oversized_fixed_count_rejected_before_allocating(self):
        g=self.custom(lambda c:[TriggerDeathrattles(c.state.players[1].board[0],times=1000000)])
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'do')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_fixed_counts_rejected(self):
        for count in (0,-1,True,None,1.5,'2'):
            with self.subTest(count=count),self.assertRaises(ValueError):TriggerDeathrattles(1,times=count)

    def test_source_removed_in_first_round_does_not_change_accepted_plan(self):
        self.r.register_behavior('remove',lambda c:[GainArmor(1,1),*[Destroy(i) for i in c.state.players[1].board if c.state.entities[i].card_id=='baron']])
        self.minion('remover','remove');g=self.game(hand=('twice','twice'),board=('remover','baron'))
        self.invoke(g);self.assertEqual(self.armor(g),4);self.invoke(g);self.assertEqual(self.armor(g),6)
        self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[2,1]);self.check(g)

    def test_player_policy_removed_in_first_round_is_frozen(self):
        self.r.register_behavior('remove',lambda c:[GainArmor(1,1),*([RemovePlayerEffect(1,c.state.players[1].player_effects[0].id)] if c.state.players[1].player_effects else [])])
        self.minion('remover','remove');g=self.game(hand=('policy','twice'),board=('remover',));self.play(g,'policy');self.invoke(g)
        self.assertFalse(g.state.players[1].player_effects);self.assertEqual(self.armor(g),4);self.check(g)

    def test_policy_added_in_first_round_does_not_expand_batch(self):
        self.r.register_behavior('add',lambda c:[AddPlayerEffect(1,'policy',c.source_id),GainArmor(1,1)]);self.minion('adder','add')
        g=self.game(hand=('twice','twice'),board=('adder',));self.invoke(g);self.assertEqual(self.armor(g),2);self.invoke(g)
        self.assertEqual(self.armor(g),6);self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[1,2]);self.check(g)

    def test_carrier_lifecycle_does_not_cancel_accepted_rounds(self):
        for operation in (lambda i:ReturnToHand(i),lambda i:Transform(i,'body'),lambda i:Silence(i),lambda i:ChangeControl(i,2)):
            with self.subTest(operation=operation):
                self.setUp();self.r.register_behavior('change',lambda c:[GainArmor(c.player_id,1),operation(c.source_id)])
                self.minion('changer','change');g=self.game(board=('changer','baron'));self.invoke(g)
                self.assertEqual((self.armor(g),self.armor(g,2)),(4,0));self.check(g)

    def test_newly_granted_payload_does_not_enter_accepted_rounds(self):
        self.r.register_behavior('grant',lambda c:[GainArmor(1,1),GrantDeathrattle(c.source_id,'armor')]);self.minion('granter','grant')
        g=self.game(board=('granter',));self.invoke(g);self.assertEqual(self.armor(g),2)
        self.assertEqual(len(self.batch(g).abilities),1);self.assertEqual(len(g.state.entities[self.body(g,1)].abilities),3);self.check(g)

    def test_nested_natural_death_keeps_single_trigger_round(self):
        self.r.register_behavior('nested',lambda c:[GainArmor(1,1),*([Destroy(c.state.players[2].board[0])] if c.deathrattle.trigger_index==1 else [])])
        self.minion('nestedbody','nested');g=self.game(board=('nestedbody',),enemy=('rattle',));self.invoke(g)
        self.assertEqual([d.execution_order for d in self.records(g)],[1,3,2])
        self.assertEqual([b.trigger_count for b in g.state.deathrattle_batches],[2,1]);self.assertEqual((self.armor(g),self.armor(g,2)),(2,1));self.check(g)

    def test_no_deathrattle_payload_creates_no_empty_batch(self):
        g=self.game(board=('body',));self.invoke(g);self.assertFalse(g.state.deathrattle_batches);self.assertFalse(self.records(g));self.check(g)

    def test_dormant_carrier_does_not_trigger(self):
        from hs_sim.engine.dormancy import MakeDormant
        g=self.custom(lambda c:[MakeDormant(c.state.players[1].board[0],2),TriggerDeathrattles(c.state.players[1].board[0],times=2)])
        self.play(g,'do');self.assertFalse(self.records(g));self.check(g)

    def test_stale_carrier_is_not_a_new_fixed_group(self):
        g=self.custom(lambda c:[ReturnToHand(c.state.players[1].board[0]),TriggerDeathrattles(c.state.players[1].board[0],times=2)],('body','rattle'))
        # Both effects capture the same original ID before the return resolves.
        self.play(g,'do');self.assertFalse(self.records(g));self.check(g)

    def test_reborn_is_not_created_by_active_rounds(self):
        self.minion('reborn_rattle','armor',keywords=(Keyword.REBORN,));g=self.game(board=('reborn_rattle',));original=self.body(g,1);self.invoke(g)
        self.assertEqual(g.state.players[1].board,[original]);self.assertEqual(self.armor(g),2);self.assertFalse(g.state.death_history);self.check(g)

    def test_opponent_controller_receives_payload_and_repeat_policy(self):
        g=self.game(board=('body',),enemy=('rattle','baron'));self.play(g,'twice',self.body(g,2))
        self.assertEqual((self.armor(g),self.armor(g,2)),(0,4));self.assertEqual(self.batch(g).plan.contributors[0].player_id,2);self.check(g)

    def test_unspecified_effect_source_remains_unknown(self):
        g=self.custom(lambda c:[TriggerDeathrattles(c.state.players[1].board[0],times=2)]);self.play(g,'do')
        self.assertTrue(all(d.capture.trigger_source_id is None for d in self.records(g)));self.check(g)

    def test_unknown_effect_source_rolls_back(self):
        g=self.custom(lambda c:[TriggerDeathrattles(c.state.players[1].board[0],99999,times=2)]);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'do')
        self.assertEqual(g.snapshot(),before)

    def test_battlecry_repeat_creates_distinct_fixed_deathrattle_batches(self):
        self.r.register_behavior('cry',lambda c:[TriggerDeathrattles(c.target_id,c.source_id,times=2)])
        self.r.register_card(CardDefinition('caller','caller',CardType.MINION,health=3,battlecry='cry',targeting=TargetSpec()))
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=3,battlecry_repeats=(BattlecryRepeatSpec(),)))
        g=self.game(hand=('caller',),board=('rattle','baron','brann'));self.play(g,'caller',self.body(g,1))
        self.assertEqual(self.armor(g),8);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertEqual([b.trigger_count for b in g.state.deathrattle_batches],[2,2]);self.check(g)

    def test_normal_rewind_replaces_full_fixed_plan(self):
        self.script('rewinder',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id,times=2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewinder',),board=('rattle','baron'));self.play(g,'rewinder');c=g.state.pending_choice
        g.apply(SelectChoice(c.player_id,c.id,('retry',)));self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.deathrattle_batches),1);self.check(g)

    def test_retained_rewind_keeps_two_full_fixed_plans(self):
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.script('rewinder',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id,times=2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewinder',),board=('rattle','baron','retainer'));self.play(g,'rewinder')
        self.assertEqual(self.armor(g),8);self.assertEqual(len(g.state.deathrattle_batches),2);self.check(g)

    def test_malformed_trigger_count_is_rejected(self):
        g=self.waiting()
        for value in (0,-1,True,1,3):
            s=g.snapshot();s['state']['deathrattle_batches'][0]['trigger_count']=value
            with self.subTest(value=value):self.reject(s)

    def test_missing_duplicate_or_reindexed_round_is_rejected(self):
        g=self.waiting()
        for change in ('missing','duplicate','index','repeat','bool'):
            s=g.snapshot();rows=s['state']['deathrattle_history']
            if change=='missing':rows.pop()
            elif change=='duplicate':rows.append(rows[-1])
            elif change=='index':rows[2]['capture']['trigger_index']=1
            elif change=='repeat':rows[2]['capture']['repeat_index']=2
            else:rows[2]['capture']['trigger_index']=True
            with self.subTest(change=change):self.reject(s)

    def test_natural_death_cannot_have_second_trigger_index(self):
        g=self.game(hand=('kill',));self.play(g,'kill',self.body(g,1));s=g.snapshot()
        s['state']['deathrattle_history'][0]['capture']['trigger_index']=2;self.reject(s)

    def test_swapped_pending_rounds_are_rejected(self):
        g=self.waiting();s=g.snapshot();work=s['resolution_frame']['fields']['continuation']['tuple']
        positions=[i for i,w in enumerate(work) if w.get('type','').endswith('.InvokeDeathrattle')]
        a,b=positions[-2:];work[a],work[b]=work[b],work[a];self.reject(s)

    def test_missing_new_fields_are_not_silently_defaulted(self):
        g=self.waiting()
        for category,key in (('deathrattle_batches','trigger_count'),('deathrattle_history','trigger_index')):
            s=g.snapshot();row=s['state'][category][0];row=row['capture'] if category=='deathrattle_history' else row;del row[key];self.reject(s)

    def test_axes_are_not_added_to_player_information(self):
        g=self.waiting()
        for player in (1,2):
            text=json.dumps(g.observe(player))+json.dumps(g.player_events(player))
            self.assertNotIn('trigger_index',text);self.assertNotIn('trigger_count',text);self.assertNotIn('deathrattle_batches',text)

    def real_game(self,board=('GDB_100',),enemy=(),hand=('JAM_005',),registry=None):
        from hs_sim.engine.representative import build_registry
        self.r=registry or build_registry()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03',hand=hand,board=board,deck=('CS2_182',)*10,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=enemy,deck=('CS2_182',)*10,mana=10,max_mana=10)),seed=98),self.r)

    def test_real_yodeler_triggers_twice_and_pays_once(self):
        g=self.real_game();self.play(g,'JAM_005',self.body(g,1))
        self.assertEqual(self.armor(g),8);self.assertEqual(g.state.players[1].mana,6)
        self.assertEqual(len(g.state.play_history),1);self.assertEqual(len(g.state.battlecry_history),1)
        self.assertFalse(g.state.death_history);self.check(g)

    def test_real_metadata_has_two_classes_battlecry_and_no_own_deathrattle(self):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine import CardClass
        card=build_registry().card('JAM_005');self.assertEqual(set(card.metadata.classes),{CardClass.HUNTER,CardClass.DEATH_KNIGHT})
        self.assertEqual(card.metadata.tribes,('undead',));self.assertIsNotNone(card.battlecry);self.assertIsNone(card.deathrattle)

    def test_real_no_friendly_target_plays_without_an_empty_batch(self):
        g=self.real_game(board=());self.play(g,'JAM_005')
        self.assertEqual(g.state.players[1].mana,6);self.assertFalse(self.records(g));self.check(g)

    def test_real_non_deathrattle_friendly_target_is_allowed_by_r139(self):
        g=self.real_game(board=('CS2_182',));self.play(g,'JAM_005',self.body(g,1))
        self.assertFalse(g.state.deathrattle_batches);self.assertEqual(len(g.state.battlecry_history),1);self.check(g)

    def test_real_enemy_target_is_rejected_transactionally(self):
        from hs_sim.engine import IllegalAction
        g=self.real_game(enemy=('GDB_100',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'JAM_005',self.body(g,2))
        self.assertEqual(g.snapshot(),before)

    def test_real_existing_friendly_target_cannot_be_omitted(self):
        from hs_sim.engine import IllegalAction
        g=self.real_game();before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'JAM_005')
        self.assertEqual(g.snapshot(),before)

    def test_real_dormant_friendly_minion_is_not_a_target(self):
        from hs_sim.engine.dormancy import MakeDormant
        from hs_sim.engine.representative import build_registry
        r=build_registry();r.register_behavior('sleep',lambda c:[MakeDormant(c.state.players[1].board[0],2)])
        r.register_card(CardDefinition('sleep','sleep',CardType.SPELL,on_play='sleep'))
        g=self.real_game(hand=('sleep','JAM_005'),registry=r);self.play(g,'sleep');self.play(g,'JAM_005')
        self.assertFalse(self.records(g));self.check(g)

    def test_real_played_history_replay_keeps_fixed_count_and_new_source(self):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine.played_battlecries import RepeatPlayedBattlecry
        r=build_registry();r.register_behavior('replay',lambda c:[RepeatPlayedBattlecry(1,c.source_id,1,c.state.players[1].board[0],'explicit')])
        r.register_card(CardDefinition('replay','replay',CardType.MINION,health=3,battlecry='replay'))
        g=self.real_game(hand=('JAM_005','replay'),registry=r);self.play(g,'JAM_005',self.body(g,1));self.play(g,'replay')
        self.assertEqual(self.armor(g),16);self.assertEqual([b.trigger_count for b in g.state.deathrattle_batches],[2,2])
        self.assertEqual([d.capture.trigger_source_card_id for d in self.records(g)],['JAM_005']*2+['replay']*2);self.check(g)

    def test_native_fixed_repeat_and_starship_composition_restores_and_replays(self):
        from examples.fixed_deathrattles import run
        g,s=run();self.assertEqual(s['schema_version'],266);self.assertEqual(self.armor(g),48)
        self.assertEqual(len(self.records(g)),12);self.assertEqual(len(g.state.death_history),2)


if __name__=='__main__':unittest.main()
