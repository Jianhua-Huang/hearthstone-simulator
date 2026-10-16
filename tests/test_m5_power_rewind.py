"""Hero Power checkpoints and cumulative outcomes; provisional R-102."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest

from hs_sim.engine import (CardDefinition,CardType,Game,Registry,PlayerSetup,Scenario,
    PlayCard,UseHeroPower,SelectChoice,EndTurn,TriggerSpec,TargetSpec,Keyword,RewindSpec,
    TriggerHeroPower,PaymentType,CostSpec,IllegalAction,ResolutionError,SnapshotError,
    Ruleset,ResolutionLimitExceeded,CastSpell)
from hs_sim.engine.effects import (GainArmor,Damage,Summon,Destroy,AddToHand,RandomDamage,
    ReplaceHeroPower,RefreshHeroPower,ModifyCost,AddCostModifier,RequestChoice,
    ChoiceOption,Silence,RevealHandCard)
from hs_sim.engine.model import ChoicePurpose,DamageKind
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


class PowerRewindTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('power-rewind-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=1,health=4))
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.power('power',lambda c:[GainArmor(c.player_id,c.rewind_attempt+2)])
        self.power('plain',lambda c:[GainArmor(c.player_id,1)],retries=None)
        self.script('trigger',lambda c:[TriggerHeroPower(c.player_id,c.source_id)])
    def power(self,cid,fn,retries=1,**kw):
        self.r.register_behavior(cid,fn)
        if retries is not None:kw.update(rewind=RewindSpec(retries),keywords=(Keyword.REWIND,))
        self.r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=2,on_use=cid,**kw))
    def script(self,cid,fn,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,**kw))
    def watch(self,cid,fn,event):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,triggers=(TriggerSpec(event,cid),)))
    def game(self,power='power',hand=(),board=(),enemy=(),mana=10,rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,
            deck=('body',)*4,hero_power_card_id=power,mana=mana,max_mana=10),
            PlayerSetup('hero',hand=('body',),board=enemy,deck=('body',)*4,
                hero_power_card_id='plain',mana=10,max_mana=10)),seed=62),self.r,rules)
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def use(self,g,target=None):g.apply(UseHeroPower(1,g.state.players[1].hero_power_id,target))
    def source(self,g):return g.state.entities[g.state.players[1].hero_power_id]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def choose(self,g,option='retry'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option,)))
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))
    def choice_power(self):
        self.power('choice',lambda c:[RequestChoice(1,tuple(ChoiceOption(str(n),str(n),
            (GainArmor(1,n+c.rewind_attempt),)) for n in (2,5)),source_id=c.source_id)])

    def test_keep_commits_one_payment_use_and_history(self):
        g=self.game();self.use(g);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND);self.check(g)
        self.choose(g,'keep');self.assertEqual((g.state.players[1].mana,self.source(g).uses_this_turn,self.hero(g).armor),(8,1,2))
        self.assertEqual((len(g.state.hero_power_history),g.state.play_history,g.state.cast_history),(1,[],[]));self.check(g)

    def test_retry_restores_payment_use_and_completed_history(self):
        g=self.game();power=self.source(g).id;self.use(g);self.choose(g)
        self.assertEqual((g.state.players[1].mana,self.source(g).uses_this_turn,g.state.players[1].hero_power_uses_this_turn),(8,1,1))
        self.assertEqual((self.source(g).id,self.hero(g).armor),(power,3));self.assertEqual(len(g.state.hero_power_history),1)
        self.assertTrue(g.state.hero_power_history[0].completed);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_multiple_retries_exhaust_budget_without_extra_activation(self):
        self.power('many',lambda c:[GainArmor(1,c.rewind_attempt+1)],retries=3)
        g=self.game(power='many');self.use(g)
        for n in range(1,4):self.choose(g);self.assertEqual(self.hero(g).armor,n+1);self.check(g)
        self.assertEqual(len(g.state.hero_power_history),1);self.assertIsNone(g.state.pending_choice)

    def test_next_turn_starts_fresh_budget_on_same_entity(self):
        g=self.game();eid=self.source(g).id;self.use(g);self.choose(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.use(g)
        self.assertEqual(self.source(g).id,eid);self.assertEqual(self.hero(g).armor,5)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g);self.assertEqual(self.hero(g).armor,6);self.check(g)

    def test_refresh_starts_fresh_budget_and_preserves_prior_history(self):
        self.script('refresh',lambda c:[RefreshHeroPower(1)])
        g=self.game(hand=('refresh',));self.use(g);self.choose(g);first=g.state.hero_power_history[0]
        self.play(g,'refresh');self.use(g);self.choose(g)
        self.assertEqual(g.state.hero_power_history[0],first);self.assertEqual(len(g.state.hero_power_history),2)
        self.assertEqual((g.state.players[1].mana,self.hero(g).armor),(6,6));self.check(g)

    def test_retry_consumes_single_use_discount_once(self):
        self.script('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-1,card_types=(CardType.HERO_POWER,)),uses_remaining=1)])
        g=self.game(hand=('discount',));self.play(g,'discount');self.use(g);self.choose(g)
        self.assertEqual(g.state.players[1].mana,9);self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.hero_power_history[0].cost,1);self.check(g)

    def test_health_payment_is_restored_and_charged_once(self):
        self.script('health',lambda c:[ModifyCost(c.state.players[1].hero_power_id,CostSpec(payment=PaymentType.HEALTH,card_types=(CardType.HERO_POWER,)))])
        g=self.game(hand=('health',));self.play(g,'health');self.use(g);self.choose(g)
        self.assertEqual((self.hero(g).health,g.state.players[1].mana),(28,10))
        self.assertEqual(g.state.hero_power_history[0].payment,PaymentType.HEALTH);self.check(g)

    def test_random_stream_advances_but_only_final_damage_survives(self):
        self.power('random',lambda c:[RandomDamage(tuple(c.state.players[2].board),1,c.source_id,kind=DamageKind.HERO_POWER)])
        g=self.game(power='random',enemy=('body',)*3);self.use(g);rng=g.snapshot()['rng_state'];self.choose(g)
        self.assertNotEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(sum(g.state.entities[i].damage for i in g.state.players[2].board),1);self.check(g)

    def test_generated_entities_removed_without_reusing_identity(self):
        self.power('generate',lambda c:[AddToHand(1,'body'),Summon(1,'body')])
        g=self.game(power='generate');self.use(g);old=tuple(g.state.players[1].hand+g.state.players[1].board);self.choose(g)
        self.assertTrue(all(i not in g.state.entities for i in old))
        self.assertGreater(min(g.state.players[1].hand+g.state.players[1].board),max(old));self.check(g)

    def test_target_and_source_held_constant_across_retry(self):
        self.power('target',lambda c:[Damage(c.target_id,c.rewind_attempt+1,c.source_id,DamageKind.HERO_POWER)],requires_target=True)
        g=self.game(power='target');target=self.hero(g,2).id;self.use(g,target);self.choose(g)
        self.assertEqual((self.hero(g,2).health,g.state.hero_power_history[0].target_id),(28,target));self.check(g)

    def test_replaced_source_restored_before_retry_and_old_payload_finishes(self):
        self.power('replace',lambda c:[ReplaceHeroPower(1,'plain'),GainArmor(1,c.rewind_attempt+2)])
        g=self.game(power='replace');old=self.source(g).id;self.use(g);replacement=self.source(g).id;self.check(g);self.choose(g)
        self.assertNotIn(replacement,g.state.entities);self.assertEqual(g.state.hero_power_history[0].source_id,old)
        self.assertEqual((self.source(g).card_id,self.hero(g).armor),('plain',3));self.check(g)

    def test_start_and_finish_reactions_retried_as_part_of_activation(self):
        self.watch('start',lambda c:[GainArmor(1,3)],'hero_power_started')
        self.watch('end',lambda c:[GainArmor(1,5)],'hero_power_used')
        g=self.game(board=('start','end'));self.use(g);self.choose(g)
        self.assertEqual(self.hero(g).armor,11);self.check(g)

    def test_choices_suspend_inside_each_attempt_and_restore(self):
        self.choice_power();g=self.game(power='choice');self.use(g);self.check(g)
        self.choose(g,'2');self.check(g);self.choose(g);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match,'5')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,6);self.check(g)

    def test_opponent_choice_keeps_its_owner_on_retry(self):
        self.power('opponent',lambda c:[RequestChoice(2,(ChoiceOption('ok','ok',(GainArmor(2,1),)),),source_id=c.source_id)])
        g=self.game(power='opponent');self.use(g);self.assertEqual(g.state.pending_choice.player_id,2)
        self.choose(g,'ok');self.choose(g);self.assertEqual(g.state.pending_choice.player_id,2);self.check(g)
        self.choose(g,'ok');self.assertEqual(self.hero(g,2).armor,1);self.check(g)

    def test_invalid_choice_rolls_back_pending_checkpoint(self):
        g=self.game();self.use(g);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_retry_failure_rolls_back_to_prior_result_choice(self):
        self.power('badretry',lambda c:[Summon(1,'missing')] if c.rewind_attempt else [GainArmor(1,2)])
        g=self.game(power='badretry');self.use(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.choose(g,'keep');self.check(g)

    def test_terminal_attempt_has_no_rewind_prompt(self):
        self.power('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)])
        g=self.game(power='lethal');self.use(g)
        self.assertEqual(g.state.status,'finished');self.assertIsNone(g.snapshot()['rewind_session'])
        self.assertTrue(g.state.hero_power_history[0].interrupted);self.check(g)

    def test_nested_indirect_same_power_does_not_inherit_root_attempt(self):
        self.power('nested',lambda c: [TriggerHeroPower(1,c.source_id),GainArmor(1,10+c.rewind_attempt)]
            if c.power.origin=='manual' else [GainArmor(1,1+c.rewind_attempt)])
        g=self.game(power='nested');self.use(g);self.choose(g)
        self.assertEqual(self.hero(g).armor,12)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history],[None,1]);self.check(g)

    def test_indirect_without_retainer_has_no_manual_checkpoint(self):
        g=self.game(hand=('trigger',),mana=0);self.play(g,'trigger')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.hero(g).armor,2)
        self.assertEqual((g.state.players[1].mana,self.source(g).uses_this_turn),(0,0));self.check(g)

    def test_indirect_inside_rewind_spell_keeps_independent_provenance(self):
        self.script('rewindspell',lambda c:[TriggerHeroPower(1,c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewindspell',));self.play(g,'rewindspell');self.choose(g)
        self.assertEqual((len(g.state.hero_power_history),len(g.state.play_history),self.hero(g).armor),(1,1,2));self.check(g)

    def test_retained_payloads_share_one_payment_and_use(self):
        g=self.game(board=('retainer',));self.use(g)
        self.assertEqual((self.hero(g).armor,g.state.players[1].mana,self.source(g).uses_this_turn),(5,8,1))
        self.assertEqual(len(g.state.hero_power_history),1);out=g.state.rewind_outcomes[0]
        self.assertEqual((out.power_id,out.play_id,out.cast_id,out.completed,out.total),(1,None,None,2,2))
        self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_multiple_retainers_do_not_stack(self):
        g=self.game(board=('retainer',)*2);self.use(g)
        self.assertEqual(self.hero(g).armor,5);self.assertEqual(len(g.state.rewind_outcomes[0].contributors),2);self.check(g)

    def test_retained_indirect_power_spends_neither_mana_nor_use(self):
        g=self.game(hand=('trigger',),board=('retainer',),mana=0);self.play(g,'trigger')
        self.assertEqual((self.hero(g).armor,g.state.players[1].mana,self.source(g).uses_this_turn),(5,0,0))
        self.assertEqual(g.state.rewind_outcomes[0].power_id,1);self.check(g)

    def test_retained_power_reactions_fire_once_for_activation(self):
        self.watch('end',lambda c:[GainArmor(1,10)],'hero_power_used')
        g=self.game(board=('retainer','end'));self.use(g)
        self.assertEqual(self.hero(g).armor,15);self.assertEqual(sum(e.kind=='hero_power_used' for e in g.events),1);self.check(g)

    def test_retainer_destroyed_in_first_outcome_does_not_cancel_capture(self):
        self.power('kill',lambda c:[Destroy(c.state.players[1].board[0]),GainArmor(1,c.rewind_attempt+2)]
            if c.state.players[1].board else [GainArmor(1,c.rewind_attempt+2)])
        g=self.game(power='kill',board=('retainer',));self.use(g)
        self.assertEqual(self.hero(g).armor,5);self.assertFalse(g.state.players[1].board);self.check(g)

    def test_retainer_created_by_payload_does_not_retroactively_capture(self):
        self.power('make',lambda c:[Summon(1,'retainer')])
        g=self.game(power='make');self.use(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.rewind_outcomes);self.choose(g);self.assertEqual(len(g.state.players[1].board),1);self.check(g)

    def test_silenced_retainer_does_not_capture(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(hand=('silence',),board=('retainer',));self.play(g,'silence');self.use(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.rewind_outcomes);self.choose(g,'keep');self.check(g)

    def test_retained_choices_resume_at_each_outcome(self):
        self.choice_power();g=self.game(power='choice',board=('retainer',));self.use(g);self.check(g)
        self.choose(g,'2');self.assertEqual(self.hero(g).armor,2);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match,'5')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,8);self.check(g)

    def test_retained_nested_same_power_uses_each_activation_outcome_index(self):
        self.power('nested',lambda c: [TriggerHeroPower(1,c.source_id),GainArmor(1,10+c.rewind_attempt)]
            if c.power.origin=='manual' else [GainArmor(1,1+c.rewind_attempt)])
        g=self.game(power='nested',board=('retainer',));self.use(g)
        self.assertEqual(self.hero(g).armor,27)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history],[None,1,1])
        self.assertEqual([o.power_id for o in g.state.rewind_outcomes],[1,2,3]);self.check(g)

    def test_retained_nested_choices_have_distinct_closers_after_restore(self):
        self.power('nested',lambda c:[TriggerHeroPower(1,c.source_id,choices='player')]
            if c.power.origin=='manual' else [RequestChoice(1,(ChoiceOption('ok','ok',(GainArmor(1,c.rewind_attempt+1),)),),source_id=c.source_id)])
        g=self.game(power='nested',board=('retainer',));self.use(g)
        for _ in range(4):self.check(g);self.choose(g,'ok')
        self.assertEqual(self.hero(g).armor,6);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_retained_terminal_outcome_interrupts_remaining_work(self):
        self.power('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)])
        g=self.game(power='lethal',board=('retainer',));self.use(g)
        self.assertTrue(g.state.rewind_outcomes[0].interrupted);self.assertTrue(g.state.hero_power_history[0].interrupted);self.check(g)

    def test_retained_missing_target_has_no_outcome_record(self):
        self.power('target',lambda c:[GainArmor(1,20)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(power='target',hand=('trigger',),board=('retainer',));self.play(g,'trigger')
        self.assertEqual(g.state.hero_power_history[0].failure,'no_target');self.assertFalse(g.state.rewind_outcomes);self.check(g)

    def test_retained_resolution_budget_errors_transactionally(self):
        self.power('many',lambda c:[GainArmor(1,1)],retries=100)
        g=self.game(power='many',board=('retainer',),rules=Ruleset(max_resolution_steps=50));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_snapshot_rejects_wrong_rewind_action_kind(self):
        g=self.game();self.use(g);s=g.snapshot();s['rewind_session']['action']={'type':'end_turn','player_id':1};self.reject(s)

    def test_snapshot_rejects_rewind_root_without_manual_history(self):
        g=self.game();self.use(g);s=g.snapshot();s['state']['hero_power_history']=[];self.reject(s)

    def test_snapshot_rejects_invalid_retained_power_reference(self):
        g=self.game(board=('retainer',));self.use(g)
        for value in (None,0,True,99):
            with self.subTest(value=value):s=g.snapshot();s['state']['rewind_outcomes'][0]['power_id']=value;self.reject(s)

    def test_snapshot_rejects_mixed_power_and_play_references(self):
        g=self.game(board=('retainer',));self.use(g);s=g.snapshot();s['state']['rewind_outcomes'][0]['play_id']=1;self.reject(s)

    def test_snapshot_rejects_missing_power_outcome_closer(self):
        self.choice_power();g=self.game(power='choice',board=('retainer',));self.use(g);s=g.snapshot()
        def corrupt(v):
            if isinstance(v,dict):
                if str(v.get('type','')).endswith('.FinishHeroPower'):v['fields']['record_id']=99
                for item in v.values():corrupt(item)
            elif isinstance(v,list):
                for item in v:corrupt(item)
        corrupt(s);self.reject(s)

    def test_definition_rejects_power_rewind_face_chain(self):
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.HERO_POWER,
            on_use='power',keywords=(Keyword.REWIND,),rewind=RewindSpec(next_card_id='plain')))

    def test_player_observation_hides_checkpoint_and_opponent_choices(self):
        g=self.game();self.use(g);view=g.for_player(2).observe()
        text=json.dumps(view);self.assertNotIn('rewind_session',text);self.assertNotIn('hero_power_history',text)
        self.assertEqual(g.for_player(2).legal_actions()['actions'],[{'type':'concede'}]);self.check(g)

    def test_plain_power_does_not_create_checkpoint(self):
        g=self.game(power='plain');self.use(g)
        self.assertIsNone(g.state.pending_choice);self.assertIsNone(g.snapshot()['rewind_session']);self.check(g)


class BronzeRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand=('EDR_852',),board=(),context=True):
        from hs_sim.engine import GenerationContext
        return Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=hand,board=board,
            mana=10,max_mana=10,deck=('CS2_182',)*3),PlayerSetup('HERO_01',deck=('CS2_182',)*3)),
            seed=62,generation_context=GenerationContext('local-2026-09-23','experimental') if context else None),self.r)
    play=PowerRewindTests.play
    use=PowerRewindTests.use
    choose=PowerRewindTests.choose
    check=PowerRewindTests.check
    reject=PowerRewindTests.reject
    def generated(self,g):return [g.state.entities[i] for i in g.state.players[1].hand]

    def test_frozen_power_and_explicit_incomplete_pool(self):
        from hs_sim.engine.representative import BRONZE_SAMPLE_IDS
        power=self.r.card('END_000p')
        self.assertEqual((power.name,power.cost,power.rewind.retries),('青铜龙的祝福',1,1))
        self.assertEqual(len(BRONZE_SAMPLE_IDS),5)
        g=self.game();self.play(g,'EDR_852');self.use(g);self.choose(g,'keep')
        self.assertIn(self.generated(g)[0].card_id,('EDR_451','EX1_608','TID_099'));self.check(g)

    def test_rogue_retry_replaces_generated_card_and_restores_single_cost(self):
        g=self.game();self.play(g,'EDR_852');power=g.state.players[1].hero_power_id;self.use(g)
        first=self.generated(g)[0].id;self.check(g);self.choose(g)
        self.assertNotIn(first,g.state.entities);self.assertGreater(self.generated(g)[0].id,first)
        self.assertEqual((g.state.players[1].mana,g.state.players[1].hero_power_id),(7,power))
        self.assertEqual(len(g.state.hero_power_history),1);self.check(g)

    def test_imbue_growth_applies_discount_to_each_retained_card(self):
        from hs_sim.engine.costs import local_cost
        g=self.game(hand=('EDR_852',)*3,board=('END_036',))
        for _ in range(3):self.play(g,'EDR_852')
        self.use(g);cards=self.generated(g)
        self.assertEqual(len(cards),2);self.assertTrue(all(local_cost(e)[0]==0 for e in cards))
        self.assertEqual(g.state.players[1].mana,3);self.assertEqual(g.state.rewind_outcomes[0].completed,2);self.check(g)

    def test_wisprider_triggers_rogue_without_consuming_manual_rewind(self):
        g=self.game(hand=('EDR_519',));self.play(g,'EDR_519')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.generated(g)),1)
        self.use(g);self.choose(g)
        self.assertEqual([p.origin for p in g.state.hero_power_history],['effect','manual'])
        self.assertEqual((g.state.players[1].mana,g.state.players[1].hero_power_uses_this_turn,len(self.generated(g))),(4,1,2));self.check(g)

    def test_wisprider_and_morchie_retain_both_indirect_results(self):
        g=self.game(hand=('EDR_519',),board=('END_036',));self.play(g,'EDR_519')
        self.assertEqual((len(self.generated(g)),g.state.players[1].mana,g.state.players[1].hero_power_uses_this_turn),(2,5,0))
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.rewind_outcomes[0].power_id,1);self.check(g)

    def test_full_hand_retry_keeps_burn_and_usage_consistent(self):
        g=self.game(hand=('EDR_852',)+('CS2_182',)*9);self.play(g,'EDR_852');self.use(g);self.choose(g,'keep')
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.use(g);self.check(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len(g.state.hero_power_history),2);self.assertEqual(g.state.players[1].mana,9);self.check(g)

    def test_missing_generation_context_rolls_back_entire_activation(self):
        g=self.game(context=False);self.play(g,'EDR_852');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.use(g)
        self.assertEqual(g.snapshot(),before)

    def test_generated_card_hidden_from_opponent_across_retry(self):
        g=self.game();self.play(g,'EDR_852');self.use(g)
        for retry in (False,True):
            if retry:self.choose(g)
            view=g.observe(2);owner=next(p for p in view['players'] if p['id']==1)
            self.assertTrue(all(c['card_id'] is None for c in owner['hand']))
            self.assertNotIn('rewind_session',json.dumps(view));self.check(g)

    def test_schema61_is_explicitly_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=61;self.reject(s)

    def test_real_example_restores_and_replays_player_actions(self):
        from examples.hero_power_rewind import run
        g,s=run();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(len(g.state.hero_power_history),2)
        self.assertEqual(g.state.rewind_outcomes[0].completed,2)


if __name__=='__main__':unittest.main()
