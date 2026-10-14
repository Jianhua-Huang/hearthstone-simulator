"""Explicit original hand references reuse deadline clock and retirement."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,CastWhenDrawnSpec,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Registry,ResolutionError,Scenario,ScheduleHandRemoval,SelectChoice,
    SnapshotError,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption,Draw,EquipWeapon,InvokeBehavior,RequestChoice)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from test_current_deck_empty_basics import rehash

PATH=Path(__file__).resolve().parents[1]/'data/support/bound-card-deadline-basics.json'
PIN='888dfd8839e0ba9b8d32a9294003e3b7357029182b883054c84de76d40e09276'

def evidence():
    data=json.loads(PATH.read_bytes())
    if canonical_digest(data)!=PIN:raise ValueError('Bound card deadline source changed')
    return {r['id']:r for r in data['records']}

def ordinary_draw_references(c):
    if c.cast is None or c.cast.card_id!='WORK_026' or c.cast.origin!='hand':
        raise ResolutionError('Inferno representative requires its actual manual cast profile')
    rows=tuple(d for d in c.state.draw_history if d.player_id==c.player_id and d.source_id==c.source_id
        and d.parent_id is None and d.turn==c.cast.turn and d.action>=c.cast.action)
    if len(rows)!=3 or any(not d.completed or d.interrupted for d in rows):
        raise ResolutionError('Inferno representative lost its three actual root draw results')
    if any(d.outcome=='cast' for d in rows):
        raise ResolutionError('Inferno draw-cast/replacement policy is unimplemented')
    entries={}
    for entry in c.state.hand_entries:
        if entry.reason=='draw':entries.setdefault(entry.entity_id,[]).append(entry)
    ordinals={};references=[];selected={d.id for d in rows}
    for draw in c.state.draw_history:
        if draw.outcome!='hand':continue
        ordinal=ordinals.get(draw.entity_id,0);ordinals[draw.entity_id]=ordinal+1
        acquired=entries.get(draw.entity_id,())
        if ordinal>=len(acquired):raise ResolutionError('Actual hand draw lost its original acquisition')
        entry=acquired[ordinal]
        if draw.id not in selected:continue
        if (entry.player_id,entry.card_id,entry.turn,entry.action,entry.from_zone)!=(draw.player_id,draw.card_id,draw.turn,draw.action,Zone.DECK):
            raise ResolutionError('Actual hand draw and original acquisition disagree')
        references.append(CardReference(entry.entity_id,entry.player_id,Zone.HAND,entry.card_id,entry.zone_epoch))
    return tuple(references)

def registry():
    r=Registry('isolated-bound-card-deadlines-v1');raw=evidence()['WORK_026']
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=60,metadata=metadata()))
    for cid in ('old.private','new.a','new.b','later.private'):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=3,metadata=metadata()))
    def bind(c):
        return tuple(ScheduleHandRemoval(c.player_id,3,c.source_id,'destroy',cards=(card,)) for card in ordinary_draw_references(c))
    r.register_behavior('inferno.bind',bind)
    r.register_behavior('inferno.draw',lambda c:(Draw(c.player_id,3,c.source_id),InvokeBehavior('inferno.bind',c.source_id,c.player_id)))
    r.register_card(CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.FIRE,
        on_play='inferno.draw',metadata=metadata_from_record(raw)))
    def reference(c,cid='new.a'):
        return CardReference.capture(next(c.state.entities[i]for i in c.state.players[1].hand if c.state.entities[i].card_id==cid))
    def stale(c):
        card=reference(c)
        return (MoveCard(card,1,Zone.DECK),MoveCard(replace(card,zone=Zone.DECK,zone_epoch=card.zone_epoch+1),1,Zone.HAND),
            ScheduleHandRemoval(1,1,c.source_id,'destroy',cards=(card,)))
    def pause(c):
        return (RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(EquipWeapon(1,'new.a'),))),c.source_id),
            ScheduleHandRemoval(1,1,c.source_id,'destroy',cards=(reference(c),)))
    scripts={
        'one':lambda c:(ScheduleHandRemoval(1,1,c.source_id,'destroy',cards=(reference(c),)),),
        'empty':lambda c:(ScheduleHandRemoval(1,1,c.source_id,'destroy',cards=()),),
        'remove':lambda c:(ScheduleHandRemoval(1,1,c.source_id,cards=(reference(c),)),),
        'stale':stale,'pause':pause,
        'unknown':lambda c:(ScheduleHandRemoval(1,1,c.source_id,'destroy',cards=(CardReference(999,1,Zone.HAND,'new.a',0),)),),
        'future':lambda c:(ScheduleHandRemoval(1,1,c.source_id,'destroy',cards=(replace(reference(c),zone_epoch=999),)),),
    }
    for cid,behavior in scripts.items():
        r.register_behavior(cid,behavior);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    def watch(c):
        if c.draw is None or c.draw.source_id is None or c.state.entities[c.draw.source_id].card_id!='WORK_026':return ()
        if c.draw.outcome!='hand':return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
    r.register_behavior('watch',watch)
    r.register_card(CardDefinition('watch','Pause actual draws',CardType.MINION,health=4,triggers=(TriggerSpec('card_drawn','watch'),),metadata=metadata()))
    def bounce(c):
        if c.draw is None or c.draw.outcome!='hand' or c.draw.source_id is None or c.state.entities[c.draw.source_id].card_id!='WORK_026':return ()
        card=CardReference.capture(c.state.entities[c.event.target_id])
        return (MoveCard(card,c.player_id,Zone.DECK),MoveCard(replace(card,zone=Zone.DECK,zone_epoch=card.zone_epoch+1),c.player_id,Zone.HAND))
    r.register_behavior('bounce',bounce)
    r.register_card(CardDefinition('bounce','Depart and return drawn cards',CardType.MINION,health=4,triggers=(TriggerSpec('card_drawn','bounce'),),metadata=metadata()))
    r.register_behavior('auto.body',lambda c:())
    r.register_card(CardDefinition('auto','Diagnostic draw-cast spell',CardType.SPELL,on_play='auto.body',
        keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(),metadata=metadata()))
    return r

class BoundCardDeadlineTests(unittest.TestCase):
    def game(self,hand=('WORK_026','old.private'),deck=('new.a','new.a','new.b','later.private','later.private','later.private'),board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,deck=deck,board=board,max_mana=10,mana=10),
            PlayerSetup('hero',deck=('later.private',)*8)),seed=158),registry())
    def play(self,g,cid=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if cid is None or g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,i))
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g):
        saved=g.snapshot();h=Game.from_snapshot(json.loads(json.dumps(saved)),registry())
        self.assertEqual(h.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return h
    def reject(self,saved):
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())

    def test_necessary_raw_profile_and_manual_payment(self):
        raw=evidence()['WORK_026'];g=self.game();self.play(g)
        self.assertEqual((g.registry.card('WORK_026').cost,g.registry.card('WORK_026').spell_school),(3,SpellSchool.FIRE))
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.cast_history),1)
        self.assertIn('抽三张牌',raw['text']);self.assertNotIn('WORK_026e',g.registry.cards);self.portable(g)

    def test_only_three_actual_drawn_entities_are_bound_not_old_hand(self):
        g=self.game();old=g.state.players[1].hand[1];drawn=tuple(g.state.players[1].deck[:3]);self.play(g)
        self.assertEqual(tuple(r.targets[0].entity_id for r in g.state.hand_deadlines),drawn)
        self.assertTrue(all(r.request.cards==r.targets and r.request.cards is not None for r in g.state.hand_deadlines))
        self.assertTrue(all(old not in [t.entity_id for t in r.targets]for r in g.state.hand_deadlines));self.portable(g)

    def test_bound_drawn_cards_retire_at_three_real_owner_ends(self):
        g=self.game();old=g.state.players[1].hand[1];drawn=tuple(g.state.players[1].deck[:3]);self.play(g)
        for _ in range(4):self.end(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.HAND for i in drawn));self.end(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in drawn))
        self.assertEqual(g.state.entities[old].zone,Zone.HAND);self.assertTrue(all(r.expired_event is not None for r in g.state.hand_deadlines));self.portable(g)

    def test_later_natural_draws_are_not_absorbed_by_the_bound_scope(self):
        g=self.game();later=tuple(g.state.players[1].deck[3:]);self.play(g)
        for _ in range(5):self.end(g)
        self.assertTrue(all(g.state.entities[i].zone in (Zone.HAND,Zone.DECK)for i in later));self.portable(g)

    def test_empty_explicit_tuple_never_falls_back_to_entire_hand(self):
        g=self.game(('empty','old.private','new.a'));held=tuple(g.state.players[1].hand[1:]);self.play(g);self.end(g)
        self.assertEqual(g.state.hand_deadlines[0].targets,());self.assertEqual(g.state.hand_deadlines[0].removed,())
        self.assertTrue(all(g.state.entities[i].zone==Zone.HAND for i in held));self.portable(g)

    def test_explicit_remove_still_uses_setaside_for_only_selected_card(self):
        g=self.game(('remove','old.private','new.a'));old=g.state.players[1].hand[1];chosen=g.state.players[1].hand[2]
        self.play(g);self.end(g);self.assertEqual(g.state.entities[chosen].zone,Zone.SETASIDE)
        self.assertEqual(g.state.entities[old].zone,Zone.HAND);self.portable(g)

    def test_known_stale_reference_does_not_bind_returned_new_epoch(self):
        g=self.game(('stale','old.private','new.a'));original=g.state.players[1].hand[2];epoch=g.state.entities[original].zone_epoch
        self.play(g);self.end(g);self.assertEqual(g.state.entities[original].zone,Zone.HAND)
        self.assertEqual(g.state.entities[original].zone_epoch,epoch+2);self.assertEqual(g.state.hand_deadlines[0].removed,());self.portable(g)

    def test_draw_reaction_return_does_not_upgrade_original_acquisition(self):
        g=self.game(board=('bounce',));drawn=tuple(g.state.players[1].deck[:3]);self.play(g)
        self.assertTrue(all(r.targets[0].zone_epoch<g.state.entities[r.targets[0].entity_id].zone_epoch for r in g.state.hand_deadlines))
        for _ in range(5):self.end(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.HAND for i in drawn));self.assertTrue(all(not r.removed for r in g.state.hand_deadlines));self.portable(g)

    def test_burned_cards_do_not_receive_deadline_or_hand_entry(self):
        g=self.game(('WORK_026',)+('old.private',)*9);drawn=tuple(g.state.players[1].deck[:3]);self.play(g)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','burned','burned'])
        self.assertEqual(tuple(r.targets[0].entity_id for r in g.state.hand_deadlines),(drawn[0],))
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in drawn[1:]));self.portable(g)

    def test_fatigue_does_not_create_a_bound_physical_target(self):
        g=self.game(deck=('new.a',));self.play(g)
        self.assertEqual([d.outcome for d in g.state.draw_history],['hand','fatigue','fatigue'])
        self.assertEqual(len(g.state.hand_deadlines),1);self.portable(g)

    def test_unknown_draw_cast_policy_errors_without_silent_pool_deletion(self):
        g=self.game(deck=('auto','new.a','new.a','new.a','new.b'));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'draw-cast'):self.play(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_waiting_during_draws_restores_all_three_original_results(self):
        g=self.game(board=('watch',));self.play(g);self.assertIsNotNone(g.state.pending_choice)
        h=self.portable(g)
        while g.state.pending_choice:
            self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(len(g.state.hand_deadlines),3);self.portable(g)

    def test_pending_explicit_scope_roundtrips_before_acceptance(self):
        g=self.game(('pause','old.private','new.a'));self.play(g)
        self.assertFalse(g.state.hand_deadlines);h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(len(g.state.hand_deadlines[0].targets),1);self.portable(g)

    def test_failed_choice_does_not_change_pending_scope_or_knowledge(self):
        g=self.game(('pause','old.private','new.a'));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_unknown_entity_and_future_epoch_reject_without_committing_root(self):
        for cid in ('unknown','future'):
            with self.subTest(cid=cid):
                g=self.game((cid,'new.a'));before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g)
                self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_immutable_distinct_refs_and_original_owner_hand_are_required(self):
        g=self.game(('new.a',));ref=CardReference.capture(g.state.entities[g.state.players[1].hand[0]])
        for cards in ([ref],(ref,ref),(replace(ref,player_id=2),),(replace(ref,zone=Zone.DECK),),(object(),)):
            with self.assertRaises(ValueError):ScheduleHandRemoval(1,3,cards=cards)
        request=ScheduleHandRemoval(1,3,cards=(ref,));codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(request)),request)

    def test_saved_request_cannot_broaden_or_drop_original_target_inventory(self):
        g=self.game();self.play(g)
        for change in ('whole','empty','other'):
            saved=deepcopy(g.snapshot());root=saved['state']['hand_deadlines'][0]
            if change=='whole':root['request']['cards']=None
            elif change=='empty':root['request']['cards']=[]
            else:root['request']['cards'][0]['entity_id']=g.state.players[1].hand[0]
            self.reject(saved)

    def test_player_views_hide_bound_refs_and_remain_pure(self):
        g=self.game(('pause','old.private','new.a'));self.play(g);before=g.snapshot()
        text=json.dumps(g.for_player(2).observe())+json.dumps(g.for_player(2).events())
        for private in ('old.private','new.a','zone_epoch','target_scope'):
            self.assertNotIn(private,text)
        self.assertEqual(g.snapshot(),before);self.portable(g)

if __name__=='__main__':unittest.main()
