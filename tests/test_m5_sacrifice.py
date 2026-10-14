"""Physical sacrifice, incarnation guards, death windows and Warlock Heralds."""
import json
import unittest
from dataclasses import replace

from hs_sim.engine import (AuraSpec, CardDefinition, CardType, DestroyForBuff, EndTurn, Game,
    Herald, Keyword, MinionReference, PlayCard, PlayerSetup, ResolutionError, Ruleset,
    SacrificeAdjacent, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence,
    Summon, Transform, TriggerDeathrattles)
from hs_sim.engine.model import CardClass, CardMetadata, Resource
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import CompleteDestructionBuff
from hs_sim.engine.serialization import canonical_hash


class SacrificeTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('warlock','Warlock',CardType.HERO,health=30,
            metadata=CardMetadata(False,(CardClass.WARLOCK,),None)))
        self.minion('plain',attack=2,health=5)
        self.minion('sleep',health=2,dormant_turns=None)
        self.r.register_behavior('noop',lambda c:[])
        self.r.register_card(CardDefinition('site','Site',CardType.LOCATION,durability=2,on_use='noop'))
        self.spell('herald',lambda c:[Herald(c.player_id,c.source_id)])
        self.spell('kill',lambda c:[Destroy(c.target_id)],requires_target=True)
        self.spell('silence',lambda c:[Silence(c.target_id)],requires_target=True)
        self.spell('copy',lambda c:[CopyMinion(c.target_id,c.player_id)],requires_target=True)
        self.spell('hit_hero',lambda c:[Damage(c.state.players[1].hero_id,10)])
        for n in (2,4):
            self.spell(f'prepare{n}',lambda c,n=n:[*[Herald(c.player_id,c.source_id) for _ in range(n)],
                *[Destroy(i) for i in c.state.players[c.player_id].board]])

    def minion(self,name,**fields):
        self.r.register_card(CardDefinition(name,name,CardType.MINION,**fields))

    def spell(self,name,fn,**fields):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**fields))

    def victim(self,fn,*,name='victim',**fields):
        self.r.register_behavior(name,fn)
        self.minion(name,health=1,deathrattle=name,**fields)

    def watcher(self,fn,event='turn_ended'):
        self.r.register_behavior('watch',fn)
        self.minion('watch',health=4,triggers=(TriggerSpec(event,'watch'),))

    def game(self,board=('CATA_725t','plain'),hand=(),enemy=(),enemy_hand=(),rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('warlock',board=board,hand=hand,deck=('plain',)*12,
            max_mana=10,mana=10),PlayerSetup('HERO_01',board=enemy,hand=enemy_hand,deck=('plain',)*12,
            max_mana=10,mana=10)),seed=73),self.r,rules)

    def play(self,g,card,target=None,position=None):
        p=g.state.active_player
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==card)
        g.apply(PlayCard(p,i,target,position));return i

    def board(self,g,p=1):return [g.state.entities[i] for i in g.state.players[p].board]
    def ref(self,c,index=0):return MinionReference.capture(c.state.entities[c.state.players[c.player_id].board[index]])

    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_owner_end_sacrifices_one_right_neighbor_and_gains_two(self):
        g=self.game();victim=self.board(g)[1].id;g.apply(EndTurn(1))
        self.assertEqual([(e.attack,e.health) for e in self.board(g)],[(3,3)])
        self.assertEqual(g.state.death_history[-1].entity_id,victim)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1);self.check(g)

    def test_enemy_end_does_not_trigger(self):
        g=self.game(board=('plain',),enemy=('CATA_725t','plain'));g.apply(EndTurn(1))
        self.assertEqual([e.card_id for e in self.board(g,2)],['CATA_725t','plain']);self.check(g)

    def test_no_right_neighbor_means_no_reward(self):
        g=self.game(board=('plain','CATA_725t'));g.apply(EndTurn(1))
        self.assertEqual(self.board(g)[1].attack,1);self.assertFalse(g.state.death_history);self.check(g)

    def test_location_blocks_instead_of_skipping_to_a_minion(self):
        g=self.game(board=('CATA_725t','site','plain'));g.apply(EndTurn(1))
        self.assertEqual(self.board(g)[0].attack,1);self.assertEqual(len(self.board(g)),3);self.check(g)

    def test_dormant_minion_blocks_instead_of_skipping(self):
        g=self.game(board=('CATA_725t','sleep','plain'));g.apply(EndTurn(1))
        self.assertEqual(self.board(g)[0].attack,1);self.assertFalse(g.state.death_history);self.check(g)

    def test_left_side_primitive_observes_physical_neighbors(self):
        self.spell('left',lambda c:[SacrificeAdjacent(self.ref(c,1),4,3,'left',c.source_id)])
        g=self.game(board=('plain','plain','plain'),hand=('left',));self.play(g,'left')
        self.assertEqual([(e.attack,e.health) for e in self.board(g)],[(6,8),(2,5)]);self.check(g)

    def test_silenced_soldier_does_not_start_a_sacrifice(self):
        g=self.game(hand=('silence',));self.play(g,'silence',self.board(g)[0].id);g.apply(EndTurn(1))
        self.assertEqual(len(self.board(g)),2);self.assertFalse(g.state.death_history);self.check(g)

    def test_soldier_removed_by_earlier_end_trigger_does_not_consume(self):
        self.watcher(lambda c:[Destroy(c.state.players[1].board[1])] if c.event.player_id==1 else [])
        g=self.game(board=('watch','CATA_725t','plain'));victim=self.board(g)[2].id;g.apply(EndTurn(1))
        self.assertIn(victim,g.state.players[1].board);self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_neighbor_is_selected_after_earlier_trigger_changes_position(self):
        self.watcher(lambda c:[Summon(1,'plain',position=2)] if c.event.player_id==1 else [])
        g=self.game(board=('watch','CATA_725t','plain'));old=self.board(g)[2].id;g.apply(EndTurn(1))
        self.assertIn(old,g.state.players[1].board);self.assertNotEqual(g.state.death_history[-1].entity_id,old);self.check(g)

    def test_consumed_soldier_does_not_execute_captured_end_trigger(self):
        g=self.game(board=('CATA_725t','CATA_725t','plain'));right=self.board(g)[2].id;g.apply(EndTurn(1))
        self.assertEqual([e.card_id for e in self.board(g)],['CATA_725t','plain'])
        self.assertIn(right,g.state.players[1].board);self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_multiple_independent_soldiers_each_resolve_in_order(self):
        g=self.game(board=('CATA_725t','plain','CATA_725t','plain'));g.apply(EndTurn(1))
        self.assertEqual([e.attack for e in self.board(g)],[3,3]);self.assertEqual(len(g.state.death_history),2);self.check(g)

    def test_destroy_bypasses_divine_shield_without_damage_event(self):
        self.minion('shield',health=1,keywords=(Keyword.DIVINE_SHIELD,))
        g=self.game(board=('CATA_725t','shield'));g.apply(EndTurn(1))
        self.assertEqual(self.board(g)[0].attack,3)
        self.assertFalse(any(e.kind in ('damage_dealt','divine_shield_lost') for e in g.events));self.check(g)

    def test_deathrattle_and_reborn_run_before_reward(self):
        self.victim(lambda c:[GainArmor(1,2)],keywords=(Keyword.REBORN,))
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1))
        self.assertEqual([(e.card_id,e.health) for e in self.board(g)],[('CATA_725t',3),('victim',1)])
        kinds=[e.kind for e in g.events]
        self.assertLess(kinds.index('minion_reborn'),kinds.index('stats_changed'));self.check(g)

    def test_victim_deathrattle_kills_beneficiary_no_reward(self):
        self.victim(lambda c:[Damage(c.state.players[1].board[0],10)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1))
        self.assertFalse(self.board(g));self.assertFalse(any(e.kind=='stats_changed' for e in g.events));self.check(g)

    def test_victim_deathrattle_bounces_beneficiary_no_reward(self):
        self.victim(lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(board=('CATA_725t','victim'));source=self.board(g)[0].id;g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[source].zone,g.state.entities[source].attack),(Zone.HAND,1));self.check(g)

    def test_returned_and_resummoned_same_entity_is_not_buffed(self):
        from hs_sim.engine.colossal import SummonStoredCard
        from hs_sim.engine.zones import CardReference
        self.r.register_behavior('resummon',lambda c:[SummonStoredCard(CardReference.capture(c.state.entities[c.state.players[1].hand[0]]),1)])
        self.victim(lambda c:[ReturnToHand(c.state.players[1].board[0]),InvokeBehavior('resummon',c.source_id,1)])
        g=self.game(board=('CATA_725t','victim'));source=self.board(g)[0].id;g.apply(EndTurn(1))
        self.assertEqual((self.board(g)[0].id,self.board(g)[0].attack),(source,1));self.check(g)

    def test_beneficiary_transform_to_same_definition_invalidates_reward(self):
        self.victim(lambda c:[Transform(c.state.players[1].board[0],'CATA_725t')])
        g=self.game(board=('CATA_725t','victim'));old=self.board(g)[0].zone_epoch;g.apply(EndTurn(1))
        self.assertEqual((self.board(g)[0].attack,self.board(g)[0].zone_epoch),(1,old+1));self.check(g)

    def test_beneficiary_transform_away_and_back_invalidates_reward(self):
        self.victim(lambda c:[Transform(c.state.players[1].board[0],'plain'),Transform(c.state.players[1].board[0],'CATA_725t')])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1));self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_control_roundtrip_invalidates_reward(self):
        self.victim(lambda c:[ChangeControl(c.state.players[1].board[0],2),ChangeControl(c.state.players[1].board[0],1)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1));self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_dormant_beneficiary_cannot_receive_reward(self):
        self.victim(lambda c:[MakeDormant(c.state.players[1].board[0],None)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1));self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_reborn_beneficiary_is_a_new_entity_and_not_rewarded(self):
        self.victim(lambda c:[Destroy(c.state.players[1].board[0])])
        self.spell('reborn',lambda c:[GrantKeyword(c.state.players[1].board[0],Keyword.REBORN)])
        g=self.game(board=('CATA_725t','victim'),hand=('reborn',));old=self.board(g)[0].id
        self.play(g,'reborn');g.apply(EndTurn(1))
        self.assertNotEqual(self.board(g)[0].id,old);self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_already_running_effect_keeps_reward_after_beneficiary_silence(self):
        self.victim(lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1))
        self.assertTrue(self.board(g)[0].silenced);self.assertEqual(self.board(g)[0].attack,3);self.check(g)

    def test_reward_is_additive_after_ordinary_buff_reaction(self):
        self.victim(lambda c:[Buff(c.state.players[1].board[0],5,5)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1))
        self.assertEqual((self.board(g)[0].attack,self.board(g)[0].health),(8,8));self.check(g)

    def test_public_destroy_for_buff_can_use_nonadjacent_enemy_victim(self):
        self.spell('reward',lambda c:[DestroyForBuff(MinionReference.capture(c.state.entities[c.state.players[2].board[0]]),self.ref(c),3,4,c.source_id)])
        g=self.game(board=('plain',),enemy=('plain',),hand=('reward',));self.play(g,'reward')
        self.assertFalse(self.board(g,2));self.assertEqual((self.board(g)[0].attack,self.board(g)[0].health),(5,9));self.check(g)

    def test_stale_victim_does_not_reward(self):
        self.spell('reward',lambda c:[ReturnToHand(c.state.players[1].board[1]),DestroyForBuff(self.ref(c,1),self.ref(c),5,5)])
        g=self.game(hand=('reward',));self.play(g,'reward');self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_victim_transform_to_same_definition_is_stale(self):
        self.spell('reward',lambda c:[Transform(c.state.players[1].board[1],'plain'),DestroyForBuff(self.ref(c,1),self.ref(c),5,5)])
        g=self.game(hand=('reward',));self.play(g,'reward')
        self.assertEqual(len(self.board(g)),2);self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_two_destructions_of_same_victim_do_not_reward_twice(self):
        self.spell('reward',lambda c:[DestroyForBuff(self.ref(c,1),self.ref(c),2,2)]*2)
        g=self.game(hand=('reward',));self.play(g,'reward');self.assertEqual(self.board(g)[0].attack,3);self.check(g)

    def test_dead_beneficiary_does_not_consume_live_victim(self):
        self.spell('reward',lambda c:[Destroy(c.state.players[1].board[0]),DestroyForBuff(self.ref(c,1),self.ref(c),5,5)])
        g=self.game(hand=('reward',));self.play(g,'reward');self.assertEqual(self.board(g)[0].card_id,'plain');self.check(g)

    def test_self_destruction_never_rewards_graveyard_entity(self):
        self.spell('reward',lambda c:[DestroyForBuff(self.ref(c),self.ref(c),5,5)])
        g=self.game(board=('plain',),hand=('reward',));source=self.board(g)[0].id;self.play(g,'reward')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[source].attack,2);self.check(g)

    def test_terminal_death_abandons_reward(self):
        self.victim(lambda c:[Damage(c.state.players[2].hero_id,100)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1))
        self.assertEqual(g.state.winner,1);self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_three_herald_ranks_reward_two_four_eight(self):
        for n,base,gain in ((0,1,2),(2,2,4),(4,4,8)):
            with self.subTest(n=n):
                g=self.game(board=('plain',)*7 if n else (),hand=((f'prepare{n}',) if n else ())+('herald','plain'))
                if n:self.play(g,f'prepare{n}')
                self.play(g,'herald');self.play(g,'plain');g.apply(EndTurn(1))
                self.assertEqual((self.board(g)[0].attack,self.board(g)[0].health),(base+gain,base+gain));self.check(g)

    def test_disciple_battlecry_uses_warlock_mapping(self):
        g=self.game(board=(),hand=('CATA_725',));self.play(g,'CATA_725')
        self.assertEqual([e.card_id for e in self.board(g)],['CATA_725','CATA_725t'])
        self.assertEqual(len(g.state.herald_history),1);self.check(g)

    def test_disciple_deathrattle_heals_current_controller(self):
        g=self.game(board=('CATA_725',),hand=('hit_hero','kill'));self.play(g,'hit_hero');self.play(g,'kill',self.board(g)[0].id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,23);self.check(g)

    def test_disciple_active_deathrattle_does_not_herald_or_die(self):
        self.spell('trigger',lambda c:[TriggerDeathrattles(c.state.players[1].board[0])])
        g=self.game(board=('CATA_725',),hand=('hit_hero','trigger'));self.play(g,'hit_hero');self.play(g,'trigger')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,23)
        self.assertFalse(g.state.death_history);self.assertFalse(g.state.herald_history);self.check(g)

    def test_both_independent_arms_use_same_sacrifice_contract(self):
        for cid in ('CATA_726t','CATA_726t1'):
            g=self.game(board=(cid,'plain'));g.apply(EndTurn(1));self.assertEqual(self.board(g)[0].attack,3);self.check(g)

    def test_current_copy_keeps_rank_and_has_independent_growth(self):
        g=self.game(board=(),hand=('herald','copy','plain'));self.play(g,'herald');self.play(g,'copy',self.board(g)[0].id)
        self.play(g,'plain',position=1);g.apply(EndTurn(1))
        self.assertEqual([e.attack for e in self.board(g)],[3,1]);self.check(g)

    def test_pending_deathrattle_choice_restores_reward(self):
        self.victim(lambda c:[RequestChoice(1,(ChoiceOption('ok','OK'),),c.source_id)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1))
        self.assertEqual(self.board(g)[0].attack,1);self.check(g);restored=g.clone()
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.board(g)[0].attack,3);self.check(g)

    def test_choice_transform_invalidates_pending_reward(self):
        self.victim(lambda c:[RequestChoice(1,(ChoiceOption('change','Change',
            (Transform(c.state.players[1].board[0],'CATA_725t'),)),),c.source_id)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1));self.check(g)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('change',)));self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_unknown_reward_source_rolls_back(self):
        self.spell('bad',lambda c:[DestroyForBuff(self.ref(c,1),self.ref(c),2,2,999999)])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_reaction_failure_rolls_back_death_and_reward(self):
        def fail(c):raise ResolutionError('sacrifice reaction failed')
        self.victim(fail);g=self.game(board=('CATA_725t','victim'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'reaction failed'):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),before)

    def test_invalid_reference_and_reward_payloads_rejected(self):
        ref=MinionReference(1,1,'plain',0,1)
        for fields in ({'entity_id':True},{'player_id':3},{'card_id':''},{'zone_epoch':-1},{'entered_order':0}):
            with self.assertRaises(ValueError):replace(ref,**fields)
        for effect in (lambda:SacrificeAdjacent(ref,health=-1),lambda:SacrificeAdjacent(ref,side='far-right'),
                       lambda:SacrificeAdjacent(ref,attack=True),lambda:DestroyForBuff(1,ref),
                       lambda:CompleteDestructionBuff(ref,ref,0)):
            with self.assertRaises(ValueError):effect()

    def test_reference_capture_refuses_hero_and_location(self):
        g=self.game(board=('site',))
        for entity in (self.board(g)[0],g.state.entities[g.state.players[1].hero_id]):
            with self.assertRaises(ValueError):MinionReference.capture(entity)

    def test_future_death_boundary_in_resumed_effect_is_rejected(self):
        self.spell('bad',lambda c:[CompleteDestructionBuff(self.ref(c,1),self.ref(c),c.state.next_death_id+1,2,2)])
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'future death'):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_reward_respects_suspended_starship_death_deferral(self):
        from hs_sim.engine.starships import LaunchStarshipEffect, construction
        self.r.register_behavior('launch_sacrifice',lambda c:[SacrificeAdjacent(MinionReference.capture(c.source),2,2,source_id=c.source_id)])
        self.minion('piece',attack=1,health=1,keywords=(Keyword.STARSHIP_PIECE,),on_launch='launch_sacrifice')
        self.spell('launch',lambda c:[LaunchStarshipEffect(1,construction(c.state,1).id)])
        self.watcher(lambda c:[RequestChoice(1,(ChoiceOption('ok','OK'),),c.source_id)],event='destroyed')
        g=self.game(board=('piece','plain','watch'),hand=('kill','launch'))
        self.play(g,'kill',self.board(g)[0].id)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)))
        ship=construction(g.state,1).id;victim=self.board(g)[1].id
        self.play(g,'launch')
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(g.state.entities[victim].doomed)
        self.assertEqual(g.state.entities[ship].attack,1);self.check(g);restored=g.clone()
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[ship].attack,3)
        self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);self.check(g)

    def test_malformed_suspended_reference_rejected_after_rehash(self):
        self.victim(lambda c:[RequestChoice(1,(ChoiceOption('ok','OK'),),c.source_id)])
        g=self.game(board=('CATA_725t','victim'));g.apply(EndTurn(1));data=g.snapshot()
        def tamper(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.MinionReference'):
                    value['fields']['zone_epoch']=True;return True
                return any(tamper(v) for v in value.values())
            if isinstance(value,list):return any(tamper(v) for v in value)
            return False
        self.assertTrue(tamper(data))
        data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_old_schema_35_rejected(self):
        data=self.game().snapshot();data['schema_version']=35
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)


if __name__=='__main__':unittest.main()
