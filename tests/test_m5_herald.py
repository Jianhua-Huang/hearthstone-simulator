"""Herald effect sources, frozen ranks and shared lifecycle/replay contracts."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AppendageSpec, CardDefinition, CardType, EndTurn, Game, Herald,
    Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SummonStoredCard, TriggerSpec, Zone, herald_count, herald_multiplier, herald_rank)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GrantKeyword, RequestChoice, ReturnToHand, Summon, Transform, TriggerDeathrattles,
    ReplaceHero, InvokeBehavior, EquipWeapon)
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference


class HeraldTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('dh','DH',CardType.HERO,health=30,
            metadata=CardMetadata(False,(CardClass.DEMON_HUNTER,),None)))
        self.r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=2,health=5))
        self.spell('herald',lambda c:[Herald(c.player_id,c.source_id)])
        self.spell('twice',lambda c:[Herald(c.player_id,c.source_id),Herald(c.player_id,c.source_id)])
        self.spell('four',lambda c:[Herald(c.player_id,c.source_id) for _ in range(4)])
        self.spell('kill',lambda c:[Destroy(c.target_id)],requires_target=True)
        self.spell('silence',lambda c: self.silence(c),requires_target=True)
        self.spell('bounce',lambda c:[ReturnToHand(c.target_id)],requires_target=True)
        self.spell('copy',lambda c:[CopyMinion(c.target_id,1)],requires_target=True)
        self.spell('base',lambda c:[CopyMinion(c.target_id,1,mode='base')],requires_target=True)
        self.spell('steal',lambda c:[ChangeControl(c.target_id,2)],requires_target=True)
        self.spell('dhform',lambda c:[ReplaceHero(c.player_id,'dh')])
        self.spell('trigger',lambda c:[TriggerDeathrattles(c.target_id)],requires_target=True)

    @staticmethod
    def silence(c):
        from hs_sim.engine.effects import Silence
        return [Silence(c.target_id)]

    def spell(self,name,fn,**fields):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**fields))

    def watcher(self,name,fn,event='minion_summoned'):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.MINION,health=8,
            triggers=(TriggerSpec(event,name),)))

    def game(self,hand=(),board=(),enemy_hand=(),enemy_board=(),hero='HERO_01',enemy_hero='HERO_01',**kw):
        defaults=dict(deck=('plain',)*10,max_mana=10,mana=10);defaults.update(kw)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,**defaults),
            PlayerSetup(enemy_hero,hand=enemy_hand,board=enemy_board,deck=('plain',)*10,max_mana=10,mana=10)),seed=71),self.r)

    def find(self,g,card,p=None,zone='hand'):
        p=g.state.active_player if p is None else p
        return next(i for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id==card)

    def play(self,g,card,target=None,position=None):
        i=self.find(g,card);g.apply(PlayCard(g.state.active_player,i,target,position));return i

    def last(self,g):return g.state.entities[g.state.herald_history[-1].soldier_id]
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]

    def check(self,g):
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        self.assertEqual(restored.snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_rank_thresholds_cap_strength_but_not_use_count(self):
        self.assertEqual([herald_rank(n) for n in range(9)],[0,0,1,1,2,2,2,2,2])
        for value in (-1,True,1.2):
            with self.assertRaises(ValueError):herald_rank(value)

    def test_first_two_soldiers_base_next_two_double_then_quadruple(self):
        g=self.game(hand=('herald',)*7)
        for _ in range(7):self.play(g,'herald')
        records=g.state.herald_history
        self.assertEqual([x.rank for x in records],[0,0,1,1,2,2,2])
        self.assertEqual([g.state.entities[x.soldier_id].attack for x in records],[2,2,4,4,8,8,8])
        self.assertEqual(herald_count(g.state,1),7);self.assertEqual(herald_multiplier(g.state,1),4);self.check(g)

    def test_full_board_still_records_and_upgrades_future_summons(self):
        g=self.game(hand=('four','kill','herald'),board=('plain',)*7)
        self.play(g,'four');self.assertTrue(all(x.soldier_id is None for x in g.state.herald_history))
        self.play(g,'kill',g.state.players[1].board[0]);self.play(g,'herald')
        self.assertEqual((self.last(g).attack,self.last(g).health),(8,4));self.check(g)

    def test_each_player_has_separate_history(self):
        g=self.game(hand=('twice',),enemy_hand=('herald',))
        self.play(g,'twice');g.apply(EndTurn(1));self.play(g,'herald')
        self.assertEqual((herald_count(g.state,1),herald_count(g.state,2)),(2,1))
        self.assertEqual(self.last(g).attack,2);self.check(g)

    def test_soldier_type_uses_current_hero_not_source_card_class(self):
        g=self.game(hand=('CATA_525',));self.play(g,'CATA_525')
        self.assertEqual(self.last(g).card_id,'CATA_580t');self.check(g)

    def test_current_class_change_retains_count(self):
        g=self.game(hand=('twice','dhform','herald'))
        for c in ('twice','dhform','herald'):self.play(g,c)
        self.assertEqual(self.last(g).card_id,'CATA_525t');self.assertEqual(self.last(g).attack,4)
        self.assertEqual(self.hero(g).attack,2);self.check(g)

    def test_unimplemented_class_fails_transactionally(self):
        g=self.game(hand=('herald',),hero='HERO_08');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Herald Soldier'):self.play(g,'herald')
        self.assertEqual(g.snapshot(),before)

    def test_soldier_does_not_require_colossal_in_deck(self):
        g=self.game(hand=('herald',));self.play(g,'herald')
        self.assertEqual(self.last(g).card_id,'CATA_580t');self.assertEqual(len(g.state.play_history),1)
        self.assertEqual(len(g.state.colossal_history),0);self.check(g)

    def test_keyword_alone_does_not_herald(self):
        self.r.register_card(CardDefinition('marked','Marked',CardType.MINION,health=1,keywords=(Keyword.HERALD,)))
        g=self.game(hand=('marked',));self.play(g,'marked');self.assertEqual(herald_count(g.state,1),0)

    def test_summoning_battlecry_source_does_not_herald(self):
        self.spell('summoner',lambda c:[Summon(c.player_id,'CATA_722')])
        g=self.game(hand=('summoner',));self.play(g,'summoner');self.assertEqual(herald_count(g.state,1),0)

    def test_deathrattle_counts_when_it_resolves_not_on_play(self):
        self.r.register_behavior('dying',lambda c:[Herald(c.player_id,c.source_id)])
        self.r.register_card(CardDefinition('dr','DR',CardType.MINION,health=1,deathrattle='dying',keywords=(Keyword.HERALD,)))
        g=self.game(hand=('dr','kill'));i=self.play(g,'dr');self.assertEqual(herald_count(g.state,1),0)
        self.play(g,'kill',i);self.assertEqual(herald_count(g.state,1),1);self.check(g)

    def test_enemy_turn_death_uses_death_controller(self):
        self.r.register_behavior('dying',lambda c:[Herald(c.player_id,c.source_id)])
        self.r.register_card(CardDefinition('dr','DR',CardType.MINION,health=1,deathrattle='dying'))
        g=self.game(board=('dr',),enemy_hand=('kill',));i=g.state.players[1].board[0]
        g.apply(EndTurn(1));self.play(g,'kill',i)
        self.assertEqual((herald_count(g.state,1),herald_count(g.state,2)),(1,0));self.check(g)

    def test_weapon_battlecry_heralds_but_equip_effect_does_not(self):
        self.spell('equip',lambda c:[EquipWeapon(c.player_id,'CATA_580')])
        g=self.game(hand=('equip','CATA_580'));self.play(g,'equip');self.assertEqual(herald_count(g.state,1),0)
        self.play(g,'CATA_580');self.assertEqual(herald_count(g.state,1),1)
        self.assertNotIn(Keyword.HERALD,self.hero(g).keywords);self.check(g)

    def test_ravager_grants_rush_only_to_its_soldier(self):
        g=self.game(hand=('CATA_160',),board=('plain','plain'));source=self.play(g,'CATA_160',position=0)
        self.assertEqual(g.state.players[1].board[1],self.last(g).id)
        self.assertIn(Keyword.RUSH,self.last(g).keywords);self.assertNotIn(Keyword.RUSH,g.state.entities[source].keywords);self.check(g)

    def test_ravager_with_last_board_slot_still_counts(self):
        g=self.game(hand=('CATA_160',),board=('plain',)*6);self.play(g,'CATA_160')
        self.assertIsNone(g.state.herald_history[0].soldier_id);self.assertEqual(herald_count(g.state,1),1);self.check(g)

    def test_colossal_body_is_not_scaled_but_new_appendages_are(self):
        g=self.game(hand=('four','CATA_150'));self.play(g,'four');body=self.play(g,'CATA_150')
        self.assertEqual((g.state.entities[body].attack,g.state.entities[body].health),(8,8))
        limbs=g.state.colossal_history[0].limbs
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health) for i in limbs],[(8,4),(8,4)]);self.check(g)

    def test_old_colossal_appendages_are_not_scaled(self):
        g=self.game(hand=('four','TSC_216'));self.play(g,'four');self.play(g,'TSC_216')
        limb=g.state.entities[g.state.colossal_history[0].limbs[0]]
        self.assertEqual((limb.attack,limb.health,limb.herald_rank),(1,4,None));self.check(g)

    def test_direct_summon_of_appendage_uses_current_progress(self):
        self.spell('limb',lambda c:[Summon(1,'CATA_150t')])
        g=self.game(hand=('twice','limb'));self.play(g,'twice');self.play(g,'limb')
        limb=g.state.entities[g.state.players[1].board[-1]];self.assertEqual((limb.attack,limb.health),(4,2));self.check(g)

    def test_stored_limb_gets_rank_when_entering_not_when_acquired(self):
        self.spell('stored',lambda c:[SummonStoredCard(CardReference.capture(next(c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id=='CATA_150t')),1)])
        g=self.game(hand=('CATA_150t','twice','stored'));i=self.find(g,'CATA_150t')
        self.play(g,'twice');self.assertIsNone(g.state.entities[i].herald_rank);self.play(g,'stored')
        self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(4,2));self.check(g)

    def test_ragnaros_end_triggers_limb_deathrattles_without_killing(self):
        g=self.game(hand=('CATA_150',));self.play(g,'CATA_150');g.apply(EndTurn(1))
        self.assertEqual(self.hero(g,2).health,26);self.assertEqual(g.state.death_history,[])
        self.assertEqual(len(g.state.players[1].board),3);self.check(g)

    def test_scaled_deathrattle_uses_frozen_dead_instance(self):
        g=self.game(hand=('four','herald','kill'));self.play(g,'four');self.play(g,'herald');i=self.last(g).id
        self.play(g,'kill',i);self.assertEqual(self.hero(g,2).health,22)
        self.assertEqual(g.state.death_history[-1].herald_rank,2);self.check(g)

    def test_old_soldier_is_not_retroactively_upgraded(self):
        g=self.game(hand=('herald','four','kill'));self.play(g,'herald');i=self.last(g).id
        self.play(g,'four');self.play(g,'kill',i);self.assertEqual(self.hero(g,2).health,28);self.check(g)

    def test_demon_hunter_summon_gains_scaled_temporary_attack(self):
        g=self.game(hand=('twice','CATA_525'),hero='dh');self.play(g,'twice');self.play(g,'CATA_525')
        self.assertEqual(self.hero(g).attack,4);g.apply(EndTurn(1));self.assertEqual(self.hero(g).attack,0);self.check(g)

    def test_fel_infusion_lifesteal_expires(self):
        g=self.game(hand=('CATA_530',),hero='dh');self.play(g,'CATA_530')
        self.assertEqual(self.hero(g).attack,1);self.assertIn(Keyword.LIFESTEAL,self.hero(g).keywords)
        g.apply(EndTurn(1));self.assertNotIn(Keyword.LIFESTEAL,self.hero(g).keywords);self.check(g)

    def test_countered_spell_does_not_herald(self):
        g=self.game(hand=('CATA_530',),enemy_hand=('EX1_287',),hero='dh')
        g.apply(EndTurn(1));self.play(g,'EX1_287');g.apply(EndTurn(2));self.play(g,'CATA_530')
        self.assertEqual(herald_count(g.state,1),0);self.assertEqual(self.hero(g).attack,0);self.check(g)

    def test_current_copy_preserves_old_rank_instead_of_reapplying(self):
        g=self.game(hand=('herald','twice','copy'));self.play(g,'herald');i=self.last(g).id
        self.play(g,'twice');self.play(g,'copy',i);copied=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((copied.attack,copied.health,copied.herald_rank),(2,1,0));self.check(g)

    def test_base_copy_uses_new_controller_progress(self):
        g=self.game(hand=('herald','twice','base'));self.play(g,'herald');i=self.last(g).id
        self.play(g,'twice');self.play(g,'base',i);copied=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual((copied.attack,copied.health,copied.herald_rank),(4,2,1));self.check(g)

    def test_silence_removes_stats_and_deathrattle_but_not_player_count(self):
        g=self.game(hand=('twice','herald','silence','kill'));self.play(g,'twice');self.play(g,'herald');i=self.last(g).id
        self.play(g,'silence',i);self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(2,1))
        self.play(g,'kill',i);self.assertEqual(self.hero(g,2).health,30);self.assertEqual(herald_count(g.state,1),3);self.check(g)

    def test_current_copy_of_silenced_soldier_does_not_regain_buff(self):
        g=self.game(hand=('twice','herald','silence','copy'));self.play(g,'twice');self.play(g,'herald');i=self.last(g).id
        self.play(g,'silence',i);self.play(g,'copy',i);e=g.state.entities[g.state.players[1].board[-1]]
        self.assertTrue(e.silenced);self.assertEqual((e.attack,e.health),(2,1));self.check(g)

    def test_bounce_resets_capture_and_replay_uses_new_rank(self):
        g=self.game(hand=('herald','twice','bounce'));self.play(g,'herald');i=self.last(g).id
        self.play(g,'twice');self.play(g,'bounce',i);self.assertIsNone(g.state.entities[i].herald_rank)
        self.play(g,'CATA_580t');self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),(4,2));self.check(g)

    def test_control_change_preserves_rank_and_does_not_herald(self):
        g=self.game(hand=('twice','herald','steal'));self.play(g,'twice');self.play(g,'herald');i=self.last(g).id
        self.play(g,'steal',i);self.assertEqual((g.state.entities[i].controller,g.state.entities[i].attack),(2,4))
        self.assertEqual(herald_count(g.state,2),0);self.check(g)

    def test_transform_captures_rank_and_removes_it_on_plain_form(self):
        self.spell('form',lambda c:[Transform(c.target_id,'CATA_150t')],requires_target=True)
        self.spell('unform',lambda c:[Transform(c.target_id,'plain')],requires_target=True)
        g=self.game(hand=('twice','form','unform'),board=('plain',));i=g.state.players[1].board[0]
        self.play(g,'twice');self.play(g,'form',i);self.assertEqual(g.state.entities[i].attack,4)
        self.play(g,'unform',i);self.assertIsNone(g.state.entities[i].herald_rank);self.check(g)

    def test_reborn_uses_new_rank_and_one_remaining_health(self):
        self.spell('reborn',lambda c:[GrantKeyword(c.target_id,Keyword.REBORN)],requires_target=True)
        g=self.game(hand=('herald','twice','reborn','kill'));self.play(g,'herald');i=self.last(g).id
        self.play(g,'twice');self.play(g,'reborn',i);self.play(g,'kill',i)
        child=next(e for e in g.state.entities.values() if e.origin_entity_id==i)
        self.assertEqual((child.attack,child.health,child.max_health,child.herald_rank),(4,1,2,1));self.check(g)

    def test_soldier_reaction_choice_restores_counter_and_followup(self):
        self.watcher('pause',lambda c:[RequestChoice(1,(ChoiceOption('ok','OK'),),c.source_id)] if c.state.entities[c.target_id].card_id=='CATA_580t' else [])
        g=self.game(hand=('CATA_160',),board=('pause',));self.play(g,'CATA_160')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(herald_count(g.state,1),1);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            while match.state.pending_choice:match.apply(SelectChoice(1,match.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertIn(Keyword.RUSH,self.last(g).keywords);self.check(g)

    def test_nested_summon_trigger_has_independent_use(self):
        self.watcher('nest',lambda c:[Herald(1,c.source_id)] if c.state.entities[c.target_id].card_id=='CATA_580t' and herald_count(c.state,1)<2 else [])
        g=self.game(hand=('herald',),board=('nest',));self.play(g,'herald')
        self.assertEqual(herald_count(g.state,1),2);self.assertEqual([r.rank for r in g.state.herald_history],[0,0]);self.check(g)

    def test_failure_rolls_back_count_entities_rng_and_history(self):
        def fail(c):raise ResolutionError('Herald reaction failed')
        self.watcher('fail',fail);g=self.game(hand=('herald',),board=('fail',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'herald')
        self.assertEqual(g.snapshot(),before)

    def test_terminal_stops_remaining_herald_effects(self):
        self.watcher('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.game(hand=('four',),board=('lethal',));self.play(g,'four')
        self.assertEqual(g.state.status,'finished');self.assertEqual(herald_count(g.state,1),1);self.check(g)

    def test_public_count_does_not_expose_hidden_hand(self):
        g=self.game(hand=('herald',),enemy_hand=('CATA_150t',));self.play(g,'herald')
        for viewer in (1,2):
            observation=g.observe(viewer);self.assertEqual(observation['players'][0]['herald_count'],1)
            self.assertNotIn('herald_history',json.dumps(observation))
        self.assertNotIn('herald_rank',g.observe(1)['players'][1]['hand'][0]);self.check(g)

    @staticmethod
    def rehash(data):
        data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_rejects_tampered_history_after_digest_recomputed(self):
        g=self.game(hand=('herald',));self.play(g,'herald')
        for field,value in (('id',2),('count_before',2),('rank',1),('hero_class','mage'),('soldier_card_id','plain'),('source_id',99999),('soldier_id',1),('turn',99)):
            data=g.snapshot();data['state']['herald_history'][0][field]=value;self.rehash(data)
            with self.subTest(field=field),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_rejects_invalid_instance_rank(self):
        g=self.game(hand=('herald',));self.play(g,'herald')
        for value in (None,True,-1,3,'1'):
            data=g.snapshot();data['state']['entities'][str(self.last(g).id)]['herald_rank']=value;self.rehash(data)
            with self.subTest(value=value),self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_rejects_prior_snapshot_schema(self):
        g=self.game();data=g.snapshot();data['schema_version']=33
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_duplicate_soldier_class_mapping_rejected(self):
        self.r.register_card(CardDefinition('duplicate','Duplicate',CardType.MINION,health=1,herald_scaling=True,herald_soldier_for=CardClass.WARRIOR))
        with self.assertRaisesRegex(ValueError,'Multiple Herald'):self.r.freeze()

    def test_invalid_scaling_definitions_rejected(self):
        for card in (CardDefinition('x','x',CardType.SPELL,herald_scaling=True),
                     CardDefinition('x','x',CardType.MINION,health=1,herald_scaling=1),
                     CardDefinition('x','x',CardType.MINION,health=1,herald_soldier_for=CardClass.WARRIOR)):
            with self.assertRaises(ValueError):self.r.register_card(card)

    def test_invalid_herald_effect_arguments(self):
        for args in ((True,), (3,), (1,0), (1,None,['rush']), (1,None,(Keyword.RUSH,Keyword.RUSH))):
            with self.assertRaises(ValueError):Herald(*args)

    def test_forced_deathrattle_uses_shared_effect_without_death_or_corpses(self):
        g=self.game(hand=('trigger',),board=('FP1_007',));i=g.state.players[1].board[0]
        self.play(g,'trigger',i);self.assertIn(i,g.state.players[1].board)
        self.assertEqual(g.state.death_history,[]);self.assertEqual(len(g.state.players[1].board),2);self.check(g)

    def test_forced_biopod_uses_captured_current_attack(self):
        self.spell('buff',lambda c:[Buff(c.target_id,4,0)],requires_target=True)
        g=self.game(hand=('buff','trigger'),board=('GDB_111',));i=g.state.players[1].board[0]
        self.play(g,'buff',i);amount=g.state.entities[i].attack;self.play(g,'trigger',i)
        self.assertEqual(self.hero(g,2).health,30-amount);self.assertEqual(g.state.death_history,[]);self.check(g)

    def test_ragnaros_ignores_locations_when_triggering_minions(self):
        g=self.game(board=('CATA_150','CORE_REV_990','CATA_150t'))
        g.apply(EndTurn(1));self.assertEqual(self.hero(g,2).health,28);self.check(g)

    def test_multiple_granted_deathrattles_all_trigger(self):
        from hs_sim.engine.effects import GrantDeathrattle
        self.spell('grantdr',lambda c:[GrantDeathrattle(c.target_id,'m1.loot')],requires_target=True)
        g=self.game(hand=('grantdr','trigger'),board=('CATA_580t',));i=g.state.players[1].board[0]
        self.play(g,'grantdr',i);self.play(g,'trigger',i)
        self.assertEqual(self.hero(g,2).health,28);self.assertEqual(len(g.state.players[1].hand),1);self.check(g)

    def test_deathrattle_after_silence_has_no_effect(self):
        g=self.game(hand=('silence','trigger'),board=('CATA_580t',));i=g.state.players[1].board[0]
        self.play(g,'silence',i);self.play(g,'trigger',i);self.assertEqual(self.hero(g,2).health,30);self.check(g)

    def test_herald_from_location_activation(self):
        from hs_sim.engine import UseLocation
        self.r.register_card(CardDefinition('site','Site',CardType.LOCATION,durability=2,on_use='herald'))
        g=self.game(hand=('site',));i=self.play(g,'site');self.assertEqual(herald_count(g.state,1),0)
        g.apply(UseLocation(1,i));self.assertEqual(herald_count(g.state,1),1);self.check(g)

    def test_paused_queue_can_restore_unexecuted_herald_effect(self):
        self.spell('choosefirst',lambda c:[RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id),Herald(1,c.source_id)])
        g=self.game(hand=('choosefirst',));self.play(g,'choosefirst');self.assertEqual(herald_count(g.state,1),0);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(herald_count(g.state,1),1);self.check(g)

    def test_herald_budget_rollback_includes_counter(self):
        from hs_sim.engine import Ruleset, ResolutionLimitExceeded
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('four',)),PlayerSetup('HERO_01'))),self.r,Ruleset(max_resolution_steps=4))
        before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'four')
        self.assertEqual(g.snapshot(),before)

    def test_real_example_through_fixed_seat_player_commands(self):
        from examples.herald_colossal import run
        g,snapshot=run();self.assertEqual(len(g.history),6);self.assertEqual(snapshot['schema_version'],SNAPSHOT_SCHEMA_VERSION)


if __name__=='__main__':unittest.main()
