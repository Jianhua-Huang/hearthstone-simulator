"""Exodar protocols and the shared continuations they require."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, Game, IllegalAction, Keyword,
    LaunchStarshipEffect, PlayCard, PlayerSetup, ResolutionError, Ruleset, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, DamageBatch,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, SplitDamage, Summon, Transform)
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.pools import GenerateFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.spell('scrap',lambda c:[DamageBatch(tuple(Damage(i,100) for i in c.state.players[1].board))])
        self.spell('free',lambda c:[LaunchStarshipEffect(1,construction(c.state,1).id)])
        self.r.register_card(CardDefinition('plain','plain',CardType.MINION,attack=1,health=1))

    def spell(self,name,callback):
        self.r.register_behavior(name,callback)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))

    def game(self,board=('SC_403a',),hand=('scrap','GDB_120'),enemy=(),seed=31,rules=None,context=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=board,hand=hand,max_mana=10,mana=10),
            PlayerSetup('HERO_01',board=enemy)),seed=seed,generation_context=context),self.r,ruleset=rules)

    def cast(self,g,card_id):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==card_id)
        return g.apply(PlayCard(1,i))

    def waiting(self,**kwargs):
        g=self.game(**kwargs);self.cast(g,'scrap');ship=construction(g.state,1).id
        self.cast(g,'GDB_120');return g,ship

    def choose(self,g,protocol):
        choice=g.state.pending_choice
        return g.apply(SelectChoice(choice.player_id,choice.id,(protocol,)))

    def armor(self,g,player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def check_replay(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_without_construction_exodar_is_paid_minion_without_choice(self):
        g=self.game(board=(),hand=('GDB_120',));self.cast(g,'GDB_120')
        self.assertEqual(g.state.players[1].mana,3);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].board),1);self.check_replay(g)

    def test_already_launched_ship_does_not_qualify(self):
        g=self.game(hand=('scrap','free','GDB_120'))
        self.cast(g,'scrap');self.cast(g,'free');self.cast(g,'GDB_120')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(sum(e.kind=='starship_launched' for e in g.events),1)

    def test_enemy_construction_does_not_qualify(self):
        self.spell('enemy_scrap',lambda c:[Destroy(c.state.players[2].board[0])])
        g=self.game(board=(),hand=('enemy_scrap','GDB_120'),enemy=('SC_403a',))
        self.cast(g,'enemy_scrap');self.cast(g,'GDB_120')
        self.assertIsNone(g.state.pending_choice);self.assertIsNotNone(construction(g.state,2))

    def test_exodar_launches_free_and_then_offers_three_protocols(self):
        g,ship=self.waiting()
        self.assertTrue(g.state.entities[ship].active)
        self.assertEqual(g.state.players[1].mana,3);self.assertEqual(self.armor(g),5)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['GDB_100a','GDB_100b','GDB_100c'])
        self.assertEqual(g.snapshot()['resolution_frame']['fields']['death_deferrals'],0)
        self.assertEqual(sum(e.kind=='mana_spent' and e.amount==5 for e in g.events),0)
        self.check_replay(g)

    def test_real_free_launch_consumes_scv_discount_once(self):
        g=self.game(hand=('SC_401','scrap','GDB_120'))
        self.cast(g,'SC_401');self.cast(g,'scrap');self.cast(g,'GDB_120')
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.players[1].mana,2)

    def test_emergency_repairs_emits_two_separate_armor_gains(self):
        g,_=self.waiting();result=self.choose(g,'GDB_100a')
        self.assertEqual([e.amount for e in result.events if e.kind=='armor_gained'],[1,1])
        self.assertEqual(self.armor(g),7);self.check_replay(g)

    def test_protocol_stats_include_completed_supercapacitor_launch_buff(self):
        g,ship=self.waiting(board=('SC_405',))
        self.assertEqual((g.state.entities[ship].attack,g.state.entities[ship].health),(2,2))
        self.choose(g,'GDB_100a');self.assertEqual(self.armor(g),4)

    def test_protocol_values_are_frozen_when_offered(self):
        self.r.register_behavior('damage_on_choice',lambda c:[Damage(next(i for i in c.state.players[1].board
            if c.state.entities[i].components),1)])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,attack=1,health=1,
            triggers=(TriggerSpec('choice_requested','damage_on_choice'),)))
        self.spell('summon_watch',lambda c:[Summon(1,'watch')])
        g=self.game(board=('SC_405',),hand=('scrap','summon_watch','GDB_120'))
        self.cast(g,'scrap');self.cast(g,'summon_watch');self.cast(g,'GDB_120')
        self.choose(g,'GDB_100a');self.assertEqual(self.armor(g),6)

    def test_offensive_formation_is_unit_damage_from_exodar(self):
        g,ship=self.waiting();source=g.state.pending_choice.source_id
        result=self.choose(g,'GDB_100b')
        hits=[e for e in result.events if e.kind=='damage_dealt']
        self.assertEqual([e.amount for e in hits],[1,1])
        self.assertEqual({e.source_id for e in hits},{source})
        self.assertNotEqual(source,ship);self.check_replay(g)

    def test_offensive_formation_does_not_inherit_ship_lifesteal_or_spell_damage(self):
        self.spell('hurt',lambda c:[Damage(c.state.players[1].hero_id,10),Summon(1,'EX1_012')])
        g=self.game(board=('GDB_109',),hand=('scrap','hurt','GDB_120'))
        self.cast(g,'scrap');self.cast(g,'hurt');self.cast(g,'GDB_120');self.choose(g,'GDB_100b')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,20)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)

    def test_launch_damage_and_deaths_precede_protocol_request(self):
        g,ship=self.waiting(board=('SC_403b',),enemy=('plain',))
        self.assertFalse(g.state.players[2].board)
        death=max(e.sequence for e in g.events if e.kind=='minion_died')
        requested=max(e.sequence for e in g.events if e.kind=='choice_requested')
        self.assertLess(death,requested)
        self.choose(g,'GDB_100b');self.check_replay(g)

    def test_crew_transport_preserves_component_order_and_multiplicity(self):
        g,ship=self.waiting(board=('SC_403a','SC_403a','GDB_100'))
        self.choose(g,'GDB_100c')
        cards=[g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([c.card_id for c in cards],['SC_403a','SC_403a','GDB_100'])
        self.assertEqual([c.cost for c in cards],[1,1,1])
        self.assertEqual([c.base_cost for c in cards],[1,1,4])
        self.assertEqual(len({c.id for c in cards}),3)
        self.assertEqual(len({c.enchantments[0].id for c in cards}),3);self.check_replay(g)

    def test_crew_copies_base_definitions_without_original_piece_buffs(self):
        self.spell('buff_scrap',lambda c:[Buff(c.state.players[1].board[0],9,9),Destroy(c.state.players[1].board[0])])
        g=self.game(board=('GDB_100',),hand=('buff_scrap','GDB_120'))
        self.cast(g,'buff_scrap');self.cast(g,'GDB_120');self.choose(g,'GDB_100c')
        piece=g.state.entities[g.state.players[1].hand[0]]
        self.assertEqual((piece.attack,piece.health,piece.cost),(3,4,1))
        self.assertEqual(len(piece.enchantments),1)

    def test_crew_handles_full_hand_without_deathrattles_or_corpses(self):
        g,_=self.waiting(board=('GDB_100','GDB_100','GDB_100'),
            hand=('scrap','GDB_120')+('plain',)*8)
        before=self.armor(g);deaths=len(g.state.death_history)
        result=self.choose(g,'GDB_100c')
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(sum(e.kind=='card_burned' for e in result.events),1)
        self.assertEqual(len(g.state.death_history),deaths);self.assertEqual(self.armor(g),before)

    def test_generated_cost_is_applied_before_added_card_trigger(self):
        self.r.register_behavior('cost_watch',lambda c:[GainArmor(1,c.state.entities[c.target_id].cost)])
        self.r.register_card(CardDefinition('cost_watch','cost_watch',CardType.MINION,attack=1,health=1,
            triggers=(TriggerSpec('card_added_to_hand','cost_watch'),)))
        self.spell('summon_watch',lambda c:[Summon(1,'cost_watch')])
        g=self.game(board=('GDB_100',),hand=('scrap','summon_watch','GDB_120'))
        self.cast(g,'scrap');self.cast(g,'summon_watch');self.cast(g,'GDB_120')
        before=self.armor(g);self.choose(g,'GDB_100c');self.assertEqual(self.armor(g)-before,1)

    def test_protocol_options_restore_and_all_three_branches_replay(self):
        g,_=self.waiting(board=('GDB_100','SC_403d'))
        for option in ('GDB_100a','GDB_100b','GDB_100c'):
            with self.subTest(option=option):
                clone=g.clone();restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
                self.choose(clone,option);self.choose(restored,option)
                self.assertEqual(clone.snapshot(),restored.snapshot());self.check_replay(clone)

    def test_fixed_seat_choice_privacy_and_command(self):
        g,_=self.waiting();one=g.for_player(1);two=g.for_player(2)
        own=one.observe();enemy=two.observe()
        self.assertIn('GDB_100c',json.dumps(own,ensure_ascii=False))
        self.assertNotIn('GDB_100c',json.dumps(enemy,ensure_ascii=False))
        actions=one.legal_actions();cmd=next(a for a in actions['actions'] if a['type']=='select_choice')
        self.assertTrue(one.submit({'revision':actions['revision'],'action':cmd})['accepted'])
        self.check_replay(g)

    def test_invalid_choice_rolls_back_only_to_paid_launched_boundary(self):
        g,_=self.waiting();before=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,'not-a-protocol')
        self.assertEqual(before,g.snapshot());self.assertEqual(g.state.players[1].mana,3)

    def test_exodar_needs_space_to_play_but_launch_uses_existing_slot(self):
        self.spell('fill',lambda c:[Summon(1,'plain') for _ in range(5)])
        g=self.game(hand=('scrap','fill','GDB_120'));self.cast(g,'scrap');self.cast(g,'fill')
        self.cast(g,'GDB_120');self.assertEqual(len(g.state.players[1].board),7)
        self.assertIsNotNone(g.state.pending_choice)

    def test_full_board_rejects_exodar_without_consuming_mana(self):
        self.spell('fill',lambda c:[Summon(1,'plain') for _ in range(6)])
        g=self.game(hand=('scrap','fill','GDB_120'));self.cast(g,'scrap');self.cast(g,'fill');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.cast(g,'GDB_120')
        self.assertEqual(before,g.snapshot())

    def test_followup_binds_original_ship_despite_a_new_construction(self):
        self.r.register_behavior('new_ship',lambda c:[Summon(1,'SC_403a'),
            InvokeBehavior('kill_piece',c.source_id,1)])
        self.r.register_behavior('kill_piece',lambda c:[Destroy(c.state.players[1].board[-1])])
        self.r.register_card(replace(self.r.card('GDB_100'),id='new_ship',deathrattle=None,on_launch='new_ship'))
        g,ship=self.waiting(board=('new_ship',))
        self.assertNotEqual(construction(g.state,1).id,ship)
        self.choose(g,'GDB_100a');self.assertEqual(self.armor(g),8)

    def test_launch_choice_resumes_before_offering_protocols(self):
        self.r.register_behavior('ask',lambda c:[RequestChoice(1,(ChoiceOption('yes','yes',(Buff(c.source_id,2,3),)),))])
        self.r.register_card(replace(self.r.card('SC_403a'),id='ask',on_launch='ask'))
        g,ship=self.waiting(board=('ask',))
        self.assertEqual([o.id for o in g.state.pending_choice.options],['yes'])
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        self.choose(g,'yes');self.choose(restored,'yes')
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(g.state.entities[ship].health,4)
        self.choose(g,'GDB_100a');self.assertEqual(self.armor(g),8);self.check_replay(g)

    def test_destroyed_exodar_does_not_cancel_completed_battlecry(self):
        self.r.register_behavior('kill_exodar',lambda c:[Destroy(c.state.players[1].board[-1])])
        self.r.register_card(replace(self.r.card('SC_403a'),id='killer',on_launch='kill_exodar'))
        g,_=self.waiting(board=('killer',))
        self.assertEqual(g.state.entities[g.state.pending_choice.source_id].zone,Zone.GRAVEYARD)
        self.choose(g,'GDB_100b');self.check_replay(g)

    def test_destroyed_ship_protocol_uses_last_known_death_stats(self):
        self.r.register_behavior('self_destroy',lambda c:[Destroy(c.source_id)])
        self.r.register_card(replace(self.r.card('SC_403a'),id='self_destroy',on_launch='self_destroy'))
        g,ship=self.waiting(board=('self_destroy',));self.assertEqual(g.state.entities[ship].zone,Zone.GRAVEYARD)
        self.choose(g,'GDB_100a');self.assertEqual(self.armor(g),2);self.check_replay(g)

    def test_transformed_ship_without_composition_skips_protocol_under_prototype_policy(self):
        self.r.register_behavior('transform',lambda c:[Transform(c.source_id,'plain')])
        self.r.register_card(replace(self.r.card('SC_403a'),id='transform',on_launch='transform'))
        g,ship=self.waiting(board=('transform',))
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.entities[ship].components)

    def test_hero_lethal_launch_does_not_offer_post_game_choice(self):
        self.r.register_behavior('lethal',lambda c:[Damage(c.state.players[2].hero_id,30)])
        self.r.register_card(replace(self.r.card('SC_403a'),id='lethal',on_launch='lethal'))
        g,_=self.waiting(board=('lethal',))
        self.assertEqual(g.state.winner,1);self.assertIsNone(g.state.pending_choice);self.check_replay(g)

    def test_stale_launch_skips_its_followup(self):
        self.spell('stale',lambda c:[LaunchStarshipEffect(1,c.source_id,followup=(GainArmor(1,99),))])
        g=self.game(hand=('stale',));self.cast(g,'stale');self.assertEqual(self.armor(g),0)

    def test_followup_error_rolls_back_launch_and_fee(self):
        self.spell('bad',lambda c:[LaunchStarshipEffect(1,construction(c.state,1).id,
            followup=(InvokeBehavior('absent',c.source_id,1),))])
        g=self.game(hand=('scrap','bad'));self.cast(g,'scrap');before=g.snapshot()
        with self.assertRaises(ValueError):self.cast(g,'bad')
        self.assertEqual(before,g.snapshot())

    def test_split_damage_requeries_after_deathrattle_summons(self):
        self.r.register_behavior('hatch',lambda c:[Summon(2,'plain')])
        self.r.register_card(CardDefinition('egg','egg',CardType.MINION,health=1,deathrattle='hatch'))
        self.spell('shots',lambda c:[SplitDamage(2,3,c.source_id,include_hero=False)])
        g=self.game(board=(),hand=('shots',),enemy=('egg',));result=self.cast(g,'shots')
        hits=[e for e in result.events if e.kind=='damage_dealt']
        self.assertEqual(len(hits),2);self.assertNotEqual(hits[0].target_id,hits[1].target_id)
        self.assertFalse(g.state.players[2].board);self.check_replay(g)

    def test_split_damage_divine_shield_consumes_one_hit(self):
        self.r.register_card(CardDefinition('shield','shield',CardType.MINION,health=1,keywords=(Keyword.DIVINE_SHIELD,)))
        self.spell('shots',lambda c:[SplitDamage(2,2,c.source_id,include_hero=False)])
        g=self.game(board=(),hand=('shots',),enemy=('shield',));result=self.cast(g,'shots')
        self.assertEqual(sum(e.kind=='random_choice' for e in result.events),2)
        self.assertEqual(sum(e.kind=='damage_dealt' for e in result.events),1)
        self.assertFalse(g.state.players[2].board)

    def test_zero_split_damage_consumes_no_rng(self):
        self.spell('zero',lambda c:[SplitDamage(2,0,c.source_id)])
        g=self.game(board=(),hand=('zero',));before=g.snapshot()['rng_state']
        self.cast(g,'zero');self.assertEqual(before,g.snapshot()['rng_state'])

    def test_split_damage_budget_failure_is_transactional(self):
        self.spell('shots',lambda c:[SplitDamage(2,100,c.source_id)])
        g=self.game(board=(),hand=('shots',),rules=Ruleset(max_resolution_steps=30));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'shots')
        self.assertEqual(before,g.snapshot())

    def test_choice_during_split_damage_restores_remaining_shots(self):
        self.r.register_behavior('ask_on_hit',lambda c:[RequestChoice(2,(ChoiceOption('ok','ok',()),))]
            if c.event.target_id==c.source_id else [])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=3,
            triggers=(TriggerSpec('damage_dealt','ask_on_hit'),)))
        self.spell('shots',lambda c:[SplitDamage(2,2,c.source_id,include_hero=False)])
        g=self.game(board=(),hand=('shots',),enemy=('watch',));self.cast(g,'shots')
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        while g.state.pending_choice:self.choose(g,'ok');self.choose(restored,'ok')
        self.assertEqual(g.snapshot(),restored.snapshot());self.check_replay(g)

    def test_crew_add_card_choice_preserves_remaining_cost_initializers(self):
        self.r.register_behavior('ask_added',lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',()),))])
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=1,
            triggers=(TriggerSpec('card_added_to_hand','ask_added'),)))
        self.spell('summon_watch',lambda c:[Summon(1,'watch')])
        g=self.game(board=('GDB_100','GDB_100'),hand=('scrap','summon_watch','GDB_120'))
        self.cast(g,'scrap');self.cast(g,'summon_watch');self.cast(g,'GDB_120');self.choose(g,'GDB_100c')
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        while g.state.pending_choice:self.choose(g,'ok');self.choose(restored,'ok')
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual([g.state.entities[i].cost for i in g.state.players[1].hand],[1,1]);self.check_replay(g)

    def test_choice_only_descriptors_cannot_enter_hand_or_deck(self):
        for zone in ('hand','deck'):
            with self.subTest(zone=zone),self.assertRaises(ResolutionError):
                Game.from_scenario(Scenario((PlayerSetup('HERO_01',**{zone:('GDB_100a',)}),PlayerSetup('HERO_01'))),self.r)

    def test_choice_only_generation_fails_without_filtering_pool(self):
        card=self.r.card('GDB_100a');self.r.register_pool_card(PoolCard.from_definition(card))
        self.r.register_pool(PoolDefinition('bad','v1','target','experimental',(PoolMember(card.id),)))
        self.spell('generate',lambda c:[GenerateFromPool(1,'bad')])
        g=self.game(board=(),hand=('generate',),context=GenerationContext('target','experimental'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'generate')
        self.assertEqual(before,g.snapshot())

    def test_choice_only_snapshot_entities_are_rejected(self):
        g=self.game(board=(),hand=('scrap',));row=g.snapshot()
        i=str(g.state.players[1].hand[0]);row['state']['entities'][i]['card_id']='GDB_100a'
        row['information']['players']['1']['known'][i]='GDB_100a'
        row['state_hash']=canonical_hash({k:v for k,v in row.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaisesRegex(SnapshotError,'Choice-only'):Game.from_snapshot(row,self.r)

    def test_choice_only_definition_rejects_playable_behavior_and_collectibility(self):
        for kwargs in ({'choice_only':1},{'choice_only':True,'on_play':'x'},
                       {'choice_only':True,'metadata':CardMetadata(True,(CardClass.NEUTRAL,),None)}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('bad','bad',CardType.SPELL,**kwargs))

    def test_generated_cost_filter_mismatch_rolls_back(self):
        self.spell('bad',lambda c:[AddToHand(1,'plain',c.source_id,cost=CostSpec(card_types=(CardType.SPELL,),set_to=1))])
        g=self.game(board=(),hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'bad')
        self.assertEqual(before,g.snapshot())

    def test_public_continuation_payloads_are_strict(self):
        for callback in (lambda:InvokeBehavior('',1,1),lambda:InvokeBehavior('x',True,1),
            lambda:SplitDamage(2,True),lambda:SplitDamage(2,1,include_hero=1),
            lambda:AddToHand(1,'plain',cost=1),lambda:LaunchStarshipEffect(1,1,followup=[])):
            with self.assertRaises(ValueError):callback()

    def test_real_example_restores_all_protocols_via_player_commands(self):
        from examples.exodar_protocols import run
        snapshot,branches=run()
        self.assertEqual(snapshot['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(set(branches),{'GDB_100a','GDB_100b','GDB_100c'})
        self.assertTrue(all(len(g.history)==4 for g in branches.values()))

    def test_split_damage_skips_inactive_construction(self):
        self.spell('shoot',lambda c:[Destroy(c.state.players[2].board[0]),
            SplitDamage(2,3,c.source_id,include_hero=False)])
        g=self.game(board=(),hand=('shoot',),enemy=('SC_403a',));self.cast(g,'shoot')
        ship=construction(g.state,2);self.assertEqual(ship.health,1);self.assertFalse(ship.active)

    def test_choice_only_direct_generation_rolls_back(self):
        self.spell('generate',lambda c:[AddToHand(1,'GDB_100a',c.source_id)])
        g=self.game(board=(),hand=('generate',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'generate')
        self.assertEqual(before,g.snapshot())


if __name__=='__main__':unittest.main()
