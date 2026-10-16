"""Private carrier counters, finite competition and incarnation boundaries (R-117)."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest
from copy import deepcopy
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, CardDefinition, CardType, CounterPolicySpec, GrantCounterPolicy,
    AbilityInstance, EndTurn, PlayCard, Scenario, PlayerSetup, SecretSpec, Keyword,
    CounterSpell, CounterMinion, SetSecret, SelectChoice, IllegalAction, ResolutionError,
    MakeDormant, AwakenMinion, BattlecryRepeatSpec, RewindSpec, Zone)
from hs_sim.engine.effects import (RequestChoice, ChoiceOption, GainArmor, Damage, Silence,
    Destroy, Transform, ChangeControl, ReturnToHand, CopyMinion, Summon, InvokeBehavior)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.counter_policies import private_policies


class CounterPolicyTests(unittest.TestCase):
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
        self.card('okani', self.decision)
        self.script('spell',lambda c:[GainArmor(c.player_id,9)])
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=4,
            battlecry_repeats=(BattlecryRepeatSpec(),)))
        self.script('arm',lambda c:[self.grant(c,c.state.players[2].board[0])])

    def grant(self,c,i,kind=CardType.MINION,uses=1,key=None,expiry=None):
        return GrantCounterPolicy(MinionReference.capture(c.state.entities[i]),
            CounterPolicySpec(kind,uses,key),c.source_id,expiry)

    def decision(self,c):
        source=c.state.entities[c.source_id]
        if source.zone!=Zone.BOARD:return []
        return [RequestChoice(c.player_id,tuple(ChoiceOption(k.value,k.value,
            (self.grant(c,c.source_id,k,key='okani'),)) for k in (CardType.MINION,CardType.SPELL)),
            source_id=c.source_id,prompt='秘密选择反制类型')]

    def armed(self,hand=('cry',),enemy=('body',),**kw):
        g=self.game(hand=('arm',*hand),enemy=enemy,**kw);self.play(g,'arm');return g

    def policies(self,g,p=2,index=0):
        return private_policies(g.state.entities[g.state.players[p].board[index]])

    def turn_play(self,g,cid):
        g.apply(EndTurn(1));i=next(i for i in g.state.players[2].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(2,i));return i

    def test_secret_choice_private_and_restorable(self):
        g=self.game(hand=('okani',));i=self.play(g,'okani')
        self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1})
        self.assertEqual(len(g.observe(1)['pending_choice']['options']),2);self.check(g)
        restored=g.clone();self.choose(g,'minion');self.choose(restored,'minion')
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.policies(g,1)[0]['kind'],'minion')
        self.assertIsNone(g.observe(2)['players'][0]['board'][0]['counter_policies']);self.check(g)

    def test_opponent_cannot_distinguish_selected_kind(self):
        g=self.game(hand=('okani',));self.play(g,'okani');other=g.clone()
        self.choose(g,'minion');self.choose(other,'spell')
        self.assertEqual(g.observe(2),other.observe(2));self.assertNotEqual(g.observe(1),other.observe(1))
        self.assertEqual(g.player_events(2),other.player_events(2))
        self.assertEqual(g.for_player(2).legal_actions(),other.for_player(2).legal_actions())

    def test_wrong_choice_rolls_back(self):
        g=self.game(hand=('okani',));self.play(g,'okani');s=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'invalid')
        self.assertEqual(g.snapshot(),s)

    def test_minion_counter_consumes_once(self):
        g=self.armed(hand=('cry','cry'));self.play(g);self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(self.policies(g)[0]['uses_remaining'],0);self.play(g)
        self.assertFalse(g.state.play_history[-1].countered);self.assertEqual(self.armor(g),2);self.check(g)

    def test_spell_counter_cancels_payload(self):
        self.script('armspell',lambda c:[self.grant(c,c.state.players[2].board[0],CardType.SPELL)])
        g=self.game(hand=('armspell','spell'),enemy=('body',));self.play(g,'armspell');self.play(g,'spell')
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_nonmatching_spell_does_not_spend(self):
        g=self.armed(hand=('spell',));self.play(g,'spell');self.assertEqual(self.policies(g)[0]['uses_remaining'],1)
        self.assertEqual(self.armor(g),9);self.check(g)

    def test_own_play_does_not_spend(self):
        g=self.game(hand=('okani','cry'));self.play(g,'okani');self.choose(g,'minion');self.play(g)
        self.assertEqual(self.policies(g,1)[0]['uses_remaining'],1);self.check(g)

    def test_summon_does_not_spend(self):
        self.script('summon',lambda c:[Summon(1,'cry')]);g=self.armed(hand=('summon',));self.play(g,'summon')
        self.assertEqual(self.policies(g)[0]['uses_remaining'],1);self.check(g)

    def test_two_carriers_only_first_spends(self):
        self.script('two',lambda c:[self.grant(c,i) for i in c.state.players[2].board])
        g=self.game(hand=('two','cry','cry'),enemy=('body','body'));self.play(g,'two');self.play(g)
        self.assertEqual([self.policies(g,index=i)[0]['uses_remaining'] for i in (0,1)],[0,1])
        self.play(g);self.assertEqual(self.policies(g,index=1)[0]['uses_remaining'],0);self.check(g)

    def test_same_carrier_independent_policies_do_not_double_spend(self):
        self.script('two',lambda c:[self.grant(c,c.state.players[2].board[0]) for _ in range(2)])
        g=self.game(hand=('two','cry','cry'),enemy=('body',));self.play(g,'two');self.play(g)
        self.assertEqual([p['uses_remaining'] for p in self.policies(g)],[0,1]);self.play(g);self.check(g)

    def test_finite_budget_and_expiry(self):
        self.script('multi',lambda c:[self.grant(c,c.state.players[2].board[0],uses=3,expiry=c.state.turn)])
        g=self.game(hand=('multi','cry','cry'),enemy=('body',));self.play(g,'multi');self.play(g);self.play(g)
        self.assertEqual(self.policies(g)[0]['uses_remaining'],1);g.apply(EndTurn(1))
        self.assertFalse(self.policies(g));self.check(g)

    def test_same_key_and_kind_refreshes_with_new_identity(self):
        self.script('refresh',lambda c:[self.grant(c,c.state.players[2].board[0],key='one')])
        g=self.game(hand=('refresh','cry','refresh','cry'),enemy=('body',));self.play(g,'refresh')
        old=g.state.entities[g.state.players[2].board[0]].abilities[-1].id
        self.play(g);self.play(g,'refresh');self.assertEqual(len(self.policies(g)),1)
        self.assertGreater(g.state.entities[g.state.players[2].board[0]].abilities[-1].id,old)
        self.play(g);self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_repeated_battlecry_same_kind_refreshes_one_budget(self):
        g=self.game(hand=('okani',),board=('brann',));self.play(g,'okani');self.choose(g,'minion');self.choose(g,'minion')
        self.assertEqual(len(self.policies(g,1,1)),1);self.assertEqual(len(g.state.battlecry_history),2);self.check(g)

    def test_repeated_battlecry_different_kinds_coexist_and_stay_private(self):
        g=self.game(hand=('okani',),board=('brann',));self.play(g,'okani');self.choose(g,'minion');other=g.clone()
        self.choose(g,'spell');self.choose(other,'minion');self.assertEqual(g.observe(2),other.observe(2))
        self.assertEqual(len(self.policies(g,1,1)),2);self.check(g)

    def secret(self,kind):
        self.r.register_secret_condition('counter',lambda c:c.window is not None and c.window.kind==kind.value
            and not c.window.countered and c.window.player_id!=c.player_id)
        self.r.register_behavior('counter',lambda c:[CounterMinion(c.window.id) if kind==CardType.MINION else CounterSpell(c.window.id)])
        self.r.register_card(CardDefinition('secret','secret',CardType.SPELL,keywords=(Keyword.SECRET,),
            secret=SecretSpec('counter',('minion_counter_check' if kind==CardType.MINION else 'card_committed',),'counter','counter')))

    def test_carrier_before_secret_preserves_secret(self):
        self.secret(CardType.MINION);self.script('set',lambda c:[SetSecret(2,'secret')])
        g=self.armed(hand=('set','cry'));self.play(g,'set');self.play(g)
        self.assertEqual(len(g.state.players[2].secrets),1);self.assertEqual(self.policies(g)[0]['uses_remaining'],0);self.check(g)

    def test_secret_before_carrier_preserves_policy(self):
        self.secret(CardType.MINION)
        self.script('set',lambda c:[SetSecret(2,'secret'),Summon(2,'body')])
        g=self.game(hand=('set','arm','cry'));self.play(g,'set');self.play(g,'arm');self.play(g)
        self.assertFalse(g.state.players[2].secrets);self.assertEqual(self.policies(g)[0]['uses_remaining'],1);self.check(g)

    def test_spell_secret_before_carrier_preserves_policy(self):
        self.secret(CardType.SPELL)
        self.script('set',lambda c:[SetSecret(2,'secret'),Summon(2,'body'),InvokeBehavior('attach',c.source_id,1)])
        self.r.register_behavior('attach',lambda c:[self.grant(c,c.state.players[2].board[0],CardType.SPELL)])
        g=self.game(hand=('set','spell'));self.play(g,'set');self.play(g,'spell')
        self.assertFalse(g.state.players[2].secrets);self.assertEqual(self.policies(g)[0]['uses_remaining'],1);self.check(g)

    def test_public_reveal_sees_already_countered_window(self):
        self.watch('observe','counter_policy_used',lambda c:[GainArmor(1,7 if c.state.action_windows[-1].countered else 99)])
        g=self.armed(board=('observe',));self.play(g);self.assertEqual(self.armor(g),7)
        event=next(e for e in g.player_events(1) if e['kind']=='counter_policy_used')
        self.assertEqual(event['counter_policy'],dict(kind='minion',uses_remaining=0,expires_turn=None));self.check(g)

    def mutate(self,effect):
        self.script('mutate',lambda c:[effect(c.state.players[2].board[0])])
        g=self.armed(hand=('mutate','cry'));self.play(g,'mutate');self.play(g)
        self.assertFalse(g.state.play_history[-1].countered);self.assertEqual(self.armor(g),2);self.check(g);return g

    def test_dead_carrier_stops_countering(self):self.mutate(Destroy)
    def test_silenced_carrier_stops_countering(self):self.mutate(Silence)
    def test_transformed_carrier_loses_policy(self):self.mutate(lambda i:Transform(i,'body'))
    def test_returned_carrier_loses_policy(self):self.mutate(ReturnToHand)
    def test_dormant_carrier_stops_countering(self):self.mutate(lambda i:MakeDormant(i,None))
    def test_controlled_carrier_protects_new_controller(self):self.mutate(lambda i:ChangeControl(i,1))

    def test_awakened_carrier_resumes_unspent_policy(self):
        self.script('sleep',lambda c:[MakeDormant(c.state.players[2].board[0],None)])
        self.script('wake',lambda c:[AwakenMinion(c.state.players[2].board[0])])
        g=self.armed(hand=('sleep','wake','cry'));self.play(g,'sleep');self.play(g,'wake');self.play(g)
        self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_captured_check_revalidates_silence(self):
        self.watch('silencer','minion_counter_check',lambda c:[Silence(c.state.players[2].board[0])])
        g=self.armed(board=('silencer',));self.play(g);self.assertFalse(g.state.play_history[-1].countered);self.check(g)

    def test_captured_check_revalidates_transfer_away_and_back(self):
        self.watch('steal','minion_counter_check',lambda c:[ChangeControl(c.state.players[2].board[0],1),
            ChangeControl(c.state.players[2].board[0],2)])
        g=self.armed(board=('steal',));self.play(g);self.assertFalse(g.state.play_history[-1].countered)
        self.assertEqual(self.policies(g)[0]['uses_remaining'],1);self.check(g)

    def test_old_grant_cannot_attach_after_transform(self):
        self.script('stale',lambda c:[Transform(c.state.players[2].board[0],'body'),self.grant(c,c.state.players[2].board[0])])
        g=self.game(hand=('stale','cry'),enemy=('body',));self.play(g,'stale');self.play(g)
        self.assertFalse(self.policies(g));self.check(g)

    def test_copy_preserves_budget_with_distinct_attachment(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[2].board[0],2)])
        g=self.armed(hand=('copy','cry','cry'));self.play(g,'copy');self.play(g)
        self.assertEqual(self.policies(g,index=1)[0]['uses_remaining'],1);self.play(g)
        self.assertEqual(self.policies(g,index=1)[0]['uses_remaining'],0);self.check(g)

    def test_copy_of_consumed_policy_stays_consumed(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[2].board[0],2)])
        g=self.armed(hand=('cry','copy','cry'));self.play(g);self.play(g,'copy');self.play(g)
        self.assertFalse(g.state.play_history[-1].countered);self.assertEqual(self.policies(g,index=1)[0]['uses_remaining'],0);self.check(g)

    def test_new_controller_learns_policy_and_retains_receipt_after_loss(self):
        self.script('take',lambda c:[ChangeControl(c.state.players[2].board[0],1)])
        self.script('give',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        g=self.armed(hand=('take','give'));self.play(g,'take')
        learned=next(e for e in g.player_events(1) if e['kind']=='control_changed')['counter_policies']
        self.assertEqual(learned[0]['kind'],'minion');self.play(g,'give')
        self.assertIsNone(g.observe(1)['players'][1]['board'][0]['counter_policies'])
        self.assertEqual(next(e for e in g.player_events(1) if e['kind']=='control_changed')['counter_policies'],learned);self.check(g)

    def test_copy_owner_learns_only_own_copy(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[2].board[0],1)])
        g=self.armed(hand=('copy',));self.play(g,'copy');v=g.observe(1)
        self.assertEqual(v['players'][0]['board'][0]['counter_policies'][0]['kind'],'minion')
        self.assertIsNone(v['players'][1]['board'][0]['counter_policies'])
        self.assertEqual(next(e for e in g.player_events(1) if e['kind']=='minion_summoned')['counter_policies'][0]['kind'],'minion');self.check(g)

    def test_pending_check_roundtrip_and_resume(self):
        self.watch('wait','minion_counter_check',lambda c:[self.pause(c)])
        g=self.armed(board=('wait',));self.play(g);self.check(g);other=g.clone()
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.check(g)

    def test_reveal_pause_does_not_spend_later_carrier_on_resume(self):
        self.watch('wait','counter_policy_used',lambda c:[self.pause(c)])
        self.script('two',lambda c:[self.grant(c,i) for i in c.state.players[2].board])
        g=self.game(hand=('two','cry'),board=('wait',),enemy=('body','body'));self.play(g,'two');self.play(g)
        self.assertTrue(g.state.action_windows[-1].countered);self.check(g);self.choose(g)
        self.assertEqual(self.policies(g,index=1)[0]['uses_remaining'],1);self.check(g)

    def test_terminal_reveal_clears_pending_play(self):
        self.watch('finish','counter_policy_used',lambda c:[Damage(c.state.players[1].hero_id,100)])
        g=self.armed(board=('finish',));self.play(g);self.assertFalse(g.state.players[1].pending_plays)
        self.assertTrue(g.state.play_history[-1].interrupted);self.check(g)

    def test_error_after_grant_rolls_back_choice_and_hidden_fact(self):
        def explode(c):
            self.assertTrue(private_policies(c.state.entities[c.source_id]))
            raise ResolutionError('failure after grant')
        self.r.register_behavior('explode',explode)
        def bad(c):
            request=self.decision(c)[0]
            return [replace(request,options=tuple(replace(o,effects=(*o.effects,
                InvokeBehavior('explode',c.source_id,c.player_id))) for o in request.options))]
        self.card('bad',bad)
        g=self.game(hand=('bad',));self.play(g,'bad');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'minion')
        self.assertEqual(g.snapshot(),s)

    def test_invalid_specs_and_consumption_rejected(self):
        for kwargs in ({'kind':'minion'},{'kind':CardType.HERO},{'kind':CardType.MINION,'uses':0},
                       {'kind':CardType.MINION,'uses':True},{'kind':CardType.MINION,'key':''}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):CounterPolicySpec(**kwargs)
        with self.assertRaises(ValueError):AbilityInstance(1,'counter_policy',counter_policy=CounterPolicySpec(CardType.MINION),uses_remaining=0)

    def test_corrupt_saved_policy_rejected(self):
        g=self.armed();base=g.snapshot();i=g.state.players[2].board[0]
        for field,value in [('uses_remaining',2),('consumed',True),('counter_policy',{'kind':'hero','uses':1,'key':None})]:
            s=deepcopy(base);s['state']['entities'][str(i)]['abilities'][-1][field]=value;self.reject(s)

    def test_corrupt_queued_check_rejected(self):
        self.watch('wait','minion_counter_check',lambda c:[self.pause(c)])
        g=self.armed(board=('wait',));self.play(g);base=g.snapshot()
        for field,value in [('ability_id',99999),('window_id',99999)]:
            s=deepcopy(base);self.nested(s,'CheckCounterPolicy')['fields'][field]=value;self.reject(s)

    def test_corrupt_private_event_rejected(self):
        g=self.armed();s=g.snapshot()
        events=s['information']['players']['2']['events']
        item=next(e for e in events if e['kind']=='counter_policy_added');item['player_id']=1;self.reject(s)

    def test_base_copy_and_reborn_start_without_granted_policy(self):
        self.r.register_card(CardDefinition('reborn','reborn',CardType.MINION,health=4,keywords=(Keyword.REBORN,)))
        self.script('copykill',lambda c:[CopyMinion(c.state.players[2].board[0],2,mode='base'),Destroy(c.state.players[2].board[0])])
        g=self.armed(hand=('copykill','cry'),enemy=('reborn',));self.play(g,'copykill');self.play(g)
        self.assertFalse(g.state.play_history[-1].countered)
        self.assertTrue(all(not self.policies(g,index=i) for i in range(2)));self.check(g)

    def test_return_and_replay_does_not_restore_old_choice(self):
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[2].board[0])])
        g=self.armed(hand=('bounce',));self.play(g,'bounce');g.apply(EndTurn(1))
        i=next(i for i in g.state.players[2].hand if g.state.entities[i].card_id=='body')
        g.apply(PlayCard(2,i));self.assertFalse(self.policies(g));self.check(g)

    def test_queued_grant_cannot_reach_returned_incarnation(self):
        self.script('old',lambda c:[ReturnToHand(c.state.players[2].board[0]),self.grant(c,c.state.players[2].board[0])])
        g=self.game(hand=('old',),enemy=('body',));self.play(g,'old')
        self.assertFalse(any(a.counter_policy for e in g.state.entities.values() for a in e.abilities));self.check(g)

    def test_choice_reaction_transform_invalidates_captured_grant(self):
        self.watch('change','choice_selected',lambda c:[Transform(c.state.players[1].board[-1],'body')])
        g=self.game(hand=('okani',),board=('change',));self.play(g,'okani');self.choose(g,'minion')
        self.assertFalse(self.policies(g,1,1));self.check(g)

    def test_rewind_retry_restores_before_choice_then_allows_new_choice(self):
        self.card('rewind',self.decision,keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',));self.play(g,'rewind');self.choose(g,'minion');self.check(g)
        self.choose(g,'retry');self.choose(g,'spell')
        self.assertEqual([p['kind'] for p in self.policies(g,1)],['spell']);self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_retained_rewind_outcomes_can_choose_both_kinds(self):
        self.card('rewind',self.decision,keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.choose(g,'minion');self.check(g);self.choose(g,'spell')
        self.assertEqual([p['kind'] for p in self.policies(g,1,1)],['minion','spell'])
        self.assertEqual(len(g.state.battlecry_history),2);self.check(g)

    def test_first_revealed_kind_does_not_publish_other_policy(self):
        self.script('both',lambda c:[self.grant(c,c.state.players[2].board[0],k) for k in (CardType.MINION,CardType.SPELL)])
        g=self.game(hand=('both','cry'),enemy=('body',));self.play(g,'both');self.play(g)
        facts=[e['counter_policy'] for e in g.player_events(1) if e['kind']=='counter_policy_used']
        self.assertEqual([p['kind'] for p in facts],['minion'])
        self.assertIsNone(g.observe(1)['players'][1]['board'][0]['counter_policies']);self.check(g)

    def test_future_carrier_in_choice_branch_rejected(self):
        g=self.game(hand=('okani',));self.play(g,'okani');s=g.snapshot()
        self.nested(s['resolution_frame'],'MinionReference')['fields']['zone_epoch']=99999;self.reject(s)

    def test_old_schema_and_missing_spec_rejected(self):
        from hs_sim.engine import SnapshotError
        g=self.armed();s=g.snapshot();s['schema_version']=75
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)
        s=g.snapshot();i=g.state.players[2].board[0];del s['state']['entities'][str(i)]['abilities'][-1]['counter_policy'];self.reject(s)

    def test_receipt_cannot_be_copied_into_opponent_log(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[2].board[0],1)])
        g=self.armed(hand=('copy',));self.play(g,'copy');s=g.snapshot()
        item=next(e for e in s['information']['players']['2']['events'] if e['kind']=='minion_summoned')
        item['counter_policies']=[dict(kind='minion',uses_remaining=1,expires_turn=None)];self.reject(s)

    def test_real_private_choices_compete_with_objection(self):
        from examples.private_counter_choices import run
        g,s=run();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION);self.assertEqual(sum(p.countered for p in g.state.play_history),3)


if __name__=='__main__':unittest.main()
