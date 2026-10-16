"""Locations across board semantics, activation, players and persistence."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.model import CostAuraSpec
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, CostSpec, DestroyLocation, EndTurn,
    Game, IllegalAction, Keyword, LaunchStarship, ModifyLocation, PlaceLocation, PlayCard,
    PlayerSetup, RefreshLocation, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TargetSpec, TriggerSpec, UseLocation, Zone)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (AddCostModifier, AddToHand, Buff, ChoiceOption, Damage,
    DamageBatch, Destroy, GainArmor, GrantKeyword, Heal, ModifyCost, RequestChoice,
    ShuffleIntoDeck, Summon)
from hs_sim.engine.model import Resource
from hs_sim.engine.representative import build_registry, TERRAN_LAUNCH_PIECES
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.starships import construction


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.r.register_card(CardDefinition('plain','plain',CardType.MINION,attack=2,health=5))

    def spell(self, name, callback, **fields):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**fields))

    def location(self, name='loc', callback=None, **fields):
        self.r.register_behavior(name, callback or (lambda c: [GainArmor(c.player_id,1)]))
        defaults = dict(durability=3, on_use=name)
        defaults.update(fields)
        self.r.register_card(CardDefinition(name,name,CardType.LOCATION,**defaults))

    def game(self, hand=(), board=(), enemy=(), deck=(), mana=10, enemy_hand=(), seed=31):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01', hand=hand, board=board,deck=deck,max_mana=10,mana=mana),
            PlayerSetup('HERO_01',board=enemy,hand=enemy_hand,max_mana=10,mana=10)),seed=seed),self.r)

    def play(self,g,card,target=None,position=None):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==card)
        return g.apply(PlayCard(1,i,target,position))

    def loc(self,g,player=1):
        return next(i for i in g.state.players[player].board if g.state.entities[i].kind==CardType.LOCATION)

    def cycle(self,g):
        g.apply(EndTurn(1));g.apply(EndTurn(2))

    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def select(self,g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('ok',)))

    def test_placement_pays_mana_and_does_not_activate_or_summon_minion(self):
        g=self.game(hand=('SC_403',),mana=2);result=self.play(g,'SC_403');i=self.loc(g)
        self.assertEqual((g.state.players[1].mana,g.state.entities[i].durability), (0,2))
        self.assertEqual(len(g.state.players[1].board),1)
        self.assertNotIn('minion_summoned',[e.kind for e in result.events])
        self.assertIn('location_placed',[e.kind for e in result.events]);self.check(g)

    def test_immediate_activation_is_free_and_uses_complete_piece_list(self):
        g=self.game(hand=('SC_403',),mana=2);self.play(g,'SC_403');i=self.loc(g)
        g.apply(UseLocation(1,i));self.assertEqual(g.state.players[1].mana,0)
        self.assertEqual((g.state.entities[i].durability,g.state.entities[i].location_cooldown),(1,2))
        self.assertIn(g.state.entities[g.state.players[1].board[-1]].card_id,TERRAN_LAUNCH_PIECES);self.check(g)

    def test_cooldown_skips_next_own_turn_and_opponent_does_not_tick_it(self):
        g=self.game(board=('SC_403',));i=self.loc(g);g.apply(UseLocation(1,i))
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,i))
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[i].location_cooldown,2)
        g.apply(EndTurn(2));self.assertEqual(g.state.entities[i].location_cooldown,1)
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,i))
        self.cycle(g);self.assertEqual(g.state.entities[i].location_cooldown,0)
        g.apply(UseLocation(1,i));self.check(g)

    def test_last_use_destroys_location_without_minion_event_or_corpses(self):
        self.location(durability=1);g=self.game(board=('loc',));i=self.loc(g)
        result=g.apply(UseLocation(1,i))
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0)
        self.assertNotIn('minion_died',[e.kind for e in result.events])
        self.assertIn('location_destroyed',[e.kind for e in result.events])
        self.assertEqual(g.state.death_history[-1].corpse_value,0);self.check(g)

    def test_location_destruction_runs_its_own_deathrattle_once(self):
        self.r.register_behavior('death',lambda c:[GainArmor(c.player_id,4)])
        self.location(durability=1,deathrattle='death');g=self.game(board=('loc',));i=self.loc(g)
        g.apply(UseLocation(1,i))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_two_locations_have_independent_uses_and_cooldowns(self):
        self.location();g=self.game(board=('loc','loc'));a,b=g.state.players[1].board
        g.apply(UseLocation(1,a));g.apply(UseLocation(1,b))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)

    def test_locations_and_minions_share_seven_positions(self):
        g=self.game(board=('plain',)*6,hand=('SC_403','SC_403a'))
        self.play(g,'SC_403',position=2)
        self.assertEqual(self.loc(g),g.state.players[1].board[2])
        with self.assertRaises(IllegalAction):self.play(g,'SC_403a')
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,self.loc(g)))
        self.check(g)

    def test_full_board_prevents_placing_another_location(self):
        g=self.game(board=('plain',)*7,hand=('SC_403',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'SC_403')
        self.assertEqual(before,g.snapshot())

    def test_last_use_frees_a_slot_before_summoning_under_prototype_policy(self):
        self.spell('wear',lambda c:[ModifyLocation(c.state.players[1].board[0],-1)])
        g=self.game(board=('SC_403',)+('plain',)*6,hand=('wear',));i=self.loc(g);self.play(g,'wear')
        g.apply(UseLocation(1,i));self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertIn(g.state.entities[g.state.players[1].board[-1]].card_id,TERRAN_LAUNCH_PIECES);self.check(g)

    def test_position_validation_counts_locations(self):
        g=self.game(board=('SC_403',),hand=('SC_403',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'SC_403',position=2)
        self.assertEqual(g.snapshot(),before)

    def test_no_target_needed_to_place_a_targeted_location(self):
        g=self.game(hand=('CORE_REV_990',));i=g.state.players[1].hand[0]
        self.assertEqual(g.legal_targets(i),())
        self.play(g,'CORE_REV_990')
        self.assertFalse(any(isinstance(a,UseLocation) for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,i))
        self.check(g)

    def test_location_placement_cannot_supply_activation_target(self):
        g=self.game(hand=('CORE_REV_990',),board=('plain',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'CORE_REV_990',g.state.players[1].board[0])
        self.assertEqual(before,g.snapshot())

    def test_sanguine_depths_uses_target_and_ignores_spell_damage(self):
        g=self.game(board=('CORE_REV_990','plain','EX1_012'));i=self.loc(g);target=g.state.players[1].board[1]
        self.assertIn(target,g.legal_targets(i));g.apply(UseLocation(1,i,target))
        self.assertEqual((g.state.entities[target].damage,g.state.entities[target].attack),(1,4));self.check(g)

    def test_sanguine_depths_does_not_buff_a_minion_killed_by_its_damage(self):
        g=self.game(board=('CORE_REV_990','SC_403t'),enemy=('SC_403a',));i=self.loc(g);target=g.state.players[2].board[0]
        g.apply(UseLocation(1,i,target));self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.death_history[0].attack,2);self.check(g)

    def test_location_can_target_elusive_but_not_enemy_stealth(self):
        self.r.register_card(replace(self.r.card('plain'),id='elusive',keywords=(Keyword.ELUSIVE,)))
        g=self.game(board=('CORE_REV_990',),enemy=('elusive','EX1_010'));i=self.loc(g);a,b=g.state.players[2].board
        self.assertIn(a,g.legal_targets(i));self.assertNotIn(b,g.legal_targets(i))
        g.apply(UseLocation(1,i,a));self.check(g)

    def test_location_cannot_be_targeted_as_a_character_or_attacked(self):
        g=self.game(board=('SC_403','plain'),enemy=('SC_403','plain'),hand=('CS2_029',))
        own,enemy=self.loc(g),self.loc(g,2)
        self.assertNotIn(enemy,g.legal_targets(g.state.players[1].hand[0]))
        for a in (Attack(1,own,g.state.players[2].hero_id),Attack(1,g.state.players[1].board[1],enemy)):
            with self.assertRaises(IllegalAction):g.apply(a)

    def test_damage_heal_buff_keywords_and_generic_destroy_cannot_change_location(self):
        self.spell('effects',lambda c:[Damage(c.state.players[1].board[0],100),Heal(c.state.players[1].board[0],100),
            Buff(c.state.players[1].board[0],2,3),GrantKeyword(c.state.players[1].board[0],Keyword.TAUNT),
            Destroy(c.state.players[1].board[0])])
        g=self.game(board=('SC_403',),hand=('effects',));i=self.loc(g);self.play(g,'effects')
        e=g.state.entities[i];self.assertEqual((e.durability,e.health,e.attack,e.zone),(2,0,0,Zone.BOARD));self.check(g)

    def test_aoe_and_health_auras_leave_locations_unchanged(self):
        self.spell('sweep',lambda c:[DamageBatch(tuple(Damage(i,2) for i in c.state.players[1].board))])
        g=self.game(board=('SC_403','CS2_222','plain'),hand=('sweep',));i=self.loc(g)
        self.assertEqual(g.state.entities[i].max_health,0);self.play(g,'sweep')
        self.assertEqual((g.state.entities[i].durability,g.state.entities[i].damage,g.state.entities[i].aura_health),(2,0,0));self.check(g)

    def test_supercapacitor_counts_other_minions_not_locations(self):
        g=self.game(board=('SC_403','plain'),hand=('SC_405',));self.play(g,'SC_405')
        e=g.state.entities[g.state.players[1].board[-1]];self.assertEqual((e.attack,e.health),(2,2));self.check(g)

    def test_location_and_starship_construction_share_capacity_but_stay_distinct(self):
        self.spell('kill',lambda c:[Destroy(c.state.players[1].board[1])])
        g=self.game(board=('SC_403','SC_403a'),hand=('kill',));i=self.loc(g);self.play(g,'kill')
        ship=construction(g.state,1);self.assertIsNotNone(ship);self.assertNotEqual(ship.id,i)
        g.apply(LaunchStarship(1,ship.id));self.assertEqual(g.state.entities[i].durability,2);self.check(g)

    def test_spell_only_cost_modifier_does_not_discount_location(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-2,card_types=(CardType.SPELL,)),uses_remaining=1)])
        g=self.game(hand=('discount','SC_403'));self.play(g,'discount');self.play(g,'SC_403')
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(len(g.state.players[1].cost_modifiers),1)

    def test_general_cost_modifier_discounts_placement_not_activation(self):
        self.spell('discount',lambda c:[AddCostModifier(1,CostSpec(delta=-1),uses_remaining=2)])
        g=self.game(hand=('discount','SC_403'));self.play(g,'discount');self.play(g,'SC_403');g.apply(UseLocation(1,self.loc(g)))
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining,1);self.check(g)

    def test_explicit_location_target_can_destroy_closed_location(self):
        self.spell('demolish',lambda c:[DestroyLocation(c.target_id,c.source_id)],
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.LOCATION,)))
        g=self.game(board=('SC_403',),hand=('demolish',));i=self.loc(g);g.apply(UseLocation(1,i));self.play(g,'demolish',i)
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD);self.check(g)

    def test_refresh_reopens_without_changing_durability(self):
        self.location();self.spell('open',lambda c:[RefreshLocation(c.state.players[1].board[0])])
        g=self.game(board=('loc',),hand=('open',));i=self.loc(g);g.apply(UseLocation(1,i));self.play(g,'open')
        self.assertEqual(g.state.entities[i].durability,2);g.apply(UseLocation(1,i));self.check(g)

    def test_durability_repair_and_zero_destruction(self):
        self.spell('repair',lambda c:[ModifyLocation(c.state.players[1].board[0],3)])
        self.spell('break',lambda c:[ModifyLocation(c.state.players[1].board[0],-5)])
        g=self.game(board=('SC_403',),hand=('repair','break'));i=self.loc(g);self.play(g,'repair')
        self.assertEqual(g.state.entities[i].durability,5);self.play(g,'break');self.assertFalse(g.state.players[1].board);self.check(g)

    def test_closed_location_passive_trigger_remains_active(self):
        self.r.register_behavior('tick',lambda c:[GainArmor(c.player_id,2)])
        self.location(triggers=(TriggerSpec('turn_started','tick'),))
        g=self.game(board=('loc',));i=self.loc(g);g.apply(UseLocation(1,i));self.cycle(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4) # one fatigue damage
        self.assertEqual(g.state.entities[i].location_cooldown,1);self.check(g)

    def test_place_location_effect_has_capacity_and_type_checks(self):
        self.spell('place',lambda c:[PlaceLocation(1,'SC_403',0)])
        g=self.game(hand=('place',),board=('plain',));self.play(g,'place');self.assertEqual(self.loc(g),g.state.players[1].board[0]);self.check(g)
        g=self.game(hand=('place',),board=('plain',)*7);self.play(g,'place');self.assertEqual(len(g.state.players[1].board),7)

    def test_location_generation_draw_and_shuffle_reset_are_supported(self):
        self.spell('create',lambda c:[AddToHand(1,'SC_403')])
        self.spell('shuffle',lambda c:[ShuffleIntoDeck(c.state.players[1].board[0])])
        g=self.game(hand=('create','shuffle'));self.play(g,'create');self.play(g,'SC_403');i=self.loc(g)
        g.apply(UseLocation(1,i));self.play(g,'shuffle')
        self.assertEqual((g.state.entities[i].durability,g.state.entities[i].location_cooldown),(2,0));self.check(g)

    def test_opponent_and_hand_activation_are_rejected_without_side_effects(self):
        g=self.game(hand=('SC_403',),enemy=('SC_403',));before=g.snapshot()
        for i in (g.state.players[1].hand[0],self.loc(g,2),g.state.players[1].hero_id):
            with self.assertRaises(IllegalAction):g.apply(UseLocation(1,i))
        self.assertEqual(before,g.snapshot())

    def test_player_port_uses_public_location_handles_and_logs(self):
        g=self.game(board=('SC_403',));port=g.for_player(1);commands=port.legal_actions()
        command=next(a for a in commands['actions'] if a['type']=='use_location')
        result=port.submit({'revision':commands['revision'],'action':command})
        self.assertTrue(result['accepted']);self.assertIn('location_activated',[e['kind'] for e in result['events']])
        view=result['observation']['players'][0]['board'][0]
        self.assertEqual(view['location'],{'cooldown_remaining':2,'open':False});self.check(g)

    def test_legacy_omniscient_use_rule_rejected_by_player_port(self):
        self.r.register_use_rule('private',lambda c:True)
        self.location(use_rule='private');g=self.game(board=('loc',))
        self.assertEqual(g.for_player(1).legal_actions()['error'],'unsupported_rule')

    def test_player_use_rule_is_shared_by_validation_and_enumeration(self):
        self.r.register_use_rule('no',lambda c:False,visibility='player');self.location(use_rule='no')
        g=self.game(board=('loc',));i=self.loc(g)
        self.assertFalse(any(isinstance(a,UseLocation) for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):g.apply(UseLocation(1,i))

    def test_suspended_activation_retains_durability_and_continuation(self):
        self.location(callback=lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(GainArmor(1,5),)),)),GainArmor(1,2)],durability=1)
        g=self.game(board=('loc',));i=self.loc(g);g.apply(UseLocation(1,i))
        self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        self.select(g);self.select(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_failed_activation_rolls_back_durability_cooldown_rng_and_events(self):
        self.location(callback=lambda c:[Summon(1,'SC_403a'),ModifyLocation(999999,-1,source_id=999999)])
        g=self.game(board=('loc',));before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(UseLocation(1,self.loc(g)))
        self.assertEqual(g.snapshot(),before)

    def test_use_location_wire_round_trip_and_malformed_fields(self):
        a=UseLocation(1,7,3);self.assertEqual(action_from_dict(action_to_dict(a)),a)
        for row in ({'type':'use_location','player_id':1,'entity_id':True},
                    {'type':'use_location','player_id':1,'entity_id':7,'position':0}):
            with self.assertRaises(ValueError):action_from_dict(row)

    def test_corrupt_location_snapshot_type_cooldown_and_combat_state_rejected(self):
        g=self.game(board=('SC_403',));i=self.loc(g)
        for field,value in (('kind','minion'),('location_cooldown',-1),('location_cooldown',True),('base_health',1),('durability',0)):
            row=deepcopy(g.snapshot());row['state']['entities'][str(i)][field]=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(row,self.r)

    def test_location_definitions_reject_character_fields_and_play_callbacks(self):
        for changes in ({'health':1},{'attack':1},{'keywords':(Keyword.TAUNT,)},{'on_play':'m4.starport'}, {'durability':0}):
            with self.assertRaises(ValueError):self.r.register_card(replace(self.r.card('SC_403'),id='bad',**changes))

    def test_location_cost_aura_remains_active_while_closed_and_ends_on_destruction(self):
        self.location(cost_auras=(CostAuraSpec(CostSpec(delta=-1)),),durability=2)
        self.spell('remove',lambda c:[DestroyLocation(c.state.players[1].board[0])])
        g=self.game(board=('loc',),hand=('SC_403','remove'));i=self.loc(g);g.apply(UseLocation(1,i))
        self.assertEqual(g.quote_cost(g.state.players[1].hand[0]).amount,1)
        self.play(g,'remove');self.assertEqual(g.quote_cost(g.state.players[1].hand[0]).amount,2);self.check(g)

    def test_location_is_valid_in_constructed_deck_and_opening(self):
        from hs_sim.engine import CardClass,DeckPolicy,DeckSpec,MatchSetup,validate_deck
        policy=DeckPolicy('locations','t','experimental',('SC_403','SC_401','CORE_REV_990','SC_411'),deck_size=8)
        deck=DeckSpec('HERO_01','HERO_01bp',CardClass.WARRIOR,('SC_403',)*2+('SC_401',)*2+('CORE_REV_990',)*2+('SC_411',)*2)
        self.assertTrue(validate_deck(deck,self.r,policy).valid)
        game=Game.from_decks(MatchSetup((deck,deck),policy,'GAME_005',seed=2),self.r)
        self.assertIsNotNone(game.state.pending_choice)
        self.check(game)

    def test_hidden_enemy_location_face_does_not_change_blind_commands(self):
        kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO)
        self.spell('blind',lambda c:[ModifyCost(c.target_id,CostSpec(delta=-1))],
            targeting=TargetSpec(zones=(Zone.HAND,),kinds=kinds,relation='enemy'))
        a=self.game(hand=('blind',),enemy_hand=('SC_403',));b=self.game(hand=('blind',),enemy_hand=('SC_410',))
        self.assertEqual(a.for_player(1).legal_actions(),b.for_player(1).legal_actions())
        for g in (a,b):
            p=g.for_player(1);actions=p.legal_actions()
            action=next(a for a in actions['actions'] if a['type']=='play_card')
            self.assertTrue(p.submit({'revision':actions['revision'],'action':action})['accepted'])
        self.assertEqual(a.for_player(1).observe(),b.for_player(1).observe())

    def test_real_starport_example_restores_and_replays(self):
        from examples.use_starport import run
        game,snapshot=run();self.assertEqual(len(game.history),11);self.assertEqual(snapshot['schema_version'],SNAPSHOT_SCHEMA_VERSION)

    def test_unsupported_location_health_rule_is_rejected_instead_of_inactive(self):
        from hs_sim.engine import HealthFlow,HealthOp,HealthRule
        from hs_sim.engine.effects import GrantHealthRule
        self.spell('grant',lambda c:[GrantHealthRule(c.state.players[1].board[0],HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2))])
        g=self.game(hand=('grant',),board=('SC_403',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'grant')
        self.assertEqual(before,g.snapshot())


if __name__ == '__main__':unittest.main()
