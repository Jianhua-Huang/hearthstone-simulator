"""Manual/effect power provenance, shared targets/choices, and durable nesting."""
import json
import unittest

from hs_sim.engine import (CardDefinition,CardType,Game,Registry,PlayerSetup,Scenario,
    PlayCard,UseHeroPower,SelectChoice,EndTurn,TriggerSpec,TargetSpec,TargetMode,Keyword,
    TriggerHeroPower,HeroPowerRecord,activated_powers,DamageKind,PaymentType,CostSpec,
    IllegalAction,ResolutionError,ResolutionLimitExceeded,SnapshotError,Ruleset,RewindSpec,
    CastSpell,Imbue,imbue_count)
from hs_sim.engine.effects import (GainArmor,Damage,Summon,Destroy,ReturnToHand,
    ReplaceHeroPower,RefreshHeroPower,SetHeroPowerUses,ModifyCost,AddCostModifier,
    RequestChoice,ChoiceOption,InvokeBehavior)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


class PowerActivationTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('power-activation-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('plain','plain',CardType.MINION,attack=2,health=4))
        self.power('power',lambda c:[GainArmor(c.player_id,1)])
        self.script('trigger',lambda c:[TriggerHeroPower(c.player_id,c.source_id)])
    def power(self,cid,fn,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=2,on_use=cid,**kw))
    def script(self,cid,fn,kind=CardType.SPELL,**kw):
        self.r.register_behavior(cid,fn)
        if kind==CardType.MINION:kw.setdefault('health',4)
        self.r.register_card(CardDefinition(cid,cid,kind,on_play=cid,**kw))
    def watch(self,cid,fn,event):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),)))
    def game(self,hand=('trigger',),power='power',board=(),enemy=(),mana=10,rules=None,seed=61):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,
            deck=('plain',)*4,hero_power_card_id=power,mana=mana,max_mana=10),
            PlayerSetup('hero',hand=('plain',),board=enemy,deck=('plain',)*4,
                hero_power_card_id='power',mana=10,max_mana=10)),seed=seed),self.r,rules)
    def play(self,g,cid='trigger'):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def use(self,g,target=None):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,target))
    def source(self,g,p=1):return g.state.entities[g.state.players[p].hero_power_id]
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
    def choice_power(self,cid='choice'):
        self.power(cid,lambda c:[RequestChoice(c.player_id,tuple(ChoiceOption(str(n),str(n),
            (GainArmor(c.player_id,n),)) for n in (1,3)),source_id=c.source_id)])

    def test_manual_records_payment_uses_and_completed_payload(self):
        g=self.game(hand=());power=self.source(g).id;self.use(g)
        p=g.state.hero_power_history[0]
        self.assertEqual((p.source_id,p.origin,p.cost,p.payment,p.uses_before,p.player_uses_before),
                         (power,'manual',2,PaymentType.MANA,0,0))
        self.assertTrue(p.completed);self.assertFalse(p.interrupted)
        self.assertEqual((g.state.players[1].mana,self.source(g).uses_this_turn),(8,1))
        self.assertEqual((g.state.play_history,g.state.cast_history),([],[]));self.check(g)

    def test_indirect_with_zero_mana_neither_pays_nor_uses(self):
        g=self.game(mana=0);origin=self.play(g);p=g.state.hero_power_history[0]
        self.assertEqual((p.origin,p.activator_id,p.cost,p.payment),('effect',origin,None,None))
        self.assertEqual((g.state.players[1].mana,self.source(g).uses_this_turn,g.state.players[1].hero_power_uses_this_turn),(0,0,0))
        self.assertEqual(self.armor(g),1);self.check(g)

    def test_indirect_does_not_consume_next_power_discount(self):
        self.script('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-1,card_types=(CardType.HERO_POWER,)),uses_remaining=1)])
        g=self.game(hand=('discount','trigger'));self.play(g,'discount');self.play(g)
        self.assertEqual(len(g.state.players[1].cost_modifiers),1);self.use(g)
        self.assertEqual(g.state.hero_power_history[-1].cost,1)
        self.assertFalse(g.state.players[1].cost_modifiers);self.check(g)

    def test_health_payment_frozen_only_for_manual_activation(self):
        self.script('health',lambda c:[ModifyCost(c.state.players[1].hero_power_id,
            CostSpec(payment=PaymentType.HEALTH,card_types=(CardType.HERO_POWER,)))])
        g=self.game(hand=('health','trigger'));self.play(g,'health');self.use(g);self.play(g)
        self.assertEqual(g.state.hero_power_history[0].payment,PaymentType.HEALTH)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)
        self.assertIsNone(g.state.hero_power_history[1].payment);self.check(g)

    def test_used_power_can_trigger_without_refresh_or_extra_use(self):
        g=self.game();self.use(g);self.play(g)
        self.assertEqual((self.source(g).uses_this_turn,g.state.players[1].hero_power_uses_this_turn),(1,1))
        self.assertEqual(self.armor(g),2)
        with self.assertRaises(IllegalAction):self.use(g)
        self.check(g)

    def test_exhausted_modified_limit_does_not_disable_indirect_payload(self):
        self.script('twice',lambda c:[SetHeroPowerUses(1,2)])
        g=self.game(hand=('twice','trigger'));self.play(g,'twice');self.use(g);self.use(g);self.play(g)
        self.assertEqual((self.armor(g),self.source(g).use_limit,self.source(g).uses_this_turn),(3,2,2))
        with self.assertRaises(IllegalAction):self.use(g)
        self.check(g)

    def test_indirect_bypasses_manual_board_space_condition(self):
        self.power('summon',lambda c:[Summon(c.player_id,'plain'),GainArmor(c.player_id,2)],requires_board_space=True)
        g=self.game(power='summon',board=('plain',)*7)
        with self.assertRaises(IllegalAction):self.use(g)
        self.play(g);self.assertEqual((len(g.state.players[1].board),self.armor(g)),(7,2));self.check(g)

    def test_indirect_bypasses_manual_use_predicate_under_r101(self):
        self.r.register_use_rule('never',lambda c:False)
        self.power('restricted',lambda c:[GainArmor(1,2)],use_rule='never')
        g=self.game(power='restricted')
        with self.assertRaises(IllegalAction):self.use(g)
        self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_refresh_preserves_prior_history(self):
        self.script('refresh',lambda c:[RefreshHeroPower(1)])
        g=self.game(hand=('refresh',));self.use(g);self.play(g,'refresh');self.use(g)
        records=g.state.hero_power_history
        self.assertEqual([p.uses_before for p in records],[0,0])
        self.assertEqual([p.player_uses_before for p in records],[0,1]);self.check(g)

    def test_invalid_manual_action_has_no_history_or_randomness(self):
        g=self.game(mana=1);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_missing_current_power_errors_transactionally(self):
        g=self.game(power=None);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'no hero power'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_nonexistent_activator_errors_transactionally(self):
        self.script('bad',lambda c:[TriggerHeroPower(1,99999)])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_looks_up_current_power_after_prior_replacement(self):
        self.power('other',lambda c:[GainArmor(c.player_id,4)])
        self.script('replace',lambda c:[ReplaceHeroPower(1,'other'),TriggerHeroPower(1,c.source_id)])
        g=self.game(hand=('replace',));self.play(g,'replace')
        self.assertEqual((g.state.hero_power_history[0].card_id,self.armor(g)),('other',4));self.check(g)

    def test_start_reaction_replacement_keeps_captured_old_power_payload(self):
        self.power('other',lambda c:[GainArmor(1,7)])
        self.watch('replace',lambda c:[ReplaceHeroPower(1,'other')],'hero_power_trigger_started')
        g=self.game(board=('replace',));old=self.source(g).id;self.play(g)
        self.assertEqual(self.armor(g),1)
        self.assertEqual((g.state.hero_power_history[0].source_id,self.source(g).card_id),(old,'other'));self.check(g)

    def test_indirect_opponent_power_runs_outside_its_turn(self):
        self.script('opponent',lambda c:[TriggerHeroPower(2,c.source_id)])
        g=self.game(hand=('opponent',));self.play(g,'opponent')
        p=g.state.hero_power_history[0]
        self.assertEqual((p.player_id,p.turn,self.armor(g,2),self.source(g,2).uses_this_turn),(2,1,1,0));self.check(g)

    def test_nested_same_power_has_explicit_parent_and_lifo_completion(self):
        self.power('nested',lambda c:[TriggerHeroPower(c.player_id,c.source_id),GainArmor(1,2)]
            if c.power.origin=='manual' else [GainArmor(1,1)])
        g=self.game(power='nested',hand=());self.use(g)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history],[None,1])
        self.assertEqual([e.kind for e in g.events if e.kind in ('hero_power_used','hero_power_triggered')],
                         ['hero_power_triggered','hero_power_used'])
        self.assertEqual(self.armor(g),3);self.check(g)

    def test_nested_power_choice_restores_both_completion_markers(self):
        self.power('nested',lambda c:[TriggerHeroPower(1,c.source_id,choices='player')]
            if c.power.origin=='manual' else [RequestChoice(1,(ChoiceOption('ok','ok',(GainArmor(1,3),)),),source_id=c.source_id)])
        g=self.game(power='nested',hand=());self.use(g);self.check(g)
        self.assertTrue(all(not p.completed for p in g.state.hero_power_history))
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_power_context_available_to_start_and_finish_reactions(self):
        self.watch('start',lambda c:[GainArmor(1,1)] if c.power and not c.power.completed else [],'hero_power_started')
        self.watch('finish',lambda c:[GainArmor(1,2)] if c.power and c.power.completed else [],'hero_power_used')
        g=self.game(board=('start','finish'),hand=());self.use(g)
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_indirect_does_not_emit_manual_use_events(self):
        self.watch('manual',lambda c:[GainArmor(1,9)],'hero_power_used')
        g=self.game(board=('manual',));self.play(g)
        self.assertEqual(self.armor(g),1)
        self.assertFalse(any(e.kind in ('hero_power_started','hero_power_used') for e in g.events));self.check(g)

    def test_random_required_target_uses_automatic_protection_policy(self):
        self.r.register_card(CardDefinition('protected','protected',CardType.MINION,health=4,keywords=(Keyword.STEALTH,Keyword.ELUSIVE)))
        self.power('target',lambda c:[Damage(c.target_id,1,c.source_id,DamageKind.HERO_POWER)],
                   targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(power='target',enemy=('protected',));target=g.state.players[2].board[0]
        with self.assertRaises(IllegalAction):self.use(g,target)
        self.play(g);self.assertEqual(g.state.entities[target].health,3);self.check(g)

    def test_no_required_target_records_failure_and_continues(self):
        self.power('target',lambda c:[GainArmor(1,9)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.script('after',lambda c:[TriggerHeroPower(1,c.source_id),GainArmor(1,2)])
        g=self.game(power='target',hand=('after',));rng=g.snapshot()['rng_state'];self.play(g,'after')
        p=g.state.hero_power_history[0]
        self.assertEqual((p.failure,p.completed,self.armor(g)),('no_target',True,2))
        self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertFalse(any(e.kind=='hero_power_triggered' for e in g.events));self.check(g)

    def test_invalid_explicit_target_records_failure_without_dangling_id(self):
        self.script('badtarget',lambda c:[TriggerHeroPower(1,c.source_id,99999,targeting='explicit')])
        g=self.game(hand=('badtarget',));self.play(g,'badtarget');p=g.state.hero_power_history[0]
        self.assertEqual((p.failure,p.target_id),('invalid_target',None));self.check(g)

    def test_explicit_valid_target_avoids_random_selection(self):
        self.power('target',lambda c:[Damage(c.target_id,1,c.source_id,DamageKind.HERO_POWER)],requires_target=True)
        self.script('aim',lambda c:[TriggerHeroPower(1,c.source_id,c.state.players[2].hero_id,targeting='explicit')])
        g=self.game(power='target',hand=('aim',));rng=g.snapshot()['rng_state'];self.play(g,'aim')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_if_available_target_can_be_omitted_only_when_no_candidates(self):
        self.power('optional',lambda c:[GainArmor(1,1)],
            targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy',mode=TargetMode.IF_AVAILABLE))
        self.script('omit',lambda c:[TriggerHeroPower(1,c.source_id,targeting='explicit')])
        for enemy,failed in (((),False),(('plain',),True)):
            with self.subTest(enemy=enemy):
                g=self.game(power='optional',hand=('omit',),enemy=enemy);self.play(g,'omit')
                self.assertEqual(g.state.hero_power_history[0].failure is not None,failed);self.check(g)

    def test_random_targeting_reproducible_across_same_seed(self):
        self.power('target',lambda c:[Damage(c.target_id,1,c.source_id,DamageKind.HERO_POWER)],requires_target=True)
        a=self.game(power='target',enemy=('plain',)*3);b=self.game(power='target',enemy=('plain',)*3)
        self.play(a);self.play(b);self.assertEqual(a.snapshot(),b.snapshot());self.check(a)

    def test_player_target_rule_receives_only_detached_observation(self):
        def own_minion(c):
            self.assertFalse(hasattr(c,'state'))
            self.assertFalse(any(x.get('card_id') is not None for p in c.observation['players'] if p['id']==2 for x in p['hand']))
            return c.target is not None and c.target['controller']==c.player_id
        self.r.register_target_rule('own',own_minion,visibility='player')
        self.power('target',lambda c:[GainArmor(1,1)],targeting=TargetSpec(kinds=(CardType.MINION,)),target_rule='own')
        g=self.game(power='target',board=('plain',),enemy=('plain',));self.play(g)
        self.assertEqual(g.state.hero_power_history[0].target_id,g.state.players[1].board[0]);self.check(g)

    def test_manual_choices_suspend_and_indirect_random_choices_do_not(self):
        self.choice_power();manual=self.game(power='choice',hand=());self.use(manual)
        self.assertIsNotNone(manual.state.pending_choice);self.check(manual);self.choose(manual)
        indirect=self.game(power='choice');self.play(indirect)
        self.assertIsNone(indirect.state.pending_choice)
        self.assertTrue(any(e.kind=='hero_power_choice_automatic' for e in indirect.events));self.check(indirect)

    def test_explicit_player_choice_for_indirect_source_restores(self):
        self.choice_power();self.script('ask',lambda c:[TriggerHeroPower(1,c.source_id,choices='player')])
        g=self.game(power='choice',hand=('ask',));self.play(g,'ask');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match,'3')
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_independent_reaction_choices_remain_player_controlled(self):
        self.watch('watch',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok'),),source_id=c.source_id)],'hero_power_trigger_started')
        self.choice_power();g=self.game(power='choice',board=('watch',));self.play(g)
        self.assertEqual(g.state.pending_choice.source_id,g.state.players[1].board[0]);self.check(g)
        self.choose(g);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_opponent_owned_choice_does_not_inherit_automatic_policy(self):
        self.power('opponentchoice',lambda c:[RequestChoice(2,(ChoiceOption('ok','ok'),),source_id=c.source_id)])
        g=self.game(power='opponentchoice');self.play(g)
        self.assertEqual(g.state.pending_choice.player_id,2);self.choose(g);self.check(g)

    def test_nested_spells_keep_independent_random_choice_policy(self):
        self.script('choose_spell',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(GainArmor(1,3),)),),source_id=c.source_id)])
        self.power('cast',lambda c:[CastSpell(1,'choose_spell',c.source_id)])
        g=self.game(power='cast',hand=());self.use(g)
        self.assertEqual((len(g.state.hero_power_history),len(g.state.cast_history),len(g.state.play_history)),(1,1,0))
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.armor(g),3);self.check(g)

    def test_automatic_spell_can_trigger_power_without_fake_hand_play(self):
        self.script('auto',lambda c:[CastSpell(1,'trigger',c.source_id)])
        g=self.game(hand=('auto',));self.play(g,'auto')
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history),len(g.state.hero_power_history)),(1,2,1));self.check(g)

    def test_origin_removed_by_start_reaction_does_not_cancel_power(self):
        self.script('minion',lambda c:[TriggerHeroPower(1,c.source_id)],CardType.MINION)
        self.watch('kill',lambda c:[Destroy(c.power.activator_id)],'hero_power_trigger_started')
        g=self.game(hand=('minion',),board=('kill',));eid=self.play(g,'minion')
        self.assertNotIn(eid,g.state.players[1].board);self.assertEqual(self.armor(g),1);self.check(g)

    def test_lethal_power_interrupts_pending_activation_and_followups(self):
        self.power('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id,DamageKind.HERO_POWER),GainArmor(1,9)])
        g=self.game(power='lethal');self.play(g)
        self.assertEqual(g.state.status,'finished');p=g.state.hero_power_history[0]
        self.assertTrue(p.interrupted);self.assertFalse(p.completed)
        self.assertEqual(self.armor(g),0);self.check(g)

    def test_lethal_start_reaction_interrupts_before_payload(self):
        self.watch('kill',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)],'hero_power_started')
        g=self.game(board=('kill',),hand=());self.use(g)
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.hero_power_history[0].interrupted);self.check(g)

    def test_hero_power_exception_rolls_back_payment_and_history(self):
        self.power('bad',lambda c:[GainArmor(1,3),TriggerHeroPower(1,99999)])
        g=self.game(power='bad',hand=());before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_error_after_choice_rolls_back_only_selection(self):
        self.power('badchoice',lambda c:[RequestChoice(1,(ChoiceOption('bad','bad',(TriggerHeroPower(1,99999),)),
            ChoiceOption('ok','ok',(GainArmor(1,3),))),source_id=c.source_id)])
        g=self.game(power='badchoice',hand=());self.use(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g,'ok');self.check(g)

    def test_recursive_trigger_uses_common_budget_and_transaction(self):
        self.power('loop',lambda c:[TriggerHeroPower(1,c.source_id)])
        g=self.game(power='loop',rules=Ruleset(max_resolution_steps=30));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_hand_rewind_restores_indirect_power_history_and_costs(self):
        self.script('rewind',lambda c:[TriggerHeroPower(1,c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual((len(g.state.hero_power_history),self.armor(g),self.source(g).uses_this_turn),(1,1,0));self.check(g)

    def test_history_query_filters_origins_success_and_turn(self):
        g=self.game(hand=('trigger','trigger'));self.use(g);self.play(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        self.assertEqual([p.id for p in activated_powers(g.state,1,origin='manual')],[1])
        self.assertEqual([p.id for p in activated_powers(g.state,1,turn=1)],[1,2])
        self.assertEqual([p.id for p in activated_powers(g.state,1,successful=True,before_id=3)],[1,2]);self.check(g)

    def test_corrupt_record_fields_rejected_after_rehashing(self):
        g=self.game(hand=());self.use(g)
        for key,value in (('id',2),('source_id',99999),('source_id',g.state.players[1].hero_id),
            ('card_id','plain'),('player_id',2),('payment',None),('cost',True),('origin','effect'),
            ('parent_id',1),('turn',99),('action',99),('interrupted',True),('failure','no_target')):
            with self.subTest(key=key,value=value):
                s=g.snapshot();s['state']['hero_power_history'][0][key]=value;self.reject(s)

    def test_missing_history_and_missing_completion_marker_rejected(self):
        self.choice_power();g=self.game(power='choice',hand=());self.use(g)
        s=g.snapshot();del s['state']['hero_power_history'];self.reject(s)
        s=g.snapshot()
        def corrupt(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.FinishHeroPower'):v['fields']['record_id']=99999
                for x in v.values():corrupt(x)
            elif isinstance(v,list):
                for x in v:corrupt(x)
        corrupt(s);self.reject(s)

    def test_invalid_effect_and_query_arguments_fail_strictly(self):
        for fn in (lambda:TriggerHeroPower(True),lambda:TriggerHeroPower(1,False),
            lambda:TriggerHeroPower(1,target_id=3),lambda:TriggerHeroPower(1,choices='first'),
            lambda:TriggerHeroPower(1,targeting='player'),lambda:activated_powers(self.game().state,1,origin='spell'),
            lambda:activated_powers(self.game().state,1,successful=1),lambda:activated_powers(self.game().state,1,turn=0)):
            with self.subTest(fn=fn),self.assertRaises(ValueError):fn()

    def test_player_logs_distinguish_origins_without_exposing_history(self):
        g=self.game();self.play(g);port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='use_hero_power')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        for viewer in (1,2):
            public=g.player_events(viewer);kinds=[e['kind'] for e in public]
            self.assertIn('hero_power_triggered',kinds);self.assertIn('hero_power_used',kinds)
            text=json.dumps((g.observe(viewer),public))
            for key in ('hero_power_history','activator_id','parent_id','power_id','choices'):
                self.assertNotIn('"'+key+'"',text)
        self.check(g)


class WispriderTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand=('EDR_519',),board=(),hero='HERO_08',power='HERO_08bp',mana=10):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,hero_power_card_id=power,mana=mana,max_mana=10),
            PlayerSetup('HERO_01')),seed=61),self.r)
    def play(self,g,cid='EDR_519'):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def check(self,g):
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())
    def test_frozen_wisprider_imbues_before_trigger_with_exact_five_mana(self):
        card=self.r.card('EDR_519');self.assertEqual((card.cost,card.attack,card.health),(5,4,4))
        g=self.game(mana=5);eid=self.play(g)
        self.assertEqual((imbue_count(g.state,1),g.state.players[1].mana),(1,0))
        p=g.state.hero_power_history[0]
        self.assertEqual((p.card_id,p.origin,p.activator_id),('EDR_851p','effect',eid))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.check(g)
    def test_wisprider_does_not_refresh_already_used_imbued_power(self):
        g=self.game(hand=('EDR_852','EDR_519'));self.play(g,'EDR_852')
        power=g.state.players[1].hero_power_id;g.apply(UseHeroPower(1,power));self.play(g)
        self.assertEqual(g.state.players[1].hero_power_id,power)
        self.assertEqual(g.state.entities[power].uses_this_turn,1)
        self.assertEqual([p.origin for p in g.state.hero_power_history],['manual','effect'])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.check(g)
    def test_full_board_mage_still_gets_damage(self):
        g=self.game(board=('CS2_182',)*6);self.play(g)
        self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,29);self.check(g)
    def test_stolen_druid_source_uses_druid_power(self):
        g=self.game(hero='HERO_06',power='HERO_06bp');self.play(g)
        self.assertEqual(g.state.hero_power_history[0].card_id,'EDR_847p')
        self.assertTrue(any(g.state.entities[i].card_id=='EDR_847pt2' for i in g.state.players[1].board));self.check(g)
    def test_no_imbue_class_still_triggers_unchanged_power(self):
        g=self.game(hero='HERO_01',power='HERO_01bp');self.play(g)
        self.assertEqual(g.state.hero_power_history[0].card_id,'HERO_01bp')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(imbue_count(g.state,1,applied_only=True),0);self.check(g)
    def test_example_uses_manual_and_indirect_activation(self):
        from examples.hero_power_sources import run
        g,snapshot=run();self.assertEqual(snapshot['schema_version'],266)
        self.assertEqual([p.origin for p in g.state.hero_power_history],['effect','manual'])


if __name__=='__main__':unittest.main()
