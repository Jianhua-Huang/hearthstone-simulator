"""Shared manual-completion predicate and Inspire composition; provisional R-111."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, Registry, PlayerSetup, Scenario,
    PlayCard, UseHeroPower, EndTurn, SelectChoice, TriggerSpec, LimitedTriggerSpec,
    GrantLimitedTrigger, TriggerHeroPower, AddHeroPower, RemoveHeroPower, CostSpec,
    PaymentType, RewindSpec, Keyword, TargetSpec, IllegalAction, ResolutionError,
    completed_manual_power, is_inspire)
from hs_sim.engine.effects import (GainArmor, Buff, Summon, Destroy, Silence, ChangeControl,
    CopyMinion, Transform, ReturnToHand, GrantTrigger, ReplaceHeroPower, RefreshHeroPower,
    SetHeroPowerUses, ModifyCost, Damage, RequestChoice, ChoiceOption, InvokeBehavior)
from hs_sim.engine.model import Event
from hs_sim.engine.replay import build_replay, replay


class InspireTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('inspire-tests-v1')
        self.r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=1, health=4))
        self.r.register_card(CardDefinition('retainer', 'retainer', CardType.MINION, health=4,
                                            retain_rewind_outcomes=True))
        self.power('power', lambda c: [GainArmor(c.player_id, 1)])
        self.r.register_trigger_condition('inspire', lambda c: is_inspire(c.state, c.event, c.player_id))
        self.watch('watch')
        self.watch('finite', limited=True)
        self.script('trigger', lambda c: [TriggerHeroPower(c.player_id, c.source_id)])
        self.script('refresh', lambda c: [RefreshHeroPower(c.player_id)])

    def power(self, cid, fn, **kw):
        self.r.register_behavior(cid, fn)
        self.r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, cost=2, on_use=cid, **kw))

    def script(self, cid, fn):
        self.r.register_behavior(cid, fn)
        self.r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))

    def watch(self, cid, fn=None, *, limited=False, event='hero_power_used', **kw):
        fn = fn or (lambda c: [GainArmor(c.player_id, 10)] if is_inspire(c.state, c.event, c.player_id) else [])
        self.r.register_behavior(cid, fn)
        specs = {'limited_triggers': (LimitedTriggerSpec(event, cid, 'inspire'),)} if limited else {
            'triggers': (TriggerSpec(event, cid),)}
        self.r.register_card(CardDefinition(cid, cid, CardType.MINION, health=4, **specs, **kw))

    def game(self, *, power='power', board=('watch',), enemy=(), hand=(), mana=10):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            hero_power_card_id=power, deck=('plain',)*4, mana=mana, max_mana=10),
            PlayerSetup('hero', board=enemy, hero_power_card_id='power', deck=('plain',)*4,
                        mana=10, max_mana=10)), seed=71), self.r)

    def use(self, g, power=None, player=1):
        g.apply(UseHeroPower(player, power or g.state.players[player].hero_power_id))

    def play(self, g, cid):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid)); return eid

    def choose(self, g, option='ok'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))

    def armor(self, g, p=1): return g.state.entities[g.state.players[p].hero_id].armor
    def body(self, g, p=1, index=0): return g.state.entities[g.state.players[p].board[index]]
    def event(self, g): return next(e for e in reversed(g.events) if e.kind == 'hero_power_used')
    def uses(self, g): return [a.uses_remaining for a in self.body(g).abilities if a.kind == 'limited_trigger']
    def pause(self, c): return RequestChoice(c.player_id, (ChoiceOption('ok', 'ok', ()),), source_id=c.source_id)

    def check(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s, self.r).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), s)

    def test_manual_completes_before_trigger_and_context_contains_record(self):
        self.watch('inspect', lambda c: [GainArmor(c.player_id, c.power.cost)]
            if c.power == completed_manual_power(c.state, c.event) else [])
        g=self.game(board=('watch','inspect'));self.use(g)
        self.assertEqual(self.armor(g),13);self.assertTrue(is_inspire(g.state,self.event(g),1))
        self.assertFalse(is_inspire(g.state,self.event(g),2));self.check(g)

    def test_opponent_use_only_inspires_its_controller(self):
        g=self.game(enemy=('watch',));self.use(g);g.apply(EndTurn(1));self.use(g,player=2)
        self.assertEqual((self.armor(g),self.armor(g,2)),(11,11));self.check(g)

    def test_indirect_and_start_events_are_not_manual_completion(self):
        g=self.game(hand=('trigger',));self.play(g,'trigger')
        self.assertEqual(self.armor(g),1)
        self.assertTrue(all(completed_manual_power(g.state,e) is None for e in g.events));self.check(g)

    def test_nested_indirect_only_outer_manual_inspires(self):
        self.power('nested',lambda c:[TriggerHeroPower(1,c.source_id),GainArmor(1,1)]
            if c.power.origin=='manual' else [GainArmor(1,2)])
        g=self.game(power='nested');self.use(g)
        self.assertEqual(self.armor(g),13);self.assertEqual(len(g.state.hero_power_history),2);self.check(g)

    def test_indirect_no_target_failure_does_not_inspire(self):
        self.power('target',lambda c:[],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(power='target',hand=('trigger',));self.play(g,'trigger')
        self.assertEqual(g.state.hero_power_history[0].failure,'no_target');self.assertEqual(self.armor(g),0);self.check(g)

    def test_passive_failure_and_rejected_manual_action_do_not_inspire(self):
        self.r.register_behavior('passive',lambda c:[])
        self.r.register_card(CardDefinition('passive','passive',CardType.HERO_POWER,passive_hero_power=True,
                                            triggers=(TriggerSpec('card_played','passive'),)))
        g=self.game(power='passive',hand=('trigger',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),before);self.play(g,'trigger')
        self.assertEqual(g.state.hero_power_history[0].failure,'passive');self.assertEqual(self.armor(g),0);self.check(g)

    def test_invalid_manual_payment_has_no_history_or_trigger(self):
        g=self.game(mana=1);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_successful_payload_still_inspires(self):
        self.power('empty',lambda c:[]);g=self.game(power='empty');self.use(g)
        self.assertEqual(self.armor(g),10);self.check(g)

    def test_zero_cost_manual_use_still_inspires(self):
        self.script('free',lambda c:[ModifyCost(c.state.players[1].hero_power_id,
            CostSpec(set_to=0,card_types=(CardType.HERO_POWER,)))])
        g=self.game(hand=('free',),mana=0);self.play(g,'free');self.use(g)
        self.assertEqual((self.armor(g),g.state.hero_power_history[0].cost),(11,0));self.check(g)

    def test_health_paid_manual_use_still_inspires(self):
        self.script('health',lambda c:[ModifyCost(c.state.players[1].hero_power_id,
            CostSpec(payment=PaymentType.HEALTH,card_types=(CardType.HERO_POWER,)))])
        g=self.game(hand=('health',));self.play(g,'health');self.use(g)
        self.assertEqual((self.armor(g),g.state.entities[g.state.players[1].hero_id].health),(11,28));self.check(g)

    def test_refresh_and_multiple_uses_each_inspire(self):
        self.script('twice',lambda c:[SetHeroPowerUses(1,2)])
        g=self.game(hand=('twice','refresh'));self.play(g,'twice');self.use(g);self.use(g)
        self.play(g,'refresh');self.use(g)
        self.assertEqual((self.armor(g),len(g.state.hero_power_history)),(33,3));self.check(g)

    def test_additional_power_counts_as_independent_manual_use(self):
        self.script('add',lambda c:[AddHeroPower(1,'power')])
        g=self.game(hand=('add',));self.play(g,'add');self.use(g)
        self.use(g,g.state.players[1].additional_hero_power_ids[0])
        self.assertEqual(self.armor(g),22);self.check(g)

    def test_replacement_during_payload_preserves_old_completion(self):
        self.power('replace',lambda c:[ReplaceHeroPower(1,'power')])
        g=self.game(power='replace');old=g.state.players[1].hero_power_id;self.use(g)
        p=completed_manual_power(g.state,self.event(g))
        self.assertEqual((p.source_id,p.card_id,self.armor(g)),(old,'replace',10))
        self.use(g);self.assertEqual(self.armor(g),21);self.check(g)

    def test_removal_during_payload_does_not_cancel_successful_use(self):
        self.power('remove',lambda c:[RemoveHeroPower(1)])
        g=self.game(power='remove');self.use(g)
        self.assertIsNone(g.state.players[1].hero_power_id);self.assertEqual(self.armor(g),10);self.check(g)

    def test_choice_delays_completion_and_resumes_on_later_action(self):
        self.power('pause',lambda c:[self.pause(c),GainArmor(1,1)])
        g=self.game(power='pause');self.use(g);self.assertEqual(self.armor(g),0);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),11)
        self.assertLess(g.state.hero_power_history[0].action,self.event(g).action);self.check(g)

    def test_nested_choice_keeps_outer_incomplete_until_both_finish(self):
        self.power('nested',lambda c:[TriggerHeroPower(1,c.source_id,choices='player')]
            if c.power.origin=='manual' else [self.pause(c)])
        g=self.game(power='nested');self.use(g);self.check(g);self.assertEqual(self.armor(g),0)
        self.choose(g);self.assertEqual(self.armor(g),10);self.check(g)

    def test_terminal_payload_interrupts_without_inspire(self):
        self.power('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.game(power='lethal');self.use(g)
        self.assertTrue(g.state.hero_power_history[0].interrupted);self.assertEqual(self.armor(g),0)
        self.assertFalse(any(e.kind=='hero_power_used' for e in g.events));self.check(g)

    def test_summoned_during_payload_listens_at_completion(self):
        self.power('make',lambda c:[Summon(1,'watch')]);g=self.game(power='make',board=());self.use(g)
        self.assertEqual(self.armor(g),10);self.check(g)

    def test_granted_during_payload_listens_at_completion(self):
        self.power('grant',lambda c:[GrantTrigger(c.state.players[1].board[0],'hero_power_used','watch')])
        g=self.game(power='grant',board=('plain',));self.use(g);self.assertEqual(self.armor(g),10);self.check(g)

    def test_granted_after_completion_waits_for_next_use(self):
        self.watch('grant',lambda c:[GrantTrigger(c.state.players[1].board[1],'hero_power_used','watch')])
        g=self.game(board=('grant','plain'),hand=('refresh',));self.use(g);self.assertEqual(self.armor(g),1)
        self.play(g,'refresh');self.use(g);self.assertEqual(self.armor(g),12);self.check(g)

    def test_silenced_before_completion_cannot_listen(self):
        self.power('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(power='silence');self.use(g);self.assertEqual(self.armor(g),0);self.check(g)

    def test_removed_before_completion_cannot_listen(self):
        self.power('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(power='kill');self.use(g);self.assertEqual(self.armor(g),0);self.check(g)

    def test_transferred_before_completion_uses_new_controller(self):
        self.power('take',lambda c:[ChangeControl(c.state.players[2].board[0],1)])
        g=self.game(power='take',board=(),enemy=('watch',));self.use(g)
        self.assertEqual(self.armor(g),10);self.check(g)

    def test_transformed_during_payload_uses_new_definition(self):
        self.power('transform',lambda c:[Transform(c.state.players[1].board[0],'watch')])
        g=self.game(power='transform',board=('plain',));self.use(g);self.assertEqual(self.armor(g),10);self.check(g)

    def test_dormant_source_does_not_listen(self):
        self.watch('sleep',dormant_turns=2)
        g=self.game(board=('sleep',));self.use(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_ordinary_captured_reaction_survives_later_silence(self):
        self.watch('first',lambda c:[Silence(c.state.players[1].board[1])])
        g=self.game(board=('first','watch'));self.use(g);self.assertEqual(self.armor(g),11);self.check(g)

    def test_ordinary_captured_reaction_keeps_original_controller(self):
        self.watch('first',lambda c:[ChangeControl(c.state.players[1].board[1],2)])
        g=self.game(board=('first','watch'));self.use(g)
        self.assertEqual((self.armor(g),self.armor(g,2)),(11,0));self.check(g)

    def test_finite_condition_receives_history_without_context_power(self):
        g=self.game(board=('finite',),hand=('refresh',));self.use(g);self.play(g,'refresh');self.use(g)
        self.assertEqual((self.armor(g),self.uses(g)),(12,[0]));self.check(g)

    def test_opponent_use_does_not_consume_finite_trigger(self):
        g=self.game(board=('finite',));g.apply(EndTurn(1));self.use(g,player=2)
        self.assertEqual((self.armor(g),self.uses(g)),(0,[1]));self.check(g)

    def test_indirect_does_not_consume_finite_trigger(self):
        g=self.game(board=('finite',),hand=('trigger',));self.play(g,'trigger')
        self.assertEqual((self.armor(g),self.uses(g)),(1,[1]));self.check(g)

    def test_finite_removed_before_consumption_is_cancelled(self):
        self.watch('first',lambda c:[Silence(c.state.players[1].board[1])])
        g=self.game(board=('first','finite'));self.use(g);self.assertEqual(self.armor(g),1);self.check(g)

    def test_finite_same_name_reinstall_does_not_reuse_captured_ability(self):
        self.watch('first',lambda c:[Transform(c.state.players[1].board[1],'finite')])
        g=self.game(board=('first','finite'));self.use(g);self.assertEqual(self.armor(g),1)
        self.assertEqual([a.uses_remaining for a in self.body(g,index=1).abilities if a.kind=='limited_trigger'],[1]);self.check(g)

    def test_finite_consumes_before_its_choice_and_restores(self):
        self.watch('choice',lambda c:[self.pause(c),GainArmor(1,10)],limited=True)
        g=self.game(board=('choice',));self.use(g);self.assertEqual((self.armor(g),self.uses(g)),(1,[0]));self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),11);self.check(g)

    def test_finite_copied_consumed_state_and_base_copy_new_instance(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1),
                                     CopyMinion(c.state.players[1].board[0],1,mode='base')])
        g=self.game(board=('finite',),hand=('copy','refresh'));self.use(g);self.play(g,'copy');self.play(g,'refresh');self.use(g)
        self.assertEqual(self.armor(g),22);self.check(g)

    def test_finite_return_and_replay_installs_fresh_instance(self):
        self.script('return',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(board=('finite',),hand=('return','refresh'));old=self.body(g).id;self.use(g)
        self.play(g,'return');self.play(g,'finite');self.play(g,'refresh');self.use(g)
        self.assertEqual((self.body(g).id,self.armor(g)),(old,22));self.check(g)

    def test_rewind_restores_trigger_effect_and_consumption(self):
        self.power('rewind',lambda c:[GainArmor(1,1+c.rewind_attempt)],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(power='rewind',board=('finite',));self.use(g);self.assertEqual(self.armor(g),11);self.check(g)
        self.choose(g,'retry');self.assertEqual((self.armor(g),self.uses(g)),(12,[0]))
        self.assertEqual(len(g.state.hero_power_history),1);self.check(g)

    def test_retained_outcomes_inspire_once(self):
        self.power('rewind',lambda c:[GainArmor(1,1+c.rewind_attempt)],rewind=RewindSpec(2),keywords=(Keyword.REWIND,))
        g=self.game(power='rewind',board=('retainer','watch'));self.use(g)
        self.assertEqual(self.armor(g),16);self.assertEqual(sum(e.kind=='hero_power_used' for e in g.events),1);self.check(g)

    def test_retained_payload_choices_inspire_only_after_last_outcome(self):
        self.power('rewind',lambda c:[self.pause(c)],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(power='rewind',board=('retainer','watch'));self.use(g);self.choose(g)
        self.assertEqual(self.armor(g),0);self.check(g);restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),10);self.check(g)

    def test_failing_reaction_rolls_back_payment_history_and_consumption(self):
        self.watch('bad',lambda c:[Summon(1,'missing')],limited=True)
        g=self.game(board=('bad',));s=g.snapshot()
        with self.assertRaises((ValueError,ResolutionError)):self.use(g)
        self.assertEqual(g.snapshot(),s)

    def test_retryable_failure_after_choice_keeps_pending_completion(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'missing')])
        self.power('bad',lambda c:[RequestChoice(1,(
            ChoiceOption('bad','bad',(InvokeBehavior('fail',c.source_id,1),)),ChoiceOption('ok','ok',())),source_id=c.source_id)])
        g=self.game(power='bad');self.use(g);s=g.snapshot()
        with self.assertRaises((ValueError,ResolutionError)):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),s);self.choose(g);self.assertEqual(self.armor(g),10);self.check(g)

    def test_finite_transfer_after_capture_cancels_old_controller_candidate(self):
        self.watch('first',lambda c:[ChangeControl(c.state.players[1].board[1],2)])
        g=self.game(board=('first','finite'));self.use(g)
        self.assertEqual((self.armor(g),self.armor(g,2)),(1,0))
        self.assertEqual([a.uses_remaining for a in self.body(g,2).abilities if a.kind=='limited_trigger'],[1]);self.check(g)

    def test_ordinary_copies_have_independent_trigger_instances(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        g=self.game(hand=('copy',));self.play(g,'copy');self.use(g)
        self.assertEqual(self.armor(g),21)
        ids=[a.id for i in g.state.players[1].board for a in g.state.entities[i].abilities if a.kind=='trigger']
        self.assertEqual(len(set(ids)),2);self.check(g)

    def test_finite_granted_in_payload_uses_shared_completion_condition(self):
        self.power('grant',lambda c:[GrantLimitedTrigger(c.state.players[1].board[0],
            LimitedTriggerSpec('hero_power_used','watch','inspire'))])
        g=self.game(power='grant',board=('plain',));self.use(g)
        self.assertEqual((self.armor(g),self.uses(g)),(10,[0]));self.check(g)

    def test_retained_nested_activations_do_not_multiply_inspire(self):
        self.power('nested',lambda c:[TriggerHeroPower(1,c.source_id),GainArmor(1,1)]
            if c.power.origin=='manual' else [GainArmor(1,2)],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(power='nested',board=('retainer','watch'));self.use(g)
        self.assertEqual((self.armor(g),len(g.state.hero_power_history)),(20,3))
        self.assertEqual(sum(e.kind=='hero_power_used' for e in g.events),1);self.check(g)

    def test_lethal_inspire_keeps_already_completed_power_record(self):
        self.watch('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)]
            if is_inspire(c.state,c.event,c.player_id) else [])
        g=self.game(board=('lethal','watch'));self.use(g)
        self.assertTrue(g.state.hero_power_history[0].completed)
        self.assertEqual(self.armor(g),1);self.check(g)

    def test_private_history_and_predicate_ids_not_in_player_projection(self):
        g=self.game(board=('finite',));self.use(g)
        for p in (1,2):
            text=json.dumps(g.observe(p))
            for field in ('hero_power_history','power_id','condition_id','player_uses_before','inspire-tests'):
                self.assertNotIn(field,text)
        self.check(g)

    def test_unrelated_inputs_and_invalid_player(self):
        g=self.game()
        self.assertIsNone(completed_manual_power(g.state,None))
        self.assertIsNone(completed_manual_power(g.state,Event(1,0,'other')))
        for value in (True,0,3,'1'):
            with self.subTest(value=value),self.assertRaises(ValueError):is_inspire(g.state,None,value)
        with self.assertRaises(ValueError):completed_manual_power(g.state,{})

    def test_malformed_completion_fields_rejected(self):
        g=self.game();self.use(g);e=self.event(g)
        for values in ({'data':()}, {'data':e.data*2}, {'data':(('power_id',True),)},
                       {'data':(('power_id',999),)}, {'data':(('other',1),)},
                       {'source_id':999}, {'player_id':2}, {'target_id':True},
                       {'action':0}, {'action':999}, {'amount':True}, {'sequence':False}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                completed_manual_power(g.state,replace(e,**values))

    def test_incomplete_or_indirect_record_cannot_be_called_manual_completion(self):
        self.power('pause',lambda c:[self.pause(c)])
        g=self.game(power='pause');self.use(g)
        start=next(e for e in g.events if e.kind=='hero_power_started')
        with self.assertRaises(ValueError):completed_manual_power(g.state,replace(start,kind='hero_power_used'))
        self.choose(g)
        h=self.game(hand=('trigger',));self.play(h,'trigger')
        finish=next(e for e in h.events if e.kind=='hero_power_triggered')
        with self.assertRaises(ValueError):completed_manual_power(h.state,replace(finish,kind='hero_power_used'))


class InspireRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()

    def game(self,power='HERO_03bp',hand=(),board=('AT_082','AT_066')):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_03',hero_power_card_id=power,
            hand=hand,board=board,mana=10,max_mana=10),PlayerSetup('HERO_08'))),self.r)

    def use(self,g):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
    def check(self,g):self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_frozen_metadata(self):
        for cid,values in [('AT_082',('低阶侍从',1,1,2)),('AT_066',('奥格瑞玛狼骑士',3,3,3))]:
            c=self.r.card(cid);self.assertEqual((c.name,c.cost,c.attack,c.health),values)

    def test_squire_and_aspirant_apply_after_dagger_equipped(self):
        g=self.game();self.use(g)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,2)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].attack,2);self.check(g)

    def test_no_weapon_is_a_successful_noop_for_aspirant(self):
        g=self.game(power='HERO_01bp');self.use(g)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,2);self.check(g)

    def test_indirect_dagger_does_not_inspire(self):
        self.r.register_behavior('probe',lambda c:[TriggerHeroPower(1,c.source_id)])
        self.r.register_card(CardDefinition('probe','probe',CardType.SPELL,on_play='probe'))
        g=self.game(hand=('probe',));g.apply(PlayCard(1,g.state.players[1].hand[0]))
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,1)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].attack,1);self.check(g)

    def test_silenced_squire_does_not_gain_attack(self):
        self.r.register_behavior('probe',lambda c:[Silence(c.state.players[1].board[0])])
        self.r.register_card(CardDefinition('probe','probe',CardType.SPELL,on_play='probe'))
        g=self.game(hand=('probe',));g.apply(PlayCard(1,g.state.players[1].hand[0]));self.use(g)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,1);self.check(g)

    def test_player_scenario_and_pending_recovery(self):
        from examples.inspire import run
        g,s=run();self.assertIsNotNone(s['state']['pending_choice']);self.assertEqual(len(g.history),6)


if __name__ == '__main__': unittest.main()
