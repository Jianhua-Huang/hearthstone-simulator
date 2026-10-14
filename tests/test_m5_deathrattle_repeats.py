"""R-137: frozen Deathrattle plans, separate iterations and recovery."""
import json
import unittest
from dataclasses import replace
import test_m5_deathrattle_activations as base
from hs_sim.engine import (CardDefinition,CardType,Keyword,Zone,Resource,EndTurn,
    DeathrattleRepeatSpec,DeathrattleRepeatPlan,GrantDeathrattleRepeatAura,ResolutionError,Ruleset,Game)
from hs_sim.engine.effects import (Damage,DamageBatch,Destroy,GrantDeathrattle,TriggerDeathrattles,
    GainArmor,Silence,Transform,ChangeControl,Summon,CopyMinion,ReturnToHand,EquipWeapon)


class DeathrattleRepeatTests(unittest.TestCase):
    script=base.DeathrattleActivationTests.script
    game=base.DeathrattleActivationTests.game
    play=base.DeathrattleActivationTests.play
    body=base.DeathrattleActivationTests.body
    check=base.DeathrattleActivationTests.check
    choose=base.DeathrattleActivationTests.choose
    reject=base.DeathrattleActivationTests.reject
    pause=base.DeathrattleActivationTests.pause
    minion=base.DeathrattleActivationTests.minion
    records=base.DeathrattleActivationTests.records
    armor=base.DeathrattleActivationTests.armor
    script_game=base.DeathrattleActivationTests.script_game
    invoke=base.DeathrattleActivationTests.invoke
    frames=base.DeathrattleActivationTests.frames

    def setUp(self):
        base.DeathrattleActivationTests.setUp(self)
        for cid,spec in [('baron',DeathrattleRepeatSpec()),('triple',DeathrattleRepeatSpec(3)),
                         ('all',DeathrattleRepeatSpec(kinds=(CardType.MINION,CardType.WEAPON,CardType.LOCATION)))]:
            self.r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=7,deathrattle_repeats=(spec,)))
    def batch(self,g,index=0):return g.state.deathrattle_batches[index]
    def kill_game(self,board=('rattle','baron'),enemy=()):
        return self.script_game(lambda c:[Destroy(c.state.players[1].board[0])],board,enemy)
    def waiting(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))]);self.minion('waiter','wait')
        g=self.kill_game(('waiter','baron'));self.invoke(g);return g

    def test_natural_death_repeats_without_another_death(self):
        g=self.kill_game();rows=self.invoke(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual([d.capture.repeat_index for d in rows],[1,2])
        self.assertEqual(len({d.capture.ability.id for d in rows}),1);self.assertTrue(all(d.completed for d in rows))
        self.check(g)

    def test_effect_trigger_repeats_without_death(self):
        g=self.game(hand=('trigger',),board=('rattle','baron'),enemy=());self.play(g,'trigger',self.body(g,1))
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.death_history)
        self.assertEqual({d.capture.origin for d in self.records(g)},{'effect'});self.check(g)

    def test_two_set_count_sources_do_not_multiply(self):
        g=self.kill_game(('rattle','baron','baron'));self.invoke(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(len(self.batch(g).plan.contributors),2);self.check(g)

    def test_highest_set_count_wins(self):
        g=self.kill_game(('rattle','baron','triple'));self.invoke(g)
        self.assertEqual(self.armor(g),3);self.assertEqual(self.batch(g).plan.repetitions,3);self.check(g)

    def test_enemy_source_does_not_contribute(self):
        g=self.kill_game(('rattle',),('baron',));self.invoke(g)
        self.assertEqual(self.armor(g),1);self.assertFalse(self.batch(g).plan.contributors);self.check(g)

    def test_source_and_victim_simultaneous_death_excludes_source(self):
        g=self.script_game(lambda c:[DamageBatch(tuple(Damage(i,10) for i in c.state.players[1].board))],('rattle','baron'))
        self.invoke(g);self.assertEqual(self.armor(g),1);self.assertEqual(len(g.state.death_history),2);self.check(g)

    def test_source_disabled_before_acceptance(self):
        for operation in (lambda i:Silence(i),lambda i:Transform(i,'body'),lambda i:Destroy(i),lambda i:ReturnToHand(i)):
            with self.subTest(operation=operation):
                self.setUp()
                g=self.script_game(lambda c:[operation(c.state.players[1].board[1]),Destroy(c.state.players[1].board[0])],('rattle','baron'))
                self.invoke(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_source_control_change_affects_new_plan(self):
        g=self.script_game(lambda c:[ChangeControl(c.state.players[1].board[1],2),Destroy(c.state.players[1].board[0]),
                                   Destroy(c.state.players[2].board[0])],('rattle','baron'),('rattle',))
        self.invoke(g);self.assertEqual((self.armor(g,1),self.armor(g,2)),(1,2));self.check(g)

    def test_first_iteration_removes_source_without_losing_accepted_repeat(self):
        self.r.register_behavior('remove',lambda c:[GainArmor(1,1),*(
            [Destroy(i) for i in c.state.players[1].board if c.state.entities[i].card_id=='baron'])])
        self.minion('remover','remove');g=self.kill_game(('remover','baron'));self.invoke(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(self.batch(g).plan.contributors[0].card_id,'baron');self.check(g)

    def test_first_iteration_transforms_source_keeps_captured_card(self):
        self.r.register_behavior('change',lambda c:[GainArmor(1,1),Transform(c.state.players[1].board[0],'body')])
        self.minion('changer','change');g=self.kill_game(('changer','baron'));self.invoke(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(self.batch(g).plan.contributors[0].card_id,'baron');self.check(g)

    def test_source_summoned_by_deathrattle_does_not_retroactively_repeat(self):
        self.r.register_behavior('addbaron',lambda c:[Summon(c.player_id,'baron'),GainArmor(1,1)])
        self.minion('creator','addbaron');g=self.kill_game(('creator',));self.invoke(g)
        self.assertEqual(self.armor(g),1);self.assertEqual(self.batch(g).plan.repetitions,1);self.check(g)

    def test_extra_iteration_reads_updated_world(self):
        self.r.register_behavior('grow',lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].armor+1)])
        self.minion('grower','grow');g=self.kill_game(('grower','baron'));self.invoke(g)
        self.assertEqual(self.armor(g),3);self.check(g)

    def test_each_ability_repeats_before_next_ability(self):
        self.r.register_behavior('grow',lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].armor+1)])
        self.r.register_behavior('ten',lambda c:[GainArmor(1,10)]);self.minion('grower','grow')
        g=self.script_game(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'ten'),Destroy(c.state.players[1].board[0])],('grower','baron'))
        rows=self.invoke(g);self.assertEqual(self.armor(g),23)
        self.assertEqual([(d.capture.ability.behavior_id,d.capture.repeat_index) for d in rows],[('grow',1),('grow',2),('ten',1),('ten',2)])
        self.check(g)

    def test_identical_grants_each_have_two_positions(self):
        g=self.script_game(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),GrantDeathrattle(c.state.players[1].board[0],'armor'),
                                   Destroy(c.state.players[1].board[0])],('body','baron'))
        rows=self.invoke(g);self.assertEqual(self.armor(g),4);self.assertEqual(len({d.capture.ability.id for d in rows}),2);self.check(g)

    def test_reborn_occurs_once_after_both_iterations(self):
        self.minion('reborn_rattle','armor',keywords=(Keyword.REBORN,));g=self.kill_game(('reborn_rattle','baron'));old=self.body(g,1)
        self.invoke(g);self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.death_history),1)
        self.assertNotIn(old,g.state.players[1].board);self.assertEqual(len(g.state.players[1].board),2);self.check(g)

    def test_minion_only_policy_does_not_repeat_weapon(self):
        self.r.register_card(CardDefinition('rweapon','rweapon',CardType.WEAPON,attack=1,durability=2,deathrattle='armor'))
        g=self.script_game(lambda c:[EquipWeapon(1,'weapon')],('baron',),weapon='rweapon');self.invoke(g)
        self.assertEqual(self.armor(g),1);self.check(g)

    def test_explicit_weapon_scope_repeats_replaced_weapon(self):
        self.r.register_card(CardDefinition('rweapon','rweapon',CardType.WEAPON,attack=1,durability=2,deathrattle='armor'))
        g=self.script_game(lambda c:[EquipWeapon(1,'weapon')],('all',),weapon='rweapon');self.invoke(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(self.records(g)[0].capture.kind,CardType.WEAPON);self.check(g)

    def test_explicit_location_scope_repeats_location(self):
        from hs_sim.engine.locations import DestroyLocation
        self.r.register_behavior('use',lambda c:[])
        self.r.register_card(CardDefinition('loc','loc',CardType.LOCATION,durability=2,on_use='use',deathrattle='armor'))
        g=self.script_game(lambda c:[DestroyLocation(c.state.players[1].board[0])],('loc','all'));self.invoke(g)
        self.assertEqual(self.armor(g),2);self.check(g)

    def test_granted_source_expires_using_existing_lifecycle(self):
        self.script('grant',lambda c:[GrantDeathrattleRepeatAura(c.target_id,source_id=c.source_id,expires_turn=1)],target=True)
        g=self.game(hand=('grant','trigger','trigger'),board=('rattle','body'),enemy=());self.play(g,'grant',self.body(g,1,1))
        self.play(g,'trigger',self.body(g,1));self.assertEqual(self.armor(g),2)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'trigger',self.body(g,1));self.assertEqual(self.armor(g),3);self.check(g)

    def test_current_copy_of_aura_has_independent_source_identity(self):
        g=self.script_game(lambda c:[CopyMinion(c.state.players[1].board[1],1),Destroy(c.state.players[1].board[0])],('rattle','baron'))
        self.invoke(g);sources=self.batch(g).plan.contributors
        self.assertEqual(len(sources),2);self.assertEqual(len({s.ability.id for s in sources}),2);self.assertEqual(self.armor(g),2);self.check(g)

    def test_active_carrier_transforms_during_first_repeat(self):
        self.r.register_behavior('selfchange',lambda c:[GainArmor(1,1),Transform(c.source_id,'body')])
        self.minion('changer','selfchange');g=self.game(hand=('trigger',),board=('changer','baron'),enemy=())
        self.play(g,'trigger',self.body(g,1));self.assertEqual(self.armor(g),2);self.assertFalse(g.state.death_history);self.check(g)

    def test_active_carrier_leaves_during_first_repeat(self):
        self.r.register_behavior('bounce',lambda c:[GainArmor(1,1),ReturnToHand(c.source_id)])
        self.minion('bouncer','bounce');g=self.game(hand=('trigger',),board=('bouncer','baron'),enemy=())
        self.play(g,'trigger',self.body(g,1));self.assertEqual(self.armor(g),2);self.check(g)

    def test_independent_choices_and_restore_between_iterations(self):
        g=self.waiting();self.assertEqual([d.execution_order for d in self.records(g)],[1,None]);self.check(g)
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.armor(g),1);self.check(g)
        self.choose(g);self.assertIsNone(g.state.pending_choice);self.assertEqual(self.armor(g),2);self.check(g)

    def test_second_iteration_error_rolls_back_whole_action(self):
        def fail(c):
            if c.deathrattle.repeat_index==2:raise ValueError('second repetition failed')
            return [GainArmor(1,1)]
        self.r.register_behavior('bad',fail);self.minion('badbody','bad');g=self.kill_game(('badbody','baron'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'second repetition failed'):self.invoke(g)
        self.assertEqual(g.snapshot(),before)

    def test_terminal_interrupt_keeps_unstarted_positions(self):
        self.r.register_behavior('fatal',lambda c:[Damage(c.state.players[2].hero_id,40)])
        self.minion('fatalbody','fatal');g=self.kill_game(('fatalbody','baron'));rows=self.invoke(g)
        self.assertEqual([d.execution_order for d in rows],[1,None]);self.assertTrue(all(d.interrupted for d in rows));self.check(g)

    def test_terminal_before_batch_execution_keeps_both_positions(self):
        g=self.script_game(lambda c:[DamageBatch((Damage(c.state.players[1].board[0],10),Damage(c.state.players[2].hero_id,40)))],('rattle','baron'))
        rows=self.invoke(g);self.assertEqual([d.execution_order for d in rows],[None,None]);self.assertTrue(all(d.interrupted for d in rows));self.check(g)

    def test_oversized_repeat_rejected_before_allocating_plan(self):
        self.r.register_card(CardDefinition('huge','huge',CardType.MINION,health=5,deathrattle_repeats=(DeathrattleRepeatSpec(100000),)))
        g=self.kill_game(('rattle','huge'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.invoke(g)
        self.assertEqual(g.snapshot(),before)

    def test_duplicate_or_missing_repeat_positions_rejected(self):
        g=self.waiting()
        for change in ('missing','duplicate','index','group'):
            s=g.snapshot();rows=s['state']['deathrattle_history']
            if change=='missing':rows.pop()
            elif change=='duplicate':rows.append(rows[-1])
            elif change=='index':rows[1]['capture']['repeat_index']=1
            else:rows[1]['capture']['group_id']=2
            with self.subTest(change=change):self.reject(s)

    def test_inconsistent_or_missing_batch_rejected(self):
        g=self.waiting()
        for change in ('missing','count','ability','source','scope'):
            s=g.snapshot();batches=s['state']['deathrattle_batches'];b=batches[0]
            if change=='missing':batches.clear()
            elif change=='count':b['payloads'][0]['plan']['repetitions']=3
            elif change=='ability':b['payloads'].clear()
            elif change=='source':b['payloads'][0]['plan']['contributors'][0]['carrier_id']=99999
            else:b['payloads'][0]['plan']['contributors'][0]['ability']['deathrattle_repeat']['kinds']=['weapon']
            with self.subTest(change=change):self.reject(s)

    def test_saved_plan_cannot_disagree_with_pending_context(self):
        g=self.waiting();s=g.snapshot();source=s['state']['deathrattle_batches'][0]['payloads'][0]['plan']['contributors'][0]
        source['card_id']='triple';self.reject(s)

    def test_reordered_pending_iterations_rejected(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))]);self.minion('waiter','wait')
        g=self.kill_game(('waiter','triple'));self.invoke(g);s=g.snapshot()
        work=s['resolution_frame']['fields']['continuation']['tuple']
        positions=[i for i,w in enumerate(work) if w.get('type','').endswith('.InvokeDeathrattle')]
        self.assertEqual(len(positions),2);a,b=positions;work[a],work[b]=work[b],work[a];self.reject(s)

    def test_batch_data_is_not_player_information(self):
        g=self.waiting()
        for p in (1,2):
            text=json.dumps(g.observe(p),ensure_ascii=False)+json.dumps(g.player_events(p),ensure_ascii=False)
            self.assertNotIn('deathrattle_batches',text);self.assertNotIn('contributors',text);self.assertNotIn('repeat_index',text)

    def test_invalid_specifications_and_carriers_rejected(self):
        for kw in ({'repetitions':True},{'repetitions':1},{'kinds':()},{'kinds':(CardType.SPELL,)},{'kinds':(CardType.MINION,CardType.MINION)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):DeathrattleRepeatSpec(**kw)
        with self.assertRaises(ValueError):DeathrattleRepeatPlan(2)
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.SPELL,deathrattle_repeats=(DeathrattleRepeatSpec(),)))

    def test_unknown_grant_source_rolls_back(self):
        g=self.script_game(lambda c:[GrantDeathrattleRepeatAura(c.state.players[1].board[0],source_id=99999)],('body',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.invoke(g)
        self.assertEqual(g.snapshot(),before)

    def test_nested_death_has_its_own_plan_and_execution_order(self):
        self.r.register_behavior('nested',lambda c:[GainArmor(1,1),*([Destroy(c.state.players[2].board[0])] if c.deathrattle.repeat_index==1 else [])])
        self.minion('nestedbody','nested');g=self.kill_game(('nestedbody','baron'),('rattle','baron'));self.invoke(g)
        self.assertEqual([d.execution_order for d in self.records(g)],[1,4,2,3])
        self.assertEqual((self.armor(g,1),self.armor(g,2)),(2,2));self.check(g)

    def test_dormant_source_does_not_contribute(self):
        from hs_sim.engine.dormancy import MakeDormant
        g=self.script_game(lambda c:[MakeDormant(c.state.players[1].board[1],2),Destroy(c.state.players[1].board[0])],('rattle','baron'))
        self.invoke(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_control_change_mid_repeat_keeps_accepted_controller(self):
        self.r.register_behavior('switch',lambda c:[GainArmor(c.player_id,1),ChangeControl(c.source_id,2)])
        self.minion('switcher','switch');g=self.game(hand=('trigger',),board=('switcher','baron'),enemy=())
        self.play(g,'trigger',self.body(g,1));self.assertEqual((self.armor(g,1),self.armor(g,2)),(2,0));self.check(g)

    def test_normal_rewind_replaces_plan_and_both_activations(self):
        from hs_sim.engine import RewindSpec,SelectChoice
        self.script('rewinder',lambda c:[Destroy(c.state.players[1].board[0])],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewinder',),board=('rattle','baron'),enemy=());self.play(g,'rewinder');self.check(g)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('retry',)))
        self.assertEqual(len(self.records(g)),2);self.assertEqual(len(g.state.deathrattle_batches),1);self.assertEqual(self.armor(g),2);self.check(g)

    def test_retained_rewind_combines_two_separate_repeat_batches(self):
        from hs_sim.engine import RewindSpec
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.script('rewinder',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewinder',),board=('rattle','baron','retainer'),enemy=());self.play(g,'rewinder')
        self.assertEqual([d.capture.group_id for d in self.records(g)],[1,1,3,3]);self.assertEqual(self.armor(g),4);self.check(g)

    def test_magnetic_deathrattle_repeats_same_inherited_attachment(self):
        from hs_sim.engine import CardMetadata,CardClass,PlayCard
        metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.minion('part','armor',keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),metadata=metadata)
        self.r.register_card(CardDefinition('host','host',CardType.MINION,health=4,metadata=metadata))
        g=self.game(hand=('part','kill'),board=('host','baron'),enemy=());part=g.state.players[1].hand[0]
        g.apply(PlayCard(1,part,position=0));self.play(g,'kill',self.body(g,1));a,b=self.records(g)
        self.assertEqual(a.capture.ability,b.capture.ability);self.assertEqual(a.capture.ability.deathrattle_card_id,'part')
        self.assertEqual(self.armor(g),2);self.check(g)

    def test_real_starship_component_repeats_but_contributes_once(self):
        from hs_sim.engine import Scenario,PlayerSetup,LaunchStarship
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine.starships import construction
        from examples.colossal_appendages import submit
        self.r=build_registry()
        g=Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',board=('GDB_100','FP1_031'),hand=('CS2_029',),deck=('CS2_182',)*4,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_182',)*4,mana=10,max_mana=10)),seed=96),self.r)
        submit(g,'CS2_029','GDB_100');ship=construction(g.state,1)
        self.assertEqual(ship.components,('GDB_100',));self.assertEqual(self.armor(g),8)
        g.apply(LaunchStarship(1,ship.id));submit(g);submit(g,'CS2_029',g.state.entities[ship.id].card_id)
        self.assertEqual(self.armor(g),16);self.assertEqual(len(g.state.death_history),2)
        rows=[d for d in self.records(g) if d.capture.carrier_id==ship.id]
        self.assertEqual(len(rows),2);self.assertEqual(rows[0].capture.ability.deathrattle_card_id,'GDB_100');self.check(g)

    def test_real_baron_is_an_aura_not_a_deathrattle(self):
        from hs_sim.engine.representative import build_registry
        card=build_registry().card('FP1_031')
        self.assertIsNone(card.deathrattle);self.assertEqual(card.deathrattle_repeats,(DeathrattleRepeatSpec(),))

    def test_native_representative_composition_restores_and_replays(self):
        from examples.deathrattle_repeats import run
        g,s=run();self.assertEqual(s['schema_version'],265)
        self.assertEqual(len(g.state.deathrattle_history),8);self.assertEqual(len(g.state.death_history),1)

    def test_waiting_second_iteration_preserves_source_removed_by_first(self):
        def work(c):
            return [*[Destroy(i) for i in c.state.players[1].board if c.state.entities[i].card_id=='baron'],self.pause(c,GainArmor(1,1))]
        self.r.register_behavior('wait_remove',work);self.minion('waitremove','wait_remove')
        g=self.kill_game(('waitremove','baron'));self.invoke(g);self.check(g)
        self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        self.choose(g);self.assertEqual(self.armor(g),2);self.check(g)


if __name__=='__main__':unittest.main()
