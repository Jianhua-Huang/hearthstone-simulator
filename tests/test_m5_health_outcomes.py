"""Packet-local Overkill/Honorable Kill/Overheal conditions and durable followups."""
import json
import unittest
from dataclasses import replace

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, HealthFlow,
    HealthLayer, HealthOp, HealthRule, Keyword, LimitedTriggerSpec, PlayCard, PlayerSetup,
    Registry, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    DamageKind, HealingKind, health_result, is_overkill, is_honorable_kill, is_overheal)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, DamageBatch, Destroy, GainArmor, GrantHealthRule, GrantTrigger, Heal, HealBatch,
    InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.limited_triggers import GrantLimitedTrigger
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class HealthOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('health-outcome-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        self.r.register_card(CardDefinition('body','body',CardType.MINION,attack=1,health=3))
        self.r.register_card(CardDefinition('weak','weak',CardType.MINION,attack=1,health=1))
        self.r.register_card(CardDefinition('large','large',CardType.MINION,attack=9,health=3))
        for name,kw in (('shield',Keyword.DIVINE_SHIELD),('immune',Keyword.IMMUNE),('life',Keyword.LIFESTEAL),('poison',Keyword.POISONOUS)):
            self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=1,health=3,keywords=(kw,)))
        self.r.register_behavior('overkill',lambda c:[GainArmor(c.player_id,5)] if is_overkill(c.event,c.source_id) else [])
        self.r.register_behavior('honorable',lambda c:[GainArmor(c.player_id,2)] if is_honorable_kill(c.event,c.source_id) else [])
        self.r.register_behavior('overheal',lambda c:[Buff(c.source_id,attack=c.health_result.overheal)] if is_overheal(c.event,c.source_id) else [])
        for name,behavior in (('killer','overkill'),('exact','honorable'),('medic','overheal')):
            self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=3,health=5,
                keywords=(Keyword.CHARGE,),triggers=(TriggerSpec('health_resolved',behavior),)))
        self.script('damage',lambda c:[Damage(c.target_id,3,c.source_id,DamageKind.SPELL)],target=True)
        self.script('heal',lambda c:[Heal(c.target_id,3,c.source_id,HealingKind.SPELL)],target=True)

    def script(self,cid,fn,target=False,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=target,**kw))
    def watch(self,cid,kind,fn):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=5,triggers=(TriggerSpec(kind,cid),)))
    def provider(self,cid,*rules):
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=5,health_rules=rules))
    def game(self,hand=(),board=(),enemy=('body',),armor=0,weapon=None,active=1):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('body',)*4,
            mana=10,max_mana=10,weapon_card_id=weapon),PlayerSetup('hero',hand=hand,board=enemy,deck=('body',)*4,
            mana=10,max_mana=10,armor=armor)),seed=69,active_player=active),self.r)
    def play(self,g,cid,target=None):
        p=g.state.active_player
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(p,eid,target))
    def body(self,g,p=1,i=0): return g.state.entities[g.state.players[p].board[i]]
    def hero(self,g,p=1): return g.state.entities[g.state.players[p].hero_id]
    def events(self,g): return [e for e in g.events if e.kind=='health_resolved']
    def outcomes(self,g): return [health_result(e) for e in self.events(g)]
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def choose(self,g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as err:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(err.exception))
    def from_board(self,c,n=3,index=0):
        return Damage(c.state.players[2].board[index],n,c.state.players[1].board[0])

    def test_exact_and_excess_use_packet_health_and_enemy_ownership(self):
        self.script('strike',lambda c:[self.from_board(c)])
        for name,target,armor in (('killer','body',0),('killer','weak',5),('exact','body',2),('exact','weak',0)):
            with self.subTest(source=name,target=target):
                g=self.game(hand=('strike',),board=(name,),enemy=(target,));self.play(g,'strike')
                self.assertEqual(self.hero(g).armor,armor);self.check(g)

    def test_conditions_use_active_turn_and_captured_controller(self):
        self.script('strike',lambda c:[self.from_board(c,4)])
        g=self.game(hand=('strike',),board=('killer',),active=2);self.play(g,'strike')
        out=self.outcomes(g)[0];self.assertEqual((out.active_player,out.source_controller),(2,1))
        self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_honorable_rejects_friendly_target_but_overkill_allows_it(self):
        self.script('friendly',lambda c:[Damage(c.state.players[1].board[1],3,c.state.players[1].board[0])])
        for source,target in (('exact','body'),('killer','weak')):
            with self.subTest(source=source):
                g=self.game(hand=('friendly',),board=(source,target));self.play(g,'friendly')
                self.assertEqual(self.hero(g).armor,0 if source=='exact' else 5);self.check(g)

    def test_armor_absorption_enters_exact_required_damage(self):
        self.script('face',lambda c:[Damage(c.state.players[2].hero_id,32,c.source_id,DamageKind.SPELL)])
        g=self.game(hand=('face',),armor=2);self.play(g,'face');event=self.events(g)[0];out=health_result(event)
        self.assertEqual((out.health_before,out.armor_before,out.armor_absorbed,out.health_lost),(30,2,2,30))
        self.assertTrue(is_honorable_kill(event,event.source_id));self.assertFalse(is_overkill(event,event.source_id));self.check(g)

    def test_prior_health_damage_not_printed_health_controls_exact_kill(self):
        self.script('wound',lambda c:[Damage(c.state.players[2].board[0],1)])
        self.script('strike',lambda c:[self.from_board(c,2)])
        g=self.game(hand=('wound','strike'),board=('exact',));self.play(g,'wound');self.play(g,'strike')
        self.assertEqual((self.outcomes(g)[-1].health_before,self.hero(g).armor),(2,2));self.check(g)

    def test_same_batch_later_hit_cannot_kill_an_already_zero_health_target_again(self):
        self.script('twice',lambda c:[DamageBatch((self.from_board(c),self.from_board(c,5)))])
        g=self.game(hand=('twice',),board=('exact',));self.play(g,'twice');a,b=self.outcomes(g)
        self.assertEqual((a.health_before,b.health_before,b.health_after),(3,0,-5))
        self.assertEqual(a.batch_id,b.batch_id);self.assertEqual((a.packet_index,b.packet_index),(1,2))
        self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_distinct_batches_have_distinct_association_and_no_phantom_stale_result(self):
        self.script('sequence',lambda c:[self.from_board(c),self.from_board(c,4),Damage(c.state.players[2].hero_id,1)])
        g=self.game(hand=('sequence',),board=('exact',));self.play(g,'sequence');a,b=self.outcomes(g)
        self.assertNotEqual(a.batch_id,b.batch_id);self.assertEqual((a.packet_index,b.packet_index),(1,1))
        self.assertTrue(any(e.kind=='effect_skipped' for e in g.events));self.check(g)

    def test_shield_immune_prevention_and_zero_damage_do_not_trigger_kill(self):
        self.script('strike',lambda c:[self.from_board(c,4)])
        self.script('zero',lambda c:[self.from_board(c,0)])
        for target,spell,reason in (('shield','strike','divine_shield'),('immune','strike','immune'),('weak','zero','zero_damage')):
            with self.subTest(reason=reason):
                g=self.game(hand=(spell,),board=('killer',),enemy=(target,));self.play(g,spell)
                out=self.outcomes(g)[0];self.assertEqual((out.prevention,out.health_lost),(reason,0))
                self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_rule_prevention_is_distinct_from_shield_and_keeps_old_listener_counts(self):
        self.provider('prevent',HealthRule(HealthFlow.DAMAGE,HealthOp.PREVENT,target_relation='friendly',layer=HealthLayer.TARGET))
        self.script('strike',lambda c:[self.from_board(c,9)])
        g=self.game(hand=('strike',),board=('killer',),enemy=('body','prevent'));self.play(g,'strike')
        self.assertEqual(self.outcomes(g)[0].prevention,'rule_prevention')
        self.assertEqual(sum(e.kind=='damage_dealt' for e in g.events),0)
        self.assertEqual(sum(e.kind=='damage_prevented' for e in g.events),1);self.check(g)

    def test_poisonous_insufficient_damage_is_not_a_numeric_kill(self):
        self.script('strike',lambda c:[Damage(c.state.players[2].board[0],1,c.state.players[1].board[0])])
        g=self.game(hand=('strike',),board=('poison',));self.play(g,'strike');event=self.events(g)[0]
        self.assertTrue(health_result(event).doomed_after)
        self.assertFalse(is_overkill(event,event.source_id));self.assertFalse(is_honorable_kill(event,event.source_id));self.check(g)

    def test_second_packet_does_not_credit_already_poisoned_target(self):
        self.script('poisoned',lambda c:[DamageBatch((Damage(c.state.players[2].board[0],1,c.state.players[1].board[1]),self.from_board(c,2)))])
        g=self.game(hand=('poisoned',),board=('exact','poison'));self.play(g,'poisoned')
        self.assertTrue(self.outcomes(g)[1].doomed_before);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_death_of_damage_source_in_same_combat_does_not_lose_captured_trigger(self):
        g=self.game(board=('exact',),enemy=('large',));attacker=self.body(g).id;defender=self.body(g,2).id
        g.apply(Attack(1,attacker,defender));self.assertFalse(g.state.players[1].board)
        self.assertEqual(self.hero(g).armor,2);self.assertEqual(len(self.outcomes(g)),2);self.check(g)

    def test_weapon_result_attributes_final_durability_hit_to_old_equipment(self):
        self.r.register_card(CardDefinition('weapon','weapon',CardType.WEAPON,attack=4,durability=1,
            triggers=(TriggerSpec('health_resolved','overkill'),)))
        g=self.game(weapon='weapon');weapon=g.state.players[1].weapon_id
        g.apply(Attack(1,self.hero(g).id,self.body(g,2).id));event=self.events(g)[0]
        self.assertEqual(health_result(event).weapon_id,weapon);self.assertTrue(is_overkill(event,weapon))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(self.hero(g).armor,5);self.check(g)

    def test_hero_effect_damage_does_not_claim_equipped_weapon(self):
        self.r.register_card(CardDefinition('weapon','weapon',CardType.WEAPON,attack=4,durability=2,
            triggers=(TriggerSpec('health_resolved','overkill'),)))
        self.script('hero.effect',lambda c:[Damage(c.state.players[2].board[0],4,c.state.players[1].hero_id)])
        g=self.game(weapon='weapon',hand=('hero.effect',));self.play(g,'hero.effect')
        self.assertIsNone(self.outcomes(g)[0].weapon_id);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_spell_damage_scaling_uses_modified_result_and_separate_base(self):
        self.r.register_card(CardDefinition('spellpower','spellpower',CardType.MINION,health=3,spell_damage=1))
        self.r.register_behavior('bonus',lambda c:[GainArmor(1,5)] if is_overkill(c.event,c.source_id) else [])
        self.script('scaled',lambda c:[Damage(c.target_id,3,c.source_id,DamageKind.SPELL,on_result='bonus')],target=True)
        g=self.game(hand=('scaled',),board=('spellpower',));self.play(g,'scaled',self.body(g,2).id)
        out=self.outcomes(g)[0];self.assertEqual((out.base_amount,out.modified_amount,out.spell_bonus),(3,4,1))
        self.assertEqual(self.hero(g).armor,5);self.check(g)

    def test_overheal_at_full_health_fires_without_legacy_healed_event(self):
        g=self.game(hand=('heal',),board=('medic',));self.play(g,'heal',self.body(g).id)
        self.assertEqual((self.body(g).attack,self.body(g).health),(6,5))
        out=self.outcomes(g)[0];self.assertEqual((out.healed,out.overheal),(0,3))
        self.assertFalse(any(e.kind=='healed' for e in g.events));self.check(g)

    def test_exact_full_heal_and_under_heal_do_not_trigger_overheal(self):
        for amount in (2,3,4):
            self.script('wound'+str(amount),lambda c,n=amount:[Damage(c.state.players[1].board[0],n)])
        for amount,expected in ((2,1),(3,0),(4,0)):
            with self.subTest(missing=amount):
                g=self.game(hand=('wound'+str(amount),'heal'),board=('medic',));self.play(g,'wound'+str(amount));self.play(g,'heal',self.body(g).id)
                self.assertEqual(self.outcomes(g)[-1].overheal,expected);self.assertEqual(self.body(g).attack,3+expected);self.check(g)

    def test_enemy_healing_can_overheal_holder_on_opponents_turn(self):
        g=self.game(hand=('heal',),board=('medic',),active=2);self.play(g,'heal',self.body(g).id)
        self.assertEqual(self.body(g).attack,6);self.assertEqual(self.outcomes(g)[0].source_controller,2);self.check(g)

    def test_heal_batch_uses_each_packets_remaining_missing_health(self):
        self.script('batchheal',lambda c:[Damage(c.state.players[1].board[0],4),HealBatch(tuple(
            Heal(c.state.players[1].board[0],3,c.source_id) for _ in range(2)))])
        g=self.game(hand=('batchheal',),board=('medic',));self.play(g,'batchheal');a,b=self.outcomes(g)[1:]
        self.assertEqual((a.healed,a.overheal,b.healed,b.overheal),(3,0,1,2))
        self.assertEqual(a.batch_id,b.batch_id);self.assertEqual(self.body(g).attack,5);self.check(g)

    def test_zero_or_prevented_heal_is_not_overheal(self):
        self.script('zeroheal',lambda c:[Heal(c.state.players[1].board[0],0,c.source_id)])
        self.provider('preventheal',HealthRule(HealthFlow.HEALING,HealthOp.PREVENT,target_relation='friendly'))
        for hand,board,prevented in ((('zeroheal',),('medic',),False),(('heal',),('medic','preventheal'),True)):
            with self.subTest(prevented=prevented):
                g=self.game(hand=hand,board=board);self.play(g,hand[0],self.body(g).id if hand[0]=='heal' else None)
                self.assertEqual(self.outcomes(g)[0].overheal,0);self.assertEqual(self.body(g).attack,3);self.check(g)

    def test_converted_damage_can_overheal_but_cannot_overkill(self):
        self.provider('convert',HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT,source_relation='friendly'))
        g=self.game(hand=('damage',),board=('medic','convert'));self.play(g,'damage',self.body(g).id)
        out=self.outcomes(g)[0];self.assertEqual((out.original_flow,out.flow,out.converted),('damage','healing',True))
        self.assertEqual(self.body(g).attack,6);self.check(g)

    def test_converted_healing_can_exact_kill_without_overheal(self):
        self.provider('convert',HealthRule(HealthFlow.HEALING,HealthOp.CONVERT,source_relation='friendly'))
        self.r.register_behavior('exactbonus',lambda c:[GainArmor(1,2)] if is_honorable_kill(c.event,c.source_id) else [])
        self.script('convertheal',lambda c:[Heal(c.target_id,3,c.source_id,on_result='exactbonus')],target=True)
        g=self.game(hand=('convertheal',),board=('convert',));self.play(g,'convertheal',self.body(g,2).id)
        self.assertEqual(self.hero(g).armor,2);self.assertEqual(self.outcomes(g)[0].overheal,0);self.check(g)

    def test_lifesteal_restoration_has_own_packet_and_no_duplicate_callback(self):
        self.r.register_behavior('once',lambda c:[GainArmor(1,1)])
        self.script('lifestrike',lambda c:[Damage(c.state.players[2].board[0],3,c.state.players[1].board[0],on_result='once')])
        g=self.game(hand=('lifestrike',),board=('life',));self.play(g,'lifestrike');a,b=self.outcomes(g)
        self.assertEqual(a.batch_id,b.batch_id);self.assertTrue(b.from_lifesteal)
        self.assertEqual((b.flow,b.overheal,self.hero(g).armor),('healing',3,1));self.check(g)

    def test_redirected_result_uses_actual_target_and_retains_original_path(self):
        self.provider('redirect',HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,
            target_relation='friendly',redirect_to='self'))
        g=self.game(hand=('damage',),enemy=('body','redirect'));original=self.body(g,2).id;actual=self.body(g,2,1).id
        self.play(g,'damage',original);out=self.outcomes(g)[0]
        self.assertEqual((out.original_target_id,out.target_id,out.redirect_path),(original,actual,(original,actual)));self.check(g)

    def test_health_loss_replacement_is_not_a_numeric_kill_or_heal(self):
        from hs_sim.engine.model import HealthLossReplacementSpec
        self.r.register_card(CardDefinition('replace','replace',CardType.MINION,health=5,
            health_loss_replacements=(HealthLossReplacementSpec(),)))
        g=self.game(hand=('damage',),board=('replace',));self.play(g,'damage',self.hero(g).id)
        out=self.outcomes(g)[0]
        self.assertEqual((out.health_before,out.health_after,out.max_health,out.max_health_after),(30,33,30,33))
        self.assertEqual((out.health_lost,out.health_gained,out.health_replaced,out.healed),(0,3,3,0));self.check(g)

    def test_result_callback_carries_original_numbers_after_earlier_trigger_heals_target(self):
        self.watch('autoheal','damage_dealt',lambda c:[Heal(c.event.target_id,3,c.source_id)])
        self.r.register_behavior('read',lambda c:[GainArmor(1,c.health_result.health_after)])
        self.script('readstrike',lambda c:[Damage(c.target_id,1,c.source_id,on_result='read')],target=True)
        g=self.game(hand=('readstrike',),board=('autoheal',));self.play(g,'readstrike',self.body(g,2).id)
        self.assertEqual((self.body(g,2).health,self.hero(g).armor),(3,2));self.check(g)

    def test_result_callback_choice_keeps_original_target_identity_after_transform(self):
        self.watch('transformer','damage_dealt',lambda c:[Transform(c.event.target_id,'weak')])
        self.r.register_behavior('choose',lambda c:[RequestChoice(1,(ChoiceOption('ok',c.health_result.target_card_id,
            (GainArmor(1,c.health_result.health_before),)),),source_id=c.source_id)])
        self.script('choicehit',lambda c:[Damage(c.target_id,1,c.source_id,on_result='choose')],target=True)
        g=self.game(hand=('choicehit',),board=('transformer',));self.play(g,'choicehit',self.body(g,2).id)
        self.assertEqual(self.body(g,2).card_id,'weak');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_batch_callbacks_run_in_packet_order_with_independent_context(self):
        self.r.register_behavior('ordered',lambda c:[AddToHand(1,'weak' if c.health_result.packet_index==1 else 'body')])
        self.script('callbacks',lambda c:[DamageBatch(tuple(Damage(i,3,c.source_id,on_result='ordered') for i in c.state.players[2].board))])
        g=self.game(hand=('callbacks',),enemy=('weak','body'));self.play(g,'callbacks')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['weak','body']);self.check(g)

    def test_random_damage_forwards_callback_once_with_chosen_target(self):
        self.r.register_behavior('randomresult',lambda c:[GainArmor(1,c.health_result.packet_index)])
        self.script('random',lambda c:[RandomDamage(tuple(c.state.players[2].board),3,c.source_id,on_result='randomresult')])
        g=self.game(hand=('random',),enemy=('body',)*3);self.play(g,'random')
        self.assertEqual((len(self.outcomes(g)),self.hero(g).armor),(1,1));self.check(g)

    def test_bad_callback_fails_before_even_empty_random_candidates(self):
        self.script('bad',lambda c:[RandomDamage((),1,c.source_id,on_result='unknown')])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_callback_failure_rolls_back_rng_damage_history_and_events(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'unknown')])
        self.script('bad',lambda c:[RandomDamage(tuple(c.state.players[2].board),1,c.source_id,on_result='fail')])
        g=self.game(hand=('bad',),enemy=('body',)*2);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_terminal_damage_suppresses_unstarted_callback(self):
        self.r.register_behavior('bonus',lambda c:[GainArmor(1,99)])
        self.script('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id,on_result='bonus')])
        g=self.game(hand=('lethal',));self.play(g,'lethal')
        self.assertEqual(g.state.winner,1);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_silence_and_transform_remove_keyword_listener(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0]),self.from_board(c,4)])
        self.script('transform',lambda c:[Transform(c.state.players[1].board[0],'body'),self.from_board(c,4)])
        for card in ('silence','transform'):
            with self.subTest(card=card):
                g=self.game(hand=(card,),board=('killer',));self.play(g,card)
                self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_copy_listener_is_bound_to_each_physical_source(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        self.script('copiedhit',lambda c:[Damage(c.state.players[2].board[0],4,c.state.players[1].board[1])])
        g=self.game(hand=('copy','copiedhit'),board=('killer',));self.play(g,'copy');self.play(g,'copiedhit')
        self.assertEqual(self.hero(g).armor,5);self.check(g)

    def test_control_change_uses_new_controller_for_turn_predicate(self):
        self.script('steal',lambda c:[ChangeControl(c.state.players[2].board[0],1)])
        self.script('newhit',lambda c:[Damage(c.state.players[2].board[0],4,c.state.players[1].board[0])])
        g=self.game(hand=('steal','newhit'),enemy=('killer','body'));self.play(g,'steal');self.play(g,'newhit')
        self.assertEqual(self.hero(g).armor,5);self.assertEqual(self.outcomes(g)[0].source_controller,1);self.check(g)

    def test_granted_listener_expires_without_leaving_condition_state(self):
        self.script('grant',lambda c:[GrantTrigger(c.state.players[1].board[0],'health_resolved','overkill',expires_turn=c.state.turn)])
        self.script('hit',lambda c:[self.from_board(c,4)])
        g=self.game(hand=('grant','hit','hit'),board=('body',),enemy=('body',)*2);self.play(g,'grant');self.play(g,'hit')
        self.assertEqual(self.hero(g).armor,5);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'hit')
        self.assertEqual(self.hero(g).armor,5);self.check(g)

    def test_limited_trigger_consumes_only_matching_overheal_even_when_actual_heal_zero(self):
        self.r.register_trigger_condition('overheal.condition',lambda c:is_overheal(c.event,c.source_id))
        self.r.register_behavior('limited',lambda c:[GainArmor(1,7)])
        self.script('grant',lambda c:[GrantLimitedTrigger(c.state.players[1].board[0],
            LimitedTriggerSpec('health_resolved','limited','overheal.condition'))])
        g=self.game(hand=('grant','heal','heal'),board=('body',));self.play(g,'grant');self.play(g,'heal',self.body(g).id);self.play(g,'heal',self.body(g).id)
        self.assertEqual(self.hero(g).armor,7);self.assertEqual(sum(e.kind=='limited_trigger_used' for e in g.events),1);self.check(g)

    def test_legacy_damage_and_healing_triggers_still_fire_once(self):
        self.watch('damage.watch','damage_dealt',lambda c:[GainArmor(1,1)])
        self.watch('heal.watch','healed',lambda c:[GainArmor(1,2)])
        g=self.game(hand=('damage','heal','heal'),board=('damage.watch','heal.watch'))
        self.play(g,'damage',self.body(g).id);self.play(g,'heal',self.body(g).id);self.play(g,'heal',self.body(g).id)
        self.assertEqual(self.hero(g).armor,3);self.assertEqual(len(self.outcomes(g)),3);self.check(g)

    def test_snapshot_rejects_inconsistent_numeric_result_even_with_recomputed_hashes(self):
        g=self.game(hand=('damage',));self.play(g,'damage',self.body(g,2).id)
        for field,value in (('health_lost',99),('source_controller',True),('overheal',1),('target_card_id',''),('batch_id',99999)):
            with self.subTest(field=field):
                snapshot=g.snapshot();event=next(e for e in snapshot['events'] if e['kind']=='health_resolved')
                for row in event['data']['result']:
                    if row[0]==field:row[1]=value
                self.reject(snapshot)

    def test_snapshot_rejects_duplicate_or_missing_result_fields(self):
        g=self.game(hand=('heal',),board=('medic',));self.play(g,'heal',self.body(g).id)
        for duplicate in (False,True):
            with self.subTest(duplicate=duplicate):
                s=g.snapshot();rows=next(e for e in s['events'] if e['kind']=='health_resolved')['data']['result']
                if duplicate:rows.append(rows[0])
                else:rows.pop()
                self.reject(s)

    def test_result_and_predicate_argument_validation(self):
        self.assertIsNone(health_result(None))
        for fn in (is_overkill,is_honorable_kill,is_overheal):
            self.assertFalse(fn(None,1))
            with self.assertRaises(ValueError):fn(None,True)
        for fn in (lambda:Damage(1,1,on_result='x'),lambda:Heal(1,1,on_result='x'),
                   lambda:RandomDamage((),1,on_result='x'),lambda:Damage(1,1,1,on_result='')):
            with self.assertRaises(ValueError):fn()

    def test_internal_result_details_are_not_exposed_in_player_logs(self):
        g=self.game(hand=('damage',));self.play(g,'damage',self.body(g,2).id)
        for seat in (1,2):
            text=json.dumps(g.observe(seat))
            for hidden in ('health_resolved','packet_index','source_zone_epoch','rule_ids'):
                self.assertNotIn(hidden,text)
        self.check(g)

    def test_result_callback_rewind_undoes_only_prior_attempt_bonus(self):
        from hs_sim.engine import RewindSpec
        self.r.register_behavior('killbonus',lambda c:[GainArmor(1,2 if is_honorable_kill(c.event,c.source_id) else 5)]
            if is_honorable_kill(c.event,c.source_id) or is_overkill(c.event,c.source_id) else [])
        self.script('rewind',lambda c:[Damage(c.target_id,3+c.rewind_attempt,c.source_id,on_result='killbonus')],
            target=True,keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind',));self.play(g,'rewind',self.body(g,2).id);self.check(g)
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,('retry',)))
        self.assertEqual(self.hero(g).armor,5);self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_retained_rewind_keeps_callback_bonus_but_stale_target_has_no_second_result(self):
        from hs_sim.engine import RewindSpec
        self.r.register_card(CardDefinition('retainer','retainer',CardType.MINION,health=4,retain_rewind_outcomes=True))
        self.r.register_behavior('bonus',lambda c:[GainArmor(1,2)])
        self.script('rewind',lambda c:[Damage(c.target_id,3,c.source_id,on_result='bonus')],
            target=True,keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind',self.body(g,2).id)
        self.assertEqual((self.hero(g).armor,len(self.outcomes(g))),(2,1));self.check(g)

    def test_auto_cast_source_retains_result_callback_without_manual_play(self):
        from hs_sim.engine import CastSpell
        self.r.register_behavior('bonus',lambda c:[GainArmor(1,2)] if is_honorable_kill(c.event,c.source_id) else [])
        self.script('strike',lambda c:[Damage(c.target_id,3,c.source_id,DamageKind.SPELL,on_result='bonus')],target=True)
        self.script('auto',lambda c:[CastSpell(1,'strike',c.source_id,target_id=c.state.players[2].board[0],targeting='explicit')])
        g=self.game(hand=('auto',));self.play(g,'auto')
        self.assertEqual((self.hero(g).armor,len(g.state.play_history),len(g.state.cast_history)),(2,1,2));self.check(g)

    def test_simultaneous_hero_lethal_results_survive_terminal_snapshot(self):
        self.script('both',lambda c:[DamageBatch(tuple(Damage(p.hero_id,30,c.source_id) for p in c.state.players.values()))])
        g=self.game(hand=('both',));self.play(g,'both')
        self.assertEqual(g.state.status,'draw');self.assertEqual(len(self.outcomes(g)),2);self.check(g)

    def test_choice_failure_preserves_health_result_and_pending_callback(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'unknown')])
        self.r.register_behavior('choose',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',
            (InvokeBehavior('fail',c.source_id,1),)),),source_id=c.source_id)])
        self.script('choicehit',lambda c:[Damage(c.target_id,1,c.source_id,on_result='choose')],target=True)
        g=self.game(hand=('choicehit',));self.play(g,'choicehit',self.body(g,2).id);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.outcomes(g)[0].health_after,2);self.check(g)


class HealthOutcomeRepresentativeTests(unittest.TestCase):
    def test_three_representatives_use_frozen_text_and_shared_trigger_entry(self):
        from hs_sim.engine.representative import build_registry
        r=build_registry()
        for cid,name,cost,attack,health in (('TRL_506','古拉巴什小鸡',1,1,1),('AV_121','侏儒列兵',1,1,3),('AT_011','神圣勇士',2,1,4)):
            with self.subTest(card=cid):
                card=r.card(cid);self.assertEqual((card.name,card.cost,card.attack,card.health),(name,cost,attack,health))
                self.assertEqual(card.triggers[0].event,'health_resolved')

    def test_representative_player_interface_and_paused_recovery(self):
        from examples.health_outcomes import run
        game,snapshot=run()
        self.assertIsNotNone(snapshot['state']['pending_choice']);self.assertEqual(len(game.history),6)
        self.assertIsNone(game.state.pending_choice)


if __name__=='__main__':unittest.main()
