"""Native own-discard body acceptance, using the original effects and frames."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (AbilityInstance, CardClass, CardDefinition, CardType, EndTurn,
    Game, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, SpellSchool, TriggerSpec, Zone, discarded_cards)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discard_history import validate_call
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Destroy, Draw, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.model import validate_invariants
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import BehaviorCall
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import (CardReference, ChooseFromZone, CopyCard, DiscardCard,
    DiscardMatching, MoveCard)
from hs_sim.engine.pools import PoolQuery
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

NATIVE='BT_300'
PATH=Path(__file__).resolve().parents[1]/'data/support/own-discard-body-basics.json'
PIN='00e641b36f881c9826e5c07507cf43381a15b177049a640fbc2cf4a21597434e'


def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Own-discard raw evidence changed')
    row=support['records'][0]
    if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw card changed')
    return row['data']


def first(c,player=None):
    p=c.player_id if player is None else player
    return CardReference.capture(c.state.entities[c.state.players[p].hand[0]])


def registry():
    r=Registry('isolated-own-discard-body-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_behavior('native.draw3',lambda c:(Draw(c.player_id,3,c.source_id),))
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.SPELL,cost=raw['cost'],
        on_play='native.draw3',on_discard='native.draw3',spell_school=SpellSchool.SHADOW,
        metadata=metadata(CardClass.WARLOCK,rarity=Rarity.COMMON)))
    r.register_card(CardDefinition('a','a',CardType.MINION,cost=1,attack=1,health=20,metadata=metadata()))
    r.register_card(CardDefinition('b','b',CardType.SPELL,metadata=metadata()))

    def armor(c):
        # A synthetic context probe, not an adapter for a real summon card.
        if c.discard is None or c.source.zone!=Zone.GRAVEYARD:raise ValueError('Missing own-discard fact')
        return (GainArmor(c.player_id,c.discard.id),)
    r.register_behavior('fixture.armor',armor)
    r.register_card(CardDefinition('own.fixture','Own-discard probe',CardType.MINION,
        attack=1,health=20,on_discard='fixture.armor',metadata=metadata()))

    def selected(c):
        # Existing on_select uses a fresh context; original operands are frozen
        # in the choice effects rather than inferred from another body root.
        if c.discard is not None or c.choice is None:raise ValueError('Wrong selection context')
        return ()
    r.register_behavior('fixture.selected',selected)

    def waiting(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('draw','Draw',(Draw(c.player_id,2,c.source_id),)),
            ChoiceOption('armor','Original occurrence',(GainArmor(c.player_id,c.discard.id),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('fixture.fault',c.source_id,c.player_id),)),
        ),c.source_id,on_select='fixture.selected'),GainArmor(c.player_id,1))
    r.register_behavior('fixture.wait',waiting)
    r.register_card(CardDefinition('own.wait','Own-discard choice probe',CardType.SPELL,
        on_discard='fixture.wait',metadata=metadata()))
    def fault(c):raise RuntimeError('Deliberate own-discard fault')
    r.register_behavior('fixture.fault',fault)
    r.register_behavior('fixture.badwork',lambda c:(object(),))
    for cid,body in (('own.fault','fixture.fault'),('own.badwork','fixture.badwork')):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_discard=body,metadata=metadata()))

    def reference_twice(c):
        ref=first(c);return (DiscardCard(ref,c.source_id),DiscardCard(ref,c.source_id))
    def wait_observer(c):
        if c.event.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),)
    r.register_behavior('observer.wait',wait_observer)
    r.register_card(CardDefinition('observer','Discard observer',CardType.MINION,health=20,
        triggers=(TriggerSpec('card_discarded','observer.wait'),),metadata=metadata()))
    scripts={
        'discard':lambda c:(DiscardCard(first(c),c.source_id),),
        'private':lambda c:(DiscardCard(first(c),c.source_id,False),),
        'bare':lambda c:(DiscardCard(first(c)),),
        'enemy':lambda c:(DiscardCard(first(c,3-c.player_id),c.source_id),),
        'twice':reference_twice,
        'many':lambda c:(DiscardMatching(c.player_id,count=2,selection='first',source_id=c.source_id),),
        'chosen':lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.HAND,PoolQuery(),'discard',None,'entity',c.source_id),),
        'transfer':lambda c:(MoveCard(first(c),2,Zone.HAND,source_id=c.source_id),),
        'move':lambda c:(MoveCard(first(c),c.player_id,Zone.DECK,position='top',source_id=c.source_id),),
        'stale':lambda c:(MoveCard(first(c),c.player_id,Zone.DECK,position='top'),DiscardCard(first(c),c.source_id)),
        'copyhand':lambda c:(CopyCard(first(c),c.player_id,source_id=c.source_id),),
        'draw3':lambda c:(Draw(c.player_id,3,c.source_id),),
        'latefault':lambda c:(DiscardCard(first(c),c.source_id),InvokeBehavior('fixture.fault',c.source_id,c.player_id)),
    }
    targeted={
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'away':lambda c:(Transform(c.target_id,'a'),),
        'into':lambda c:(Transform(c.target_id,'own.fixture'),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'basecopy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
    }
    for cid,body in {**scripts,**targeted}.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            requires_target=cid in targeted,metadata=metadata()))
    return r


class OwnDiscardBodyTests(unittest.TestCase):
    def game(self,hand=('discard',NATIVE),board=(),enemy_hand=(),deck=('a','b')*5):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,deck=('a','b')*5,mana=10,max_mana=10),
        ),seed=50),registry())
    def play(self,g,cid,target=None,player=1):
        eid=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target));return eid
    def armor(self,g,player=1):return g.state.entities[g.state.players[player].hero_id].armor
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h
    def queued(self,g):
        return next(w for w in (*g._frame.prefix,*g._frame.continuation)
            if type(w)is BehaviorCall and w.context.discard is not None)
    def waiting_native(self):
        g=self.game(board=('observer',));self.play(g,'discard');return g
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_complete_raw_pin_and_only_necessary_native_draw_adapter(self):
        raw=evidence();original=next(x for x in json.loads((PATH.parents[1]/'extracted/cards.json').read_text(encoding='utf-8'))if x['id']==NATIVE)
        self.assertEqual(raw,original);card=registry().card(NATIVE)
        self.assertEqual((card.kind,card.cost,card.on_play,card.on_discard),(CardType.SPELL,6,'native.draw3','native.draw3'))
        self.assertEqual((card.metadata.classes,card.metadata.rarity),((CardClass.WARLOCK,),Rarity.COMMON))
        self.assertEqual((raw['tags']['SPELL_SCHOOL'],card.spell_school),(6,SpellSchool.SHADOW))
        self.assertNotIn('KAR_205',registry().cards)

    def test_own_discard_draws_three_from_its_original_source(self):
        g=self.game();eid=g.state.players[1].hand[-1];cause=self.play(g,'discard')
        self.assertEqual(len(g.state.players[1].hand),3)
        self.assertEqual([e.source_id for e in g.events if e.kind=='card_drawn'],[eid]*3)
        self.assertEqual((len(discarded_cards(g.state,1)),g.state.entities[eid].zone),(1,Zone.GRAVEYARD))
        self.assertEqual(discarded_cards(g.state,1)[0].source_id,cause);self.portable(g)

    def test_manual_play_uses_ordinary_cast_without_discard_occurrence(self):
        g=self.game((NATIVE,));eid=self.play(g,NATIVE)
        self.assertEqual(len(g.state.players[1].hand),3);self.assertEqual(discarded_cards(g.state,1),())
        self.assertEqual([x.source_id for x in g.state.cast_history],[eid]);self.portable(g)

    def test_discard_body_does_not_add_an_extra_play_or_cast(self):
        g=self.game();cause=self.play(g,'discard')
        self.assertEqual([x.source_id for x in g.state.cast_history],[cause])
        self.assertEqual([x.source_id for x in g.state.play_history],[cause]);self.portable(g)

    def test_two_physical_copies_have_two_bodies_without_card_name_dedup(self):
        g=self.game(('many',NATIVE,NATIVE));ids=g.state.players[1].hand[1:];self.play(g,'many')
        self.assertEqual([r.entity_id for r in discarded_cards(g.state,1)],ids)
        self.assertEqual([e.source_id for e in g.events if e.kind=='card_drawn'],[ids[0]]*3+[ids[1]]*3)
        self.assertEqual(len(g.state.players[1].hand),6);self.portable(g)

    def test_stale_second_discard_cannot_repeat_the_accepted_body(self):
        g=self.game(('twice',NATIVE));self.play(g,'twice')
        self.assertEqual(len(discarded_cards(g.state,1)),1);self.assertEqual(len(g.state.players[1].hand),3);self.portable(g)

    def test_no_cause_is_valid_and_body_source_is_still_the_card(self):
        g=self.game(('bare',NATIVE));self.play(g,'bare')
        self.assertIsNone(discarded_cards(g.state,1)[0].source)
        self.assertEqual(len(g.state.players[1].hand),3);self.portable(g)

    def test_enemy_discard_runs_for_original_hand_controller(self):
        g=self.game(('enemy',),enemy_hand=(NATIVE,));self.play(g,'enemy')
        self.assertEqual(len(g.state.players[2].hand),3);self.assertEqual(g.state.players[1].hand,[])
        self.assertEqual(len(discarded_cards(g.state,2)),1);self.portable(g)

    def test_original_owner_is_distinct_from_current_discard_controller(self):
        g=self.game(('transfer',NATIVE),enemy_hand=('discard',));eid=g.state.players[1].hand[-1]
        self.play(g,'transfer');g.apply(EndTurn(1));self.play(g,'discard',player=2)
        row=discarded_cards(g.state,2)[0];self.assertEqual((row.entity_id,row.card.owner,row.player_id),(eid,1,2))
        self.assertEqual(len([e for e in g.events if e.kind=='card_drawn'and e.source_id==eid]),3);self.portable(g)

    def test_full_hand_burns_use_original_draw_limit_and_not_discard_history(self):
        g=self.game(('discard',NATIVE)+('b',)*8);self.play(g,'discard')
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)
        self.assertEqual(len(discarded_cards(g.state,1)),1);self.portable(g)

    def test_empty_deck_uses_original_three_fatigue_payments(self):
        g=self.game(deck=());self.play(g,'discard');hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((g.state.players[1].fatigue,hero.damage),(3,6));self.portable(g)

    def test_successful_discard_is_distinct_from_burn_move_and_board_death(self):
        g=self.game(('move',NATIVE));self.play(g,'move');self.assertEqual(len(g.state.players[1].hand),0)
        self.assertEqual(discarded_cards(g.state,1),())
        g=self.game(('kill',),board=('own.fixture',));self.play(g,'kill',g.state.players[1].board[0])
        self.assertEqual(self.armor(g),0);self.assertEqual(discarded_cards(g.state,1),());self.portable(g)
        g=self.game(('draw3',)+('b',)*9,deck=(NATIVE,'b','b'));self.play(g,'draw3')
        self.assertEqual(discarded_cards(g.state,1),());self.assertEqual(len(g.state.players[1].deck),0);self.portable(g)

    def test_reference_moved_to_deck_does_not_run_a_discard_body(self):
        g=self.game(('stale',NATIVE));self.play(g,'stale')
        self.assertEqual(discarded_cards(g.state,1),());self.assertEqual(g.state.players[1].hand,[]);self.portable(g)

    def test_choice_before_discard_has_no_premature_body_and_restores(self):
        g=self.game(('chosen',NATIVE,'b'));self.play(g,'chosen')
        self.assertEqual(discarded_cards(g.state,1),());h=self.portable(g)
        q=g.state.pending_choice;name=next(x.id for x in q.options if x.card_id==NATIVE)
        self.choose(g,name);self.choose(h,name);self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_original_listener_wait_keeps_detached_native_acceptance(self):
        g=self.waiting_native();call=self.queued(g);row=call.context.discard
        self.assertEqual((call.behavior_id,call.context.source_id,call.context.player_id),('native.draw3',row.entity_id,1))
        self.assertEqual((call.context.source.zone,call.context.source.card_id),(Zone.GRAVEYARD,NATIVE))
        self.assertEqual(call.context.event.sequence,row.event_sequence)
        self.assertTrue(all(getattr(call.context,n)is None for n in ('play','cast','draw','power','physical','battlecry','combo')))
        self.assertEqual(len(g.state.players[1].hand),0)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(len(g.state.players[1].hand),3);self.portable(g)

    def test_own_body_choice_restores_original_frozen_effects_and_tail(self):
        g=self.game(('discard','own.wait'));self.play(g,'discard');h=self.portable(g)
        self.choose(g,'armor');self.choose(h,'armor');self.assertEqual(g.snapshot(),h.snapshot())
        self.assertEqual(self.armor(g),2);self.assertEqual(len(discarded_cards(g.state,1)),1);self.portable(g)

    def test_own_body_choice_draw_branch_uses_the_existing_interpreter(self):
        g=self.game(('discard','own.wait'));self.play(g,'discard');self.choose(g,'draw')
        self.assertEqual((len(g.state.players[1].hand),self.armor(g)),(2,1));self.portable(g)

    def test_selection_failure_restores_the_original_waiting_boundary(self):
        g=self.game(('discard','own.wait'));self.play(g,'discard');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g,'armor');self.assertEqual(self.armor(g),2);self.portable(g)

    def test_body_and_later_failures_rollback_whole_original_action(self):
        for hand in (('discard','own.fault'),('discard','own.badwork'),('latefault',NATIVE)):
            with self.subTest(hand=hand):
                g=self.game(hand);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,hand[0])
                self.assertEqual(g.snapshot(),before);self.assertEqual(discarded_cards(g.state,1),())

    def test_current_hand_copy_installs_distinct_native_source(self):
        g=self.game(('copyhand',NATIVE,'many'));self.play(g,'copyhand')
        ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==NATIVE]
        self.assertEqual(len(ids),2);self.assertNotEqual(ids[0],ids[1])
        for eid in ids:
            e=g.state.entities[eid];self.assertEqual(len([a for a in e.abilities if a.kind=='on_discard']),1)
        self.play(g,'many');self.assertEqual([x.entity_id for x in discarded_cards(g.state,1)],ids)
        self.assertEqual(len([x for x in g.events if x.kind=='card_drawn']),6)
        self.portable(g)

    def test_silence_removes_native_and_bounce_restores_printed_declaration(self):
        g=self.game(('silence','copy','basecopy','bounce'),board=('own.fixture',));eid=g.state.players[1].board[0]
        self.play(g,'silence',eid);self.play(g,'copy',eid);self.play(g,'basecopy',eid)
        copied=g.state.players[1].board[-2:]
        self.assertEqual([len([a for a in g.state.entities[i].abilities if a.kind=='on_discard'])for i in copied],[0,1])
        self.play(g,'bounce',eid);e=g.state.entities[eid]
        self.assertEqual((e.zone,len([a for a in e.abilities if a.kind=='on_discard'])),(Zone.HAND,1));self.portable(g)

    def test_transform_replaces_native_body_with_current_printed_face(self):
        g=self.game(('away','into'),board=('own.fixture',));eid=g.state.players[1].board[0]
        self.play(g,'away',eid);self.assertFalse(any(a.kind=='on_discard'for a in g.state.entities[eid].abilities))
        self.play(g,'into',eid);self.assertEqual(len([a for a in g.state.entities[eid].abilities if a.kind=='on_discard']),1);self.portable(g)

    def test_unknown_native_behavior_fails_registry_freeze(self):
        r=Registry('bad');r.register_card(CardDefinition('x','x',CardType.SPELL,on_discard='missing',metadata=metadata()))
        with self.assertRaises(UnsupportedDefinitionError):r.freeze()

    def test_native_definition_requires_physical_hand_playable_card(self):
        for fields in ({'kind':CardType.HERO_POWER},{'kind':CardType.MINION,'health':1,'choice_only':True},
                       {'kind':CardType.SPELL,'on_discard':''},{'kind':CardType.SPELL,'on_discard':True}):
            values={'kind':CardType.SPELL,'on_discard':'body',**fields}
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                r=Registry('bad');r.register_behavior('body',lambda c:());r.register_card(CardDefinition('x','x',metadata=metadata(),**values));r.freeze()

    def test_native_ability_is_removable_and_rejects_optional_grant_payload(self):
        native=AbilityInstance(1,'on_discard',origin='printed',source_id=1,behavior_id='body')
        for fields in ({'origin':'granted'},{'source_id':None},{'expires_turn':1},{'consumed':True},
                       {'remove_on_silence':False},{'magnetic_id':1},{'event':'card_discarded'}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(native,**fields)

    def test_duplicate_or_wrong_native_body_is_rejected_in_carrier(self):
        g=self.game();eid=g.state.players[1].hand[-1]
        for duplicate in (False,True):
            s=g.state;e=s.entities[eid];a=next(a for a in e.abilities if a.kind=='on_discard')
            if duplicate:e.abilities.append(replace(a,id=s.next_attachment_id));s.next_attachment_id+=1
            else:e.abilities=[replace(a,behavior_id='fixture.armor')if x==a else x for x in e.abilities]
            with self.subTest(duplicate=duplicate),self.assertRaises(ValueError):validate_invariants(s,g.registry)

    def test_typed_frame_roundtrip_preserves_original_discard_fact(self):
        g=self.waiting_native();call=self.queued(g);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        decoded=codec.decode(codec.encode(call));self.assertEqual(decoded,call);validate_call(decoded,g.registry)
        self.portable(g)

    def test_frame_rejects_missing_fact_source_player_event_or_body_substitution(self):
        g=self.waiting_native();call=self.queued(g);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state);c=call.context
        contexts=(replace(c,discard=None),replace(c,discard={}),replace(c,source_id=c.event.source_id),
            replace(c,player_id=2),replace(c,event=replace(c.event,sequence=c.event.sequence+1)),
            replace(c,trigger=replace(c.trigger,behavior_id='fixture.armor')),replace(c,cast=g.state.cast_history[0]),
            replace(c,rewind_attempt=1))
        for context in contexts:
            with self.subTest(context=context),self.assertRaises(ValueError):codec.encode(replace(call,context=context))
        with self.assertRaises(ValueError):codec.encode(replace(call,behavior_id='fixture.armor'))

    def test_frame_rejects_original_window_or_post_discard_allocation_changes(self):
        g=self.waiting_native();call=self.queued(g);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        for field in ('turn','action','cursor','zone','face'):
            s=deepcopy(call.context.state)
            if field=='turn':s.turn+=1
            elif field=='action':s.action_number+=1
            elif field=='cursor':s.next_discard_id+=1
            elif field=='zone':s.entities[call.context.source_id].zone=Zone.HAND
            else:s.entities[call.context.source_id].card_id='b'
            with self.subTest(field=field),self.assertRaises(ValueError):codec.encode(replace(call,context=replace(call.context,state=s)))

    def test_rehashed_current_snapshot_cannot_change_native_body(self):
        g=self.game();eid=g.state.players[1].hand[-1];s=g.snapshot()
        a=next(x for x in s['state']['entities'][str(eid)]['abilities']if x['kind']=='on_discard')
        a['behavior_id']='fixture.armor';self.reject(s)

    def test_player_views_are_pure_and_never_contain_private_body_facts(self):
        g=self.waiting_native();before=g.snapshot()
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe());g.for_player(player).legal_actions()
            for key in ('discard_history','hand_entry_id','zone_epoch','resolution_frame','behavior_id','RuleContext','on_discard'):
                self.assertNotIn(key,view)
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_private_original_discard_keeps_original_reveal_policy(self):
        g=self.game(('private','own.fixture'));self.play(g,'private')
        self.assertFalse(discarded_cards(g.state,1)[0].reveal);self.assertEqual(self.armor(g),1)
        view=json.dumps(g.observe(2));self.assertNotIn('"card_id": "own.fixture"',view);self.assertNotIn('discard_history',view);self.portable(g)

    def test_schema_195_rejects_all_older_suspended_protocols(self):
        g=self.waiting_native();s=g.snapshot();self.assertEqual(s['schema_version'],265)
        for version in range(1,218):
            with self.subTest(version=version):bad=deepcopy(s);bad['schema_version']=version;self.reject(bad)
        self.portable(g)
