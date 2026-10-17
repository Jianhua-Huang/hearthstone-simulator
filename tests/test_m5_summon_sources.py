"""Recruitment and immutable-death resurrection; R-087 source/timing policies."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AppendageSpec, BuffStoredCard, CardDefinition, CardType,
    DeathQuery, EndTurn, Game, HandRepeatSpec, Keyword, PlayCard, PlayerSetup,
    PoolQuery, ResolutionError, Resurrect, ResurrectMinion, Scenario, SelectChoice,
    SnapshotError, SummonFromZone, SummonStats, TriggerSpec, Zone, death_candidates)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy,
    EquipWeapon, GainArmor, GrantDeathrattle, GrantKeyword, RequestChoice, ReturnToHand,
    Silence, Summon, Transform)
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_sources import ContinueResurrection
from hs_sim.engine.zones import AddToDeck, CardReference, DiscardCard, MoveCard


class SummonSourceTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        for name,cost,attack,health,tribes in (('a',2,2,3,()),('b',5,4,5,()),
                ('beast',1,1,1,('beast',)),('all',2,2,3,('all',))):
            self.minion(name,cost=cost,attack=attack,health=health,
                metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes))
        self.spell('nothing',lambda c:[])
        self.spell('kill',lambda c:[Destroy(c.target_id)],requires_target=True)
        self.spell('silence',lambda c:[Silence(c.target_id)],requires_target=True)
        self.spell('buff',lambda c:[Buff(c.target_id,4,5)],requires_target=True)
        self.spell('steal',lambda c:[ChangeControl(c.target_id,1)],requires_target=True)
        self.spell('transform',lambda c:[Transform(c.target_id,'b')],requires_target=True)
        self.spell('recruit',lambda c:[SummonFromZone(c.player_id,source_id=c.source_id)])
        self.spell('revive',lambda c:[Resurrect(c.player_id,source_id=c.source_id)])
    def minion(self,name,**kw):self.r.register_card(CardDefinition(name,name,CardType.MINION,**kw))
    def spell(self,name,fn,**kw):
        self.r.register_behavior(name,fn);self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kw))
    def game(self,hand=(),board=(),deck=('nothing',)*12,enemy=(),enemy_deck=('nothing',)*12):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=deck,max_mana=10,mana=10),
            PlayerSetup('HERO_08',board=enemy,deck=enemy_deck,max_mana=10,mana=10)),seed=201),self.r)
    def entities(self,g,zone='board',player=1):
        s=g.state;return [s.entities[i] for i in getattr(s.players[player],zone)]
    def find(self,g,name,zone='hand',player=1):return next(e.id for e in self.entities(g,zone,player) if e.card_id==name)
    def play(self,g,name,target=None):
        eid=self.find(g,name);g.apply(PlayCard(1,eid,target));return eid
    def kill(self,g,name='a',player=1):return self.play(g,'kill',self.find(g,name,'board',player))
    def ref(self,c,name='a',zone=Zone.DECK):
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[1],zone.value) if c.state.entities[i].card_id==name))
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)

    def test_recruit_moves_original_entity_without_draw_or_payment(self):
        g=self.game(('recruit',),deck=('a',));eid=self.find(g,'a','deck');self.play(g,'recruit')
        self.assertEqual(self.find(g,'a','board'),eid);self.assertFalse(g.state.players[1].deck)
        self.assertEqual(g.state.players[1].mana,10);self.assertEqual(len(g.state.play_history),1)
        self.assertFalse(any(e.kind=='card_drawn' for e in g.events));self.check(g)

    def test_recruit_preserves_stored_buffs(self):
        self.spell('prepare',lambda c:[BuffStoredCard(self.ref(c),3,4)])
        g=self.game(('prepare','recruit'),deck=('a',));self.play(g,'prepare');self.play(g,'recruit')
        self.assertEqual((self.entities(g)[0].attack,self.entities(g)[0].health),(5,7));self.check(g)

    def test_recruit_does_not_execute_battlecry(self):
        self.r.register_behavior('cry',lambda c:[GainArmor(1,5)])
        self.minion('cry',health=2,on_play='cry')
        g=self.game(('recruit',),deck=('cry',));self.play(g,'recruit')
        self.assertEqual(self.armor(g),0);self.check(g)

    def test_hand_source_has_no_echo_hand_play(self):
        self.minion('echo',health=2,keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
        self.spell('hand',lambda c:[SummonFromZone(1,zone=Zone.HAND)])
        g=self.game(('hand','echo'));eid=self.find(g,'echo');self.play(g,'hand')
        self.assertEqual(self.find(g,'echo','board'),eid);self.assertFalse(g.state.players[1].hand);self.check(g)

    def test_cross_player_deck_preserves_owner_and_changes_controller(self):
        self.spell('enemy',lambda c:[SummonFromZone(1,owner_id=2)])
        g=self.game(('enemy',),enemy_deck=('a',));eid=self.find(g,'a','deck',2);self.play(g,'enemy')
        entity=g.state.entities[eid];self.assertEqual((entity.owner,entity.controller,entity.zone),(2,1,Zone.BOARD));self.check(g)

    def test_query_filters_cost_type_and_tribe_including_all(self):
        self.spell('filtered',lambda c:[SummonFromZone(1,count=3,selection='first',
            query=PoolQuery(max_cost=2,tribes_any=('beast',)))])
        g=self.game(('filtered',),deck=('nothing','b','a','all','beast'));self.play(g,'filtered')
        self.assertEqual([e.card_id for e in self.entities(g)],['all','beast'])
        self.assertEqual([e.card_id for e in self.entities(g,'deck')],['nothing','b','a']);self.check(g)

    def test_repeated_recruit_requeries_after_reactions(self):
        self.r.register_behavior('inject',lambda c:[] if c.event.target_id==c.source_id else [AddToDeck(1,'beast',position='top')])
        self.minion('watch',health=2,triggers=(TriggerSpec('minion_summoned','inject'),))
        self.spell('twice',lambda c:[SummonFromZone(1,count=2,selection='first')])
        g=self.game(('twice',),board=('watch',),deck=('a','b'));self.play(g,'twice')
        self.assertEqual([e.card_id for e in self.entities(g)],['watch','a','beast']);self.check(g)

    def test_full_board_keeps_hidden_deck_and_rng_unchanged(self):
        g=self.game(('recruit',),board=('a',)*7,deck=('b','beast'));before=g.snapshot();self.play(g,'recruit')
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state']);self.assertEqual(g.state.players[1].deck,before['state']['players']['1']['deck'])
        self.assertFalse(any(e.kind=='minion_summoned' for e in g.events));self.check(g)

    def test_empty_recruit_does_not_fatigue_or_consume_rng(self):
        g=self.game(('recruit',),deck=());before=g.snapshot()['rng_state'];self.play(g,'recruit')
        self.assertEqual(g.state.players[1].fatigue,0);self.assertEqual(g.snapshot()['rng_state'],before);self.check(g)

    def test_nonmatching_deck_remains_hidden(self):
        g=self.game(('recruit',),deck=('nothing',));self.play(g,'recruit')
        self.assertEqual(len(g.state.players[1].deck),1)
        self.assertFalse(any(e.kind=='card_drawn' for e in g.events));self.check(g)

    def test_numeric_position_cursor_preserves_selection_order(self):
        self.spell('position',lambda c:[SummonFromZone(1,count=2,selection='first',position=0)])
        g=self.game(('position',),board=('beast',),deck=('a','b'));self.play(g,'position')
        self.assertEqual([e.card_id for e in self.entities(g)],['a','b','beast']);self.check(g)

    def test_recruit_choice_restores_remaining_count(self):
        self.r.register_behavior('choose',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',()),),c.source_id)])
        self.minion('watch',health=2,triggers=(TriggerSpec('minion_summoned','choose'),))
        self.spell('twice',lambda c:[SummonFromZone(1,count=2,selection='first')])
        g=self.game(('twice',),board=('watch',),deck=('a','b'));self.play(g,'twice')
        while g.state.pending_choice:
            self.check(g);choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r)
            g.apply(SelectChoice(1,choice.id,('yes',)))
        self.assertEqual([e.card_id for e in self.entities(g)],['watch','a','b']);self.check(g)

    def test_recruit_missing_required_metadata_rolls_back(self):
        self.minion('unknown',health=1)
        self.spell('filter',lambda c:[SummonFromZone(1,query=PoolQuery(tribes_any=('beast',)))])
        g=self.game(('filter',),deck=('unknown',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'filter')
        self.assertEqual(g.snapshot(),before)

    def test_recruit_honors_colossal_shared_capacity(self):
        self.minion('limb',health=1)
        self.minion('big',health=3,keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('limb'),))
        self.spell('many',lambda c:[SummonFromZone(1,count=3,selection='first')])
        g=self.game(('many',),board=('a',)*5,deck=('big','b'));self.play(g,'many')
        self.assertEqual(len(self.entities(g)),7);self.assertEqual([e.card_id for e in self.entities(g,'deck')],['b']);self.check(g)

    def test_resurrection_creates_new_entity_without_consuming_death(self):
        g=self.game(('kill','revive','revive'),board=('a',));old=self.find(g,'a','board');self.kill(g)
        self.play(g,'revive');self.play(g,'revive')
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(len(g.state.resurrection_history),2)
        self.assertEqual(len({e.id for e in self.entities(g)}),2)
        self.assertTrue(all(e.origin_entity_id==old for e in self.entities(g)))
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.check(g)

    def test_resurrection_resets_buffs_damage_and_silence(self):
        self.minion('taunt',attack=2,health=3,keywords=(Keyword.TAUNT,))
        g=self.game(('buff','silence','kill','revive'),board=('taunt',));old=self.find(g,'taunt','board')
        self.play(g,'buff',old);self.play(g,'silence',old);self.play(g,'kill',old);self.play(g,'revive')
        e=self.entities(g)[0];self.assertEqual((e.attack,e.health,e.damage,e.silenced),(2,3,0,False))
        self.assertIn(Keyword.TAUNT,e.keywords);self.check(g)

    def test_resurrection_uses_death_identity_after_transform(self):
        g=self.game(('transform','kill','revive'),board=('a',));old=self.find(g,'a','board')
        self.play(g,'transform',old);self.kill(g,'b');self.play(g,'revive')
        self.assertEqual(self.entities(g)[0].card_id,'b');self.assertEqual(self.entities(g)[0].origin_entity_id,old);self.check(g)

    def test_friendly_death_uses_controller_not_original_owner(self):
        g=self.game(('steal','kill','revive'),enemy=('a',));old=self.find(g,'a','board',2)
        self.play(g,'steal',old);self.play(g,'kill',old);self.play(g,'revive')
        self.assertEqual(g.state.death_history[0].owner,2)
        self.assertEqual((self.entities(g)[0].owner,self.entities(g)[0].controller),(1,1));self.check(g)

    def test_enemy_or_both_history_is_explicit(self):
        self.spell('enemy_revive',lambda c:[Resurrect(1,query=DeathQuery(side='enemy'))])
        g=self.game(('kill','revive','enemy_revive'),enemy=('b',));self.kill(g,'b',2)
        self.play(g,'revive');self.assertFalse(self.entities(g));self.play(g,'enemy_revive')
        self.assertEqual(self.entities(g)[0].card_id,'b')
        self.assertEqual(len(death_candidates(g.state,self.r,1,DeathQuery(side='both'))),1);self.check(g)

    def test_discard_is_not_a_minion_death(self):
        self.spell('discard',lambda c:[DiscardCard(self.ref(c,zone=Zone.HAND))])
        g=self.game(('discard','a','revive'));self.play(g,'discard');self.play(g,'revive')
        self.assertFalse(g.state.death_history);self.assertFalse(self.entities(g));self.check(g)

    def test_weapon_destruction_is_excluded(self):
        self.spell('weapon',lambda c:[EquipWeapon(1,'CS2_106')])
        self.spell('break',lambda c:[Destroy(c.state.players[1].weapon_id)])
        g=self.game(('weapon','break','revive'));self.play(g,'weapon');self.play(g,'break');self.play(g,'revive')
        self.assertEqual(len(g.state.death_history),1);self.assertFalse(self.entities(g));self.check(g)

    def test_multiple_deaths_are_separate_candidates(self):
        self.spell('many',lambda c:[Resurrect(1,count=3,selection='first')])
        g=self.game(('kill','kill','many'),board=('a','a'));self.kill(g);self.kill(g);self.play(g,'many')
        self.assertEqual([e.card_id for e in self.entities(g)],['a','a'])
        self.assertEqual([x.death_id for x in g.state.resurrection_history],[1,2]);self.check(g)

    def test_distinct_card_policy_deduplicates_deaths(self):
        self.spell('many',lambda c:[Resurrect(1,count=3,distinct='card',selection='first')])
        g=self.game(('kill','kill','kill','many'),board=('a','a','b'))
        self.kill(g);self.kill(g);self.kill(g,'b');self.play(g,'many')
        self.assertEqual([e.card_id for e in self.entities(g)],['a','b']);self.check(g)

    def test_candidate_pool_is_frozen_before_new_deaths_in_reactions(self):
        self.r.register_behavior('die',lambda c:[Destroy(c.event.target_id)])
        self.minion('watch',health=2,triggers=(TriggerSpec('minion_summoned','die'),))
        self.spell('many',lambda c:[Resurrect(1,count=3,selection='first')])
        g=self.game(('kill','many'),board=('a','watch'));self.kill(g);self.play(g,'many')
        self.assertEqual(len(g.state.resurrection_history),1);self.assertEqual(len(g.state.death_history),2);self.check(g)

    def test_reborn_is_reinstalled_by_resurrection(self):
        self.minion('reborn',attack=2,health=3,keywords=(Keyword.REBORN,))
        g=self.game(('kill','revive'),board=('reborn',));self.kill(g,'reborn');self.play(g,'revive')
        e=self.entities(g)[-1];self.assertEqual(e.health,3);self.assertIn(Keyword.REBORN,e.keywords)
        self.assertEqual(self.entities(g)[0].health,1);self.check(g)

    def test_resurrection_does_not_execute_battlecry(self):
        self.r.register_behavior('cry',lambda c:[GainArmor(1,5)])
        self.minion('cry',health=2,on_play='cry')
        g=self.game(('kill','revive'),board=('cry',));self.kill(g,'cry');self.play(g,'revive')
        self.assertEqual(self.armor(g),0);self.check(g)

    def test_full_board_resurrection_does_not_use_rng_or_history(self):
        self.spell('fill',lambda c:[Summon(1,'a')])
        g=self.game(('kill','fill','revive'),board=('a',)*7);self.kill(g);self.play(g,'fill');before=g.snapshot()['rng_state']
        self.play(g,'revive');self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(g.state.resurrection_history);self.check(g)

    def test_printed_and_death_keyword_filters_are_distinct(self):
        self.spell('taunt',lambda c:[GrantKeyword(c.target_id,Keyword.TAUNT)],requires_target=True)
        g=self.game(('taunt','kill'),board=('a',));eid=self.find(g,'a','board');self.play(g,'taunt',eid);self.kill(g)
        query=DeathQuery(cards=PoolQuery(keywords_all=(Keyword.TAUNT,)))
        self.assertFalse(death_candidates(g.state,self.r,1,query))
        self.assertEqual(len(death_candidates(g.state,self.r,1,replace(query,keywords_at_death=True))),1);self.check(g)

    def test_deathrattle_filter_uses_captured_ability(self):
        self.r.register_behavior('rattle',lambda c:[])
        self.spell('grant',lambda c:[GrantDeathrattle(c.target_id,'rattle')],requires_target=True)
        g=self.game(('grant','kill','kill'),board=('a','b'));self.play(g,'grant',self.find(g,'a','board'))
        self.kill(g);self.kill(g,'b')
        self.assertEqual([d.card_id for d in death_candidates(g.state,self.r,1,DeathQuery(has_deathrattle=True))],['a'])
        self.assertEqual([d.card_id for d in death_candidates(g.state,self.r,1,DeathQuery(has_deathrattle=False))],['b']);self.check(g)

    def test_query_turn_cost_tribe_and_source_exclusion(self):
        g=self.game(('kill','kill','kill'),board=('a','b','beast'))
        self.kill(g);g.apply(EndTurn(1));g.apply(EndTurn(2));self.kill(g,'b');self.kill(g,'beast')
        query=DeathQuery(min_turn=3,cards=PoolQuery(max_cost=2,tribes_any=('beast',)))
        self.assertEqual([d.card_id for d in death_candidates(g.state,self.r,1,query)],['beast'])
        eid=g.state.death_history[-1].entity_id
        self.assertFalse(death_candidates(g.state,self.r,1,replace(query,exclude_entity_ids=(eid,))))
        self.assertEqual(len(death_candidates(g.state,self.r,1,DeathQuery(max_turn=1))),1);self.check(g)

    def test_direct_selected_death_and_position(self):
        self.spell('selected',lambda c:[ResurrectMinion(1,1,position=0,source_id=c.source_id)])
        g=self.game(('kill','selected'),board=('a','b'));self.kill(g);self.play(g,'selected')
        self.assertEqual([e.card_id for e in self.entities(g)],['a','b']);self.check(g)

    def test_choose_specific_death_restores(self):
        self.spell('choose',lambda c:[RequestChoice(1,tuple(ChoiceOption(str(d.id),d.card_id,
            (ResurrectMinion(1,d.id,source_id=c.source_id),),card_id=d.card_id)
            for d in death_candidates(c.state,self.r,1)),c.source_id)])
        g=self.game(('kill','kill','choose'),board=('a','b'));self.kill(g);self.kill(g,'b');self.play(g,'choose');self.check(g)
        choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,choice.id,('2',)))
        self.assertEqual([e.card_id for e in self.entities(g)],['b']);self.check(g)

    def test_batch_resurrection_restores_between_summons(self):
        self.r.register_behavior('choice',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',()),),c.source_id)])
        self.minion('watch',health=2,triggers=(TriggerSpec('minion_summoned','choice'),))
        self.spell('many',lambda c:[Resurrect(1,count=2)])
        g=self.game(('kill','kill','many'),board=('a','b','watch'));self.kill(g);self.kill(g,'b');self.play(g,'many')
        while g.state.pending_choice:
            self.check(g);choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r)
            g.apply(SelectChoice(1,choice.id,('yes',)))
        self.assertEqual(len(g.state.resurrection_history),2);self.check(g)

    def test_colossal_resurrection_expands_and_records_origin(self):
        self.minion('limb',health=1)
        self.minion('big',health=3,keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('limb'),))
        g=self.game(('kill','revive'),board=('big',));self.kill(g,'big');self.play(g,'revive')
        self.assertEqual([e.card_id for e in self.entities(g)],['big','limb'])
        record=g.state.colossal_history[-1];self.assertEqual((record.reason,record.death_id),('resurrect',1));self.check(g)

    def test_resurrection_event_is_public_but_internal_record_ids_are_not(self):
        g=self.game(('kill','revive'),board=('a',));self.kill(g);self.play(g,'revive')
        for player in (1,2):
            event=next(e for e in g.player_events(player) if e['kind']=='minion_resurrected')
            self.assertEqual(event['target']['card_id'],'a');self.assertNotIn('death_id',event)
            self.assertNotIn('resurrection_history',g.observe(player))
        self.check(g)

    def test_late_resurrection_reaction_error_rolls_back_rng_and_history(self):
        self.r.register_behavior('bad',lambda c:[GainArmor(1,-1)])
        self.minion('watch',health=2,triggers=(TriggerSpec('minion_summoned','bad'),))
        g=self.game(('kill','revive'),board=('a','watch'));self.kill(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'revive')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_death_reference_rolls_back(self):
        self.spell('bad',lambda c:[ResurrectMinion(1,999)])
        g=self.game(('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_corrupt_resurrection_provenance_is_rejected(self):
        g=self.game(('kill','revive'),board=('a',));self.kill(g);self.play(g,'revive')
        for key,value in (('death_id',999),('entity_id',999),('turn',999),('action',999),('player_id',2),('player_id',3),('source_id',999)):
            snap=g.snapshot();snap['state']['resurrection_history'][0][key]=value
            with self.subTest(key=key),self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_history_remains_valid_after_new_entity_transform_or_control(self):
        g=self.game(('kill','revive','transform'),board=('a',));self.kill(g);self.play(g,'revive')
        self.play(g,'transform',self.find(g,'a','board'));self.assertEqual(len(g.state.resurrection_history),1);self.check(g)

    def test_missing_resurrection_history_field_rejected(self):
        g=self.game();snap=g.snapshot();del snap['state']['resurrection_history']
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_composite_starship_identity_is_rebuilt_without_relaunch(self):
        from hs_sim.engine import LaunchStarship
        from hs_sim.engine.starships import construction
        self.minion('piece',attack=3,health=4,keywords=(Keyword.STARSHIP_PIECE,Keyword.TAUNT))
        self.spell('selected',lambda c:[ResurrectMinion(1,c.state.death_history[-1].id)])
        g=self.game(('kill','kill','selected'),board=('piece',));self.kill(g,'piece')
        ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));self.play(g,'kill',ship.id)
        self.play(g,'selected');e=self.entities(g)[0]
        self.assertEqual((e.components,e.attack,e.health),(('piece',),3,4))
        self.assertFalse(e.starship_building);self.assertEqual(len(g.state.starship_history),1);self.check(g)

    def test_resurrection_captures_current_herald_rank(self):
        from hs_sim.engine import Herald
        self.minion('scaled',attack=2,health=3,herald_scaling=True)
        self.spell('heralds',lambda c:[Herald(1),Herald(1)])
        self.spell('selected',lambda c:[ResurrectMinion(1,1)])
        g=self.game(('kill','heralds','selected'),board=('scaled',));self.kill(g,'scaled')
        self.play(g,'heralds');self.play(g,'selected');e=self.entities(g)[-1]
        self.assertEqual((e.attack,e.health,e.herald_rank),(4,6,1))
        self.assertEqual(g.state.death_history[0].herald_rank,0);self.check(g)

    def test_dormant_minion_restarts_its_entry_dormancy(self):
        from hs_sim.engine import AwakenMinion
        self.minion('sleeper',attack=2,health=3,dormant_turns=2)
        self.spell('wake',lambda c:[AwakenMinion(c.state.players[1].board[0])])
        g=self.game(('wake','kill','revive'),board=('sleeper',));self.play(g,'wake');self.kill(g,'sleeper');self.play(g,'revive')
        self.assertIsNotNone(self.entities(g)[0].dormancy);self.check(g)

    def test_player_port_resurrection_uses_same_public_action(self):
        g=self.game(('kill','revive'),board=('a',));self.kill(g);port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual([e.card_id for e in self.entities(g)],['a']);self.check(g)

    def test_empty_history_does_not_consume_rng(self):
        g=self.game(('revive',));before=g.snapshot()['rng_state'];self.play(g,'revive')
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(g.state.resurrection_history);self.check(g)

    def test_unknown_death_metadata_is_not_silently_filtered_out(self):
        self.minion('unknown',health=2)
        self.spell('filter',lambda c:[Resurrect(1,query=DeathQuery(cards=PoolQuery(tribes_any=('beast',))))])
        g=self.game(('kill','filter'),board=('unknown',));self.kill(g,'unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'filter')
        self.assertEqual(g.snapshot(),before)

    def test_resolution_budget_rejects_oversized_batches(self):
        self.spell('huge_recruit',lambda c:[SummonFromZone(1,count=10**9)])
        self.spell('huge_revive',lambda c:[Resurrect(1,count=10**9)])
        g=self.game(('huge_recruit','huge_revive'))
        for name in ('huge_recruit','huge_revive'):
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,name)
            self.assertEqual(g.snapshot(),before)

    def test_full_board_selected_resurrection_records_failure_only(self):
        self.spell('fill',lambda c:[Summon(1,'a')])
        self.spell('selected',lambda c:[ResurrectMinion(1,1)])
        g=self.game(('kill','fill','selected'),board=('a',)*7);self.kill(g);self.play(g,'fill');self.play(g,'selected')
        self.assertFalse(g.state.resurrection_history)
        self.assertTrue(any(e.kind=='resurrection_failed' for e in g.events));self.check(g)

    def test_duplicate_resurrection_entity_history_rejected(self):
        g=self.game(('kill','revive','revive'),board=('a',));self.kill(g);self.play(g,'revive');self.play(g,'revive')
        snap=g.snapshot();rows=snap['state']['resurrection_history'];rows[1]['entity_id']=rows[0]['entity_id']
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)

    def test_weapon_death_cannot_be_directly_resurrected(self):
        self.spell('weapon',lambda c:[EquipWeapon(1,'CS2_106')])
        self.spell('break',lambda c:[Destroy(c.state.players[1].weapon_id)])
        self.spell('selected',lambda c:[ResurrectMinion(1,1)])
        g=self.game(('weapon','break','selected'));self.play(g,'weapon');self.play(g,'break');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'selected')
        self.assertEqual(g.snapshot(),before)

    def test_stat_override_precedes_summon_trigger_capture(self):
        self.r.register_behavior('observe',lambda c:[GainArmor(1,c.state.entities[c.event.target_id].attack)])
        self.minion('watch',health=2,triggers=(TriggerSpec('minion_summoned','observe'),))
        self.spell('small',lambda c:[Resurrect(1,stats=SummonStats(1,1))])
        g=self.game(('kill','small'),board=('b','watch'));self.kill(g,'b');self.play(g,'small')
        e=self.entities(g)[-1];self.assertEqual((e.attack,e.health),(1,1));self.assertEqual(self.armor(g),1)
        self.assertEqual(g.state.resurrection_history[0].stats,SummonStats(1,1));self.check(g)

    def test_silence_removes_resurrection_size_enchantment(self):
        self.spell('small',lambda c:[Resurrect(1,stats=SummonStats(1,1))])
        g=self.game(('kill','small','silence'),board=('b',));self.kill(g,'b');self.play(g,'small')
        self.play(g,'silence',self.find(g,'b','board'));e=self.entities(g)[0]
        self.assertEqual((e.attack,e.health),(4,5));self.check(g)

    def test_recruit_can_override_size_before_entry(self):
        self.spell('small',lambda c:[SummonFromZone(1,stats=SummonStats(1,1))])
        g=self.game(('small',),deck=('b',));eid=self.find(g,'b','deck');self.play(g,'small')
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(1,1));self.check(g)

    def test_regular_summon_uses_same_stats_and_continuous_auras(self):
        from hs_sim.engine import AuraSpec
        self.minion('aura',health=2,auras=(AuraSpec(attack=1,health=2),))
        self.spell('small',lambda c:[Summon(1,'b',stats=SummonStats(1,1))])
        g=self.game(('small',),board=('aura',));self.play(g,'small')
        e=self.entities(g)[-1];self.assertEqual((e.attack,e.health),(2,3));self.check(g)

    def test_typed_stats_restore_in_resurrection_choice(self):
        self.spell('choose_small',lambda c:[RequestChoice(1,(ChoiceOption('yes','Yes',(
            Resurrect(1,stats=SummonStats(0,1)),)),),c.source_id)])
        g=self.game(('kill','choose_small'),board=('b',));self.kill(g,'b');self.play(g,'choose_small');self.check(g)
        choice=g.state.pending_choice;g=Game.from_snapshot(g.snapshot(),self.r)
        g.apply(SelectChoice(1,choice.id,('yes',)));e=self.entities(g)[0]
        self.assertEqual((e.attack,e.health),(0,1));self.check(g)

    def test_malformed_stored_resurrection_stats_are_rejected(self):
        self.spell('small',lambda c:[Resurrect(1,stats=SummonStats(1,1))])
        g=self.game(('kill','small'),board=('b',));self.kill(g,'b');self.play(g,'small')
        snap=g.snapshot();snap['state']['resurrection_history'][0]['stats']['health']=0
        with self.assertRaises(SnapshotError):Game.from_snapshot(snap,self.r)


class SummonSourceDefinitionTests(unittest.TestCase):
    def test_zone_summon_rejects_invalid_fields(self):
        for kw in ({'zone':Zone.GRAVEYARD},{'zone':'deck'},{'owner_id':True},{'count':-1},
                   {'selection':'guess'},{'position':True},{'query':PoolQuery(kinds=(CardType.SPELL,))}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):SummonFromZone(1,**kw)
    def test_death_query_rejects_ambiguous_or_malformed_filters(self):
        for kw in ({'side':'owner'},{'has_deathrattle':1},{'keywords_at_death':1},
                   {'min_turn':2,'max_turn':1},{'exclude_entity_ids':(1,1)},{'exclude_entity_ids':(True,)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):DeathQuery(**kw)
    def test_resurrection_requires_explicit_selection_policy(self):
        for kw in ({'count':True},{'query':{}},{'distinct':'entity'},{'selection':'all'},{'source_id':0}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):Resurrect(1,**kw)
    def test_direct_resurrection_requires_valid_ids(self):
        for fields in ((1,0),(True,1),(1,True)):
            with self.assertRaises(ValueError):ResurrectMinion(*fields)
    def test_batch_continuation_requires_distinct_typed_deaths(self):
        for ids in ((1,1),(True,),[1]):
            with self.assertRaises(ValueError):ContinueResurrection(Resurrect(1),ids)
    def test_summon_stats_require_valid_nonempty_overrides(self):
        for pair in ((None,None),(-1,1),(1,-1),(True,1),(1,False)):
            with self.assertRaises(ValueError):SummonStats(*pair)
        for effect in (SummonFromZone,Resurrect):
            with self.assertRaises(ValueError):effect(1,stats={})
