"""R-140: carrier-local policies, payload origins and nonuniform repeat plans."""
import json
import unittest
import test_m5_fixed_deathrattles as base
from hs_sim.engine import (Game,Scenario,PlayerSetup,CardDefinition,CardType,Keyword,Resource,EndTurn,
    DeathrattleRepeatSpec,GrantDeathrattleRepeatAura,PlayerEffectSpec,AddPlayerEffect,RewindSpec,
    SelectChoice,ResolutionError,CardMetadata,CardClass,PlayCard)
from hs_sim.engine.effects import (GrantDeathrattle,TriggerDeathrattles,GainArmor,Destroy,DamageBatch,Damage,
    Silence,Transform,ReturnToHand,CopyMinion,ChangeControl)


class ScopedDeathrattleTests(unittest.TestCase):
    script=base.FixedDeathrattleTests.script
    play=base.FixedDeathrattleTests.play
    body=base.FixedDeathrattleTests.body
    check=base.FixedDeathrattleTests.check
    choose=base.FixedDeathrattleTests.choose
    reject=base.FixedDeathrattleTests.reject
    pause=base.FixedDeathrattleTests.pause
    minion=base.FixedDeathrattleTests.minion
    records=base.FixedDeathrattleTests.records
    armor=base.FixedDeathrattleTests.armor
    frames=base.FixedDeathrattleTests.frames
    batch=base.FixedDeathrattleTests.batch
    game=base.FixedDeathrattleTests.game
    custom=base.FixedDeathrattleTests.custom

    def setUp(self):
        base.FixedDeathrattleTests.setUp(self)
        self.scope=DeathrattleRepeatSpec(scope='self',origins=('granted',))
        self.minion('selfbody','armor',deathrattle_repeats=(self.scope,))
        self.r.register_card(CardDefinition('selfonly','selfonly',CardType.MINION,health=3,deathrattle_repeats=(self.scope,)))
        self.script('grant',lambda c:[GrantDeathrattle(c.target_id,'armor',c.source_id)],target=True)
    def mixed(self,operation='kill',board=('selfbody',),extra=()):
        g=self.game(hand=('grant',operation,*extra),board=board);i=self.body(g,1);self.play(g,'grant',i);self.play(g,operation,i);return g
    def counts(self,g,index=0):return [p.plan.repetitions for p in self.batch(g,index).payloads]
    def waiting(self):
        self.r.register_behavior('wait',lambda c:[self.pause(c,GainArmor(1,1))])
        self.minion('selfwait','wait',deathrattle_repeats=(self.scope,))
        self.script('grant_wait',lambda c:[GrantDeathrattle(c.target_id,'wait',c.source_id)],target=True)
        g=self.game(hand=('grant_wait','twice'),board=('selfwait',));self.play(g,'grant_wait',self.body(g,1));self.play(g,'twice',self.body(g,1));return g

    def test_natural_death_uses_frozen_self_source_and_distinct_payload_counts(self):
        g=self.mixed();self.assertEqual(self.armor(g),3);self.assertEqual(self.counts(g),[1,2])
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual(self.batch(g).payloads[1].plan.contributors[0].carrier_id,g.state.death_history[0].entity_id);self.check(g)

    def test_fixed_active_rounds_preserve_nonuniform_positions(self):
        g=self.mixed('twice');self.assertEqual(self.armor(g),6);self.assertFalse(g.state.death_history)
        self.assertEqual([(d.capture.trigger_index,d.capture.ability.origin,d.capture.repeat_index) for d in self.records(g)],
            [(t,o,r) for t in (1,2) for o,rs in [('printed',(1,)),('granted',(1,2))] for r in rs]);self.check(g)

    def test_self_scope_does_not_repeat_neighbor_payloads(self):
        g=self.mixed(board=('rattle','selfonly'));self.assertEqual(self.armor(g),2);self.assertEqual(self.counts(g),[1,1]);self.check(g)

    def test_duplicate_grants_keep_independent_repeated_payloads(self):
        g=self.game(hand=('grant','grant','kill'),board=('selfbody',));i=self.body(g,1)
        self.play(g,'grant',i);self.play(g,'grant',i);self.play(g,'kill',i)
        self.assertEqual(self.armor(g),5);self.assertEqual(self.counts(g),[1,2,2]);self.assertEqual(len({d.capture.ability.id for d in self.records(g)}),3);self.check(g)

    def test_external_and_self_set_counts_merge_per_payload(self):
        strong=DeathrattleRepeatSpec(3,scope='self',origins=('granted',))
        self.minion('strong','armor',deathrattle_repeats=(strong,));g=self.mixed(board=('strong','baron'))
        self.assertEqual(self.armor(g),5);self.assertEqual(self.counts(g),[2,3]);self.check(g)

    def test_player_and_self_sources_merge_without_multiplication(self):
        g=self.game(hand=('policy','grant','kill'),board=('selfbody',));self.play(g,'policy');i=self.body(g,1)
        self.play(g,'grant',i);self.play(g,'kill',i);self.assertEqual(self.armor(g),4);self.assertEqual(self.counts(g),[2,2]);self.check(g)

    def test_friendly_origin_filter_applies_to_each_payload(self):
        self.r.register_card(CardDefinition('filter','filter',CardType.MINION,health=4,
            deathrattle_repeats=(DeathrattleRepeatSpec(3,origins=('granted',)),)))
        g=self.mixed(board=('rattle','filter'));self.assertEqual(self.armor(g),4);self.assertEqual(self.counts(g),[1,3]);self.check(g)

    def test_explicit_printed_only_self_scope_does_not_repeat_grants(self):
        self.minion('printedonly','armor',deathrattle_repeats=(DeathrattleRepeatSpec(scope='self',origins=('printed',)),))
        g=self.mixed(board=('printedonly',));self.assertEqual(self.armor(g),3);self.assertEqual(self.counts(g),[2,1]);self.check(g)

    def test_simultaneous_death_retains_self_but_excludes_dying_board_aura(self):
        g=self.custom(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),DamageBatch(tuple(Damage(i,20) for i in c.state.players[1].board))],('selfbody','baron'))
        self.play(g,'do');self.assertEqual(self.armor(g),3);self.assertEqual(self.counts(g),[1,2]);self.assertEqual(len(g.state.death_history),2);self.check(g)

    def test_current_copy_binds_self_policy_to_new_carrier(self):
        self.script('copy',lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),CopyMinion(c.state.players[1].board[0],1)])
        self.script('killall',lambda c:[Destroy(i) for i in c.state.players[1].board])
        g=self.game(hand=('copy','killall'),board=('selfbody',));self.play(g,'copy');self.play(g,'killall')
        self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.death_history),2)
        for b,d in zip(g.state.deathrattle_batches,g.state.death_history):self.assertEqual(b.payloads[1].plan.contributors[0].carrier_id,d.entity_id)
        self.check(g)

    def test_silence_then_new_grant_does_not_restore_self_policy(self):
        g=self.custom(lambda c:[Silence(c.state.players[1].board[0]),GrantDeathrattle(c.state.players[1].board[0],'armor'),Destroy(c.state.players[1].board[0])],('selfbody',))
        self.play(g,'do');self.assertEqual(self.armor(g),1);self.assertEqual(self.counts(g),[1]);self.check(g)

    def test_transform_rebuilds_policy_and_discards_old_grants(self):
        g=self.custom(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),Transform(c.state.players[1].board[0],'selfbody'),Destroy(c.state.players[1].board[0])],('selfbody',))
        self.play(g,'do');self.assertEqual(self.armor(g),1);self.assertEqual(self.counts(g),[1]);self.check(g)

    def test_return_and_replay_rebuild_base_without_old_grants(self):
        self.script('bounce',lambda c:[ReturnToHand(c.target_id)],target=True)
        g=self.game(hand=('grant','bounce','kill'),board=('selfbody',));i=self.body(g,1)
        self.play(g,'grant',i);self.play(g,'bounce',i);self.play(g,'selfbody');self.play(g,'kill',i)
        self.assertEqual(self.armor(g),1);self.check(g)

    def test_reborn_reconstructs_self_policy_without_granted_payload(self):
        self.minion('rebornself','armor',keywords=(Keyword.REBORN,),deathrattle_repeats=(self.scope,))
        g=self.mixed(board=('rebornself',),extra=('trigger',));new=self.body(g,1);self.play(g,'trigger',new)
        self.assertEqual(self.armor(g),4);self.assertEqual([self.counts(g,i) for i in range(2)],[[1,2],[1]]);self.check(g)

    def test_temporary_self_policy_expiry_changes_new_plan(self):
        self.script('temporary',lambda c:[GrantDeathrattleRepeatAura(c.target_id,self.scope,c.source_id,expires_turn=1),GrantDeathrattle(c.target_id,'armor')],target=True)
        g=self.game(hand=('temporary','kill'),board=('rattle',));i=self.body(g,1);self.play(g,'temporary',i);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'kill',i)
        self.assertEqual(self.armor(g),2);self.assertEqual(self.counts(g),[1,1]);self.check(g)

    def test_expired_granted_payload_does_not_enter_plan(self):
        self.script('temporary',lambda c:[GrantDeathrattle(c.target_id,'armor',expires_turn=1)],target=True)
        g=self.game(hand=('temporary','kill'),board=('selfbody',));i=self.body(g,1);self.play(g,'temporary',i);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'kill',i)
        self.assertEqual(self.armor(g),1);self.assertEqual(self.counts(g),[1]);self.check(g)

    def test_self_scope_uses_new_controller_after_control_change(self):
        g=self.custom(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),ChangeControl(c.state.players[1].board[0],2),Destroy(c.state.players[1].board[0])],('selfbody',))
        self.play(g,'do');self.assertEqual((self.armor(g),self.armor(g,2)),(0,3));self.check(g)

    def test_accepted_mixed_plan_survives_carrier_silence(self):
        self.r.register_behavior('silencer',lambda c:[GainArmor(1,1),Silence(c.source_id)])
        self.minion('silencerbody','silencer',deathrattle_repeats=(self.scope,))
        g=self.mixed('trigger',board=('silencerbody',));self.assertEqual(self.armor(g),3);self.assertEqual(self.counts(g),[1,2]);self.check(g)

    def test_independent_choices_restore_each_nonuniform_position(self):
        g=self.waiting()
        for _ in range(6):self.check(g);self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        self.assertEqual(self.armor(g),6);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_uniform_plan_query_rejects_ambiguous_mixed_counts(self):
        g=self.mixed()
        with self.assertRaisesRegex(ValueError,'individual payloads'):_=self.batch(g).plan

    def test_payload_failure_rolls_back_complete_mixed_group(self):
        def fail(c):
            if c.deathrattle.ability.origin=='granted' and c.deathrattle.repeat_index==2:raise ValueError('scoped failure')
            return [GainArmor(1,1)]
        self.r.register_behavior('fail',fail);self.minion('failbody','armor',deathrattle_repeats=(self.scope,))
        self.script('badgrant',lambda c:[GrantDeathrattle(c.target_id,'fail')],target=True)
        g=self.game(hand=('badgrant','kill'),board=('failbody',));self.play(g,'badgrant',self.body(g,1));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'scoped failure'):self.play(g,'kill',self.body(g,1))
        self.assertEqual(g.snapshot(),before)

    def test_oversized_self_count_rejects_before_allocating(self):
        self.r.register_card(CardDefinition('huge','huge',CardType.MINION,health=3,
            deathrattle_repeats=(DeathrattleRepeatSpec(100000,scope='self',origins=('granted',)),)))
        g=self.game(hand=('grant','kill'),board=('huge',));self.play(g,'grant',self.body(g,1));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'kill',self.body(g,1))
        self.assertEqual(g.snapshot(),before)

    def test_terminal_marks_every_mixed_unstarted_position(self):
        self.r.register_behavior('fatal',lambda c:[Damage(c.state.players[2].hero_id,40)])
        self.minion('fatalself','fatal',deathrattle_repeats=(self.scope,))
        g=self.mixed(board=('fatalself',));self.assertEqual([d.execution_order for d in self.records(g)],[1,None,None]);self.check(g)

    def rewind(self,retained):
        self.script('rewinder',lambda c:[TriggerDeathrattles(c.state.players[1].board[0],c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        if retained:self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=3,retain_rewind_outcomes=True))
        g=self.game(hand=('grant','rewinder'),board=('selfbody','retainer') if retained else ('selfbody',));self.play(g,'grant',self.body(g,1));self.play(g,'rewinder')
        if not retained:
            c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('retry',)))
        return g

    def test_normal_rewind_replaces_mixed_plan(self):
        g=self.rewind(False);self.assertEqual(self.armor(g),3);self.assertEqual(len(g.state.deathrattle_batches),1);self.check(g)

    def test_retained_rewind_keeps_two_mixed_plans(self):
        g=self.rewind(True);self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.deathrattle_batches),2);self.check(g)

    def test_invalid_scope_and_origin_declarations_rejected(self):
        for kw in ({'scope':'enemy'},{'scope':True},{'origins':()},{'origins':['granted']},{'origins':('copied',)},{'origins':('granted','granted')}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):DeathrattleRepeatSpec(**kw)
        with self.assertRaises(ValueError):PlayerEffectSpec('self','selfbody',deathrattle_repeats=(self.scope,))

    def test_corrupted_payload_order_or_repeat_count_rejected(self):
        g=self.waiting()
        for change in ('order','count','missing','duplicate'):
            s=g.snapshot();payloads=s['state']['deathrattle_batches'][0]['payloads']
            if change=='order':payloads.reverse()
            elif change=='count':payloads[1]['plan']['repetitions']=3
            elif change=='missing':payloads.pop()
            else:payloads.append(payloads[1])
            with self.subTest(change=change):self.reject(s)

    def test_self_contributor_cannot_reference_neighbor_carrier(self):
        g=self.waiting();s=g.snapshot();s['state']['deathrattle_batches'][0]['payloads'][1]['plan']['contributors'][0]['carrier_id']=g.state.players[2].hero_id;self.reject(s)

    def test_granted_only_plan_cannot_be_applied_to_printed_payload(self):
        g=self.waiting();s=g.snapshot();payloads=s['state']['deathrattle_batches'][0]['payloads'];payloads[0]['plan']=payloads[1]['plan'];self.reject(s)

    def test_scope_or_origin_tampering_rejected(self):
        g=self.waiting()
        for field,value in (('scope','friendly'),('origins',['printed'])):
            s=g.snapshot();source=s['state']['deathrattle_batches'][0]['payloads'][1]['plan']['contributors'][0]
            source['ability']['deathrattle_repeat'][field]=value
            with self.subTest(field=field):self.reject(s)

    def test_scoped_plans_are_not_player_information(self):
        g=self.waiting()
        for player in (1,2):
            text=json.dumps(g.observe(player))+json.dumps(g.player_events(player));self.assertNotIn('payloads',text);self.assertNotIn('deathrattle_batches',text);self.assertNotIn('contributors',text)

    def test_magnetic_inheritance_counts_as_granted_despite_original_card_identity(self):
        meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.minion('host','armor',metadata=meta,deathrattle_repeats=(self.scope,));self.minion('part','armor',metadata=meta,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',))
        g=self.game(hand=('part','kill'),board=('host',));g.apply(PlayCard(1,g.state.players[1].hand[0],position=0));self.play(g,'kill',self.body(g,1))
        self.assertEqual(self.armor(g),3);self.assertEqual(self.counts(g),[1,2]);p=self.batch(g).payloads[1]
        self.assertEqual((p.ability.origin,p.ability.deathrattle_card_id,p.ability.deathrattle_grant_card_id),('granted','part','part'));self.check(g)

    def real_game(self,board=('RLK_912',),enemy=(),hand=('EX1_158','CS2_029'),registry=None):
        from hs_sim.engine.representative import build_registry
        self.r=registry or build_registry()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=board,deck=('CS2_182',)*10,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=enemy,deck=('CS2_182',)*10,mana=10,max_mana=10)),seed=99),self.r)

    def test_real_scourge_has_only_scoped_policy_and_no_printed_deathrattle(self):
        from hs_sim.engine.representative import build_registry
        card=build_registry().card('RLK_912');self.assertIsNone(card.deathrattle)
        self.assertEqual(card.deathrattle_repeats,(self.scope,));self.assertEqual((card.cost,card.attack,card.health),(1,1,3))

    def test_real_forest_grant_repeats_on_scourge_natural_death(self):
        g=self.real_game();self.play(g,'EX1_158');self.play(g,'CS2_029',self.body(g,1))
        self.assertEqual(self.counts(g),[2]);self.assertEqual(len(self.records(g)),2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['EX1_158t','EX1_158t']);self.check(g)

    def test_real_neighbor_printed_and_granted_payloads_remain_single(self):
        g=self.real_game(board=('RLK_912','EX1_096'));self.play(g,'EX1_158');self.play(g,'CS2_029',self.body(g,1,1))
        self.assertEqual(self.counts(g),[1,1]);self.assertEqual(len(g.state.players[1].hand),1)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],['RLK_912','EX1_158t']);self.check(g)

    def test_real_forest_does_not_grant_enemy_payloads(self):
        g=self.real_game(enemy=('EX1_096',));self.play(g,'EX1_158');self.play(g,'CS2_029',self.body(g,2))
        self.assertEqual(self.counts(g),[1]);self.assertEqual(self.records(g)[0].capture.ability.origin,'printed')
        self.assertFalse(g.state.players[2].board);self.check(g)

    def test_real_forest_excludes_dormant_friendly_minion(self):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine.dormancy import MakeDormant
        r=build_registry();r.register_behavior('sleep',lambda c:[MakeDormant(c.state.players[1].board[0],2)])
        r.register_card(CardDefinition('sleep','sleep',CardType.SPELL,on_play='sleep'))
        g=self.real_game(hand=('sleep','EX1_158'),registry=r);self.play(g,'sleep');self.play(g,'EX1_158')
        self.assertFalse(any(a.kind=='deathrattle' for a in g.state.entities[self.body(g,1)].abilities));self.check(g)

    def test_component_base_is_printed_and_dynamic_ship_grant_is_repeated(self):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine.starships import construction
        from hs_sim.engine import LaunchStarship
        r=build_registry();r.register_behavior('armor',lambda c:[GainArmor(c.player_id,1)])
        r.register_behavior('scopegrant',lambda c:[GrantDeathrattleRepeatAura(c.target_id,self.scope,c.source_id),GrantDeathrattle(c.target_id,'armor',c.source_id)])
        r.register_card(CardDefinition('scopegrant','scopegrant',CardType.SPELL,on_play='scopegrant',requires_target=True))
        g=self.real_game(board=('GDB_100',),hand=('CS2_029','scopegrant','CS2_029'),registry=r)
        self.play(g,'CS2_029',self.body(g,1));ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));self.play(g,'scopegrant',ship.id)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'CS2_029',ship.id)
        self.assertEqual(self.armor(g),10);self.assertEqual(self.counts(g,1),[1,2]);self.assertEqual(g.state.death_history[-1].components,('GDB_100',));self.check(g)

    def test_nested_self_natural_death_keeps_its_own_nonuniform_plan(self):
        self.r.register_behavior('nested',lambda c:[GainArmor(c.player_id,1),*([Destroy(c.state.players[2].board[0])] if c.state.players[2].board else [])])
        self.minion('nestedself','nested',deathrattle_repeats=(self.scope,))
        g=self.custom(lambda c:[GrantDeathrattle(c.state.players[1].board[0],'armor'),GrantDeathrattle(c.state.players[2].board[0],'armor'),
            TriggerDeathrattles(c.state.players[1].board[0],times=2)],('nestedself',),('selfonly',));self.play(g,'do')
        self.assertEqual((self.armor(g),self.armor(g,2)),(6,2));self.assertEqual([b.trigger_count for b in g.state.deathrattle_batches],[2,1]);self.check(g)

    def test_native_scourge_forest_capacity_and_neighbor_composition(self):
        from examples.scoped_deathrattles import run
        g,s=run();self.assertEqual(s['schema_version'],266);self.assertEqual(len(self.records(g)),8);self.assertEqual(len(g.state.death_history),2)


if __name__=='__main__':unittest.main()
