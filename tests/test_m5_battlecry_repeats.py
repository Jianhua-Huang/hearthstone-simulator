"""Battlecry set-count policies and independent, resumable batch progress."""
import json
import unittest
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (BattlecryRepeatSpec, BattlecryRepeatPlan, CardDefinition, CardType,
    Game, PlayCard, SelectChoice, EndTurn, Keyword, RewindSpec, Ruleset, AbilityInstance,
    GrantBattlecryRepeatAura, TargetSpec, ResolutionError, ResolutionLimitExceeded, SnapshotError)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Silence, ReturnToHand,
    CopyMinion, Transform, ChangeControl, RequestChoice, ChoiceOption, Summon, InvokeBehavior,
    GrantDeathrattle, RandomDamage)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.serialization import canonical_hash


class BattlecryRepeatTests(unittest.TestCase):
    card=foundation.BattlecryTests.card
    script=foundation.BattlecryTests.script
    watch=foundation.BattlecryTests.watch
    game=foundation.BattlecryTests.game
    play=foundation.BattlecryTests.play
    choose=foundation.BattlecryTests.choose
    pause=foundation.BattlecryTests.pause
    armor=foundation.BattlecryTests.armor
    check=foundation.BattlecryTests.check
    reject=foundation.BattlecryTests.reject
    nested=foundation.BattlecryTests.nested

    def setUp(self):
        foundation.BattlecryTests.setUp(self)
        self.aura('repeat')

    def aura(self,name,spec=None,**kw):
        self.r.register_card(CardDefinition(name,name,CardType.MINION,health=4,
            battlecry_repeats=(spec or BattlecryRepeatSpec(),),**kw))

    def board(self,g,p=1): return g.state.players[p].board
    def records(self,g): return g.state.battlecry_history
    def batch(self,g): return g.state.battlecry_batches[-1]
    def mutate(self,name,fn): self.script(name,lambda c:fn(c,c.state.players[1].board[0]))

    def test_twice_is_one_play_payment_and_no_spell_cast(self):
        g=self.game(board=('repeat',));self.play(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(4,8,1))
        self.assertEqual(g.state.cast_history,[])
        self.assertEqual([b.repeat_index for b in self.records(g)],[1,2])
        self.assertEqual({b.iteration for b in self.records(g)},{1})
        self.assertEqual((self.batch(g).completed,self.batch(g).finished),(2,True));self.check(g)

    def test_multiple_matching_sources_use_max_not_product(self):
        self.aura('three',BattlecryRepeatSpec(3))
        g=self.game(board=('repeat','repeat','three'));self.play(g)
        self.assertEqual(self.armor(g),6);self.assertEqual(len(self.batch(g).plan.contributors),3);self.check(g)

    def test_duplicate_twice_sources_remain_twice(self):
        g=self.game(board=('repeat','repeat'));self.play(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_opponent_aura_is_excluded(self):
        g=self.game(enemy=('repeat',));self.play(g);self.assertEqual(self.armor(g),2)
        self.assertEqual(self.batch(g).plan,BattlecryRepeatPlan());self.check(g)

    def test_kind_filter_and_all_physical_kinds(self):
        self.card('weapon',kind=CardType.WEAPON)
        self.card('hero_card',kind=CardType.HERO,hero_card=True,initial_hero_power='power')
        self.aura('minions',BattlecryRepeatSpec(kinds=(CardType.MINION,)))
        for carrier,name,expected in (('repeat','weapon',4),('repeat','hero_card',4),('minions','weapon',2),('minions','cry',4)):
            with self.subTest(carrier=carrier,name=name):
                g=self.game(hand=(name,),board=(carrier,));self.play(g,name)
                self.assertEqual(self.armor(g),expected);self.check(g)

    def test_generic_payload_once_then_battlecry_twice(self):
        self.r.register_behavior('generic',lambda c:[GainArmor(1,7)])
        self.card('mixed',on_play='generic')
        g=self.game(hand=('mixed',),board=('repeat',));self.play(g,'mixed')
        self.assertEqual(self.armor(g),11);self.assertEqual(len(self.records(g)),2);self.check(g)

    def test_summon_and_spell_payloads_do_not_create_batches(self):
        self.script('summon',lambda c:[Summon(1,'cry'),GainArmor(1,3)])
        g=self.game(hand=('summon',),board=('repeat',));self.play(g,'summon')
        self.assertEqual((self.armor(g),g.state.battlecry_batches),(3,[]));self.check(g)

    def test_same_manual_target_used_twice(self):
        self.card('damage',lambda c:[Damage(c.target_id,2,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,)))
        g=self.game(hand=('damage',),board=('repeat',),enemy=('body',));i=self.board(g,2)[0]
        self.play(g,'damage',i);self.assertEqual(g.state.entities[i].health,1)
        self.assertEqual([b.target_id for b in self.records(g)],[i,i]);self.check(g)

    def test_dead_target_is_not_reselected(self):
        self.card('damage',lambda c:[Damage(c.target_id,6,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,)))
        g=self.game(hand=('damage',),board=('repeat',),enemy=('body','body'));i,j=self.board(g,2)
        self.play(g,'damage',i);self.assertEqual(self.board(g,2),[j]);self.assertEqual(g.state.entities[j].health,5)
        self.assertEqual([b.target_id for b in self.records(g)],[i,i]);self.assertTrue(all(b.completed for b in self.records(g)));self.check(g)

    def test_bounced_target_keeps_reference_and_effect_stales(self):
        self.card('bounce',lambda c:[ReturnToHand(c.target_id)],targeting=TargetSpec(kinds=(CardType.MINION,)))
        g=self.game(hand=('bounce',),board=('repeat',),enemy=('body',));i=self.board(g,2)[0]
        self.play(g,'bounce',i);self.assertIn(i,g.state.players[2].hand);self.assertEqual(len(self.records(g)),2);self.check(g)

    def test_live_state_replanned_on_each_execution(self):
        self.card('growing',lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].armor+1)])
        g=self.game(hand=('growing',),board=('repeat',));self.play(g,'growing');self.assertEqual(self.armor(g),3);self.check(g)

    def test_source_leaves_during_first_execution_second_still_runs(self):
        self.card('leaves',lambda c:[GainArmor(1,2),ReturnToHand(c.source_id)])
        g=self.game(hand=('leaves',),board=('repeat',));i=self.play(g,'leaves')
        self.assertIn(i,g.state.players[1].hand);self.assertEqual(self.armor(g),4);self.check(g)

    def test_aura_removed_during_first_execution_does_not_cancel_batch(self):
        self.card('remove',lambda c:[GainArmor(1,2),Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('remove',),board=('repeat',));self.play(g,'remove')
        self.assertEqual(self.armor(g),4);self.assertEqual(self.batch(g).plan.repetitions,2);self.check(g)

    def test_aura_captured_after_commit_reactions(self):
        self.watch('kill','card_committed',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(board=('repeat','kill'));self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_aura_added_by_commit_repeats_accepted_payload(self):
        self.watch('add','card_committed',lambda c:[GrantBattlecryRepeatAura(c.source_id)])
        g=self.game(board=('add',));self.play(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_silence_transform_death_and_bounce_revoke_for_later_play(self):
        self.mutate('silence',lambda c,i:[Silence(i)])
        self.mutate('morph',lambda c,i:[Transform(i,'body')])
        self.mutate('kill',lambda c,i:[Destroy(i)])
        self.mutate('bounce',lambda c,i:[ReturnToHand(i)])
        for name in ('silence','morph','kill','bounce'):
            with self.subTest(name=name):
                g=self.game(hand=(name,'cry'),board=('repeat',));self.play(g,name);self.play(g)
                self.assertEqual(self.armor(g),2);self.check(g)

    def test_control_transfer_moves_policy(self):
        self.mutate('steal',lambda c,i:[ChangeControl(i,2)])
        g=self.game(hand=('steal','cry'),board=('repeat',));self.play(g,'steal');self.play(g)
        g.apply(EndTurn(1));i=next(i for i in g.state.players[2].hand if g.state.entities[i].card_id=='cry')
        g.apply(PlayCard(2,i));self.assertEqual((self.armor(g),self.armor(g,2)),(2,4));self.check(g)

    def test_dormancy_disables_and_awakening_reenables(self):
        self.mutate('sleep',lambda c,i:[MakeDormant(i,None)])
        self.mutate('wake',lambda c,i:[AwakenMinion(i)])
        g=self.game(hand=('sleep','cry','wake','cry'),board=('repeat',))
        self.play(g,'sleep');self.play(g);self.assertEqual(self.armor(g),2)
        self.play(g,'wake');self.play(g);self.assertEqual(self.armor(g),6);self.check(g)

    def test_dynamic_grant_copy_and_silence_lifecycle(self):
        self.mutate('grant',lambda c,i:[GrantBattlecryRepeatAura(i,source_id=c.source_id)])
        self.mutate('copy',lambda c,i:[CopyMinion(i,1)])
        self.mutate('silence',lambda c,i:[Silence(i)])
        g=self.game(hand=('grant','copy','silence','cry'),board=('body',))
        self.play(g,'grant');self.play(g,'copy');self.play(g,'silence');self.play(g)
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_granted_policy_does_not_survive_bounce_reinstall(self):
        self.mutate('grant',lambda c,i:[GrantBattlecryRepeatAura(i)])
        self.mutate('bounce',lambda c,i:[ReturnToHand(i)])
        g=self.game(hand=('grant','bounce','cry'),board=('body',))
        self.play(g,'grant');self.play(g,'bounce');self.play(g,'body');self.play(g)
        self.assertEqual(self.armor(g),2);self.check(g)

    def test_grant_expires_at_declared_turn(self):
        self.mutate('grant',lambda c,i:[GrantBattlecryRepeatAura(i,expires_turn=c.state.turn)])
        g=self.game(hand=('grant','cry','cry'),board=('body',));self.play(g,'grant');self.play(g)
        self.assertEqual(self.armor(g),4);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        self.assertEqual(self.armor(g),6);self.check(g)

    def test_stale_grant_hero_is_not_policy(self):
        self.script('grant',lambda c:[GrantBattlecryRepeatAura(c.state.players[1].hero_id)])
        g=self.game(hand=('grant','cry'));self.play(g,'grant');self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_independent_choices_pause_each_iteration_and_restore(self):
        self.card('choice',lambda c:[RequestChoice(1,(ChoiceOption('one','One',(GainArmor(1,1),)),
            ChoiceOption('three','Three',(GainArmor(1,3),))),source_id=c.source_id,repeat_key='same-key')])
        g=self.game(hand=('choice',),board=('repeat',));self.play(g,'choice');self.check(g)
        self.choose(g,'one');self.check(g);self.assertIsNotNone(g.state.pending_choice)
        self.choose(g,'three');self.assertEqual(self.armor(g),4);self.check(g)

    def test_pause_in_commit_preserves_unstarted_plan(self):
        self.watch('wait','card_committed',lambda c:[self.pause(c)])
        g=self.game(board=('repeat','wait'));self.play(g);self.assertFalse(g.state.battlecry_batches);self.check(g)
        self.choose(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_pause_in_finished_event_before_iteration_marker(self):
        self.watch('wait','battlecry_finished',lambda c:[self.pause(c)])
        g=self.game(board=('repeat','wait'));self.play(g);self.check(g)
        self.assertTrue(self.records(g)[0].completed);self.assertEqual(self.batch(g).completed,0)
        self.choose(g);self.check(g);self.choose(g);self.assertEqual(self.armor(g),4);self.check(g)

    def test_terminal_in_first_execution_stops_remaining(self):
        self.card('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.game(hand=('lethal',),board=('repeat',));self.play(g,'lethal')
        self.assertEqual(len(self.records(g)),1);self.assertTrue(self.records(g)[0].interrupted)
        self.assertTrue(self.batch(g).interrupted);self.check(g)

    def test_terminal_in_finish_reaction_keeps_completed_child(self):
        self.watch('lethal','battlecry_finished',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.game(board=('repeat','lethal'));self.play(g)
        self.assertTrue(self.records(g)[0].completed);self.assertTrue(self.batch(g).interrupted);self.check(g)

    def test_failure_on_second_iteration_rolls_back_whole_play(self):
        self.card('bad',lambda c:[GainArmor(1,2)] if c.battlecry.repeat_index==1 else [Summon(1,'missing')])
        g=self.game(hand=('bad',),board=('repeat',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),s)

    def test_failure_after_second_pause_restores_pending_batch(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'missing')])
        self.card('bad',lambda c:[self.pause(c)]+([InvokeBehavior('fail',c.source_id,1)] if c.battlecry.repeat_index==2 else [GainArmor(1,2)]))
        g=self.game(hand=('bad',),board=('repeat',));self.play(g,'bad');self.choose(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.check(g)

    def test_rewind_outcomes_and_repeats_are_distinct_axes(self):
        self.card('rewind',lambda c:[GainArmor(1,c.battlecry.iteration)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('repeat','retainer'));self.play(g,'rewind')
        self.assertEqual([(b.iteration,b.repeat_index,b.batch_id) for b in self.records(g)],[(1,1,1),(1,2,1),(2,1,2),(2,2,2)])
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(6,8,1));self.check(g)

    def test_retention_keeps_captured_plan_when_aura_disappears(self):
        self.card('rewind',lambda c:[GainArmor(1,1)]+[Destroy(i) for i in c.state.players[1].board if c.state.entities[i].card_id=='repeat'],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('repeat','retainer'));self.play(g,'rewind')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.records(g)),4);self.check(g)

    def test_retained_repetitions_pause_four_times(self):
        self.card('rewind',lambda c:[self.pause(c),GainArmor(1,1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('repeat','retainer'));self.play(g,'rewind')
        for _ in range(4):self.check(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.armor(g),4);self.check(g)

    def test_normal_rewind_retry_replaces_batch_and_all_repetitions(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('repeat',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual((self.armor(g),len(self.records(g)),len(g.state.battlecry_batches),g.state.players[1].mana),(4,2,1,8));self.check(g)

    def test_no_batch_records_in_player_views(self):
        g=self.game(board=('repeat',));self.play(g)
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe())
            for private in ('battlecry_batches','repeat_index','contributors','battlecry_started'):
                self.assertNotIn(private,view)

    def test_player_command_uses_one_action_for_repeated_payload(self):
        g=self.game(board=('repeat',));p=g.for_player(1);listing=p.legal_actions()
        a=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(p.submit({'revision':listing['revision'],'action':a})['accepted'])
        self.assertEqual((self.armor(g),len(g.history)),(4,1));self.check(g)

    def test_snapshot_rejects_batch_corruption(self):
        g=self.game(board=('repeat',));self.play(g)
        for changes in ({'completed':1},{'id':2},{'play_id':99},{'player_id':2},{'finished':False},{'iteration':2},{'interrupted':True}):
            with self.subTest(changes=changes):
                s=g.snapshot();s['state']['battlecry_batches'][0].update(changes);self.reject(s)

    def test_snapshot_rejects_wrong_plan_and_activation_association(self):
        g=self.game(board=('repeat',));self.play(g)
        for field,value in (('batch_id',99),('repeat_index',1),('repeat_index',3)):
            s=g.snapshot();s['state']['battlecry_history'][1][field]=value;self.reject(s)
        s=g.snapshot();s['state']['battlecry_batches'][0]['plan']['contributors']=[99999];self.reject(s)
        s=g.snapshot();s['state']['battlecry_batches'][0]['payloads']=[];self.reject(s)

    def test_snapshot_rejects_missing_and_reordered_markers(self):
        self.card('wait',lambda c:[self.pause(c)])
        g=self.game(hand=('wait',),board=('repeat',));self.play(g,'wait')
        for name in ('FinishBattlecryBatch','FinishBattlecryIteration','FinishBattlecry'):
            s=g.snapshot();m=self.nested(s['resolution_frame'],name);self.assertIsNotNone(m)
            m['fields']['record_id' if name=='FinishBattlecry' else 'batch_id']=99;self.reject(s)

    def test_snapshot_rejects_queued_plan_corruption(self):
        self.watch('wait','minion_summoned',lambda c:[self.pause(c)])
        g=self.game(board=('repeat','wait'));self.play(g);s=g.snapshot()
        m=self.nested(s['resolution_frame'],'BattlecryRepeatPlan');self.assertIsNotNone(m)
        m['fields']['repetitions']=0;self.reject(s)

    def test_old_schema_and_missing_batch_field_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=72
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)
        s=g.snapshot();del s['state']['battlecry_batches'];self.reject(s)

    def test_invalid_declarations_rejected(self):
        for kw in ({'repetitions':True},{'repetitions':1},{'kinds':()},{'kinds':(CardType.SPELL,)},{'kinds':['MINION']}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):BattlecryRepeatSpec(**kw)
        with self.assertRaises(ValueError):BattlecryRepeatPlan(2)
        with self.assertRaises(ValueError):AbilityInstance(1,'keyword',battlecry_repeat=BattlecryRepeatSpec())
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('invalid','invalid',CardType.SPELL,battlecry_repeats=(BattlecryRepeatSpec(),)))

    def test_resolution_budget_rejects_excessive_count_atomically(self):
        self.aura('too_many',BattlecryRepeatSpec(1000000))
        g=self.game(board=('too_many',));s=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_ordinary_death_checkpoint_between_executions(self):
        self.r.register_behavior('rattle',lambda c:[GainArmor(1,5)])
        self.card('die',lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].armor+1),Destroy(c.source_id)],deathrattle='rattle')
        g=self.game(hand=('die',),board=('repeat',));self.play(g,'die')
        # 1 armor, deathrattle +5, then second Battlecry sees 6 and adds 7.
        self.assertEqual(self.armor(g),13);self.check(g)

    def test_snapshot_rejects_reordered_iteration_and_batch_closers(self):
        self.card('wait',lambda c:[self.pause(c)]);g=self.game(hand=('wait',),board=('repeat',));self.play(g,'wait')
        s=g.snapshot();a=self.nested(s['resolution_frame'],'FinishBattlecryIteration');b=self.nested(s['resolution_frame'],'FinishBattlecryBatch')
        a['type'],b['type']=b['type'],a['type'];self.reject(s)


class RepresentativeBattlecryRepeatTests(unittest.TestCase):
    def test_brann_definition_is_aura_not_own_battlecry(self):
        from hs_sim.engine.representative import build_registry
        r=build_registry();c=r.card('LOE_077')
        self.assertEqual(c.battlecry_repeats,(BattlecryRepeatSpec(),));self.assertIsNone(c.battlecry)
        self.assertEqual((c.cost,c.attack,c.health),(3,2,4))

    def test_real_scarab_and_weapon_combination_restores_and_replays(self):
        from examples.battlecry_repetition import run
        g,s=run();self.assertEqual(len(g.state.battlecry_history),4);self.assertEqual(s['schema_version'],265)

    def test_composed_ship_uses_ability_then_repeat_order(self):
        from hs_sim.engine import Scenario,PlayerSetup,LaunchStarship
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine.starships import construction
        from hs_sim.engine.replay import build_replay,replay
        r=build_registry()
        r.register_behavior('scrap',lambda c:[Destroy(i) for i in c.state.players[1].board if c.state.entities[i].card_id=='SC_405'])
        r.register_behavior('bounce',lambda c:[ReturnToHand(i) for i in c.state.players[1].board if c.state.entities[i].card_id!='LOE_077'])
        for cid in ('scrap','bounce'):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('LOE_077','SC_405','SC_405'),
            hand=('scrap','bounce'),mana=10,max_mana=10),PlayerSetup('HERO_08')),seed=74),r)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));ship=construction(g.state,1)
        g.apply(LaunchStarship(1,ship.id));self.assertEqual(g.state.battlecry_history,[])
        g.apply(PlayCard(1,g.state.players[1].hand[0]));g.apply(PlayCard(1,ship.id))
        records=g.state.battlecry_history;self.assertEqual(len(records),4)
        a,b=records[0].payload.ability_id,records[2].payload.ability_id
        self.assertNotEqual(a,b);self.assertEqual([(v.payload.ability_id,v.repeat_index) for v in records],[(a,1),(a,2),(b,1),(b,2)])
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())


if __name__=='__main__': unittest.main()
