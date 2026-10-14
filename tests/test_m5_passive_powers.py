"""Skill listeners, passive activation boundaries and first matching plays."""
import json
import unittest
from dataclasses import replace
from hs_sim.engine import (CardDefinition,CardType,CardMetadata,CardClass,Registry,Game,
    PlayerSetup,Scenario,PlayCard,UseHeroPower,EndTurn,SelectChoice,TriggerSpec,
    TriggerHeroPower,Keyword,RewindSpec,IllegalAction,ResolutionError,SnapshotError)
from hs_sim.engine.effects import (GainArmor,Damage,ReplaceHeroPower,Summon,Transform,
    ReturnToHand,Silence,Destroy,RequestChoice,ChoiceOption,RefreshHeroPower,SetHeroPowerUses,ChangeControl)
from hs_sim.engine.play_history import played_cards,is_first_play
from hs_sim.engine.sacrifice import MinionReference,BuffCapturedMinion
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


class PassivePowerTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('passive-power-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,1)])
        self.r.register_card(CardDefinition('active','active',CardType.HERO_POWER,cost=2,on_use='armor'))
        for cid,tribes in (('undead',('undead',)),('beast',('beast',)),('all',('all',)),('dual',('undead','beast'))):
            self.r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=5,
                metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes)))
        self.passive('passive',self.first,'minion_play_accepted')
        self.script('install',lambda c:[ReplaceHeroPower(1,'passive')])
        self.script('remove',lambda c:[ReplaceHeroPower(1,'active')])
        self.script('trigger',lambda c:[TriggerHeroPower(1,c.source_id)])
    def first(self,c):
        if c.play is None or c.play.player_id!=c.player_id or not is_first_play(c.state,c.play,
                registry=self.r,kind=CardType.MINION,tribes_any=('undead',)):return []
        target=c.state.entities[c.play.magnetic_target_id if c.play.minion_result=='magnetized' else c.play.source_id]
        if target.zone.value!='board':return []
        return [BuffCapturedMinion(MinionReference.capture(target),2,0,c.source_id)]
    def passive(self,cid,fn,event):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,passive_hero_power=True,
            triggers=(TriggerSpec(event,cid),)))
    def script(self,cid,fn,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,**kw))
    def watch(self,cid,fn,event):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),),
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())))
    def game(self,hand=('undead','undead'),power='passive',board=(),enemy_power='active',enemy_hand=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('beast',)*5,
            hero_power_card_id=power,mana=10,max_mana=10),PlayerSetup('hero',hand=enemy_hand,
            deck=('beast',)*5,hero_power_card_id=enemy_power,mana=10,max_mana=10)),seed=63),self.r)
    def play(self,g,cid='undead',p=1):
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid));return eid
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def choose(self,g,option=None):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option or c.options[0].id,)))
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_first_matching_card_only_receives_buff(self):
        g=self.game(hand=('beast','undead','undead'));beast=self.play(g,'beast');a=self.play(g);b=self.play(g)
        self.assertEqual([g.state.entities[i].attack for i in (beast,a,b)],[1,3,1])
        self.assertFalse(g.state.hero_power_history);self.check(g)

    def test_dual_and_all_tribes_match_same_once_per_turn_history(self):
        for cid in ('all','dual'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,'undead'));a=self.play(g,cid);b=self.play(g)
                self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(3,1));self.check(g)

    def test_next_turn_resets_first_play_without_extra_counter(self):
        g=self.game();a=self.play(g);g.apply(EndTurn(1));g.apply(EndTurn(2));b=self.play(g)
        self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(3,3));self.check(g)

    def test_each_player_has_independent_first_play(self):
        g=self.game(enemy_power='passive',enemy_hand=('undead','undead'));a=self.play(g)
        g.apply(EndTurn(1));b=self.play(g,p=2);c=self.play(g,p=2)
        self.assertEqual([g.state.entities[i].attack for i in (a,b,c)],[3,3,1]);self.check(g)

    def test_spell_play_does_not_spend_minion_tribe_condition(self):
        g=self.game(hand=('trigger','undead'));self.play(g,'trigger');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,3);self.check(g)

    def test_summon_does_not_spend_or_trigger_play_condition(self):
        self.script('summon',lambda c:[Summon(1,'undead')])
        g=self.game(hand=('summon','undead'));self.play(g,'summon');a=self.play(g)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board],[1,3]);self.check(g)

    def test_first_before_installation_counts_under_r103(self):
        g=self.game(hand=('undead','install','undead'),power='active');self.play(g);self.play(g,'install');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_install_before_first_undead_works(self):
        g=self.game(hand=('beast','install','undead'),power='active');self.play(g,'beast');self.play(g,'install');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,3);self.check(g)

    def test_same_definition_reinstallation_does_not_refresh_condition(self):
        g=self.game(hand=('undead','install','undead'));self.play(g);old=g.state.players[1].hero_power_id
        self.play(g,'install');a=self.play(g)
        self.assertNotEqual(g.state.players[1].hero_power_id,old);self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_refresh_and_use_limit_do_not_refresh_first_play(self):
        self.script('refresh',lambda c:[RefreshHeroPower(1),SetHeroPowerUses(1,3)])
        g=self.game(hand=('undead','refresh','undead'));self.play(g);self.play(g,'refresh');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_replacement_stops_old_power_from_listening(self):
        g=self.game(hand=('remove','undead'));self.play(g,'remove');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_replacement_before_queued_listener_cancels_it(self):
        self.watch('replace',lambda c:[ReplaceHeroPower(1,'active')] if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('replace',));self.play(g,'install');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_queued_listener_and_snapshot_keep_identity_guard(self):
        self.watch('wait',lambda c:[RequestChoice(1,(ChoiceOption('go','go',(ReplaceHeroPower(1,'active'),)),))]
            if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('wait',));self.play(g,'install');a=self.play(g);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_already_started_listener_continues_after_replacement(self):
        self.passive('choice',lambda c:[RequestChoice(1,(ChoiceOption('go','go',
            (ReplaceHeroPower(1,'active'),GainArmor(1,4))),),source_id=c.source_id)],'minion_play_accepted')
        g=self.game(power='choice');self.play(g);self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_transformation_of_old_play_does_not_change_tribe_history(self):
        self.script('change',lambda c:[Transform(c.state.players[1].board[0],'beast')])
        g=self.game(hand=('undead','change','undead'));self.play(g);self.play(g,'change');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,1)
        self.assertEqual(len(played_cards(g.state,1,registry=self.r,kind=CardType.MINION,tribes_any=('undead',))),2);self.check(g)

    def test_replay_after_return_counts_second_occurrence(self):
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('undead','bounce'));a=self.play(g);self.play(g,'bounce');self.play(g)
        self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_silence_removes_buff_without_resetting_history(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(hand=('undead','silence','undead'));a=self.play(g);self.play(g,'silence');b=self.play(g)
        self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(1,1));self.check(g)

    def test_preceding_reaction_transform_does_not_receive_old_buff(self):
        self.watch('change',lambda c:[Transform(c.event.source_id,'beast')] if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('change',));self.play(g,'install');a=self.play(g)
        self.assertEqual((g.state.entities[a].card_id,g.state.entities[a].attack),('beast',1));self.check(g)

    def test_death_before_queued_buff_does_not_buff_graveyard(self):
        self.watch('kill',lambda c:[Destroy(c.event.source_id)] if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('kill',));self.play(g,'install');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,1);self.assertNotIn(a,g.state.players[1].board);self.check(g)

    def test_minion_rewind_restores_first_matching_condition(self):
        self.r.register_behavior('noop',lambda c:[])
        self.r.register_card(replace(self.r.card('undead'),id='retry',name='retry',on_play='noop',
            rewind=RewindSpec(),keywords=(Keyword.REWIND,)))
        g=self.game(hand=('retry','undead'));a=self.play(g,'retry');self.choose(g,'retry');b=self.play(g)
        self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(3,1));self.check(g)

    def test_manual_activation_rejected_with_no_state_change(self):
        g=self.game();before=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'Passive'):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertEqual(g.snapshot(),before)

    def test_passive_has_no_player_or_host_legal_activation(self):
        g=self.game()
        self.assertFalse(any(isinstance(a,UseHeroPower) for a in g.legal_actions()))
        self.assertFalse(any(a['type']=='use_hero_power' for a in g.for_player(1).legal_actions()['actions']))
        for p in (1,2):
            row=next(x for x in g.observe(p)['players'] if x['id']==1)
            self.assertTrue(row['hero_power']['passive'])

    def test_active_power_observation_is_explicitly_not_passive(self):
        g=self.game(power='active');row=next(x for x in g.observe(1)['players'] if x['id']==1)
        self.assertFalse(row['hero_power']['passive'])

    def test_indirect_attempt_records_passive_failure_without_payload_or_use(self):
        g=self.game(hand=('trigger',));self.play(g,'trigger');p=g.state.hero_power_history[0]
        self.assertEqual((p.origin,p.failure,p.completed,p.target_id),('effect','passive',True,None))
        self.assertEqual((g.state.players[1].mana,g.state.players[1].hero_power_uses_this_turn),(10,0));self.check(g)

    def test_passive_attempt_does_not_sample_random_target(self):
        g=self.game(hand=('trigger',));rng=g.snapshot()['rng_state'];self.play(g,'trigger')
        self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_passive_failure_continues_outer_effects(self):
        self.script('after',lambda c:[TriggerHeroPower(1,c.source_id),GainArmor(1,3)])
        g=self.game(hand=('after',));self.play(g,'after');self.assertEqual(self.armor(g),3);self.check(g)

    def test_active_power_can_also_have_independent_listener(self):
        self.r.register_card(replace(self.r.card('active'),id='both',name='both',triggers=(TriggerSpec('turn_ended','armor'),)))
        g=self.game(power='both');g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));g.apply(EndTurn(1))
        self.assertEqual(self.armor(g),2);self.assertEqual(len(g.state.hero_power_history),1);self.check(g)

    def test_turn_start_and_end_skill_listeners_follow_both_turns(self):
        self.passive('turns',lambda c:[GainArmor(c.player_id,1)],'turn_ended')
        g=self.game(power='turns',enemy_power='turns');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual((self.armor(g),self.armor(g,2)),(2,2));self.check(g)

    def test_listener_exception_rolls_back_play_and_condition(self):
        self.passive('bad',lambda c:[Summon(1,'missing')],'minion_play_accepted')
        g=self.game(power='bad');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_unknown_tribal_metadata_is_explicit_error(self):
        self.r.register_card(CardDefinition('unknown','unknown',CardType.MINION,health=3))
        g=self.game(hand=('unknown',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'metadata'):self.play(g,'unknown')
        self.assertEqual(g.snapshot(),before)

    def test_history_query_uses_frozen_turn_and_prefix(self):
        g=self.game();a=self.play(g);first=g.state.play_history[0];self.play(g)
        self.assertTrue(is_first_play(g.state,first,registry=self.r,kind=CardType.MINION,tribes_any=('undead',)))
        self.assertFalse(is_first_play(g.state,g.state.play_history[1],registry=self.r,tribes_any=('undead',)))
        self.assertEqual([p.source_id for p in played_cards(g.state,1,before_id=2,registry=self.r,tribes_any=('undead',))],[a])
        self.check(g)

    def test_history_query_rejects_missing_registry_and_invalid_filters(self):
        g=self.game();self.play(g);record=g.state.play_history[0]
        for kwargs in ({'tribes_any':('undead',)},{'registry':self.r,'tribes_any':['undead']},
                {'registry':self.r,'tribes_any':('undead','undead')},{'registry':self.r,'tribes_any':('',)}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):played_cards(g.state,1,**kwargs)
        with self.assertRaises(ValueError):is_first_play(g.state,replace(record,id=99))

    def test_snapshot_rejects_passive_attempt_as_active_success(self):
        g=self.game(hand=('trigger',));self.play(g,'trigger');s=g.snapshot();s['state']['hero_power_history'][0]['failure']=None;self.reject(s)

    def test_snapshot_rejects_active_attempt_as_passive(self):
        g=self.game(hand=('trigger',),power='active');self.play(g,'trigger');s=g.snapshot()
        s['state']['hero_power_history'][0]['failure']='passive';self.reject(s)

    def test_snapshot_rejects_corrupt_listener_ability(self):
        self.watch('wait',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),))] if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('wait',));self.play(g,'install');self.play(g);s=g.snapshot()
        def corrupt(v):
            if isinstance(v,dict):
                if str(v.get('type','')).endswith('.CheckHeroPowerTrigger'):v['fields']['ability_id']=99999
                for x in v.values():corrupt(x)
            elif isinstance(v,list):
                for x in v:corrupt(x)
        corrupt(s);self.reject(s)

    def test_passive_definition_rejects_inconsistent_activation_contracts(self):
        base=self.r.card('passive')
        for changes in ({'on_use':'armor'},{'cost':2},{'triggers':()},{'requires_target':True},
                {'use_rule':'never'},{'passive_hero_power':1},{'kind':CardType.MINION,'health':2}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.r.register_card(replace(base,id='bad',**changes))

    def test_initial_skill_precedes_later_board_listener(self):
        self.watch('kill',lambda c:[Destroy(c.event.source_id)],'minion_play_accepted')
        g=self.game(board=('kill',));a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,3);self.assertNotIn(a,g.state.players[1].board);self.check(g)

    def test_pending_listener_resumes_normally_when_skill_survives(self):
        self.watch('wait',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),))] if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('wait',));self.play(g,'install');a=self.play(g)
        self.assertEqual(g.state.entities[a].attack,1);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[a].attack,3);self.check(g)

    def test_independent_subscriptions_can_share_first_play_predicate(self):
        self.r.register_card(replace(self.r.card('passive'),id='two',triggers=(TriggerSpec('minion_play_accepted','passive'),)*2))
        g=self.game(power='two');a=self.play(g);b=self.play(g)
        self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(5,1));self.check(g)

    def test_terminal_reaction_discards_queued_passive_work(self):
        self.watch('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)]
            if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('lethal',));self.play(g,'install');a=self.play(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual(g.state.entities[a].attack,1);self.check(g)

    def test_prior_control_change_invalidates_captured_buff_recipient(self):
        self.watch('steal',lambda c:[ChangeControl(c.event.source_id,2)] if c.play.kind==CardType.MINION else [],'minion_play_accepted')
        g=self.game(hand=('install','undead'),power='active',board=('steal',));self.play(g,'install');a=self.play(g)
        self.assertEqual((g.state.entities[a].controller,g.state.entities[a].attack),(2,1));self.check(g)

    def test_dormant_first_play_consumes_eligibility_under_r103(self):
        self.r.register_card(replace(self.r.card('undead'),id='sleep',dormant_turns=1))
        g=self.game(hand=('sleep','undead'));a=self.play(g,'sleep');b=self.play(g)
        self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(1,1));self.check(g)

    def test_magnetic_undead_buff_delivered_to_captured_host(self):
        self.r.register_card(replace(self.r.card('undead'),id='magnetic',keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',)))
        self.r.register_card(replace(self.r.card('beast'),id='mech',metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))))
        g=self.game(hand=('magnetic','undead'),board=('mech',));material=g.state.players[1].hand[0];host=g.state.players[1].board[0]
        g.apply(PlayCard(1,material,position=0));b=self.play(g)
        self.assertEqual((g.state.entities[host].attack,g.state.entities[b].attack),(4,1));self.check(g)

    def test_snapshot_rejects_unordered_skill(self):
        g=self.game();s=g.snapshot();eid=g.state.players[1].hero_power_id
        entity=next(e for e in s['state']['entities'] if e['id']==eid) if isinstance(s['state']['entities'],list) else s['state']['entities'][str(eid)]
        entity['entered_order']=0;self.reject(s)


class InfiniteRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand=('EDR_852','ULD_205','ULD_205'),power=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_11',hand=hand,hero_power_card_id=power,
            deck=('ULD_205',)*3,mana=10,max_mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*3)),seed=63),self.r)
    play=PassivePowerTests.play
    check=PassivePowerTests.check
    reject=PassivePowerTests.reject

    def test_frozen_definition_is_passive_and_hides_active_button(self):
        c=self.r.card('END_003p');self.assertEqual((c.name,c.cost,c.passive_hero_power),('永恒龙的祝福',0,True))
        self.assertIsNone(c.on_use);g=self.game();self.play(g,'EDR_852')
        self.assertFalse(any(isinstance(a,UseHeroPower) for a in g.legal_actions()));self.check(g)

    def test_only_first_undead_gains_attack(self):
        g=self.game();self.play(g,'EDR_852');a=self.play(g,'ULD_205');b=self.play(g,'ULD_205')
        base=self.r.card('ULD_205').attack
        self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(base+1,base));self.check(g)

    def test_imbue_growth_keeps_skill_identity_and_installation_order(self):
        g=self.game(hand=('EDR_852',)*3+('ULD_205',));self.play(g,'EDR_852')
        power=g.state.players[1].hero_power_id;order=g.state.entities[power].entered_order
        self.play(g,'EDR_852');self.play(g,'EDR_852');a=self.play(g,'ULD_205')
        self.assertEqual((g.state.players[1].hero_power_id,g.state.entities[power].entered_order),(power,order))
        self.assertEqual(g.state.entities[a].attack,self.r.card('ULD_205').attack+3);self.check(g)

    def test_growth_after_first_undead_does_not_grant_another_buff(self):
        g=self.game(hand=('EDR_852','ULD_205','EDR_852','ULD_205'));self.play(g,'EDR_852');a=self.play(g,'ULD_205')
        self.play(g,'EDR_852');b=self.play(g,'ULD_205')
        self.assertEqual((g.state.entities[a].attack,g.state.entities[b].attack),(self.r.card('ULD_205').attack+1,self.r.card('ULD_205').attack));self.check(g)

    def test_undead_played_before_imbue_is_in_same_turn_history(self):
        g=self.game(hand=('ULD_205','EDR_852','ULD_205'));self.play(g,'ULD_205');self.play(g,'EDR_852');a=self.play(g,'ULD_205')
        self.assertEqual(g.state.entities[a].attack,self.r.card('ULD_205').attack);self.check(g)

    def test_wisprider_passive_attempt_keeps_later_undead_eligibility(self):
        g=self.game(hand=('EDR_519','ULD_205'));self.play(g,'EDR_519');a=self.play(g,'ULD_205')
        self.assertEqual(g.state.hero_power_history[0].failure,'passive')
        self.assertEqual(g.state.entities[a].attack,self.r.card('ULD_205').attack+1);self.check(g)

    def test_reborn_creates_unbuffed_entity_and_does_not_trigger_passive(self):
        g=self.game(hand=('EDR_852','ULD_205','CS2_029'));self.play(g,'EDR_852');a=self.play(g,'ULD_205')
        fire=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id=='CS2_029');g.apply(PlayCard(1,fire,a))
        body=next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id=='ULD_205')
        self.assertNotEqual(body.id,a);self.assertEqual(body.attack,self.r.card('ULD_205').attack);self.check(g)

    def test_default_death_knight_active_power_is_explicitly_unadapted(self):
        from hs_sim.engine import DeckPolicy,DeckSpec,Runes,validate_deck
        self.assertIsNone(self.r.card('HERO_11').initial_hero_power)
        g=self.game(hand=());self.assertIsNone(g.state.players[1].hero_power_id)
        policy=DeckPolicy('passive-start-tests','local-2026-09-23','experimental',('ULD_205',),deck_size=1)
        for power in ('HERO_11bp','END_003p'):
            with self.subTest(power=power):
                deck=DeckSpec('HERO_11',power,CardClass.DEATH_KNIGHT,('ULD_205',),Runes(3))
                report=validate_deck(deck,self.r,policy)
                self.assertFalse(report.valid)
                self.assertIn('hero_power',[issue.code for issue in report.issues])
                if power=='HERO_11bp':
                    self.assertTrue(any(issue.code=='unsupported_definition' and issue.card_id==power
                        for issue in report.issues))

    def test_schema62_rejected_after_listener_order_and_view_change(self):
        g=self.game();s=g.snapshot();s['schema_version']=62;self.reject(s)

    def test_real_example_restores_midturn_first_play_history(self):
        from examples.passive_hero_power import run
        g,s=run();self.assertEqual(s['schema_version'],266);self.assertFalse(g.state.hero_power_history)


if __name__=='__main__':unittest.main()
