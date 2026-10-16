"""Stored destruction and native departed-card bodies share the ordinary interpreter."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (AbilityInstance,CardDefinition,CardType,DestroyStoredCard,Game,
    PlayCard,PlayerSetup,Registry,RemoveFromGame,ResolutionError,Scenario,SelectChoice,
    SnapshotError,SpellSchool,TransformStoredCard,TriggerSpec,Zone)
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,Draw,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.representative import build_registry,metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.resolver import BehaviorCall
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import (CardReference,CopyCard,DestroyDeckCard,DiscardCard,MoveCard,
    destruction_result,validate_destroyed_call)
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
NATIVE='WW_441'
PIN='78b7ac157cd9958847a5ae79e67d693f2dcf940b830444720c9aa3465c8c6a72'

def evidence():
    value=json.loads((ROOT/'data/support/stored-destruction-basics.json').read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Stored destruction evidence changed')
    return value

def registry():
    r=Registry('isolated-stored-card-destruction-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,attack=1,health=5,metadata=metadata()))
    r.register_card(CardDefinition('power','Diagnostic replacement power',CardType.HERO_POWER,on_use='discard.armor'))
    r.register_behavior('draw2',lambda c:(Draw(c.player_id,2,c.source_id),))
    raw=next(x for x in evidence()['records'] if x['id']==NATIVE)
    r.register_card(CardDefinition(NATIVE,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.FIRE,
        on_play='draw2',on_discard='draw2',on_destroyed='draw2',metadata=metadata_from_record(raw)))
    def native_armor(c):
        if c.destruction is None or c.source.zone!=Zone.GRAVEYARD:raise ValueError('Missing destroyed acceptance')
        return (GainArmor(c.player_id,3),)
    r.register_behavior('native.armor',native_armor)
    def waiting(c):
        row=c.destruction
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(Draw(c.player_id,2,c.source_id),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('fault',c.source_id,c.player_id),))),c.source_id),
            GainArmor(c.player_id,row.card.entity_id))
    r.register_behavior('native.wait',waiting)
    def fault(c):raise ResolutionError('Deliberate destruction failure')
    r.register_behavior('fault',fault)
    r.register_behavior('bad.work',lambda c:(object(),))
    r.register_behavior('discard.armor',lambda c:(GainArmor(c.player_id,7),))
    for cid,body in (('native.wait','native.wait'),('native.fault','fault'),('native.bad','bad.work')):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_destroyed=body,metadata=metadata()))
    r.register_card(CardDefinition('discard.only','Discard only',CardType.SPELL,on_discard='discard.armor',metadata=metadata()))
    r.register_card(CardDefinition('native.minion','Native minion',CardType.MINION,attack=1,health=5,
        on_destroyed='native.armor',deathrattle='discard.armor',metadata=metadata()))
    for cid,kind,kw in (('weapon',CardType.WEAPON,dict(attack=1,durability=2)),
        ('location',CardType.LOCATION,dict(durability=2,on_use='discard.armor')),
        ('hero.card',CardType.HERO,dict(health=30,hero_card=True,initial_hero_power='power'))):
        r.register_card(CardDefinition(cid,cid,kind,on_destroyed='native.armor',metadata=metadata(),**kw))
    def first(c,zone=Zone.HAND,player=None):
        p=c.player_id if player is None else player
        return CardReference.capture(c.state.entities[getattr(c.state.players[p],zone.value)[0]])
    def two(c):
        ref=first(c);return (DestroyStoredCard(ref,c.source_id),DestroyStoredCard(ref,c.source_id))
    def stale(c):
        ref=first(c)
        return (MoveCard(ref,c.player_id,Zone.DECK,position='top'),
            MoveCard(replace(ref,zone=Zone.DECK,zone_epoch=ref.zone_epoch+1),c.player_id,Zone.HAND),
            DestroyStoredCard(ref,c.source_id))
    scripts={
        'hand':lambda c:(DestroyStoredCard(first(c),c.source_id),),
        'deck':lambda c:(DestroyStoredCard(first(c,Zone.DECK),c.source_id),),
        'old.deck':lambda c:(DestroyDeckCard(first(c,Zone.DECK),c.source_id),),
        'private':lambda c:(DestroyStoredCard(first(c),c.source_id,False),),
        'system':lambda c:(DestroyStoredCard(first(c)),),
        'enemy':lambda c:(DestroyStoredCard(first(c,player=2),c.source_id),),
        'discard':lambda c:(DiscardCard(first(c),c.source_id),),
        'remove':lambda c:(RemoveFromGame((first(c),),c.source_id),),
        'ordinary':lambda c:(Destroy(first(c).entity_id,c.source_id),),
        'two':two,'stale':stale,
        'transform':lambda c:(TransformStoredCard(first(c),'plain'),DestroyStoredCard(first(c),c.source_id)),
        'transfer':lambda c:(MoveCard(first(c),2,Zone.HAND,source_id=c.source_id),),
        'copy':lambda c:(CopyCard(first(c),c.player_id,mode='current'),CopyCard(first(c),c.player_id,mode='base')),
        'late.fault':lambda c:(DestroyStoredCard(first(c),c.source_id),InvokeBehavior('fault',c.source_id,c.player_id)),
        'bad.source':lambda c:(DestroyStoredCard(first(c),999999),),
        'bad.face':lambda c:(DestroyStoredCard(replace(first(c),card_id='missing'),c.source_id),),
        'bad.callback':lambda c:(DestroyStoredCard(first(c),c.source_id,on_destroy=(InvokeBehavior('missing',c.source_id,c.player_id),)),),
        'callback':lambda c:(DestroyStoredCard(first(c),c.source_id,on_destroy=(GainArmor(c.player_id,10),)),),
        'capacity':lambda c:(DestroyStoredCard(first(c),c.source_id),),}
    scripts['burn.draw']=lambda c:(Draw(c.player_id,2,c.source_id),)
    scripts['burn.generate']=lambda c:(AddToHand(c.player_id,'plain',c.source_id),AddToHand(c.player_id,NATIVE,c.source_id))
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata()))
    r.register_behavior('observer.wait',lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),),c.source_id),))
    r.register_card(CardDefinition('observer','Diagnostic observer',CardType.MINION,health=5,
        triggers=(TriggerSpec('card_destroyed_in_hand','observer.wait'),TriggerSpec('card_destroyed_in_deck','observer.wait')),metadata=metadata()))
    return r

class StoredDestructionTests(unittest.TestCase):
    def game(self,hand=(NATIVE,'hand'),deck=('plain',)*6,enemy_hand=(),board=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,deck=deck,board=board,max_mana=10,mana=10),
            PlayerSetup('hero',hand=enemy_hand,deck=('plain',)*6,max_mana=10,mana=10)),seed=150),registry())
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid
    def choose(self,g,name='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(name,)))
    def events(self,g):return [e for e in g._events if destruction_result(e) is not None]
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(s,registry())
        self.assertEqual(h.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return h
    def queued(self,g):
        return next(w for w in (*g._frame.prefix,*g._frame.continuation) if type(w)is BehaviorCall
            and w.context.trigger is not None and w.context.trigger.kind=='on_destroyed')
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_complete_raw_pin_and_only_necessary_adapter(self):
        raw=next(x for x in evidence()['records'] if x['id']==NATIVE)
        original=next(x for x in json.loads((ROOT/'data/extracted/cards.json').read_bytes()) if x['id']==NATIVE)
        self.assertEqual(raw,original);card=registry().card(NATIVE)
        self.assertEqual((card.cost,card.on_play,card.on_discard,card.on_destroyed),(3,'draw2','draw2','draw2'))
        self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertNotIn('SC_408',registry().cards);self.assertNotIn('WW_044t',registry().cards)
        default = build_registry()
        self.assertEqual((default.version, len(default.cards)), ('representative-m5-v65', 311))
        self.assertEqual(default.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_hand_destruction_preserves_identity_and_has_no_discard_or_death(self):
        g=self.game();old=g.state.entities[g.state.players[1].hand[0]];self.play(g,'hand')
        e=g.state.entities[old.id]
        self.assertEqual((e.owner,e.controller,e.card_id,e.zone,e.zone_epoch),(old.owner,1,NATIVE,Zone.GRAVEYARD,old.zone_epoch+1))
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(len(g.state.discard_history),0)
        self.assertEqual(len(g.state.death_history),0);self.assertEqual(len(g.state.cast_history),1)
        row=destruction_result(self.events(g)[0]);self.assertEqual(row.card,CardReference.capture(old));self.portable(g)

    def test_general_deck_destruction_accepts_native_body(self):
        g=self.game(hand=('deck',),deck=(NATIVE,'plain','plain','plain'));self.play(g,'deck')
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(self.events(g)[0].kind,'card_destroyed_in_deck');self.portable(g)

    def test_existing_deck_api_accepts_same_native_body(self):
        g=self.game(hand=('old.deck',),deck=(NATIVE,'plain','plain','plain'));self.play(g,'old.deck')
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(len(g.state.cast_history),1);self.portable(g)

    def test_play_and_discard_remain_exactly_two_draws(self):
        for cid,hand in ((NATIVE,(NATIVE,)),('discard',(NATIVE,'discard'))):
            with self.subTest(cid=cid):
                g=self.game(hand=hand);self.play(g,cid);self.assertEqual(len(g.state.draw_history),2)
                self.assertEqual(len(self.events(g)),0);self.portable(g)

    def test_all_physical_stored_types_use_same_destruction_without_board_death(self):
        for cid in ('native.minion','weapon','location','hero.card'):
            for zone in (Zone.HAND,Zone.DECK):
                with self.subTest(cid=cid,zone=zone):
                    g=self.game(hand=(cid,'hand') if zone==Zone.HAND else ('deck',),
                        deck=('plain',)*4 if zone==Zone.HAND else (cid,'plain','plain'))
                    self.play(g,zone.value);self.assertEqual(self.armor(g),3)
                    self.assertEqual(len(g.state.death_history),0);self.assertEqual(len(g.state.discard_history),0);self.portable(g)

    def test_private_destruction_hides_face_and_other_hand_cards(self):
        g=self.game(hand=('native.minion','plain','private'));self.play(g,'private')
        enemy=json.dumps(g.for_player(2).observe());self.assertNotIn('native.minion',enemy);self.assertNotIn('original_card',enemy)
        self.assertIn('card_destroyed_in_hand',json.dumps(g.for_player(2).events()));self.portable(g)

    def test_revealed_destruction_only_reveals_target(self):
        g=self.game(hand=('native.minion',NATIVE,'hand'));self.play(g,'hand')
        enemy=json.dumps(g.for_player(2).observe());self.assertIn('native.minion',enemy);self.assertNotIn(NATIVE,enemy)
        self.assertNotIn('original_card',enemy);self.portable(g)

    def test_source_less_destruction_has_original_physical_fact(self):
        g=self.game(hand=(NATIVE,'system'));self.play(g,'system')
        self.assertIsNone(self.events(g)[0].source_id);self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_opponent_hand_body_belongs_to_current_controller(self):
        g=self.game(hand=('enemy',),enemy_hand=(NATIVE,));self.play(g,'enemy')
        self.assertEqual(len(g.state.players[2].hand),2);self.assertEqual(len(g.state.players[1].hand),0)
        self.assertEqual(self.events(g)[0].player_id,2);self.portable(g)

    def test_transferred_card_keeps_owner_and_uses_new_controller(self):
        g=self.game(hand=(NATIVE,'transfer','enemy'));original=g.state.players[1].hand[0]
        self.play(g,'transfer');self.play(g,'enemy')
        self.assertEqual((g.state.entities[original].owner,g.state.entities[original].controller),(1,2))
        self.assertEqual(len(g.state.players[2].hand),2);self.assertEqual(destruction_result(self.events(g)[0]).owner_id,1);self.portable(g)

    def test_duplicate_captured_request_destroys_once(self):
        g=self.game(hand=(NATIVE,'two'));self.play(g,'two')
        self.assertEqual(len(self.events(g)),1);self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_left_and_returned_reference_is_stale(self):
        g=self.game(hand=(NATIVE,'stale'));self.play(g,'stale')
        self.assertEqual(len(self.events(g)),0);self.assertEqual(len(g.state.draw_history),0)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,NATIVE);self.portable(g)

    def test_changed_face_invalidates_old_request(self):
        g=self.game(hand=(NATIVE,'transform'));self.play(g,'transform')
        self.assertEqual(len(self.events(g)),0);self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id,'plain');self.portable(g)

    def test_existing_observer_wait_preserves_native_acceptance_and_callback_order(self):
        g=self.game(hand=(NATIVE,'callback'),board=('observer',));self.play(g,'callback')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.draw_history),0);self.assertEqual(self.armor(g),0)
        call=self.queued(g);self.assertIsNone(call.context.cast);self.assertEqual(call.context.source.card_id,NATIVE)
        h=self.portable(g);self.choose(g);self.choose(h);self.assertEqual(h.snapshot(),g.snapshot())
        self.assertEqual(len(g.state.draw_history),2);self.assertEqual(self.armor(g),10);self.portable(g)

    def test_native_waiting_body_roundtrips_and_resumes_original_operand(self):
        g=self.game(hand=('native.wait','hand'));target=g.state.players[1].hand[0];self.play(g,'hand')
        self.assertIsNotNone(g.state.pending_choice);h=self.portable(g);self.choose(g);self.choose(h)
        self.assertEqual(g.snapshot(),h.snapshot());self.assertEqual(self.armor(g),target)
        self.assertEqual(len(g.state.draw_history),2);self.portable(g)

    def test_native_failure_and_late_failure_roll_back_all_effects(self):
        for hand,cid in ((('native.fault','hand'),'hand'),(('native.bad','hand'),'hand'),((NATIVE,'late.fault'),'late.fault')):
            with self.subTest(hand=hand):
                g=self.game(hand=hand);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),before)

    def test_failed_waiting_selection_preserves_waiting_state(self):
        g=self.game(hand=('native.wait','hand'));self.play(g,'hand');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g);self.portable(g)

    def test_unknown_source_face_and_callback_fail_before_movement(self):
        for cid in ('bad.source','bad.face','bad.callback'):
            with self.subTest(cid=cid):
                g=self.game(hand=(NATIVE,cid));before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),before)

    def test_invalid_payloads_and_native_declarations_reject(self):
        ref=CardReference(1,1,Zone.HAND,NATIVE,0)
        for fn in (lambda:DestroyStoredCard(ref,reveal=1),lambda:DestroyStoredCard(ref,True),
            lambda:DestroyStoredCard(ref,on_destroy=[]),lambda:DestroyStoredCard(ref,on_destroy=(object(),)),
            lambda:DestroyDeckCard(ref),lambda:AbilityInstance(1,'on_destroyed',origin='granted',source_id=1,behavior_id='draw2'),
            lambda:AbilityInstance(1,'on_destroyed',origin='printed',source_id=1,behavior_id='draw2',event='fake')):
            with self.subTest(fn=fn),self.assertRaises(ValueError):fn()
        r=Registry('bad-native')
        with self.assertRaises(ValueError):r.register_card(CardDefinition('bad','bad',CardType.SPELL,on_destroyed=''))
        with self.assertRaises(ValueError):r.register_card(CardDefinition('bad','bad',CardType.SPELL,on_destroyed='draw2',choice_only=True))

    def test_native_frame_validates_original_context_event_and_behavior(self):
        g=self.game(board=('observer',));self.play(g,'hand');call=self.queued(g)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state,origin_events=g._events)
        self.assertEqual(codec.decode(codec.encode(call)),call);validate_destroyed_call(call,g.registry)
        for ctx in (replace(call.context,event=None),replace(call.context,player_id=2),replace(call.context,target_id=call.context.source_id),
            replace(call.context,cast=g.state.cast_history[0]),replace(call.context,rewind_attempt=1),
            replace(call.context,event=replace(call.context.event,sequence=call.context.event.sequence+1))):
            with self.subTest(ctx=ctx),self.assertRaises(ValueError):codec.encode(replace(call,context=ctx))
        with self.assertRaises(ValueError):codec.encode(replace(call,behavior_id='discard.armor'))
        state=deepcopy(call.context.state);state.entities[call.context.source_id].zone_epoch+=1
        with self.assertRaises(ValueError):codec.encode(replace(call,context=replace(call.context,state=state)))

    def test_rehashed_receipts_and_native_body_tampering_reject(self):
        g=self.game();self.play(g,'hand');original=g.snapshot()
        for field,value in (('owner_id',2),('card_kind','MINION'),('reveal',1),('turn',999999)):
            s=deepcopy(original);event=next(e for e in s['events'] if e['kind']=='card_destroyed_in_hand')
            event['data'][field]=value;self.reject(s)
        h=self.game();s=h.snapshot();target=h.state.players[1].hand[0]
        ability=next(a for a in s['state']['entities'][str(target)]['abilities'] if a['kind']=='on_destroyed')
        ability['behavior_id']='native.armor';self.reject(s)

    def test_other_removal_and_discard_only_cards_do_not_run_destroyed_body(self):
        for hand,cid,zone in ((('native.minion','remove'),'remove',Zone.SETASIDE),
            (('native.minion','ordinary'),'ordinary',Zone.HAND),(('discard.only','hand'),'hand',Zone.GRAVEYARD)):
            with self.subTest(hand=hand):
                g=self.game(hand=hand);target=g.state.players[1].hand[0];self.play(g,cid)
                self.assertEqual(self.armor(g),0);self.assertEqual(g.state.entities[target].zone,zone);self.portable(g)

    def test_current_and_base_copies_install_independent_native_body(self):
        g=self.game(hand=(NATIVE,'copy','hand','hand'));self.play(g,'copy')
        fuel=[g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==NATIVE]
        self.assertEqual(len(fuel),3)
        abilities=[next(a for a in e.abilities if a.kind=='on_destroyed') for e in fuel]
        self.assertEqual(len({a.id for a in abilities}),3)
        self.assertEqual([a.source_id for a in abilities],[entity.id for entity in fuel])
        self.play(g,'hand');self.play(g,'hand')
        self.assertEqual(len(self.events(g)),2);self.assertEqual(len(g.state.draw_history),4);self.portable(g)

    def test_player_views_and_commands_never_expose_acceptance_or_receipt(self):
        g=self.game(board=('observer',));self.play(g,'hand');before=g.snapshot()
        for p in (1,2):
            view=json.dumps(g.for_player(p).observe());g.for_player(p).legal_actions()
            for key in ('original_card','owner_id','zone_epoch','resolution_frame','on_destroyed','behavior_id','RuleContext'):
                self.assertNotIn(key,view)
        self.assertEqual(g.snapshot(),before);self.choose(g);self.portable(g)

    def test_supported_native_burn_paths_accept_the_destroyed_body(self):
        for cid in ('burn.draw','burn.generate'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,)+('plain',)*9,deck=('plain',NATIVE,'plain'))
                self.play(g,cid)
                self.assertEqual(len(g.state.draw_history),4)
                self.assertEqual(len(g.state.players[1].hand),10)
                self.assertEqual(g.state.death_history,[])
                self.assertTrue(any(e.kind=='card_burned' for e in self.events(g)))
                self.portable(g)

if __name__=='__main__':unittest.main()
