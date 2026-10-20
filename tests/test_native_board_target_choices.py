"""Real second arrows and Osk's original distinct, simultaneous removal batch."""
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,
    ResolutionError,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand
from hs_sim.engine.native_hand_targets import ACCEPTED,FINISHED,OFFERED,NativeChoiceResult
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from test_native_hand_targets import rehash
from test_native_random_target_domains import fixture as domain_fixture,CARD,UNIT,STEALTH,ELUSIVE,IMMUNE

DANCE='DINO_414';ROAR='CATA_554';TWO='TLC_452t21';DRAGON='WW_434';LEVIATHAN='CATA_699'
P='fixture.native.board.';WATCH=P+'watch'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=domain_fixture.__wrapped__()
    def before(c):
        if c.state.entities[c.event.source_id].card_id!=TWO:return ()
        ids=tuple(c.state.players[2].board)
        if mode in('partial','partial_wait'):
            return(RemoveFromGame(tuple(MinionReference.capture(c.state.entities[i])for i in ids[:-1]),c.source_id),)
        if mode=='empty':return(RemoveFromGame(tuple(MinionReference.capture(c.state.entities[i])for i in ids),c.source_id),)
        if mode=='kill':
            source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==CARD)
            return(Destroy(source,c.source_id),)
        if mode=='bounce':return(ReturnToHand(ids[0]),InvokeBehavior(P+'back',c.source_id,c.player_id,ids[0]))
        return ()
    def after(c):
        if c.state.entities[c.event.source_id].card_id!=TWO:return ()
        if mode=='fail':raise ResolutionError('Real removal callback observer failure')
        if mode in('wait','partial_wait'):
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
        return ()
    r.register_behavior(P+'before',before);r.register_behavior(P+'after',after)
    r.register_behavior(P+'back',lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,
        cause=SummonCause.capture(c)),))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,triggers=(
        TriggerSpec('choice_selected',P+'before'),TriggerSpec('cards_removed_from_game',P+'after'))))
    r.validate();return r


