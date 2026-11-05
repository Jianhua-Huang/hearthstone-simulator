"""Original overflow allocation, native bodies and the existing interpreter."""
from copy import deepcopy
from dataclasses import dataclass,replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Registry,
    ResolutionError,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import AddToHand,ChoiceOption,Draw,Effect,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import BehaviorCall,default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard,destruction_result
from hs_sim.engine.temporary_cards import CreateTemporaryCard
from hs_sim.engine.void_decks import SendDeckToVoid,GetFromVoid
from hs_sim.engine.temporary_deck_hands import ReplaceHandWithTemporaryDeckCards
from hs_sim.targets import canonical_digest
from test_stored_destruction_basics import registry as base_registry
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='8d89a31dd9b2d92ed9fbe36ec88cefa6e3604611290622ed32f416bf84261220'
NATIVE='WW_441'
def evidence():
    v=json.loads((ROOT/'data/support/native-overflow-body-basics.json').read_bytes())
    if canonical_digest(v)!=PIN:raise ValueError('Native overflow evidence changed')
    return v

@dataclass(frozen=True)
class UnclassifiedBurn(Effect):
    target_id:int

def registry():
    r=base_registry()
    def measure(c):
        row=c.destruction
        if row is None or row.profile=='explicit' or c.cast is not None or c.draw is not None or c.discard is not None:
            raise ValueError('Overflow body needs its independent actual receipt')
        return (GainArmor(c.player_id,3),)
    r.register_behavior('overflow.measure',measure)
    r.register_card(CardDefinition('overflow.probe','Allocation/receipt probe',CardType.SPELL,
        on_destroyed='overflow.measure',metadata=metadata()))
    def wait(c):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,7),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('overflow.fault',c.source_id,c.player_id),))),c.source_id),)
    def fault(c):raise ResolutionError('Deliberate native overflow fault')
    r.register_behavior('overflow.wait',wait);r.register_behavior('overflow.fault',fault)
    for cid,body in (('overflow.wait','overflow.wait'),('overflow.fault','overflow.fault')):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_destroyed=body,metadata=metadata()))
    def first(c,zone=Zone.HAND):return CardReference.capture(c.state.entities[getattr(c.state.players[1],zone.value)[0]])
    def create(c,cid=NATIVE):return (AddToHand(1,'plain',c.source_id),AddToHand(1,cid,c.source_id))
    scripts={
        'overflow.draw':lambda c:(Draw(1,2,c.source_id),),
        'overflow.create':create,
        'overflow.probe.create':lambda c:create(c,'overflow.probe'),
        'overflow.wait.create':lambda c:create(c,'overflow.wait'),
        'overflow.fault.create':lambda c:create(c,'overflow.fault'),
        'overflow.enemy.create':lambda c:(AddToHand(2,NATIVE,c.source_id),),
        'overflow.send':lambda c:(MoveCard(first(c),2,Zone.HAND,source_id=c.source_id),),
        'overflow.copy.current':lambda c:(AddToHand(1,'plain'),CopyCard(first(c),1,mode='current',source_id=c.source_id)),
        'overflow.copy.base':lambda c:(AddToHand(1,'plain'),CopyCard(first(c),1,mode='base',source_id=c.source_id)),
        'overflow.temporary':lambda c:(AddToHand(1,'plain'),CreateTemporaryCard(1,NATIVE,c.state.turn,source_id=c.source_id)),
        'overflow.system':lambda c:(AddToHand(1,'plain'),AddToHand(1,NATIVE)),
        'overflow.void':lambda c:(SendDeckToVoid(1,c.source_id),AddToHand(1,'plain'),GetFromVoid(1,1,c.source_id)),
        'overflow.passage':lambda c:(ReplaceHandWithTemporaryDeckCards(1,1,c.source_id),),
        'overflow.fill':lambda c:tuple(AddToHand(1,'plain',c.source_id) for _ in range(10)),
        'overflow.late.fault':lambda c:(*create(c,'overflow.probe'),InvokeBehavior('overflow.fault',c.source_id,c.player_id)),
        'overflow.unclassified':lambda c:(UnclassifiedBurn(first(c).entity_id),),
    }
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    r.register_behavior('overflow.observer',lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),))
    r.register_card(CardDefinition('overflow.observer','Burn listener',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_burned','overflow.observer'),),metadata=metadata()))
    return r

class NativeOverflowTests(unittest.TestCase):
    def game(self,hand=('overflow.draw',)+('plain',)*9,deck=('plain',NATIVE,'plain','plain'),enemy_hand=(),board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,deck=deck,board=board,max_mana=10,mana=10),
            PlayerSetup('hero',hand=enemy_hand,deck=('plain',)*6,max_mana=10,mana=10)),seed=153),registry())
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def rows(self,g):return [destruction_result(e) for e in g._events if e.kind=='card_burned' and destruction_result(e) is not None]
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h
    def queued(self,g):
        return next(w for w in (*g._frame.prefix,*g._frame.continuation) if type(w)is BehaviorCall and
            w.context.trigger is not None and w.context.trigger.kind=='on_destroyed')
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_complete_pin_preserves_only_necessary_native_source(self):
        v=evidence();self.assertEqual(len(v['records']),4)
        row=next(x for x in v['records'] if x['id']==NATIVE)
        actual=next(x for x in json.loads((ROOT/'tests/fixtures/extracted/cards.json').read_bytes()) if x['id']==NATIVE)
        self.assertEqual(row,actual);self.assertEqual(registry().card(NATIVE).on_destroyed,'draw2')
        self.assertNotIn('WW_044t',registry().cards)

    def test_overdraw_runs_native_draw_two_without_cast_discard_or_death(self):
        g=self.game();self.play(g,'overflow.draw')
        self.assertEqual(len(g.state.draw_history),4);self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.discard_history,[]);self.assertEqual(g.state.death_history,[])
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.players[1].deck),0)
        fuel=next(r for r in self.rows(g) if r.card.card_id==NATIVE)
        self.assertEqual((fuel.profile,fuel.card.zone,fuel.player_id),('stored_overflow',Zone.DECK,1));self.portable(g)

    def test_generated_overflow_accepts_newborn_identity(self):
        g=self.game(hand=('overflow.create',)+('plain',)*9,deck=('plain',)*4);self.play(g,'overflow.create')
        fuel=next(r for r in self.rows(g) if r.card.card_id==NATIVE)
        self.assertEqual((fuel.profile,fuel.card.zone_epoch,fuel.after_epoch),('created_overflow',0,0))
        self.assertEqual(fuel.card.entity_id,fuel.card.next_entity_id-1);self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_generated_foreign_body_belongs_to_receiver(self):
        g=self.game(hand=('overflow.enemy.create',),enemy_hand=('plain',)*10);self.play(g,'overflow.enemy.create')
        fuel=next(r for r in self.rows(g) if r.card.card_id==NATIVE)
        self.assertEqual((fuel.owner_id,fuel.player_id,fuel.card.controller),(2,2,2))
        self.assertEqual(len(g.state.players[2].deck),4);self.portable(g)

    def test_hand_transfer_overflow_preserves_owner_and_receiving_controller(self):
        g=self.game(hand=(NATIVE,'overflow.send'),enemy_hand=('plain',)*10);original=g.state.players[1].hand[0]
        self.play(g,'overflow.send');row=next(r for r in self.rows(g) if r.card.entity_id==original)
        self.assertEqual((row.profile,row.card.zone,row.card.owner,row.card.controller,row.player_id),
            ('stored_overflow',Zone.HAND,1,1,2))
        self.assertEqual((g.state.entities[original].owner,g.state.entities[original].controller),(1,2));self.portable(g)

    def test_current_and_base_copy_burn_only_the_new_entity(self):
        for mode in ('current','base'):
            with self.subTest(mode=mode):
                cid='overflow.copy.'+mode;g=self.game(hand=(NATIVE,cid)+('plain',)*8,deck=('plain',)*4)
                original=g.state.players[1].hand[0];self.play(g,cid)
                row=next(r for r in self.rows(g) if r.card.card_id==NATIVE)
                self.assertEqual(row.profile,'created_overflow');self.assertNotEqual(row.card.entity_id,original)
                self.assertIn(original,g.state.players[1].hand);self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_temporary_created_overflow_uses_same_native_acceptance(self):
        g=self.game(hand=('overflow.temporary',)+('plain',)*9,deck=('plain',)*4);self.play(g,'overflow.temporary')
        fuel=next(r for r in self.rows(g) if r.card.card_id==NATIVE)
        self.assertEqual(fuel.profile,'created_overflow');self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_source_less_creation_keeps_independent_native_actor(self):
        g=self.game(hand=('overflow.system',)+('plain',)*9,deck=('plain',)*4);self.play(g,'overflow.system')
        fuel=next(r for r in self.rows(g) if r.card.card_id==NATIVE);self.assertIsNone(fuel.source_id)
        self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_nested_fuel_burns_remain_independent_real_occurrences(self):
        g=self.game(deck=('plain',NATIVE,NATIVE,'plain','plain','plain'));self.play(g,'overflow.draw')
        fuels=[r for r in self.rows(g) if r.card.card_id==NATIVE]
        self.assertEqual(len(fuels),2);self.assertEqual(len({r.card.entity_id for r in fuels}),2)
        self.assertEqual(len(g.state.draw_history),6);self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_ordinary_burn_still_has_no_native_or_board_death(self):
        g=self.game(deck=('plain',)*4);self.play(g,'overflow.draw')
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(len(self.rows(g)),1)
        self.assertEqual(g.state.death_history,[]);self.assertEqual(self.armor(g),0);self.portable(g)

    def test_void_overflow_preserves_setaside_residence(self):
        g=self.game(hand=('overflow.void',)+('plain',)*9,deck=('overflow.probe',)*2);self.play(g,'overflow.void')
        row=next(r for r in self.rows(g) if r.card.card_id=='overflow.probe')
        self.assertEqual((row.profile,row.card.zone),('setaside_overflow',Zone.SETASIDE))
        self.assertEqual(self.armor(g),3);self.assertEqual(g.state.players[1].void_cards,());self.portable(g)

    def test_original_temporary_hand_overflow_accepts_after_group_restore(self):
        g=self.game(hand=('overflow.probe','overflow.passage'),deck=('overflow.fill',))
        self.play(g,'overflow.passage');self.play(g,'overflow.fill')
        g.apply(EndTurn(1));g.apply(EndTurn(2))
        row=next(r for r in self.rows(g) if r.card.card_id=='overflow.probe')
        self.assertEqual((row.profile,row.card.zone),('setaside_overflow',Zone.SETASIDE))
        # Owner-start natural draw follows restoration and spends one Armor on fatigue.
        self.assertEqual(self.armor(g),2);self.portable(g)

    def test_burn_listener_waits_before_native_body(self):
        g=self.game(hand=('overflow.probe.create',)+('plain',)*9,board=('overflow.observer',))
        self.play(g,'overflow.probe.create');self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.armor(g),0);call=self.queued(g)
        self.assertEqual(call.context.destruction.profile,'created_overflow')
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(self.armor(g),3);self.portable(g)

    def test_native_waiting_body_restores_its_original_generated_fact(self):
        g=self.game(hand=('overflow.wait.create',)+('plain',)*9);self.play(g,'overflow.wait.create')
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(self.armor(g),7);self.portable(g)

    def test_native_fault_rolls_back_creation_and_public_burn(self):
        g=self.game(hand=('overflow.fault.create',)+('plain',)*9);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'overflow.fault.create')
        self.assertEqual(g.snapshot(),before)

    def test_late_fault_rolls_back_native_reward_and_allocation(self):
        g=self.game(hand=('overflow.late.fault',)+('plain',)*9);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'overflow.late.fault')
        self.assertEqual(g.snapshot(),before)

    def test_failed_native_choice_preserves_original_waiting_state(self):
        g=self.game(hand=('overflow.wait.create',)+('plain',)*9);self.play(g,'overflow.wait.create');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_typed_frame_roundtrip_and_original_boundaries(self):
        g=self.game(hand=('overflow.probe.create',)+('plain',)*9,board=('overflow.observer',));self.play(g,'overflow.probe.create')
        call=self.queued(g);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state,origin_events=g._events)
        self.assertEqual(codec.decode(codec.encode(call)),call)
        for c in (replace(call.context,player_id=2),replace(call.context,event=None),
            replace(call.context,cast=g.state.cast_history[0]),replace(call.context,draw=g.state.draw_history[0] if g.state.draw_history else object())):
            with self.subTest(context=c),self.assertRaises(ValueError):codec.encode(replace(call,context=c))

    def test_rehashed_birth_owner_epoch_and_receiver_tampering_reject(self):
        g=self.game(hand=('overflow.probe.create',)+('plain',)*9);self.play(g,'overflow.probe.create');base=g.snapshot()
        for field,value in (('profile','stored_overflow'),('recipient_id',2),('turn',999999)):
            s=deepcopy(base);e=next(e for e in s['events'] if e['kind']=='card_burned' and 'burn_destruction' in e['data'])
            payload=e['data']['burn_destruction'];next(row for row in payload if row[0]==field)[1]=value;self.reject(s)
        for field,value in (('owner',2),('zone_epoch',1),('next_entity_id',999999)):
            s=deepcopy(base);e=next(e for e in s['events'] if e['kind']=='card_burned' and 'burn_destruction' in e['data'])
            original=next(row[1] for row in e['data']['burn_destruction'] if row[0]=='original')
            next(row for row in original if row[0]==field)[1]=value;self.reject(s)

    def test_duplicate_physical_retirement_receipt_is_rejected(self):
        g=self.game(hand=('overflow.probe.create',)+('plain',)*9);self.play(g,'overflow.probe.create');s=g.snapshot()
        event=deepcopy(next(e for e in s['events'] if e['kind']=='card_burned'))
        event['sequence']=len(s['events'])+1;s['events'].append(event);self.reject(s)

    def test_retained_graveyard_delivery_is_not_reinterpreted_as_board_death(self):
        from test_retained_discard_return_basics import RetainedDiscardReturnTests
        fixture=RetainedDiscardReturnTests();g=fixture.game(board=('fill',));fixture.play(g,'discard')
        row=next(destruction_result(e) for e in g._events if e.kind=='card_burned')
        self.assertEqual((row.profile,row.card.zone),('graveyard_delivery_overflow',Zone.GRAVEYARD))
        self.assertEqual(g.state.death_history,[]);self.assertEqual(len(g.state.discard_history),1)
        fixture.portable(g)

    def test_unclassified_native_producer_errors_without_silent_body_loss(self):
        m=default_mechanics(version='native-overflow-negative-boundary-v1')
        def burn(r,e):
            r.emit('card_burned',target_id=e.target_id,player_id=1)
            return ()
        m.register(UnclassifiedBurn,burn)
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=(NATIVE,'overflow.unclassified'),max_mana=10,mana=10),
            PlayerSetup('hero')),seed=153),registry(),mechanics=m)
        before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'original supported overflow profile'):
            self.play(g,'overflow.unclassified')
        self.assertEqual(g.snapshot(),before)

    def test_player_boundary_never_exposes_original_allocation_or_profile(self):
        g=self.game(hand=('overflow.wait.create',)+('plain',)*9);self.play(g,'overflow.wait.create');before=g.snapshot()
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe());events=json.dumps(g.for_player(p).events())
            g.for_player(p).legal_actions()
            for key in ('burn_destruction','SourceAllocationFact','next_entity_id','next_order','created_overflow','zone_epoch','resolution_frame'):
                self.assertNotIn(key,view);self.assertNotIn(key,events)
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

if __name__=='__main__':unittest.main()
