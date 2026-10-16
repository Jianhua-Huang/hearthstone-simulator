"""Finite trigger identity, eligibility, consumption, lifecycle and restoration."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, GrantLimitedTrigger,
    IllegalAction, Keyword, LimitedTriggerSpec, PlayCard, PlayerSetup, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower, UseHandAction, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, EquipWeapon, ForceAttack, GainArmor, GrantKeyword, Heal,
    ModifyCost, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine import CostSpec
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class LimitedTriggerTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=2,health=8))
        self.spell('noop',lambda c:[])
        self.spell('hit',lambda c:[Damage(c.target_id,1,c.source_id)],requires_target=True)

    def spell(self,name,callback,**kwargs):
        self.r.register_behavior(name,callback)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kwargs))

    def limited(self,name,callback,keyword=Keyword.SPELLBURST,spec=None,**kwargs):
        self.r.register_behavior(name,callback)
        spec=spec or (LimitedTriggerSpec.spellburst(name) if keyword==Keyword.SPELLBURST else LimitedTriggerSpec.frenzy(name))
        self.r.register_card(CardDefinition(name,name,CardType.MINION,health=8,
            keywords=(keyword,) if keyword else (),limited_triggers=(spec,),**kwargs))

    def game(self,hand=(),enemy_hand=(),board=(),enemy_board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=('plain',)*12,max_mana=10,mana=10,hero_power_card_id='HERO_01bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('plain',)*12,max_mana=10,mana=10)),seed=107),self.r)

    def play(self,g,card,target=None):
        state=g.state;p=state.active_player
        i=next(i for i in state.players[p].hand if state.entities[i].card_id==card)
        g.apply(PlayCard(p,i,target));return i

    def body(self,g,p=1,index=0):return g.state.entities[g.state.players[p].board[index]]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def uses(self,g,source=None):return [a.uses_remaining for a in (g.state.entities[source] if source else self.body(g)).abilities if a.kind=='limited_trigger']
    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_initiate_uses_only_once(self):
        g=self.game(hand=('noop','noop'),board=('SCH_231',));self.play(g,'noop');self.play(g,'noop')
        self.assertEqual(self.body(g).attack,3);self.assertEqual(self.uses(g),[0]);self.assertNotIn(Keyword.SPELLBURST,self.body(g).keywords);self.check(g)

    def test_opponent_spell_does_not_consume(self):
        g=self.game(hand=('noop',),enemy_board=('SCH_231',));self.play(g,'noop')
        self.assertEqual(self.uses(g,self.body(g,2).id),[1]);self.check(g)

    def test_minion_hero_power_trade_and_forge_do_not_consume(self):
        g=self.game(hand=('plain','SW_094','TTN_042'),board=('SCH_231',));self.play(g,'plain')
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        for card,action in (('SW_094','trade'),('TTN_042','forge')):
            i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==card)
            g.apply(UseHandAction(1,i,action))
        self.assertEqual(self.uses(g),[1]);self.check(g)

    def test_spell_body_resolves_before_burst(self):
        self.limited('copy_health',lambda c:[GainArmor(c.player_id,c.source.health)])
        g=self.game(hand=('hit',),board=('copy_health',));self.play(g,'hit',self.body(g).id)
        self.assertEqual(self.hero(g).armor,7)

    def test_spell_summoned_initiate_waits_for_next_spell(self):
        self.spell('make',lambda c:[Summon(c.player_id,'SCH_231')])
        g=self.game(hand=('make','noop'));self.play(g,'make');self.assertEqual(self.uses(g),[1]);self.play(g,'noop')
        self.assertEqual(self.body(g).attack,3);self.check(g)

    def test_midspell_granted_burst_waits_for_next_spell(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,2)])
        self.spell('grant',lambda c:[GrantLimitedTrigger(c.state.players[c.player_id].board[0],LimitedTriggerSpec.spellburst('armor'))])
        g=self.game(hand=('grant','noop'),board=('plain',));self.play(g,'grant');self.assertEqual(self.uses(g),[1]);self.play(g,'noop')
        self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_gibberling_new_copy_does_not_recurse(self):
        g=self.game(hand=('noop','noop'),board=('SCH_242',));self.play(g,'noop')
        self.assertEqual(len(g.state.players[1].board),2);self.assertEqual([self.uses(g,i) for i in g.state.players[1].board],[[0],[1]])
        self.play(g,'noop');self.assertEqual(len(g.state.players[1].board),3);self.check(g)

    def test_full_board_still_consumes_burst(self):
        g=self.game(hand=('noop',),board=('SCH_242',)+('plain',)*6);self.play(g,'noop')
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.uses(g),[0]);self.check(g)

    def test_countered_spell_still_triggers_burst(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('noop',),enemy_board=('SCH_231',));self.play(g,'EX1_287');g.apply(EndTurn(1));self.play(g,'noop')
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.body(g,2).attack,3);self.check(g)

    def test_spell_killed_source_does_not_trigger(self):
        g=self.game(hand=('hit',),board=('SCH_242',));i=self.body(g).id;self.play(g,'hit',i)
        self.assertFalse(g.state.players[1].board);self.assertEqual(self.uses(g,i),[1]);self.check(g)

    def test_spell_silenced_source_does_not_trigger(self):
        self.spell('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(hand=('silence',),board=('SCH_231',));self.play(g,'silence');self.assertEqual(self.body(g).attack,1);self.assertEqual(self.uses(g),[]);self.check(g)

    def test_transform_to_same_card_does_not_reuse_captured_identity(self):
        self.spell('transform',lambda c:[Transform(c.state.players[1].board[0],'SCH_231')])
        g=self.game(hand=('transform','noop'),board=('SCH_231',));self.play(g,'transform')
        self.assertEqual(self.uses(g),[1]);self.assertEqual(self.body(g).attack,1);self.play(g,'noop');self.assertEqual(self.body(g).attack,3);self.check(g)

    def test_control_away_and_back_invalidates_capture(self):
        self.spell('control',lambda c:[ChangeControl(c.state.players[1].board[0],2),ChangeControl(c.state.players[1].board[0],1)])
        g=self.game(hand=('control',),board=('SCH_231',));self.play(g,'control');self.assertEqual(self.uses(g),[1]);self.check(g)

    def test_flinger_battlecry_and_bounce_reset_printed_trigger(self):
        g=self.game(hand=('SCH_248','noop','noop'),enemy_board=('plain',));target=self.body(g,2).id
        i=self.play(g,'SCH_248',target);self.play(g,'noop');self.assertEqual(g.state.entities[i].zone,Zone.HAND);self.assertEqual(self.uses(g,i),[1])
        self.play(g,'SCH_248',target);self.play(g,'noop');self.assertEqual(self.body(g,2).health,6);self.assertEqual(g.state.entities[i].zone,Zone.HAND);self.check(g)

    def test_flinger_can_be_played_without_targets(self):
        g=self.game(hand=('SCH_248',));self.play(g,'SCH_248');self.assertEqual(self.uses(g),[1]);self.check(g)

    def test_flinger_cannot_target_hero(self):
        g=self.game(hand=('SCH_248',))
        with self.assertRaises(IllegalAction):self.play(g,'SCH_248',self.hero(g,2).id)

    def test_gidra_uses_modified_frozen_spell_cost(self):
        self.spell('discount',lambda c:[ModifyCost(c.state.players[1].hand[0],CostSpec(delta=-4))])
        g=self.game(hand=('discount','CS2_029','SCH_182'));self.play(g,'discount');i=self.play(g,'SCH_182')
        self.play(g,'CS2_029',self.hero(g,2).id);e=g.state.entities[i];self.assertEqual((e.attack,e.health),(1,4));self.assertEqual(self.uses(g,i),[0]);self.check(g)

    def test_gidra_positive_spell_cost(self):
        g=self.game(hand=('CS2_029',),board=('SCH_182',));self.play(g,'CS2_029',self.hero(g,2).id)
        self.assertEqual((self.body(g).attack,self.body(g).health),(5,8));self.check(g)

    def test_current_copy_keeps_used_state_and_base_copy_resets(self):
        self.spell('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1),CopyMinion(c.state.players[1].board[0],1,mode='base')])
        g=self.game(hand=('noop','copy','noop'),board=('SCH_231',));self.play(g,'noop');self.play(g,'copy')
        self.assertEqual([self.uses(g,i) for i in g.state.players[1].board],[[0],[0],[1]])
        self.play(g,'noop');self.assertEqual([self.body(g,index=i).attack for i in range(3)],[3,3,3]);self.check(g)

    def test_reborn_gets_fresh_printed_burst(self):
        self.spell('reborn',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.REBORN)])
        self.spell('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('reborn','kill','noop'),board=('SCH_231',));old=self.body(g).id;self.play(g,'reborn');self.play(g,'kill')
        self.assertNotEqual(self.body(g).id,old);self.assertEqual(self.uses(g),[1]);self.play(g,'noop');self.assertEqual(self.body(g).attack,3);self.check(g)

    def test_frenzy_once_after_surviving_actual_damage(self):
        g=self.game(hand=('hit','hit'),board=('BAR_024',));i=self.body(g).id;self.play(g,'hit',i);self.play(g,'hit',i)
        self.assertEqual(self.hero(g,2).health,27);self.assertEqual(self.body(g).health,1);self.assertEqual(self.uses(g),[0]);self.check(g)

    def test_zero_damage_does_not_consume_frenzy(self):
        self.spell('zero',lambda c:[Damage(c.state.players[1].board[0],0,c.source_id)])
        g=self.game(hand=('zero',),board=('BAR_024',));self.play(g,'zero');self.assertEqual(self.uses(g),[1]);self.check(g)

    def test_shield_or_immune_prevent_frenzy(self):
        for keyword in (Keyword.DIVINE_SHIELD,Keyword.IMMUNE):
            self.setUp();self.spell('protect',lambda c,k=keyword:[GrantKeyword(c.state.players[1].board[0],k)])
            g=self.game(hand=('protect','hit'),board=('BAR_024',));self.play(g,'protect');self.play(g,'hit',self.body(g).id)
            self.assertEqual(self.uses(g),[1]);self.assertEqual(self.hero(g,2).health,30);self.check(g)

    def test_lethal_damage_does_not_trigger_frenzy(self):
        self.spell('lethal',lambda c:[Damage(c.state.players[1].board[0],3,c.source_id)])
        g=self.game(hand=('lethal',),board=('BAR_024',));i=self.body(g).id;self.play(g,'lethal')
        self.assertFalse(g.state.players[1].board);self.assertEqual(self.hero(g,2).health,30);self.assertEqual(self.uses(g,i),[1]);self.check(g)

    def test_poisoned_survivor_does_not_trigger_frenzy(self):
        self.r.register_card(CardDefinition('poison','Poison',CardType.MINION,attack=1,health=9,keywords=(Keyword.POISONOUS,)))
        self.spell('fight',lambda c:[ForceAttack(c.state.players[2].board[0],c.state.players[1].board[0])])
        g=self.game(hand=('fight',),board=('BAR_024',),enemy_board=('poison',));self.play(g,'fight')
        self.assertFalse(g.state.players[1].board);self.assertEqual(self.hero(g,2).health,30);self.check(g)

    def test_two_surviving_packets_in_batch_consume_once(self):
        self.spell('batch',lambda c:[DamageBatch(tuple(Damage(c.state.players[1].board[0],1,c.source_id) for _ in range(2)))])
        g=self.game(hand=('batch',),board=('BAR_024',));self.play(g,'batch');self.assertEqual(self.hero(g,2).health,27)
        self.assertEqual(len([e for e in g.events if e.kind=='limited_trigger_used']),1);self.check(g)

    def test_batch_final_lethal_packet_prevents_frenzy(self):
        self.spell('batch',lambda c:[DamageBatch(tuple(Damage(c.state.players[1].board[0],n,c.source_id) for n in (1,2)))])
        g=self.game(hand=('batch',),board=('BAR_024',));self.play(g,'batch');self.assertEqual(self.hero(g,2).health,30);self.check(g)

    def test_healing_does_not_rearm_frenzy(self):
        self.spell('heal',lambda c:[Heal(c.state.players[1].board[0],9,c.source_id)])
        g=self.game(hand=('hit','heal','hit'),board=('BAR_024',));i=self.body(g).id;self.play(g,'hit',i);self.play(g,'heal');self.play(g,'hit',i)
        self.assertEqual(self.hero(g,2).health,27);self.check(g)

    def test_frenzy_can_trigger_on_opponent_turn(self):
        g=self.game(enemy_hand=('hit',),board=('BAR_024',));i=self.body(g).id;g.apply(EndTurn(1));self.play(g,'hit',i)
        self.assertEqual(self.hero(g,2).health,27);self.check(g)

    def test_sunwell_gains_shield_then_shield_blocks_next_hit(self):
        g=self.game(hand=('hit','hit','hit'),board=('BAR_025',));i=self.body(g).id;self.play(g,'hit',i)
        self.assertIn(Keyword.DIVINE_SHIELD,self.body(g).keywords);self.play(g,'hit',i);self.assertEqual(self.body(g).health,3)
        self.play(g,'hit',i);self.assertEqual(self.body(g).health,2);self.assertNotIn(Keyword.DIVINE_SHIELD,self.body(g).keywords);self.check(g)

    def test_grunt_gains_armor_equal_to_damage_packet(self):
        self.spell('three',lambda c:[Damage(c.state.players[1].board[0],3,c.source_id)])
        g=self.game(hand=('three',),board=('BAR_021',));self.play(g,'three');self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_samuro_uses_buffed_current_attack_and_enemy_minions_only(self):
        self.spell('fight',lambda c:[Buff(c.state.players[1].board[0],attack=2),ForceAttack(c.state.players[1].board[0],c.state.players[2].board[0])])
        g=self.game(hand=('fight',),board=('BAR_078',),enemy_board=('plain','plain'));self.play(g,'fight')
        self.assertEqual([self.body(g,2,n).health for n in range(2)],[2,5]);self.assertEqual(self.hero(g,2).health,30);self.assertEqual(self.body(g).health,4);self.check(g)

    def test_frenzy_with_no_effect_targets_still_consumes(self):
        g=self.game(hand=('hit',),board=('BAR_078',));self.play(g,'hit',self.body(g).id);self.assertEqual(self.uses(g),[0]);self.check(g)

    def test_two_granted_instances_consume_independently(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,1)])
        spec=LimitedTriggerSpec.spellburst('armor')
        self.spell('grant',lambda c:[GrantLimitedTrigger(c.state.players[1].board[0],spec) for _ in range(2)])
        g=self.game(hand=('grant','noop'),board=('plain',));self.play(g,'grant');self.play(g,'noop')
        self.assertEqual(self.uses(g),[0,0]);self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_generic_two_use_trigger_limits_batched_events(self):
        self.limited('twice',lambda c:[GainArmor(c.player_id,1)],keyword=None,spec=LimitedTriggerSpec('damage_dealt','twice',uses=2))
        self.spell('batch',lambda c:[DamageBatch(tuple(Damage(c.state.players[1].board[0],1,c.source_id) for _ in range(3)))])
        g=self.game(hand=('batch',),board=('twice',));self.play(g,'batch');self.assertEqual(self.uses(g),[0]);self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_false_condition_does_not_consume_and_context_is_detached(self):
        def condition(c):
            eligible=c.event.amount==2;c.state.entities[c.source_id].damage=999;return eligible
        self.r.register_trigger_condition('two',condition)
        self.limited('conditional',lambda c:[GainArmor(c.player_id,1)],keyword=None,spec=LimitedTriggerSpec('damage_dealt','conditional',condition_id='two'))
        self.spell('two',lambda c:[Damage(c.state.players[1].board[0],2,c.source_id)])
        g=self.game(hand=('hit','two'),board=('conditional',));self.play(g,'hit',self.body(g).id);self.assertEqual(self.uses(g),[1])
        self.play(g,'two');self.assertEqual(self.body(g).health,5);self.assertEqual(self.uses(g),[0]);self.check(g)

    def test_condition_requires_exact_bool_and_rolls_back(self):
        self.r.register_trigger_condition('bad',lambda c:1)
        self.limited('bad',lambda c:[],keyword=None,spec=LimitedTriggerSpec('card_played','bad',condition_id='bad'))
        g=self.game(hand=('noop',),board=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'noop')
        self.assertEqual(g.snapshot(),before)

    def test_consumed_before_callback_and_recursive_damage(self):
        def callback(c):
            self.assertTrue(c.trigger.consumed);self.assertEqual(c.trigger.uses_remaining,0)
            return [Damage(c.source_id,1,c.source_id),GainArmor(c.player_id,1)]
        self.limited('recursive',callback,keyword=Keyword.FRENZY)
        g=self.game(hand=('hit',),board=('recursive',));self.play(g,'hit',self.body(g).id)
        self.assertEqual(self.body(g).health,6);self.assertEqual(self.hero(g).armor,1);self.check(g)

    def test_effect_failure_rolls_back_consumption(self):
        def fail(c):raise RuntimeError('intentional')
        self.limited('fail',fail);g=self.game(hand=('noop',),board=('fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'noop')
        self.assertEqual(g.snapshot(),before)

    def test_later_live_check_skips_source_killed_by_earlier_listener(self):
        self.r.register_behavior('kill',lambda c:[Destroy(c.state.players[c.player_id].board[1])])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,triggers=(TriggerSpec('card_played','kill'),)))
        g=self.game(hand=('noop',),board=('watcher','SCH_231'));self.play(g,'noop')
        self.assertEqual(len(g.state.players[1].board),1);self.assertFalse(any(e.kind=='limited_trigger_used' for e in g.events));self.check(g)

    def test_already_consumed_callback_survives_source_leaving(self):
        self.r.register_behavior('kill',lambda c:[Destroy(c.event.source_id)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,triggers=(TriggerSpec('limited_trigger_used','kill'),)))
        self.limited('armor',lambda c:[GainArmor(c.player_id,3)])
        g=self.game(hand=('noop',),board=('watcher','armor'));self.play(g,'noop')
        self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_expired_dynamic_trigger_is_removed(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,1)])
        self.spell('grant',lambda c:[GrantLimitedTrigger(c.state.players[1].board[0],LimitedTriggerSpec.spellburst('armor'),expires_turn=c.state.turn)])
        g=self.game(hand=('grant','noop'),board=('plain',));self.play(g,'grant');g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'noop')
        self.assertEqual(self.uses(g),[]);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_weapon_spellburst_supported_and_consumed(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,4)])
        self.r.register_card(CardDefinition('weapon','Weapon',CardType.WEAPON,attack=2,durability=2,
            keywords=(Keyword.SPELLBURST,),limited_triggers=(LimitedTriggerSpec.spellburst('armor'),)))
        g=self.game(hand=('weapon','noop','noop'));i=self.play(g,'weapon')
        self.assertNotIn(Keyword.SPELLBURST,self.hero(g).keywords)
        self.play(g,'noop');self.play(g,'noop')
        self.assertEqual(self.uses(g,i),[0]);self.assertEqual(self.hero(g).armor,4);self.check(g)

    def test_replacing_weapon_midspell_does_not_transfer_capture(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,4)])
        self.r.register_card(CardDefinition('weapon','Weapon',CardType.WEAPON,attack=2,durability=2,
            keywords=(Keyword.SPELLBURST,),limited_triggers=(LimitedTriggerSpec.spellburst('armor'),)))
        self.spell('equip',lambda c:[EquipWeapon(c.player_id,'weapon')])
        g=self.game(hand=('weapon','equip','noop'));self.play(g,'weapon');self.play(g,'equip')
        self.assertEqual(self.hero(g).armor,0);self.play(g,'noop');self.assertEqual(self.hero(g).armor,4);self.check(g)

    def choice_spell(self):
        self.spell('choice',lambda c:[RequestChoice(c.player_id,(ChoiceOption('go','Go',(Summon(c.player_id,'SCH_231'),)),),c.source_id)])

    def test_pending_spell_preserves_precaptured_instances(self):
        self.choice_spell();g=self.game(hand=('choice',),board=('SCH_231',));self.play(g,'choice');self.assertEqual(self.uses(g),[1]);self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual([self.uses(g,i) for i in g.state.players[1].board],[[0],[1]]);self.check(g)

    def test_trigger_choice_resumes_with_used_state(self):
        self.limited('choose',lambda c:[RequestChoice(c.player_id,(ChoiceOption('go','Go',(GainArmor(c.player_id,2),)),),c.source_id)])
        g=self.game(hand=('noop',),board=('choose',));self.play(g,'noop');self.assertEqual(self.uses(g),[0]);self.check(g)
        g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,g.state.pending_choice.id,('go',)));self.assertEqual(self.hero(g).armor,2);self.check(g)

    def test_pending_consumed_behavior_context_roundtrips(self):
        self.r.register_behavior('pause',lambda c:[RequestChoice(c.player_id,(ChoiceOption('go','Go'),),c.source_id)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,triggers=(TriggerSpec('limited_trigger_used','pause'),)))
        self.limited('armor',lambda c:[GainArmor(c.player_id,3)])
        g=self.game(hand=('noop',),board=('watcher','armor'));self.play(g,'noop');self.check(g)
        g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,g.state.pending_choice.id,('go',)));self.assertEqual(self.hero(g).armor,3);self.check(g)

    def test_public_view_shows_remaining_without_implementation_ids(self):
        g=self.game(hand=('noop',),board=('SCH_231',));view=g.observe(2)['players'][0]['board'][0]
        self.assertEqual(view['limited_triggers'],[{'keyword':'spellburst','uses_remaining':1}]);self.play(g,'noop')
        view=g.observe(2)['players'][0]['board'][0];self.assertEqual(view['limited_triggers'],[{'keyword':'spellburst','uses_remaining':0}])
        encoded=json.dumps(g.observe(2));self.assertNotIn('behavior_id',encoded);self.assertNotIn('ability_id',encoded);self.check(g)

    def test_hidden_hand_does_not_leak_trigger_type(self):
        a=self.game(hand=('SCH_231',));b=self.game(hand=('BAR_024',));self.assertEqual(a.observe(2),b.observe(2))

    def test_corrupt_trigger_usage_is_rejected_even_with_new_hash(self):
        g=self.game(board=('SCH_231',))
        for key,value in (('uses_remaining',True),('uses_remaining',-1),('uses_remaining',2),('uses_remaining',0),('consumed',True)):
            with self.subTest(key=key,value=value):
                data=g.snapshot();entity=next(e for e in data['state']['entities'].values() if e['card_id']=='SCH_231')
                next(a for a in entity['abilities'] if a['kind']=='limited_trigger')[key]=value
                data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_keyword_grant_without_spec_is_rejected(self):
        for keyword in (Keyword.SPELLBURST,Keyword.FRENZY):
            self.setUp();self.spell('grant',lambda c,k=keyword:[GrantKeyword(c.state.players[1].board[0],k)])
            g=self.game(hand=('grant',),board=('plain',));before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,'grant')
            self.assertEqual(g.snapshot(),before)

    def test_invalid_specs_fail_fast(self):
        for kwargs in ({'uses':0},{'uses':True},{'keyword':'spellburst'},{'keyword':Keyword.FRENZY},
                       {'uses':2,'keyword':Keyword.SPELLBURST}):
            with self.assertRaises(ValueError):LimitedTriggerSpec('card_played','noop',**kwargs)

    def test_registration_rejects_bare_keyword_or_wrong_carrier(self):
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.MINION,health=1,keywords=(Keyword.SPELLBURST,)))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.WEAPON,attack=1,durability=1,
            keywords=(Keyword.FRENZY,),limited_triggers=(LimitedTriggerSpec.frenzy('noop'),)))

    def test_corrupt_pending_candidates_are_rejected(self):
        self.choice_spell();g=self.game(hand=('choice',),board=('SCH_231',));self.play(g,'choice')
        for field,value in (('source_id',99999),('ability_id',99999),('entered_order',99999),('player_id',2),('ability_id',True)):
            with self.subTest(field=field):
                data=g.snapshot();finisher=next(w['fields'] for w in data['resolution_frame']['fields']['continuation']['tuple']
                    if w.get('type','').endswith('.FinishPlay'))
                finisher['spellburst_candidates']['tuple'][0]['fields'][field]=value
                data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_duplicate_pending_candidates_are_rejected(self):
        self.choice_spell();g=self.game(hand=('choice',),board=('SCH_231',));self.play(g,'choice');data=g.snapshot()
        values=next(w['fields'] for w in data['resolution_frame']['fields']['continuation']['tuple']
            if w.get('type','').endswith('.FinishPlay'))['spellburst_candidates']['tuple']
        values.append(values[0]);data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_choice_in_committed_window_restores_capture(self):
        self.r.register_behavior('pause',lambda c:[RequestChoice(c.player_id,(ChoiceOption('go','Go'),),c.source_id)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,triggers=(TriggerSpec('card_committed','pause'),)))
        g=self.game(hand=('noop',),board=('watcher','SCH_231'));self.play(g,'noop')
        self.assertEqual(len(g.state.action_windows[0].spellburst_candidates),1);self.check(g)
        g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,g.state.pending_choice.id,('go',)))
        self.assertEqual(self.body(g,index=1).attack,3);self.check(g)

    def test_bounce_before_completion_cancels_original_capture(self):
        self.spell('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('bounce',),board=('SCH_231',));i=self.body(g).id;self.play(g,'bounce')
        self.assertEqual(g.state.entities[i].zone,Zone.HAND);self.assertEqual(self.uses(g,i),[1]);self.check(g)

    def test_dormant_source_cannot_trigger(self):
        self.limited('sleep',lambda c:[GainArmor(c.player_id,1)],dormant_turns=2)
        g=self.game(hand=('noop',),board=('sleep',));self.play(g,'noop');self.assertEqual(self.uses(g),[1]);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_undocumented_dynamic_behavior_fails_and_rolls_back(self):
        self.spell('grant',lambda c:[GrantLimitedTrigger(c.state.players[1].board[0],LimitedTriggerSpec.spellburst('missing'))])
        g=self.game(hand=('grant',),board=('plain',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'grant')
        self.assertEqual(g.snapshot(),before)

    def test_real_player_port_example_restores_and_replays(self):
        from examples.limited_triggers import run
        game,snapshot=run();self.assertEqual(len(game.history),5);self.assertEqual(snapshot['schema_version'],SNAPSHOT_SCHEMA_VERSION)


if __name__=='__main__':unittest.main()