class NativeBoardTargetChoiceTests(unittest.TestCase):
    def game(self,hand=(TWO,),board=(CARD,),enemy=(UNIT,UNIT,UNIT),mode='normal',seed=0):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=hand,board=board,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_03',board=enemy,mana=30,max_mana=30,mana_cap=30)),seed=seed),fixture(mode))
    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target))
    def select(self,g):
        q=g.state.pending_choice;ids=tuple(o.id for o in q.options[:q.min_count])
        g.apply(SelectChoice(q.player_id,q.id,ids));return ids
    def receipt(self,g):
        event=next(e for e in reversed(g.events)if e.kind==ACCEPTED);data=dict(event.data)
        codec=FrameCodec(g.mechanics,g.registry)
        return event,{k:codec.decode(json.loads(data[k]))for k in
            ('request','original','actual','selection','additional_selections')}
    def portable(self,g,mode='normal'):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,fixture.__wrapped__(mode))
        self.assertEqual(s,other.snapshot());self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),fixture.__wrapped__(mode)).snapshot(),s);return other
    def test_real_dance_second_arrow_keeps_first_actual_target_and_original_copy_effect(self):
        g=self.game(hand=(DANCE,),board=(CARD,UNIT),enemy=(DRAGON,UNIT))
        original=g.state.players[1].board[-1];mana=g.state.players[1].mana;self.play(g,DANCE,original)
        first=g.state.cast_history[-1].target_id;offer=g.state.pending_choice
        self.assertNotIn(first,{o.entity_id for o in offer.options})
        faces={i:g.state.entities[i].card_id for i in g.state.entities};self.select(g);_,row=self.receipt(g)
        selected=row['selection'].target_id
        self.assertEqual(g.state.entities[first].card_id,faces[selected])
        self.assertNotEqual(first,selected);self.assertEqual(g.state.play_history[-1].target_id,original)
        self.assertEqual(g.state.players[1].mana,mana-5);self.portable(g)
    def test_real_roar_additional_arrow_uses_distinct_enemy_and_original_health_effect(self):
        g=self.game(hand=(ROAR,DRAGON));ids=tuple(g.state.players[2].board);self.play(g,ROAR,ids[0])
        first=g.state.cast_history[-1].target_id;self.assertEqual(g.state.entities[first].health,1)
        self.assertNotIn(first,{o.entity_id for o in g.state.pending_choice.options})
        self.select(g);_,row=self.receipt(g);selection=row['selection']
        self.assertEqual({f.controller for f in selection.partition.candidates},{2})
        self.assertNotEqual(first,selection.target_id);self.assertEqual(g.state.entities[selection.target_id].health,1)
    def test_real_roar_without_held_dragon_has_no_additional_arrow(self):
        g=self.game(hand=(ROAR,));self.play(g,ROAR,g.state.players[2].board[0])
        self.assertIsNone(g.state.pending_choice);self.assertFalse(any(e.kind==OFFERED for e in g.events))
    def test_real_two_arrows_draw_distinct_targets_then_remove_one_simultaneous_nondeath_batch(self):
        g=self.game();ids=tuple(g.state.players[2].board);self.play(g,TWO);original=self.select(g);event,row=self.receipt(g)
        draws=(row['selection'],*row['additional_selections']);actual=tuple(d.target_id for d in draws)
        self.assertEqual(len(set(actual)),2);self.assertEqual(draws[1].rng_before,draws[0].rng_after)
        self.assertEqual(draws[1].partition.target_ids,tuple(i for i in ids if i!=actual[0]))
        self.assertEqual(row['original'].selected_ids,original);self.assertEqual(row['original'].choice.min_count,2)
        publication=next(e for e in g.events if e.kind=='choice_selected'and dict(e.data)['choice_id']==row['original'].choice.id)
        self.assertEqual(dict(publication.data)['option_ids'],original)
        removed=[e for e in g.events if e.kind=='cards_removed_from_game'];self.assertEqual(len(removed),1)
        self.assertEqual(removed[0].amount,2);self.assertFalse(g.state.death_history)
        self.assertEqual({i for i in ids if g.state.entities[i].zone==Zone.SETASIDE},set(actual))
        self.assertTrue(g.state.battlecry_history[-1].completed);self.portable(g)
    def test_real_two_offer_and_live_domain_keep_stealth_immunity_but_allow_minion_targeting_elusive(self):
        g=self.game(enemy=(UNIT,STEALTH,ELUSIVE,IMMUNE));ids=tuple(g.state.players[2].board);self.play(g,TWO)
        self.assertEqual(tuple(o.entity_id for o in g.state.pending_choice.options),(ids[0],ids[2]))
        self.select(g);_,row=self.receipt(g);self.assertEqual(row['selection'].partition.target_ids,(ids[0],ids[2]))
    def test_real_leviathan_three_arrows_requery_and_keep_one_paid_battlecry(self):
        g=self.game(hand=(LEVIATHAN,));ids=tuple(g.state.players[2].board);mana=g.state.players[1].mana
        self.play(g,LEVIATHAN);source=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==LEVIATHAN)
        before=g.state.entities[source].max_health
        for _ in range(3):self.select(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.entities[source].max_health,before+9)
        self.assertEqual(sum(g.state.entities[i].health for i in ids),21)
        self.assertEqual(sum(e.kind==ACCEPTED for e in g.events),3)
        self.assertEqual(sum(e.kind==FINISHED for e in g.events),3)
        self.assertEqual(len(g.state.battlecry_history),1);self.assertTrue(g.state.battlecry_history[-1].completed)
        self.assertEqual(g.state.players[1].mana,mana-g.registry.card(LEVIATHAN).cost)
    def test_real_leviathan_next_native_arrow_wait_restores_previous_acceptance_and_replays(self):
        g=self.game(hand=(LEVIATHAN,));self.play(g,LEVIATHAN);self.select(g);other=self.portable(g)
        self.assertIsNotNone(g.state.pending_choice)
        for current in(g,other):
            self.select(current);self.select(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)
    def test_no_source_keeps_two_original_targets_and_rng(self):
        g=self.game(board=());ids=tuple(g.state.players[2].board);self.play(g,TWO);rng=g.snapshot()['rng_state'];self.select(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(any(e.kind==ACCEPTED for e in g.events))
        self.assertEqual(g.state.players[2].board,[ids[2]])
    def test_original_two_choice_pending_offer_restores_before_random_draws(self):
        g=self.game();self.play(g,TWO);other=self.portable(g)
        for current in(g,other):self.select(current)
        self.assertEqual(g.snapshot(),other.snapshot())
    def test_only_one_live_candidate_executes_subset_without_falsifying_original_two_input(self):
        g=self.game(board=(CARD,WATCH),mode='partial');ids=tuple(g.state.players[2].board)
        self.play(g,TWO);original=self.select(g);_,row=self.receipt(g)
        self.assertIs(type(row['actual']),NativeChoiceResult);self.assertEqual(row['actual'].choice.min_count,2)
        self.assertEqual(row['actual'].original.selected_ids,original);self.assertEqual(len(row['actual'].selected_ids),1)
        first,second=row['selection'],row['additional_selections'][0]
        self.assertEqual(first.target_id,ids[-1]);self.assertEqual(second.failure,'no_target')
        self.assertEqual(second.rng_before,second.rng_after);self.assertFalse(g.state.players[2].board)
        self.assertTrue(g.state.battlecry_history[-1].completed);self.portable(g,'partial')
    def test_partial_execution_wait_preserves_original_two_input_full_proof_restore_and_replay(self):
        g=self.game(board=(CARD,WATCH),mode='partial_wait');self.play(g,TWO);self.select(g)
        self.assertEqual(g.state.pending_choice.options[0].id,'ok');other=self.portable(g,'partial_wait')
        for current in(g,other):self.select(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(sum(e.kind==FINISHED for e in g.events),1)
    def test_empty_live_domain_fizzles_both_arrows_without_rng_and_completes_parent(self):
        g=self.game(board=(CARD,WATCH),mode='empty');self.play(g,TWO);rng=g.snapshot()['rng_state'];self.select(g)
        _,row=self.receipt(g);self.assertIsNone(row['actual']);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual([d.failure for d in(row['selection'],*row['additional_selections'])],['no_target','no_target'])
        self.assertTrue(g.state.battlecry_history[-1].completed)
    def test_original_board_residence_cannot_be_replaced_by_same_id_reentry(self):
        g=self.game(board=(CARD,WATCH),mode='bounce');ids=tuple(g.state.players[2].board);self.play(g,TWO);self.select(g)
        _,row=self.receipt(g);self.assertEqual(row['selection'].partition.target_ids,ids[1:])
        self.assertEqual(g.state.players[2].board,[ids[0]]);self.portable(g,'bounce')
    def test_source_removed_in_original_choice_reactions_keeps_user_targets_without_rng(self):
        g=self.game(board=(CARD,WATCH),mode='kill');self.play(g,TWO);rng=g.snapshot()['rng_state'];self.select(g)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(any(e.kind==ACCEPTED for e in g.events))
    def test_failure_after_actual_batch_rolls_back_original_choice_and_rng(self):
        g=self.game(board=(CARD,WATCH),mode='fail');self.play(g,TWO);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g)
        self.assertEqual(g.snapshot(),before);self.portable(g,'fail')
    def test_partial_wait_cannot_drop_second_draw_from_full_proof(self):
        g=self.game(board=(CARD,WATCH),mode='partial_wait');self.play(g,TWO);self.select(g)
        s=json.loads(json.dumps(g.snapshot()))
        def crop(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.NativeHandTargetProof'):
                    value['fields']['additional_selections']={'tuple':[]};return True
                return any(crop(x)for x in value.values())
            if isinstance(value,list):return any(crop(x)for x in value)
            return False
        self.assertTrue(crop(s['resolution_frame']))
        with self.assertRaises((SnapshotError,ValueError)):Game.from_snapshot(rehash(s),fixture.__wrapped__('partial_wait'))
    def test_board_private_original_offers_and_draws_do_not_enter_player_views(self):
        g=self.game();self.play(g,TWO);self.select(g)
        for player in(1,2):
            visible=json.dumps(g.observe(player))
            for key in(OFFERED,ACCEPTED,FINISHED,'target_facts','rng_before','additional_selections'):
                self.assertNotIn(key,visible)


if __name__=='__main__':unittest.main()
