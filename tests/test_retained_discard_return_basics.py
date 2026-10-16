"""Original successful-discard material, numeric growth and retained return."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game,
    PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, Zone, discarded_cards)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discard_history import validate_frame_materials
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.temporary_cards import MakeHandCardTemporary
from hs_sim.engine.zones import (CardReference, ChooseFromZone, CopyCard, DiscardCard,
    DiscardMatching, MoveCard)
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

NATIVE='UNG_836'
PATH=Path(__file__).resolve().parents[1]/'data/support/retained-discard-return-basics.json'
PIN='228b92292808ba78d9a698bf5f2522318aee78626ded2698d340003417fa5a8f'


def evidence():
    data=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=PIN:raise ValueError('Retained discard raw evidence changed')
    row=data['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw row changed')
    return row['data']


def native_ref(c,player=None):
    p=c.player_id if player is None else player
    return CardReference.capture(next(c.state.entities[i]for i in c.state.players[p].hand if c.state.entities[i].card_id==NATIVE))


def registry():
    r=Registry('isolated-retained-discard-return-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('a','Whiteboard',CardType.MINION,cost=1,attack=1,health=20,metadata=metadata()))
    r.register_card(CardDefinition('b','Blank spell',CardType.SPELL,metadata=metadata()))
    def own(c):
        if c.discard is None:raise ValueError('Native return lost discard fact')
        return (BuffStoredCard(c.discard,2,2,source_id=c.source_id),ReturnToHand(c.source_id,discard=c.discard))
    r.register_behavior('native.return',own)
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        on_discard='native.return',metadata=metadata(CardClass.WARLOCK,rarity=Rarity.LEGENDARY,tribes=('beast',))))
    def fault(c):raise RuntimeError('Deliberate return fault')
    r.register_behavior('fault',fault)
    def original_then_repeat(c):
        ref=native_ref(c);return (DiscardCard(ref,c.source_id),DiscardCard(ref,c.source_id))
    def latest(c):return c.state.discard_history[-1]
    scripts={
        'discard':lambda c:(DiscardCard(native_ref(c),c.source_id),),
        'private':lambda c:(DiscardCard(native_ref(c),c.source_id,False),),
        'enemy':lambda c:(DiscardCard(native_ref(c,3-c.player_id),c.source_id),),
        'multi':lambda c:(DiscardMatching(c.player_id,count=2,selection='first',source_id=c.source_id),),
        'stale.discard':original_then_repeat,
        'chosen':lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.HAND,operation='discard',sample_size=None,distinct='entity',source_id=c.source_id),),
        'buff':lambda c:(BuffStoredCard(native_ref(c),3,4,source_id=c.source_id),),
        'temporary':lambda c:(MakeHandCardTemporary(native_ref(c),c.state.turn,source_id=c.source_id),),
        'copyhand':lambda c:(CopyCard(native_ref(c),c.player_id,source_id=c.source_id),),
        'transfer':lambda c:(MoveCard(native_ref(c),2,Zone.HAND,source_id=c.source_id),),
        'latefault':lambda c:(DiscardCard(native_ref(c),c.source_id),InvokeBehavior('fault',c.source_id,c.player_id)),
        'oldreturn':lambda c:(ReturnToHand(latest(c).entity_id,discard=latest(c)),),
        'oldbuff':lambda c:(BuffStoredCard(latest(c),2,2,source_id=latest(c).entity_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),
    }
    targeted={'bounce':lambda c:(ReturnToHand(c.target_id),),'silence':lambda c:(Silence(c.target_id),)}
    for cid,body in {**scripts,**targeted}.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=cid in targeted,metadata=metadata()))
    def before(c):
        if c.event.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior('fault',c.source_id,c.player_id),))),c.source_id),)
    def after_buff(c):
        if c.event.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
    def fill(c):
        if c.event.player_id!=c.player_id:return ()
        return tuple(AddToHand(c.player_id,'b')for _ in range(10))
    for cid,event,body in (('before','card_discarded',before),('afterbuff','stored_card_buffed',after_buff),('fill','card_discarded',fill)):
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=20,triggers=(TriggerSpec(event,cid),),metadata=metadata()))
    return r


class RetainedDiscardReturnTests(unittest.TestCase):
    def game(self,hand=('discard',NATIVE),board=(),enemy_hand=(),deck=('b',)*6):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,deck=('b',)*6,mana=10,max_mana=10),
        ),seed=52),registry())
    def play(self,g,cid,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target));return eid
    def native(self,g,player=1):return next(e for e in g.state.entities.values()if e.card_id==NATIVE and e.controller==player)
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())
    def after_buff(self):
        g=self.game(board=('afterbuff',));self.play(g,'discard');return g
    def queued_return(self,g):
        return next(w for w in(*g._frame.prefix,*g._frame.continuation)if type(w)is ReturnToHand and w.discard is not None)

    def test_complete_raw_pin_and_native_growth_return_declaration(self):
        raw=evidence();original=next(x for x in json.loads((PATH.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))if x['id']==NATIVE)
        self.assertEqual(raw,original);card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.attack,card.health,card.on_discard),(2,2,2,'native.return'))
        self.assertEqual((card.metadata.classes,card.metadata.rarity,card.metadata.tribes),((CardClass.WARLOCK,),Rarity.LEGENDARY,('beast',)))
        self.assertNotIn('TRL_252',registry().cards)

    def test_success_returns_same_physical_entity_and_keeps_native_ability(self):
        g=self.game();e=self.native(g);ids=[a.id for a in e.abilities];allocation=g.state.next_entity_id;cause=self.play(g,'discard');after=self.native(g)
        self.assertEqual((after.id,after.zone,after.attack,after.health),(e.id,Zone.HAND,4,4))
        self.assertEqual(g.state.next_entity_id,allocation);self.assertEqual([a.id for a in after.abilities],ids)
        row=discarded_cards(g.state,1)[0];self.assertEqual((row.entity_id,row.source_id),(e.id,cause));self.portable(g)

    def test_real_reacquisition_records_original_graveyard_and_new_hand_entry(self):
        g=self.game();before=self.native(g);self.play(g,'discard');e=self.native(g);entry=g.state.hand_entries[e.hand_entry_id-1]
        self.assertNotEqual(e.hand_entry_id,before.hand_entry_id)
        self.assertEqual((entry.entity_id,entry.from_zone,entry.reason,entry.zone_epoch),(e.id,Zone.GRAVEYARD,'return',before.zone_epoch+2))
        self.assertEqual(discarded_cards(g.state,1)[0].hand_entry_id,before.hand_entry_id);self.portable(g)

    def test_separate_discards_accumulate_growth_without_replacing_old_facts(self):
        g=self.game(('discard',NATIVE,'discard'));original=self.native(g).id;self.play(g,'discard');first=discarded_cards(g.state,1)[0];self.play(g,'discard')
        e=self.native(g);rows=discarded_cards(g.state,1)
        self.assertEqual((e.id,e.attack,e.health),(original,6,6));self.assertEqual(rows[0],first)
        self.assertEqual([r.entity_id for r in rows],[original,original]);self.assertNotEqual(rows[0].hand_entry_id,rows[1].hand_entry_id);self.portable(g)

    def test_existing_matching_loop_requeries_new_acquisition_and_terminates(self):
        g=self.game(('multi',NATIVE));self.play(g,'multi')
        self.assertEqual((self.native(g).attack,len(discarded_cards(g.state,1))),(6,2))
        self.assertEqual(g.state.players[1].hand,[self.native(g).id]);self.portable(g)

    def test_old_physical_discard_reference_cannot_discard_the_new_acquisition(self):
        g=self.game(('stale.discard',NATIVE));self.play(g,'stale.discard')
        self.assertEqual((self.native(g).attack,len(discarded_cards(g.state,1))),(4,1));self.portable(g)

    def test_prior_local_hand_growth_is_retained_and_new_growth_is_added(self):
        g=self.game(('buff',NATIVE,'discard'));self.play(g,'buff');self.play(g,'discard');e=self.native(g)
        self.assertEqual((e.attack,e.health,len(e.enchantments)),(7,8,2));self.portable(g)

    def test_manual_play_keeps_growth_and_normal_board_return_resets_it(self):
        g=self.game(('discard',NATIVE,'bounce'));self.play(g,'discard');eid=self.native(g).id;self.play(g,NATIVE)
        self.assertEqual((self.native(g).zone,self.native(g).attack),(Zone.BOARD,4));self.play(g,'bounce',eid)
        self.assertEqual((self.native(g).id,self.native(g).zone,self.native(g).attack,self.native(g).health),(eid,Zone.HAND,2,2));self.portable(g)

    def test_silence_and_normal_bounce_follow_the_existing_native_lifecycle(self):
        g=self.game(('discard',NATIVE,'silence','bounce','discard'));self.play(g,'discard');eid=self.native(g).id;self.play(g,NATIVE)
        self.play(g,'silence',eid);self.assertFalse(any(a.kind=='on_discard'for a in self.native(g).abilities))
        self.play(g,'bounce',eid);self.play(g,'discard');self.assertEqual((self.native(g).zone,self.native(g).attack),(Zone.HAND,4));self.portable(g)

    def test_full_hand_failure_keeps_discard_and_does_not_create_an_acquisition(self):
        g=self.game(board=('fill',));before=self.native(g);self.play(g,'discard');e=self.native(g)
        self.assertEqual((e.zone,e.zone_epoch,e.hand_entry_id,e.attack),(Zone.GRAVEYARD,before.zone_epoch+2,before.hand_entry_id,4))
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(discarded_cards(g.state,1)),1)
        self.assertEqual(len([x for x in g.events if x.kind=='card_burned']),1);self.portable(g)

    def test_old_return_and_old_growth_skip_after_successful_reacquisition(self):
        g=self.game(('discard',NATIVE,'oldreturn','oldbuff'));self.play(g,'discard');e=self.native(g);self.play(g,'oldreturn');self.play(g,'oldbuff')
        self.assertEqual(self.native(g),e);self.assertEqual(len(discarded_cards(g.state,1)),1)
        self.assertEqual(len([x for x in g.events if x.kind=='zone_target_skipped']),2);self.portable(g)

    def test_return_uses_affected_controller_and_preserves_distinct_original_owner(self):
        g=self.game(('transfer',NATIVE),enemy_hand=('discard',));eid=self.native(g).id;self.play(g,'transfer');g.apply(EndTurn(1));self.play(g,'discard',player=2)
        e=self.native(g,2);self.assertEqual((e.id,e.owner,e.controller,e.zone,e.attack),(eid,1,2,Zone.HAND,4))
        self.assertEqual((discarded_cards(g.state,2)[0].card.owner,discarded_cards(g.state,2)[0].player_id),(1,2));self.portable(g)

    def test_enemy_source_does_not_change_return_recipient(self):
        g=self.game(('enemy',),enemy_hand=(NATIVE,));self.play(g,'enemy')
        self.assertEqual((self.native(g,2).zone,self.native(g,2).attack),(Zone.HAND,4))
        self.assertEqual(g.state.players[1].hand,[]);self.portable(g)

    def test_current_copy_keeps_local_recipe_and_has_distinct_return_identity(self):
        g=self.game(('discard',NATIVE,'copyhand','multi'));self.play(g,'discard');self.play(g,'copyhand')
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==NATIVE]
        self.assertEqual([g.state.entities[i].attack for i in ids],[4,4]);self.play(g,'multi')
        self.assertEqual([r.entity_id for r in discarded_cards(g.state,1)][-2:],ids)
        self.assertEqual([g.state.entities[i].attack for i in ids],[6,6]);self.portable(g)

    def test_old_hand_lease_is_cleared_on_real_retained_reacquisition(self):
        g=self.game(('temporary',NATIVE,'discard'));self.play(g,'temporary');self.assertIsNotNone(self.native(g).hand_lifetime)
        self.play(g,'discard');self.assertIsNone(self.native(g).hand_lifetime);g.apply(EndTurn(1))
        self.assertEqual((self.native(g).zone,self.native(g).attack),(Zone.HAND,4));self.portable(g)

    def test_ordinary_deck_draw_and_manual_play_are_not_discard_returns(self):
        g=self.game(('draw',),deck=(NATIVE,));self.play(g,'draw');eid=self.native(g).id;self.play(g,NATIVE)
        self.assertEqual((self.native(g).id,self.native(g).attack),(eid,2));self.assertEqual(discarded_cards(g.state,1),())
        self.assertFalse(any(x.kind=='card_returned'for x in g.events));self.portable(g)

    def test_choice_before_discard_recovers_the_original_selected_material(self):
        g=self.game(('chosen',NATIVE,'b'));self.play(g,'chosen');h=self.portable(g)
        name=next(x.id for x in g.state.pending_choice.options if x.card_id==NATIVE)
        self.choose(g,name);self.choose(h,name);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual((self.native(g).zone,self.native(g).attack),(Zone.HAND,4));self.portable(g)

    def test_wait_before_native_body_restores_original_record_and_growth_once(self):
        g=self.game(board=('before',));self.play(g,'discard');self.assertEqual((self.native(g).zone,self.native(g).attack),(Zone.GRAVEYARD,2));h=self.portable(g)
        self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual((self.native(g).zone,self.native(g).attack),(Zone.HAND,4));self.portable(g)

    def test_wait_after_growth_keeps_original_return_effect_and_no_double_growth(self):
        g=self.after_buff();e=self.native(g);work=self.queued_return(g)
        self.assertEqual((e.zone,e.attack),(Zone.GRAVEYARD,4));self.assertEqual(work.discard,discarded_cards(g.state,1)[0]);h=self.portable(g)
        self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual((self.native(g).zone,self.native(g).attack,len(self.native(g).enchantments)),(Zone.HAND,4,1));self.portable(g)

    def test_both_waits_restore_each_original_body_without_new_acceptance(self):
        g=self.game(board=('before','afterbuff'));self.play(g,'discard');h=self.portable(g)
        self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.assertIsNotNone(g.state.pending_choice)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual((self.native(g).zone,self.native(g).attack,len(discarded_cards(g.state,1))),(Zone.HAND,4,1));self.portable(g)

    def test_choice_failure_restores_waiting_then_accepts_original_return_once(self):
        g=self.game(board=('before',));self.play(g,'discard');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.assertEqual(self.native(g).attack,4);self.portable(g)

    def test_late_failure_rolls_back_growth_return_acquisition_and_discard(self):
        g=self.game(('latefault',NATIVE));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'latefault')
        self.assertEqual(g.snapshot(),before);self.assertEqual(discarded_cards(g.state,1),())

    def test_frame_material_requires_actual_committed_occurrence(self):
        g=self.after_buff();work=self.queued_return(g)
        for fields in ({'event_sequence':work.discard.event_sequence+1},{'hand_entry_id':work.discard.hand_entry_id+1},
                       {'id':work.discard.id+1}):
            row=replace(work.discard,**fields);bad=replace(work,discard=row)
            frame=replace(g._frame,continuation=tuple(bad if x==work else x for x in g._frame.continuation),
                prefix=tuple(bad if x==work else x for x in g._frame.prefix))
            with self.subTest(fields=fields),self.assertRaises(ValueError):validate_frame_materials(g.state,g.registry,frame)

    def test_rehashed_waiting_frame_cannot_borrow_a_false_discard_fact(self):
        g=self.after_buff();work=self.queued_return(g);bad=replace(work,discard=replace(work.discard,event_sequence=work.discard.event_sequence+1))
        frame=replace(g._frame,continuation=tuple(bad if x==work else x for x in g._frame.continuation),
            prefix=tuple(bad if x==work else x for x in g._frame.prefix))
        s=g.snapshot();s['resolution_frame']=FrameCodec(g.mechanics,g.registry).encode(frame);self.reject(s)

    def test_typed_effect_roundtrip_keeps_original_reference_without_broadening_card_zones(self):
        g=self.after_buff();work=self.queued_return(g);codec=FrameCodec(g.mechanics,g.registry)
        self.assertEqual(codec.decode(codec.encode(work)),work)
        with self.assertRaises(ValueError):CardReference.capture(self.native(g))
        self.portable(g)

    def test_closed_discard_profile_rejects_unrelated_cost_owner_expiry_or_source(self):
        g=self.after_buff();row=discarded_cards(g.state,1)[0]
        for fields in ({'target_id':row.entity_id+1},{'to_owner':True},{'cost':CostSpec(set_to=1)},{'discard':{}}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):ReturnToHand(**{'target_id':row.entity_id,'discard':row,**fields})
        for fields in ({'cost':CostSpec(set_to=1)},{'expires_turn':g.state.turn},{'source_id':g.state.players[1].hero_id}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):BuffStoredCard(row,2,2,**fields)

    def test_source_and_original_history_stay_private_in_player_ports(self):
        g=self.after_buff();before=g.snapshot()
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe());g.for_player(player).legal_actions()
            for field in('discard_history','hand_entry_id','resolution_frame','zone_epoch','behavior_id','RuleContext'):
                self.assertNotIn(field,view)
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_private_discard_and_return_never_reveal_unknown_original_face(self):
        g=self.game(('private',NATIVE));self.play(g,'private')
        self.assertFalse(discarded_cards(g.state,1)[0].reveal);self.assertEqual(self.native(g).zone,Zone.HAND)
        view=json.dumps(g.observe(2));self.assertNotIn('"card_id": "UNG_836"',view);self.assertNotIn('discard_history',view);self.portable(g)

    def test_retained_return_is_neither_new_card_nor_cast_play_draw_or_death(self):
        g=self.game();cause=self.play(g,'discard')
        self.assertEqual([x.source_id for x in g.state.play_history],[cause]);self.assertEqual([x.source_id for x in g.state.cast_history],[cause])
        self.assertEqual(g.state.draw_history,[]);self.assertEqual(g.state.death_history,[])
        self.assertFalse(any(x.kind=='card_created'for x in g.events));self.assertEqual(g.snapshot()['schema_version'],SNAPSHOT_SCHEMA_VERSION);self.portable(g)
