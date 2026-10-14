"""R-138: player Deathrattle sources reuse public effects and owner clocks."""
import json
import unittest
from dataclasses import replace
import test_m5_deathrattle_repeats as base
from hs_sim.engine import (AddPlayerEffect,RemovePlayerEffect,PlayerEffectSpec,DeathrattleRepeatSpec,
    DeathrattlePlayerContributor,DeathrattleRepeatContributor,Game,Scenario,PlayerSetup,CardDefinition,
    CardType,EndTurn,TriggerSpec,Ruleset,IllegalAction,ResolutionError,Keyword,SelectChoice,RewindSpec)
from hs_sim.engine.effects import (TriggerDeathrattles,Destroy,Damage,DamageBatch,GainArmor,Silence,
    Transform,ReturnToHand,ChangeControl,EquipWeapon,GrantDeathrattle,RequestChoice,ChoiceOption)


class PlayerDeathrattleTests(unittest.TestCase):
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
        self.policy('permanent')
        self.policy('clock',kind='objective',duration=3,tick_event='turn_ended')
        self.policy('short',kind='objective',duration=1,tick_event='turn_ended')
        self.policy('start',kind='sigil',duration=1,tick_event='turn_started')
        self.policy('triple_policy',specs=(DeathrattleRepeatSpec(3),))
        self.policy('multi',specs=(DeathrattleRepeatSpec(),DeathrattleRepeatSpec(3)))
        self.policy('all_policy',specs=(DeathrattleRepeatSpec(kinds=(CardType.MINION,CardType.WEAPON,CardType.LOCATION)),))
        self.script('remove',lambda c:[RemovePlayerEffect(1,c.state.players[1].player_effects[0].id)])

    def policy(self,cid,specs=(DeathrattleRepeatSpec(),),kind='persistent',**kw):
        if kind=='persistent':self.script(cid,lambda c:[AddPlayerEffect(c.player_id,cid,c.source_id)])
        else:self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,ongoing_effect_id=cid))
        self.r.register_player_effect(PlayerEffectSpec(cid,cid,kind,deathrattle_repeats=specs,**kw))
    def game(self,hand=(),board=('rattle',),enemy=(),enemy_hand=(),weapon=None,rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('body',)*20,mana=10,max_mana=10,weapon_card_id=weapon),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('body',)*20,mana=10,max_mana=10)),seed=97),self.r,ruleset=rules)
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def effects(self,g,p=1):return g.state.players[p].player_effects
    def trigger(self,g,target=None):return self.play(g,'trigger',self.body(g,1) if target is None else target)
    def waiting(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))]);self.minion('waiter','wait')
        g=self.game(hand=('clock','trigger'),board=('waiter',));self.play(g,'clock');self.trigger(g);return g
    def end_listener(self,event='turn_ended',behavior='end_trigger'):
        self.r.register_behavior(behavior,lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id)] if c.event.player_id==1 else [])
        self.r.register_card(CardDefinition('listener','listener',CardType.MINION,health=3,triggers=(TriggerSpec(event,behavior),)))

    def test_permanent_source_repeats_natural_death(self):
        g=self.game(hand=('permanent','kill'));self.play(g,'permanent');self.play(g,'kill',self.body(g,1))
        self.assertEqual(self.armor(g),2);source=self.batch(g).plan.contributors[0]
        self.assertIsInstance(source,DeathrattlePlayerContributor);self.assertEqual(source.instance.source_card_id,'permanent');self.check(g)

    def test_timed_source_repeats_active_without_death(self):
        g=self.game(hand=('clock','trigger'));self.play(g,'clock');self.trigger(g)
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.death_history)
        self.assertEqual(self.batch(g).plan.contributors[0].instance.remaining_turns,3);self.check(g)

    def test_board_and_player_set_counts_merge_without_multiplication(self):
        g=self.game(hand=('clock','trigger'),board=('rattle','baron'));self.play(g,'clock');self.trigger(g)
        sources=self.batch(g).plan.contributors;self.assertEqual(self.armor(g),2)
        self.assertEqual({type(s) for s in sources},{DeathrattlePlayerContributor,DeathrattleRepeatContributor});self.check(g)

    def test_highest_player_and_board_count_wins(self):
        g=self.game(hand=('triple_policy','trigger'),board=('rattle','baron'));self.play(g,'triple_policy');self.trigger(g)
        self.assertEqual(self.armor(g),3);self.check(g)

    def test_two_instances_keep_distinct_identity_but_same_count(self):
        g=self.game(hand=('clock','clock','trigger'));self.play(g,'clock');self.play(g,'clock');self.trigger(g)
        self.assertEqual(self.armor(g),2);sources=self.batch(g).plan.contributors
        self.assertEqual(len({s.instance.id for s in sources}),2);self.check(g)

    def test_one_instance_can_declare_multiple_scopes(self):
        g=self.game(hand=('multi','trigger'));self.play(g,'multi');self.trigger(g);sources=self.batch(g).plan.contributors
        self.assertEqual([s.spec_index for s in sources],[0,1]);self.assertEqual(len({s.instance.id for s in sources}),1)
        self.assertEqual(self.armor(g),3);self.check(g)

    def test_three_owner_turn_ends_then_new_trigger_uses_one(self):
        g=self.game(hand=('clock','trigger','trigger','trigger','trigger'));self.play(g,'clock')
        for remaining in (3,2,1):
            self.assertEqual(self.effects(g)[0].remaining_turns,remaining);self.trigger(g);self.cycle(g)
        self.assertFalse(self.effects(g));self.trigger(g);self.assertEqual(self.armor(g),7);self.check(g)

    def test_opponent_turn_end_does_not_consume_owner_clock(self):
        g=self.game(hand=('clock',));self.play(g,'clock');g.apply(EndTurn(1));self.assertEqual(self.effects(g)[0].remaining_turns,2)
        g.apply(EndTurn(2));self.assertEqual(self.effects(g)[0].remaining_turns,2);self.check(g)

    def test_player_policy_works_for_deaths_on_opponents_turn(self):
        g=self.game(hand=('clock',),enemy_hand=('kill',));self.play(g,'clock');g.apply(EndTurn(1))
        self.play(g,'kill',self.body(g,1));self.assertEqual(self.armor(g),2);self.assertEqual(self.armor(g,2),0);self.check(g)

    def test_enemy_death_does_not_use_own_policy(self):
        g=self.game(hand=('clock','kill'),enemy=('rattle',));self.play(g,'clock');self.play(g,'kill',self.body(g,2))
        self.assertEqual(self.armor(g,2),1);self.assertFalse(self.batch(g).plan.contributors);self.check(g)

    def test_source_lifecycle_does_not_remove_player_policy(self):
        for operation in (lambda i:Destroy(i),lambda i:Silence(i),lambda i:Transform(i,'baron'),lambda i:ReturnToHand(i),lambda i:ChangeControl(i,2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.script('install',lambda c:[AddPlayerEffect(1,'permanent',c.state.players[1].board[1]),operation(c.state.players[1].board[1])])
                g=self.game(hand=('install','trigger'),board=('rattle','body'));self.play(g,'install');self.trigger(g)
                self.assertEqual(self.armor(g),2);source=next(s for s in self.batch(g).plan.contributors if type(s) is DeathrattlePlayerContributor)
                self.assertEqual(source.instance.source_card_id,'body');self.check(g)

    def test_player_source_survives_source_and_victim_same_death_batch(self):
        self.script('install',lambda c:[AddPlayerEffect(1,'permanent',c.state.players[1].board[1]),DamageBatch(tuple(Damage(i,10) for i in c.state.players[1].board))])
        g=self.game(hand=('install',),board=('rattle','body'));self.play(g,'install')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.death_history),2);self.check(g)

    def test_removal_mid_batch_keeps_repeat_but_new_batch_has_none(self):
        self.r.register_behavior('remove_policy',lambda c:[GainArmor(1,1),*([RemovePlayerEffect(1,c.state.players[1].player_effects[0].id)] if c.state.players[1].player_effects else [])])
        self.minion('remover','remove_policy');g=self.game(hand=('clock','trigger','trigger'),board=('remover',));self.play(g,'clock')
        self.trigger(g);self.assertEqual(self.armor(g),2);self.trigger(g);self.assertEqual(self.armor(g),3);self.check(g)

    def test_explicit_removal_changes_next_plan(self):
        g=self.game(hand=('clock','remove','trigger'));self.play(g,'clock');self.play(g,'remove');self.trigger(g)
        self.assertEqual(self.armor(g),1);self.assertFalse(self.batch(g).plan.contributors);self.check(g)

    def test_duplicate_clocks_expire_independently(self):
        g=self.game(hand=('clock','clock','trigger'));self.play(g,'clock');self.cycle(g);self.play(g,'clock')
        self.assertEqual([e.remaining_turns for e in self.effects(g)],[2,3]);self.cycle(g);self.cycle(g)
        self.assertEqual([e.remaining_turns for e in self.effects(g)],[1]);self.trigger(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_end_boundary_reactions_use_last_turn_before_expiry(self):
        self.end_listener();g=self.game(hand=('clock',),board=('rattle','listener'));self.play(g,'clock')
        for _ in range(3):self.cycle(g)
        self.assertFalse(self.effects(g));self.assertEqual(self.armor(g),6);self.cycle(g);self.assertEqual(self.armor(g),7);self.check(g)

    def test_start_boundary_reaction_uses_policy_before_guarded_expiry(self):
        self.end_listener('turn_started');g=self.game(hand=('start',),board=('rattle','listener'));self.play(g,'start');self.cycle(g)
        self.assertEqual(self.armor(g),2);self.assertFalse(self.effects(g));self.check(g)

    def test_expiry_payload_cannot_use_removed_policy(self):
        self.r.register_behavior('expire_trigger',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id)])
        self.policy('expiry',kind='objective',duration=1,tick_event='turn_ended',on_expire='expire_trigger')
        g=self.game(hand=('expiry',));self.play(g,'expiry');g.apply(EndTurn(1))
        self.assertEqual(self.armor(g),1);self.assertFalse(self.batch(g).plan.contributors);self.check(g)

    def test_policy_added_on_boundary_does_not_lose_a_turn(self):
        self.r.register_behavior('add_on_end',lambda c:[AddPlayerEffect(1,'clock',c.source_id)] if c.event.player_id==1 else [])
        self.r.register_card(CardDefinition('adder','adder',CardType.MINION,health=3,triggers=(TriggerSpec('turn_ended','add_on_end'),)))
        g=self.game(board=('rattle','adder'));g.apply(EndTurn(1));self.assertEqual(self.effects(g)[0].remaining_turns,3);self.check(g)

    def test_boundary_replacement_is_not_ticked_as_old_instance(self):
        self.r.register_behavior('replace_end',lambda c:[RemovePlayerEffect(1,c.state.players[1].player_effects[0].id),AddPlayerEffect(1,'clock',c.source_id)] if c.event.player_id==1 else [])
        self.r.register_card(CardDefinition('replacer','replacer',CardType.MINION,health=3,triggers=(TriggerSpec('turn_ended','replace_end'),)))
        g=self.game(hand=('short',),board=('rattle','replacer'));self.play(g,'short');old=self.effects(g)[0].id;g.apply(EndTurn(1))
        self.assertNotEqual(self.effects(g)[0].id,old);self.assertEqual(self.effects(g)[0].remaining_turns,3);self.check(g)

    def test_waiting_end_boundary_resumes_countdown_once(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))]);self.minion('waiter','wait');self.end_listener()
        g=self.game(hand=('short',),board=('waiter','listener'));self.play(g,'short');g.apply(EndTurn(1))
        self.assertEqual(self.effects(g)[0].remaining_turns,1);self.check(g);self.choose(g);self.check(g)
        self.choose(g);self.assertFalse(self.effects(g));self.assertEqual(g.state.active_player,2);self.assertEqual(self.armor(g),2);self.check(g)

    def test_mixed_source_pending_choices_restore_both_types(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))]);self.minion('waiter','wait')
        g=self.game(hand=('clock','trigger'),board=('waiter','baron'));self.play(g,'clock');self.trigger(g);self.check(g)
        self.choose(g);self.check(g);self.choose(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_weapon_and_location_scopes_use_player_specification(self):
        from hs_sim.engine.locations import DestroyLocation
        self.r.register_card(CardDefinition('rweapon','rweapon',CardType.WEAPON,attack=1,durability=2,deathrattle='armor'))
        self.r.register_behavior('use',lambda c:[]);self.r.register_card(CardDefinition('loc','loc',CardType.LOCATION,durability=2,on_use='use',deathrattle='armor'))
        self.script('destroy_both',lambda c:[EquipWeapon(1,'weapon'),DestroyLocation(c.state.players[1].board[0])])
        g=self.game(hand=('all_policy','destroy_both'),board=('loc',),weapon='rweapon');self.play(g,'all_policy');self.play(g,'destroy_both')
        self.assertEqual(self.armor(g),4);self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[2,2]);self.check(g)

    def test_minion_scope_does_not_extend_to_weapons(self):
        self.r.register_card(CardDefinition('rweapon','rweapon',CardType.WEAPON,attack=1,durability=2,deathrattle='armor'))
        self.script('replace',lambda c:[EquipWeapon(1,'weapon')]);g=self.game(hand=('clock','replace'),board=(),weapon='rweapon')
        self.play(g,'clock');self.play(g,'replace');self.assertEqual(self.armor(g),1);self.check(g)

    def test_full_ongoing_area_rejects_before_payment(self):
        g=self.game(hand=('clock','short'),rules=Ruleset(max_ongoing_effects=1));self.play(g,'clock');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'short')
        self.assertEqual(g.snapshot(),before)
        self.assertFalse(any(a['type']=='play_card' for a in g.for_player(1).legal_actions()['actions']))

    def test_permanent_effect_does_not_consume_ongoing_capacity(self):
        g=self.game(hand=('clock','permanent','trigger'),rules=Ruleset(max_ongoing_effects=1))
        self.play(g,'clock');self.play(g,'permanent');self.trigger(g);self.assertEqual(self.armor(g),2);self.assertEqual(len(self.effects(g)),2);self.check(g)

    def test_failed_effect_install_does_not_create_repeat_source(self):
        self.script('force',lambda c:[AddPlayerEffect(1,'short',c.source_id)])
        g=self.game(hand=('clock','force','trigger'),rules=Ruleset(max_ongoing_effects=1));self.play(g,'clock');self.play(g,'force');self.trigger(g)
        self.assertEqual(len(self.batch(g).plan.contributors),1);self.assertTrue(any(e.kind=='player_effect_failed' for e in g.events));self.check(g)

    def test_normal_rewind_does_not_duplicate_policy_or_plan(self):
        self.script('rewinder',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('clock','rewinder'));self.play(g,'clock');self.play(g,'rewinder');choice=g.state.pending_choice
        g.apply(SelectChoice(choice.player_id,choice.id,('retry',)));self.assertEqual(self.armor(g),2)
        self.assertEqual(len(g.state.deathrattle_batches),1);self.assertEqual(len(self.effects(g)),1);self.check(g)

    def test_retained_rewind_captures_same_live_policy_in_two_batches(self):
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.script('rewinder',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('clock','rewinder'),board=('rattle','retainer'));self.play(g,'clock');self.play(g,'rewinder')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.deathrattle_batches),2);self.assertEqual(len(self.effects(g)),1);self.check(g)

    def test_terminal_keeps_player_provenance_for_unstarted_repeat(self):
        self.r.register_behavior('fatal',lambda c:[Damage(c.state.players[2].hero_id,40)]);self.minion('fatalbody','fatal')
        g=self.game(hand=('clock','trigger'),board=('fatalbody',));self.play(g,'clock');self.trigger(g)
        self.assertEqual([d.execution_order for d in self.records(g)],[1,None]);self.check(g)

    def test_second_iteration_failure_rolls_back_policy_state(self):
        def fail(c):
            if c.deathrattle.repeat_index==2:raise ValueError('second failed')
            return [RemovePlayerEffect(1,c.state.players[1].player_effects[0].id)]
        self.r.register_behavior('fail',fail);self.minion('bad','fail');g=self.game(hand=('clock','trigger'),board=('bad',));self.play(g,'clock');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.trigger(g)
        self.assertEqual(g.snapshot(),before)

    def test_malformed_player_contributor_is_rejected(self):
        g=self.waiting()
        for field,value in (('spec_index',1),('spec_index',True),('player_id',2)):
            s=g.snapshot();s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['contributors'][0][field]=value
            with self.subTest(field=field,value=value):self.reject(s)

    def test_captured_player_instance_identity_and_duration_are_checked(self):
        g=self.waiting()
        for field,value in (('id',99999),('spec_id','missing'),('created_turn',99),('remaining_turns',4),('remaining_turns',None),('source_id',99999),('entered_order',99999)):
            s=g.snapshot();s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['contributors'][0]['instance'][field]=value
            with self.subTest(field=field,value=value):self.reject(s)

    def test_captured_spec_cannot_be_changed_to_another_valid_scope(self):
        g=self.waiting();s=g.snapshot();s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['contributors'][0]['spec']['kinds']=['weapon'];self.reject(s)

    def test_duplicate_contributor_position_rejected(self):
        g=self.waiting();s=g.snapshot();sources=s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['contributors'];sources.append(sources[0]);self.reject(s)

    def test_invalid_player_effect_repeat_declarations_rejected(self):
        for specs in ([],(None,),('two',)):
            with self.subTest(specs=specs),self.assertRaises(ValueError):PlayerEffectSpec('bad','body',deathrattle_repeats=specs)

    def test_player_projection_keeps_public_clock_without_diagnostic_sources(self):
        g=self.game(hand=('clock','trigger'));self.play(g,'clock');self.trigger(g)
        text=json.dumps(g.observe(1))+json.dumps(g.observe(2))+json.dumps(g.player_events(1))
        self.assertIn('remaining_turns',text);self.assertNotIn('deathrattle_batches',text);self.assertNotIn('spec_index',text);self.assertNotIn('DeathrattlePlayerContributor',text)

    def test_registry_fingerprint_includes_player_repeat_specifications(self):
        first=self.r.fingerprint();self.policy('extra',specs=(DeathrattleRepeatSpec(3),));self.assertNotEqual(first,self.r.fingerprint())

    def test_policy_added_by_payload_only_changes_later_batches(self):
        self.r.register_behavior('create',lambda c:[AddPlayerEffect(1,'clock',c.source_id),GainArmor(1,1)])
        self.minion('creator','create');g=self.game(hand=('trigger','trigger'),board=('creator',))
        self.trigger(g);self.assertEqual(self.armor(g),1);self.trigger(g)
        self.assertEqual(self.armor(g),3);self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[1,2]);self.check(g)

    def test_stronger_policy_mid_execution_does_not_expand_accepted_batch(self):
        self.r.register_behavior('upgrade',lambda c:[AddPlayerEffect(1,'triple_policy',c.source_id),GainArmor(1,1)])
        self.minion('upgrader','upgrade');g=self.game(hand=('clock','trigger','trigger'),board=('upgrader',));self.play(g,'clock')
        self.trigger(g);self.assertEqual(self.armor(g),2);self.trigger(g)
        self.assertEqual(self.armor(g),5);self.assertEqual([b.plan.repetitions for b in g.state.deathrattle_batches],[2,3]);self.check(g)

    def test_player_repeat_preserves_printed_and_granted_ability_order(self):
        self.script('grant',lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor',c.source_id)])
        g=self.game(hand=('clock','grant','trigger'));self.play(g,'clock');self.play(g,'grant');self.trigger(g)
        rows=self.records(g);self.assertEqual([(d.capture.ability.origin,d.capture.repeat_index) for d in rows],
            [('printed',1),('printed',2),('granted',1),('granted',2)])
        self.assertEqual(len({d.capture.ability.id for d in rows}),2);self.assertEqual(self.armor(g),4);self.check(g)

    def test_pending_second_iteration_restores_after_policy_removal(self):
        self.r.register_behavior('remove_wait',lambda c:[*([RemovePlayerEffect(1,c.state.players[1].player_effects[0].id)]
            if c.state.players[1].player_effects else []),self.pause(c,GainArmor(1,1))])
        self.minion('removewait','remove_wait');g=self.game(hand=('clock','trigger'),board=('removewait',))
        self.play(g,'clock');self.trigger(g);self.assertFalse(self.effects(g));self.check(g)
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        self.choose(g);self.assertEqual(self.armor(g),2);self.check(g)

    def real_game(self,hand=('AV_400',),board=('CATA_150','CATA_150t','CATA_150t1'),enemy_hand=()):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03',hand=hand,board=board,deck=('CS2_182',)*12,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=('CS2_182',)*12,mana=10,max_mana=10)),seed=97),self.r)

    def test_native_snowfall_duration_composition_restores_and_replays(self):
        from examples.deathrattle_player_effects import run
        g,s=run();self.assertEqual(s['schema_version'],265)
        self.assertEqual(len(self.records(g)),14);self.assertFalse(self.effects(g));self.assertEqual(len(g.state.death_history),1)

    def test_real_snowfall_and_baron_use_same_set_count(self):
        g=self.real_game(board=('CATA_150','CATA_150t','CATA_150t1','FP1_031'));self.play(g,'AV_400');g.apply(EndTurn(1))
        self.assertEqual(len(self.records(g)),4)
        for batch in g.state.deathrattle_batches:
            self.assertEqual(len(batch.plan.contributors),2);self.assertEqual(batch.plan.repetitions,2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,22);self.check(g)

    def test_real_counterspell_prevents_snowfall_policy_installation(self):
        g=self.real_game(board=(),enemy_hand=('EX1_287',));g.apply(EndTurn(1));self.play(g,'EX1_287');g.apply(EndTurn(2))
        self.play(g,'AV_400');self.assertFalse(self.effects(g));self.assertEqual(g.state.players[1].mana,5)
        self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_real_duplicate_snowfalls_have_separate_public_clocks(self):
        g=self.real_game(hand=('AV_400','AV_400'),board=());self.play(g,'AV_400');self.cycle(g);self.play(g,'AV_400')
        self.assertEqual([e.remaining_turns for e in self.effects(g)],[2,3]);self.cycle(g);self.cycle(g)
        self.assertEqual([e.remaining_turns for e in self.effects(g)],[1]);self.check(g)


if __name__=='__main__':unittest.main()
