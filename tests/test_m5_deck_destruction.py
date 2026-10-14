"""Physical deck destruction, successful continuations and live sacrifice replacement."""
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, DeckSacrificeSpec,
    DestroyDeckCard, DestroyDeckMatching, DestroyForBuff, EndTurn, Game, GrantDeckSacrificeAura,
    Herald, Keyword, MinionReference, PlayCard, PlayerSetup, ResolutionError, ResolutionLimitExceeded,
    SacrificeAdjacent, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.model import AbilityInstance, CardClass, CardMetadata, Resource
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard


class DeckDestructionTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('warlock','Warlock fixture',CardType.HERO,health=30,
            metadata=CardMetadata(False,(CardClass.WARLOCK,),None)))
        self.minion('plain',attack=2,health=5)
        self.minion('sleep',health=2,dormant_turns=None)
        self.r.register_behavior('noop',lambda c:[])
        self.r.register_card(CardDefinition('site','Site',CardType.LOCATION,durability=2,on_use='noop'))
        self.spell('pulse',lambda c:[SacrificeAdjacent(self.ref(c),2,2,source_id=c.source_id)])
        for name,fn in (('kill',lambda c:[Destroy(c.target_id)]),('silence',lambda c:[Silence(c.target_id)]),
                       ('bounce',lambda c:[ReturnToHand(c.target_id)]),('steal',lambda c:[ChangeControl(c.target_id,2)]),
                       ('copy',lambda c:[CopyMinion(c.target_id,1)]),('hit',lambda c:[Damage(c.target_id,1)])):
            self.spell(name,fn,requires_target=True)

    def minion(self,name,**kw):self.r.register_card(CardDefinition(name,name,CardType.MINION,**kw))
    def spell(self,name,fn,**kw):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kw))
    def watch(self,fn):
        self.r.register_behavior('watch',fn)
        self.minion('watch',health=4,triggers=(TriggerSpec('card_destroyed_in_deck','watch'),))
    def ref(self,c,index=0):return MinionReference.capture(c.state.entities[c.state.players[1].board[index]])
    def card(self,c,index=0,p=2):return CardReference.capture(c.state.entities[c.state.players[p].deck[index]])
    def game(self,board=('CATA_725t','plain','CATA_726'),hand=(),enemy=(),deck=('plain',)*8,
             enemy_deck=('plain','FP1_007','ULD_205','CS2_029'),enemy_hand=(),rules=None):
        return Game.from_scenario(Scenario((PlayerSetup('warlock',board=board,hand=hand,deck=deck,max_mana=10,mana=10),
            PlayerSetup('HERO_01',board=enemy,hand=enemy_hand,deck=enemy_deck,max_mana=10,mana=10)),seed=83),self.r,rules)
    def play(self,g,name,target=None,position=None):
        p=g.state.active_player
        i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(p,i,target,position));return i
    def board(self,g,p=1):return [g.state.entities[i] for i in g.state.players[p].board]
    def burns(self,g):return [e for e in g.events if e.kind=='card_destroyed_in_deck']
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)

    def test_real_body_has_aura_and_two_distinct_arms(self):
        g=self.game(board=(),hand=('CATA_726',));i=self.play(g,'CATA_726')
        self.assertEqual([(e.card_id,e.attack,e.health) for e in self.board(g)],
            [('CATA_726t',1,1),('CATA_726',6,6),('CATA_726t1',1,1)])
        self.assertEqual(len(g.state.colossal_history[0].limbs),2)
        self.assertTrue(any(a.kind=='deck_sacrifice' for a in g.state.entities[i].abilities));self.check(g)

    def test_summoning_body_does_not_trigger_arm_destruction(self):
        self.spell('summon',lambda c:[Summon(1,'CATA_726')])
        g=self.game(board=(),hand=('summon',));self.play(g,'summon')
        self.assertEqual(self.burns(g),[]);self.assertEqual(len(g.state.players[2].deck),4)
        g.apply(EndTurn(1));self.assertEqual(len(self.burns(g)),2);self.check(g)

    def test_both_arms_destroy_distinct_deck_minions_and_gain(self):
        g=self.game(board=(),hand=('CATA_726',));self.play(g,'CATA_726');g.apply(EndTurn(1))
        self.assertEqual([(e.attack,e.health) for e in self.board(g)],[(3,3),(6,6),(3,3)])
        self.assertEqual(len({e.target_id for e in self.burns(g)}),2)
        self.assertFalse(g.state.death_history);self.check(g)

    def test_soldier_preserves_right_neighbor(self):
        g=self.game(hand=('pulse',));victim=self.board(g)[1].id;self.play(g,'pulse')
        self.assertEqual(g.state.entities[victim].zone,Zone.BOARD)
        self.assertEqual(self.board(g)[0].attack,3);self.assertEqual(len(self.burns(g)),1);self.check(g)

    def test_rightmost_soldier_can_consume_deck_card(self):
        g=self.game(board=('CATA_726','CATA_725t'))
        g.apply(EndTurn(1));self.assertEqual(self.board(g)[1].attack,3);self.assertEqual(len(self.burns(g)),1);self.check(g)

    def test_location_and_dormant_neighbor_do_not_block_active_replacement(self):
        for neighbor in ('site','sleep'):
            g=self.game(board=('CATA_725t',neighbor,'CATA_726'),hand=('pulse',));self.play(g,'pulse')
            self.assertEqual(self.board(g)[0].attack,3);self.assertEqual(len(self.board(g)),3);self.check(g)

    def test_only_deck_minions_are_eligible(self):
        g=self.game(hand=('pulse',),enemy_deck=('CATA_190h','CS2_029','CATA_580','site','FP1_007'))
        self.play(g,'pulse');self.assertEqual(g.state.entities[self.burns(g)[0].target_id].card_id,'FP1_007')
        self.assertEqual(len(g.state.players[2].deck),4);self.check(g)

    def test_no_matching_minion_does_not_fall_back_to_friendly(self):
        for deck in ((),('CS2_029','CATA_190h')):
            g=self.game(hand=('pulse',),enemy_deck=deck);rng=g.snapshot()['rng_state'];self.play(g,'pulse')
            self.assertEqual(self.board(g)[0].attack,1);self.assertEqual(len(self.board(g)),3)
            self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(self.burns(g));self.check(g)

    def test_fewer_enemy_minions_than_arms_no_friendly_fallback(self):
        g=self.game(board=(),hand=('CATA_726',),enemy_deck=('plain',));self.play(g,'CATA_726');g.apply(EndTurn(1))
        self.assertEqual(len(self.board(g)),3);self.assertEqual(len(self.burns(g)),1)
        self.assertEqual([e.attack for e in self.board(g)],[3,6,1]);self.check(g)

    def test_damaged_arm_retains_replacement(self):
        self.spell('fortify',lambda c:[Buff(c.state.players[1].board[0],0,5)])
        g=self.game(board=('CATA_726t','plain','CATA_726'),hand=('fortify','hit','pulse'))
        self.play(g,'fortify');self.play(g,'hit',self.board(g)[0].id);self.play(g,'pulse')
        self.assertEqual(self.board(g)[0].health,7);self.assertEqual(len(self.board(g)),3);self.check(g)

    def test_aura_silence_restores_ordinary_sacrifice(self):
        g=self.game(hand=('silence','pulse'));self.play(g,'silence',self.board(g)[2].id);self.play(g,'pulse')
        self.assertEqual([e.card_id for e in self.board(g)],['CATA_725t','CATA_726']);self.assertFalse(self.burns(g));self.check(g)

    def test_aura_death_and_bounce_remove_replacement(self):
        for action in ('kill','bounce'):
            g=self.game(hand=(action,'pulse'));self.play(g,action,self.board(g)[2].id);self.play(g,'pulse')
            self.assertEqual([e.card_id for e in self.board(g)],['CATA_725t']);self.assertFalse(self.burns(g));self.check(g)

    def test_aura_dormancy_disables_and_waking_restores(self):
        self.spell('sleep_source',lambda c:[MakeDormant(c.state.players[1].board[2],None)])
        self.spell('wake',lambda c:[AwakenMinion(c.state.players[1].board[-1])])
        g=self.game(hand=('sleep_source','pulse','wake','pulse'));self.play(g,'sleep_source');self.play(g,'pulse')
        self.assertFalse(self.burns(g));self.play(g,'wake');self.play(g,'pulse')
        self.assertEqual(len(self.burns(g)),1);self.assertEqual(len(self.board(g)),2);self.check(g)

    def test_aura_control_follows_new_controller(self):
        g=self.game(hand=('steal','pulse'),enemy=('CATA_725t','plain'))
        self.play(g,'steal',self.board(g)[2].id);self.play(g,'pulse');self.assertFalse(self.burns(g))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(len(self.burns(g)),1)
        self.assertEqual(self.board(g,2)[0].attack,3);self.assertEqual(len(self.board(g,2)),3);self.check(g)

    def test_opponent_aura_does_not_help_friendly_soldier(self):
        g=self.game(board=('CATA_725t','plain'),enemy=('CATA_726',),hand=('pulse',));self.play(g,'pulse')
        self.assertEqual(len(self.board(g)),1);self.assertFalse(self.burns(g));self.check(g)

    def test_two_auras_do_not_double_deck_destruction(self):
        g=self.game(board=('CATA_725t','plain','CATA_726','CATA_726'),hand=('pulse',));self.play(g,'pulse')
        self.assertEqual(len(self.burns(g)),1);self.assertEqual(self.board(g)[0].attack,3);self.check(g)

    def test_current_copy_of_aura_is_independent(self):
        g=self.game(hand=('copy','kill','pulse'));old=self.board(g)[2].id;self.play(g,'copy',old);self.play(g,'kill',old)
        self.play(g,'pulse');self.assertEqual(len(self.burns(g)),1);self.check(g)

    def test_transform_aura_to_plain_removes_replacement(self):
        self.spell('change',lambda c:[Transform(c.state.players[1].board[2],'plain')])
        g=self.game(hand=('change','pulse'));self.play(g,'change');self.play(g,'pulse')
        self.assertFalse(self.burns(g));self.assertEqual(len(self.board(g)),2);self.check(g)

    def test_nonmatching_sacrifice_source_not_redirected(self):
        g=self.game(board=('plain','plain','CATA_726'),hand=('pulse',));self.play(g,'pulse')
        self.assertFalse(self.burns(g));self.assertEqual(len(self.board(g)),2);self.check(g)

    def test_plain_destroy_and_explicit_destroy_for_buff_not_redirected(self):
        self.spell('explicit',lambda c:[DestroyForBuff(self.ref(c,1),self.ref(c),2,2,c.source_id)])
        for action in ('kill','explicit'):
            g=self.game(hand=(action,));self.play(g,action,self.board(g)[1].id if action=='kill' else None)
            self.assertFalse(self.burns(g));self.assertEqual(len(self.board(g)),2);self.check(g)

    def test_silenced_soldier_no_end_turn_trigger(self):
        g=self.game(hand=('silence',));self.play(g,'silence',self.board(g)[0].id);g.apply(EndTurn(1))
        self.assertFalse(self.burns(g));self.assertEqual(len(self.board(g)),3);self.check(g)

    def test_rank_four_arms_gain_eight(self):
        self.spell('prepare',lambda c:[*[Herald(1,c.source_id) for _ in range(4)],*[Destroy(i) for i in c.state.players[1].board]])
        g=self.game(board=('plain',)*7,hand=('prepare','CATA_726'));self.play(g,'prepare');self.play(g,'CATA_726')
        g.apply(EndTurn(1));self.assertEqual([e.attack for e in self.board(g)],[12,6,12]);self.check(g)

    def test_aura_removal_between_soldier_triggers_rechecks(self):
        self.watch(lambda c:[Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='CATA_726'))])
        g=self.game(board=('CATA_725t','plain','CATA_725t','plain','CATA_726','watch'));g.apply(EndTurn(1))
        self.assertEqual(len(self.burns(g)),1)
        self.assertEqual([e.card_id for e in self.board(g)],['CATA_725t','plain','CATA_725t','watch']);self.check(g)

    def test_granted_aura_on_named_test_minion_expires(self):
        self.spell('grant',lambda c:[GrantDeckSacrificeAura(c.state.players[1].board[2],DeckSacrificeSpec(('plain',)),c.source_id,c.state.turn)])
        g=self.game(board=('plain','plain','plain'),hand=('grant','pulse'));self.play(g,'grant');self.play(g,'pulse')
        self.assertEqual(len(self.burns(g)),1);g.apply(EndTurn(1))
        self.assertFalse(any(a.kind=='deck_sacrifice' for a in self.board(g)[2].abilities));self.check(g)

    def test_deck_destruction_is_not_death_discard_draw_or_hand_entry(self):
        self.spell('erase',lambda c:[DestroyDeckMatching(2,count=4,source_id=c.source_id)])
        g=self.game(board=(),hand=('erase',),enemy_deck=('FP1_007','ULD_205','GDB_100','CS2_029'))
        self.play(g,'erase');self.assertEqual(len(self.burns(g)),4)
        self.assertFalse(g.state.death_history);self.assertEqual(self.board(g,2),[])
        self.assertEqual(g.state.players[2].resources[Resource.CORPSES],0)
        self.assertFalse(any(e.kind in ('minion_died','card_discarded','card_drawn','minion_reborn','starship_piece_added') for e in g.events))
        self.assertEqual(g.state.players[2].fatigue,0);self.check(g)

    def test_deck_minion_deathrattle_never_fires(self):
        self.r.register_behavior('boom',lambda c:[Damage(c.state.players[1].hero_id,100)])
        self.minion('bomb',health=1,deathrattle='boom',keywords=(Keyword.REBORN,Keyword.STARSHIP_PIECE))
        g=self.game(hand=('pulse',),enemy_deck=('bomb',));self.play(g,'pulse')
        self.assertEqual(g.state.status,'playing');self.assertEqual(len(self.burns(g)),1);self.check(g)

    def test_no_fatigue_when_matching_pool_or_deck_is_empty(self):
        self.spell('erase',lambda c:[DestroyDeckMatching(2,PoolQuery(kinds=(CardType.MINION,)),count=5)])
        for deck in ((),('CS2_029',)):
            g=self.game(hand=('erase',),enemy_deck=deck);self.play(g,'erase')
            self.assertEqual(g.state.players[2].fatigue,0);self.assertFalse(self.burns(g));self.check(g)

    def test_first_matching_card_keeps_order_of_survivors(self):
        self.spell('erase',lambda c:[DestroyDeckMatching(2,PoolQuery(kinds=(CardType.MINION,)),selection='first')])
        g=self.game(hand=('erase',),enemy_deck=('CS2_029','plain','FP1_007','CS2_024'));ids=g.state.players[2].deck
        self.play(g,'erase');self.assertEqual(g.state.players[2].deck,[ids[0],ids[2],ids[3]]);self.check(g)

    def test_repeated_destruction_requeries_after_reaction(self):
        self.spell('erase',lambda c:[DestroyDeckMatching(2,count=2,selection='first')])
        self.watch(lambda c:[AddToDeck(2,'CS2_029',position='top')])
        g=self.game(board=('watch',),hand=('erase',),enemy_deck=('plain','FP1_007'));self.play(g,'erase')
        self.assertEqual([g.state.entities[e.target_id].card_id for e in self.burns(g)],['plain','CS2_029']);self.check(g)

    def test_on_destroy_runs_only_after_successful_physical_removal(self):
        self.spell('erase',lambda c:[DestroyDeckCard(self.card(c),c.source_id,on_destroy=(GainArmor(1,5),)),
            DestroyDeckCard(self.card(c),c.source_id,on_destroy=(GainArmor(1,100),))])
        g=self.game(hand=('erase',));self.play(g,'erase')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5);self.assertEqual(len(self.burns(g)),1);self.check(g)

    def test_captured_card_drawn_before_removal_is_stale(self):
        self.spell('erase',lambda c:[MoveCard(self.card(c),2,Zone.HAND),
            DestroyDeckCard(self.card(c),on_destroy=(GainArmor(1,5),))])
        g=self.game(hand=('erase',));self.play(g,'erase');self.assertFalse(self.burns(g))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.check(g)

    def test_deck_hand_deck_roundtrip_invalidates_old_reference(self):
        self.r.register_behavior('put_back',lambda c:[MoveCard(
            CardReference.capture(c.state.entities[c.state.players[2].hand[0]]),2,Zone.DECK,position='top')])
        self.spell('erase',lambda c:[MoveCard(self.card(c),2,Zone.HAND),
            InvokeBehavior('put_back',c.source_id,1),DestroyDeckCard(self.card(c),on_destroy=(GainArmor(1,5),))])
        g=self.game(hand=('erase',));before=g.state.players[2].deck;self.play(g,'erase')
        self.assertEqual(g.state.players[2].deck,before);self.assertFalse(self.burns(g));self.check(g)

    def test_public_reveal_exposes_only_removed_card(self):
        self.spell('erase',lambda c:[DestroyDeckMatching(2,selection='first',source_id=c.source_id)])
        g=self.game(board=(),hand=('erase',),enemy_deck=('plain','CS2_029','FP1_007'));self.play(g,'erase')
        for viewer in (1,2):
            events=g.player_events(viewer)
            public=json.dumps(events)
            self.assertNotIn('CS2_029',public);self.assertNotIn('FP1_007',public)
            event=next(e for e in events if e['kind']=='card_destroyed_in_deck')
            self.assertEqual(event['target']['card_id'],'plain');self.assertNotIn('candidates',event)
        self.check(g)

    def test_private_reveal_owner_only(self):
        self.spell('erase',lambda c:[DestroyDeckMatching(2,selection='first',reveal=False)])
        g=self.game(board=(),hand=('erase',),enemy_deck=('FP1_007','CS2_029'));self.play(g,'erase')
        self.assertNotIn('FP1_007',json.dumps(g.player_events(1)))
        self.assertIn('FP1_007',json.dumps(g.player_events(2)));self.check(g)

    def test_reaction_choice_before_reward_is_saveable(self):
        self.watch(lambda c:[RequestChoice(2,(ChoiceOption('go','Go'),),c.source_id)])
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));self.play(g,'pulse')
        self.assertEqual(self.board(g)[0].attack,1);self.assertEqual(len(self.burns(g)),1);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):
            choice=match.state.pending_choice;match.apply(SelectChoice(2,choice.id,('go',)))
            self.assertEqual(self.board(match)[0].attack,3)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_deck_removal_during_starship_death_deferral_and_choice(self):
        from hs_sim.engine.starships import LaunchStarshipEffect, construction
        self.r.register_behavior('launch_consume',lambda c:[GrantDeckSacrificeAura(
            c.state.players[1].board[-1],DeckSacrificeSpec((c.source.card_id,))),
            SacrificeAdjacent(MinionReference.capture(c.source),2,2,source_id=c.source_id)])
        self.minion('piece',attack=1,health=1,keywords=(Keyword.STARSHIP_PIECE,),on_launch='launch_consume')
        self.spell('launch',lambda c:[LaunchStarshipEffect(1,construction(c.state,1).id)])
        self.watch(lambda c:[RequestChoice(2,(ChoiceOption('go','Go'),),c.source_id)])
        g=self.game(board=('piece','plain','watch'),hand=('kill','launch'));self.play(g,'kill',self.board(g)[0].id)
        ship=construction(g.state,1).id;self.play(g,'launch')
        self.assertGreater(g._frame.death_deferrals,0);self.assertEqual(len(self.burns(g)),1)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(g.state.entities[ship].attack,1);self.check(g)
        restored=g.clone()
        for match in (g,restored):match.apply(SelectChoice(2,match.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[ship].attack,3)
        self.assertEqual([e.card_id for e in self.board(g)][1:],['plain','watch']);self.check(g)

    def test_pending_destruction_disables_aura_before_death_checkpoint(self):
        from hs_sim.engine.starships import LaunchStarshipEffect, construction
        self.r.register_behavior('launch_consume',lambda c:[GrantDeckSacrificeAura(
            c.state.players[1].board[-1],DeckSacrificeSpec((c.source.card_id,))),
            Destroy(c.state.players[1].board[-1]),SacrificeAdjacent(MinionReference.capture(c.source),2,2)])
        self.minion('piece',attack=1,health=1,keywords=(Keyword.STARSHIP_PIECE,),on_launch='launch_consume')
        self.spell('launch',lambda c:[LaunchStarshipEffect(1,construction(c.state,1).id)])
        g=self.game(board=('piece','plain','plain'),hand=('kill','launch'));self.play(g,'kill',self.board(g)[0].id)
        self.play(g,'launch');self.assertFalse(self.burns(g));self.assertEqual(len(self.board(g)),1);self.check(g)

    def test_recipient_death_before_reward_does_not_grant(self):
        self.watch(lambda c:[Destroy(c.state.players[1].board[0])])
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));recipient=self.board(g)[0].id
        self.play(g,'pulse');self.assertEqual(g.state.entities[recipient].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[recipient].attack,1);self.check(g)

    def test_same_face_transform_before_reward_invalidates_reference(self):
        self.watch(lambda c:[Transform(c.state.players[1].board[0],'CATA_725t')])
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));self.play(g,'pulse')
        self.assertEqual(self.board(g)[0].attack,1);self.assertEqual(len(self.burns(g)),1);self.check(g)

    def test_recipient_control_roundtrip_invalidates_reference(self):
        self.watch(lambda c:[ChangeControl(c.state.players[1].board[0],2),ChangeControl(c.state.players[1].board[0],1)])
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));i=self.board(g)[0].id;self.play(g,'pulse')
        self.assertEqual(g.state.entities[i].attack,1);self.check(g)

    def test_silencing_recipient_after_success_does_not_cancel_reward(self):
        self.watch(lambda c:[Silence(c.state.players[1].board[0])])
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));self.play(g,'pulse')
        self.assertEqual(self.board(g)[0].attack,3);self.assertTrue(self.board(g)[0].silenced);self.check(g)

    def test_removing_aura_after_success_does_not_cancel_reward(self):
        self.watch(lambda c:[Destroy(c.state.players[1].board[2])])
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));self.play(g,'pulse')
        self.assertEqual(self.board(g)[0].attack,3);self.check(g)

    def test_terminal_reaction_cancels_reward(self):
        self.watch(lambda c:[Damage(c.state.players[2].hero_id,100)])
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));self.play(g,'pulse')
        self.assertEqual(g.state.status,'finished');self.assertEqual(self.board(g)[0].attack,1);self.check(g)

    def test_failed_reaction_rolls_back_card_rng_and_reward(self):
        self.watch(lambda c: (_ for _ in ()).throw(ValueError('failure')))
        g=self.game(board=('CATA_725t','plain','CATA_726','watch'),hand=('pulse',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'pulse')
        self.assertEqual(g.snapshot(),before)

    def test_unknown_continuation_rejected_before_removal(self):
        self.spell('erase',lambda c:[DestroyDeckCard(self.card(c),on_destroy=(InvokeBehavior('unknown',c.source_id,1),))])
        g=self.game(hand=('erase',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'erase')
        self.assertEqual(g.snapshot(),before)

    def test_invalid_specs_rejected(self):
        for ids in ((),[],('plain','plain'),('',),(1,)):
            with self.assertRaises(ValueError):DeckSacrificeSpec(ids)
        with self.assertRaises(ValueError):AbilityInstance(1,'deck_sacrifice')
        with self.assertRaises(ValueError):AbilityInstance(1,'aura',deck_sacrifice=DeckSacrificeSpec(('plain',)))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.SPELL,deck_sacrifice=DeckSacrificeSpec(('plain',))))
        with self.assertRaises(ValueError):GrantDeckSacrificeAura(1,('plain',))
        with self.assertRaises(ValueError):GrantDeckSacrificeAura(1,DeckSacrificeSpec(('plain',)),expires_turn=True)

    def test_invalid_destroy_requests_rejected(self):
        ref=CardReference(1,1,Zone.DECK,'plain',0)
        for kw in ({'count':-1},{'count':True},{'selection':'last'},{'reveal':1},{'query':None}):
            with self.assertRaises(ValueError):DestroyDeckMatching(1,**kw)
        with self.assertRaises(ValueError):DestroyDeckCard(CardReference(1,1,Zone.HAND,'plain',0))
        with self.assertRaises(ValueError):DestroyDeckCard(ref,on_destroy=[])
        with self.assertRaises(ValueError):DestroyDeckCard(ref,reveal=1)

    def test_destruction_count_budget_rolls_back(self):
        self.spell('erase',lambda c:[DestroyDeckMatching(2,count=1001)])
        g=self.game(hand=('erase',));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'erase')
        self.assertEqual(g.snapshot(),before)

    def test_snapshot_spec_tamper_rejected(self):
        g=self.game();s=g.snapshot();i=str(self.board(g)[2].id)
        ability=next(a for a in s['state']['entities'][i]['abilities'] if a['kind']=='deck_sacrifice')
        ability['deck_sacrifice']['card_ids']=['CATA_725t','CATA_725t']
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)

    def test_old_snapshot_schema_rejected(self):
        s=self.game().snapshot();s['schema_version']=37
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)


if __name__=='__main__':unittest.main()
