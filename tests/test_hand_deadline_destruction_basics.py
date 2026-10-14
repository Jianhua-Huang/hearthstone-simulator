"""Destruction is an explicit deadline retirement, with original owed targets."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    ResolutionError, Scenario, ScheduleHandRemoval, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, Draw, EquipWeapon, GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.hand_deadlines import CompleteHandDeadlineDestruction, ExpireHandDeadline, validate_boundary
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from test_current_deck_empty_basics import rehash
import test_bound_hand_deadline_basics as base

PATH=Path(__file__).resolve().parents[1]/'data/support/hand-deadline-destruction-basics.json'
PIN='d5a5b7a70b0e10847aa32d34263d3f3262c9f950a3445d767d09a0e5f2082975'

def evidence():
    data=json.loads(PATH.read_bytes())
    if canonical_digest(data)!=PIN: raise ValueError('Deadline destruction evidence changed')
    return {x['id']:x for x in data['records']}

def registry():
    r=base.registry(); raw=evidence()['WW_441']
    r.register_behavior('fuel.body',lambda c:(Draw(c.player_id,2,c.source_id),))
    r.register_card(CardDefinition('WW_441',raw['name'],CardType.SPELL,cost=raw['cost'],on_play='fuel.body',
        on_discard='fuel.body',on_destroyed='fuel.body',metadata=metadata_from_record(raw)))
    for n in (1,3):
        name='destroy.'+str(n)
        r.register_behavior(name,lambda c,n=n:(ScheduleHandRemoval(3-c.player_id,n,c.source_id,'destroy'),))
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,metadata=metadata()))
    def native(c):
        if c.destruction is None or c.cast is not None or c.play is not None or c.source.zone!=Zone.GRAVEYARD:
            raise ValueError('Deadline destruction lost its independent native actor')
        return (GainArmor(c.player_id,2),)
    r.register_behavior('probe.body',native)
    r.register_behavior('probe.death',lambda c:(GainArmor(c.player_id,99),))
    r.register_behavior('probe.wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('ok','Continue',(GainArmor(c.player_id,2),)),
        ChoiceOption('bad','Fail',(EquipWeapon(c.player_id,'card.1'),))),c.source_id),))
    def fault(c): raise RuntimeError('Deliberate deadline destruction fault')
    r.register_behavior('probe.fault',fault)
    r.register_behavior('probe.fail',lambda c:(InvokeBehavior('probe.fault',c.source_id,c.player_id),))
    r.register_behavior('probe.lethal',lambda c:(Damage(c.state.players[c.player_id].hero_id,99,c.source_id),))
    def move_next(c):
        target=next((c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id=='card.1'),None)
        return () if target is None else (MoveCard(CardReference.capture(target),c.player_id,Zone.DECK),)
    r.register_behavior('probe.move',move_next)
    for cid,body in (('probe.native','probe.body'),('probe.wait','probe.wait'),('probe.fail','probe.fail'),('probe.move','probe.move'),('probe.lethal','probe.lethal')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=3,
            deathrattle='probe.death',on_destroyed=body,metadata=metadata()))
    r.register_card(CardDefinition('source.body','Deadline source',CardType.MINION,health=3,battlecry='destroy.1',metadata=metadata()))
    def move_enemy(c,returned=False):
        target=CardReference.capture(c.state.entities[c.state.players[2].hand[0]])
        return (MoveCard(target,2,Zone.DECK),*((MoveCard(replace(target,zone=Zone.DECK,zone_epoch=target.zone_epoch+1),2,Zone.HAND),) if returned else ()))
    for cid,callback in (('move.enemy',lambda c:move_enemy(c)),('return.enemy',lambda c:move_enemy(c,True)),
        ('kill.source',lambda c:(Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='source.body')),))):
        r.register_behavior(cid,callback);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def wait(c):
        if c.event.player_id!=2:return ()
        return (RequestChoice(2,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(EquipWeapon(2,'card.1'),))),c.source_id),)
    r.register_behavior('watch',wait)
    for cid,event in (('end.watch','turn_ended'),('step.watch','hand_deadline_destruction_step'),('destroy.watch','card_destroyed_in_hand')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=5,triggers=(TriggerSpec(event,'watch'),),metadata=metadata()))
    return r

class HandDeadlineDestructionTests(unittest.TestCase):
    def game(self,hand=('destroy.1',),enemy_hand=('probe.native','card.1'),board=(),enemy_board=()):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=('card.30',)*12,max_mana=10,mana=10),
            PlayerSetup('warrior.hero',hand=enemy_hand,board=enemy_board,deck=('card.31',)*12,max_mana=10,mana=10)),seed=157),registry())
    def play(self,g,cid=None):
        player=g.state.active_player; i=next(i for i in g.state.players[player].hand if cid is None or g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,i));return i
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def armor(self,g):return g.state.entities[g.state.players[2].hero_id].armor
    def portable(self,g):
        saved=g.snapshot();h=Game.from_snapshot(json.loads(json.dumps(saved)),registry())
        self.assertEqual(h.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return h
    def expire(self,g):self.play(g);self.end(g);self.end(g)
    def reject(self,saved):
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())

    def test_real_immolate_three_owner_ends_destroy_and_execute_fuel_once(self):
        g=self.game(('TID_718',),('WW_441',));original=g.state.players[2].hand[0];self.play(g)
        self.assertEqual(g.state.players[1].mana,6)
        for n in range(1,4):
            self.end(g);self.end(g);self.assertEqual(g.state.hand_deadlines[0].expired_event is not None,n==3)
        root=g.state.hand_deadlines[0];self.assertEqual(root.removed,(original,))
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD);self.assertEqual(len(root.destruction_events),1)
        self.assertEqual(len(g.state.players[2].hand),5);self.assertEqual(len(g.state.cast_history),1)
        self.assertFalse(g.state.death_history);self.portable(g)

    def test_default_retirement_still_setaside_without_native_body(self):
        g=self.game(('mark.1',));original=tuple(g.state.players[2].hand);self.expire(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.SETASIDE for i in original))
        self.assertEqual(self.armor(g),0);self.assertEqual(g.state.hand_deadlines[0].destruction_events,())
        self.assertIsNone(g.state.hand_deadlines[0].destruction_started_event);self.portable(g)

    def test_all_playable_types_retire_through_stored_destruction_without_death(self):
        g=self.game(enemy_hand=('probe.native','plain.spell','plain.weapon','plain.location','plain.hero'))
        original=tuple(g.state.players[2].hand);epochs=[g.state.entities[i].zone_epoch for i in original];self.expire(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in original))
        self.assertEqual([g.state.entities[i].zone_epoch for i in original],[x+1 for x in epochs])
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind in ('card_discarded','cards_removed_from_game')for e in g.events));self.portable(g)

    def test_departed_original_target_skips_and_does_not_destroy_deck_card(self):
        g=self.game(('destroy.1','move.enemy'));original=g.state.players[2].hand[0]
        self.play(g,'destroy.1');self.play(g,'move.enemy');self.end(g);self.end(g)
        self.assertEqual(g.state.entities[original].zone,Zone.DECK);self.assertNotIn(original,g.state.hand_deadlines[0].removed)
        self.assertEqual(self.armor(g),0);self.portable(g)

    def test_same_entity_returning_hand_is_a_new_lifetime(self):
        g=self.game(('destroy.1','return.enemy'));original=g.state.players[2].hand[0];epoch=g.state.entities[original].zone_epoch
        self.play(g,'destroy.1');self.play(g,'return.enemy');self.end(g);self.end(g)
        self.assertEqual(g.state.entities[original].zone,Zone.HAND);self.assertEqual(g.state.entities[original].zone_epoch,epoch+2)
        self.assertNotIn(original,g.state.hand_deadlines[0].removed);self.portable(g)

    def test_newly_drawn_cards_are_not_original_targets(self):
        g=self.game(enemy_hand=('WW_441','card.1'));original=tuple(g.state.players[2].hand);self.expire(g)
        self.assertEqual(g.state.hand_deadlines[0].removed,original)
        self.assertEqual(len(g.state.players[2].hand),3);self.assertTrue(all(i not in original for i in g.state.players[2].hand));self.portable(g)

    def test_native_body_can_move_later_original_target_before_its_step(self):
        g=self.game(enemy_hand=('probe.move','card.1'));original=tuple(g.state.players[2].hand);self.expire(g)
        self.assertEqual(g.state.hand_deadlines[0].removed,(original[0],))
        self.assertEqual(g.state.entities[original[1]].zone,Zone.DECK);self.portable(g)

    def test_empty_original_root_closes_and_later_draw_is_not_destroyed(self):
        g=self.game(enemy_hand=());self.expire(g);root=g.state.hand_deadlines[0]
        self.assertEqual(root.removed,());self.assertEqual(root.destruction_cursor,0);self.assertIsNotNone(root.expired_event)
        self.assertEqual(len(g.state.players[2].hand),1);self.portable(g)

    def test_two_roots_retain_independent_targets_but_do_not_double_destroy(self):
        g=self.game(('destroy.1','destroy.1'));original=tuple(g.state.players[2].hand)
        self.play(g);self.play(g);self.end(g);self.end(g)
        self.assertEqual([r.removed for r in g.state.hand_deadlines],[original,()])
        self.assertEqual(self.armor(g),2);self.portable(g)

    def test_dead_source_does_not_cancel_accepted_retirement(self):
        g=self.game(('source.body','kill.source'));source=self.play(g,'source.body');self.play(g,'kill.source')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.end(g);self.end(g)
        self.assertEqual(self.armor(g),2);self.assertEqual(g.state.hand_deadlines[0].request.source_id,source);self.portable(g)

    def test_owner_end_waiting_restores_original_expiry(self):
        g=self.game(enemy_board=('end.watch',));self.expire(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertIsNone(g.state.hand_deadlines[0].destruction_started_event)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_private_step_waiting_preserves_owed_physical_movement(self):
        g=self.game(enemy_hand=('probe.native',),enemy_board=('step.watch',));self.expire(g)
        root=g.state.hand_deadlines[0];self.assertEqual(root.destruction_cursor,0)
        self.assertEqual(g.state.entities[root.targets[0].entity_id].zone,Zone.HAND)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_destroy_listener_waits_before_native_body_and_later_target(self):
        g=self.game(enemy_hand=('WW_441','card.1'),enemy_board=('destroy.watch',));self.expire(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.hand_deadlines[0].destruction_cursor,0)
        self.assertEqual(len(g.state.players[2].hand),2)
        h=self.portable(g)
        while g.state.pending_choice:self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(g.state.players[2].hand),3);self.portable(g)

    def test_native_body_waiting_preserves_partial_deadline_results(self):
        g=self.game(enemy_hand=('probe.wait','card.1'));self.expire(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.armor(g),0)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(self.armor(g),2);self.assertEqual(g.state.hand_deadlines[0].destruction_cursor,2);self.portable(g)

    def test_failed_native_choice_keeps_original_waiting_state(self):
        g=self.game(enemy_hand=('probe.wait',));self.expire(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_native_fault_rolls_back_entire_owner_end_and_retirement(self):
        g=self.game(enemy_hand=('probe.fail','card.1'));self.play(g);self.end(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Deliberate'):self.end(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_terminal_native_body_stops_later_original_targets_without_false_close(self):
        g=self.game(enemy_hand=('probe.lethal','card.1'));original=tuple(g.state.players[2].hand);self.expire(g)
        self.assertNotEqual(g.state.status,'playing');self.assertEqual(g.state.entities[original[0]].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[original[1]].zone,Zone.HAND)
        self.assertIsNone(g.state.hand_deadlines[0].expired_event);self.assertEqual(g.state.hand_deadlines[0].destruction_cursor,0)
        self.portable(g)

    def test_missing_completion_is_rejected_by_deadline_boundary(self):
        g=self.game(enemy_hand=('probe.wait',));self.expire(g);before=g._frame
        g._frame=replace(before,continuation=tuple(w for w in before.continuation if type(w)is not CompleteHandDeadlineDestruction))
        with self.assertRaises(ValueError):validate_boundary(g)
        g._frame=before;self.portable(g)

    def test_closed_result_and_retirement_tampering_are_rejected(self):
        g=self.game();self.expire(g)
        for change in ('mode','cursor','event'):
            saved=deepcopy(g.snapshot());root=saved['state']['hand_deadlines'][0]
            if change=='mode':root['request']['retirement']='remove'
            elif change=='cursor':root['destruction_cursor']=0
            else:root['destruction_events'][0]=root['destruction_started_event']
            self.reject(saved)

    def test_requests_codec_and_old_schema_guard(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry);request=ScheduleHandRemoval(2,3,None,'destroy')
        self.assertEqual(codec.decode(codec.encode(request)),request)
        for value in ('unknown',None,True):
            with self.assertRaises(ValueError):ScheduleHandRemoval(2,1,retirement=value)
        saved=g.snapshot();saved['schema_version']=247;self.reject(saved)

    def test_player_views_hide_cursor_receipts_targets_and_unrevealed_hand(self):
        g=self.game(enemy_hand=('probe.wait','card.1'));self.expire(g);before=g.snapshot()
        text=json.dumps(g.for_player(1).observe())+json.dumps(g.for_player(1).events())
        for private in ('probe.wait','destruction_cursor','destruction_events','original_card','CompleteHandDeadlineDestruction'):
            self.assertNotIn(private,text)
        self.assertEqual(g.snapshot(),before);self.portable(g)

if __name__=='__main__':unittest.main()
