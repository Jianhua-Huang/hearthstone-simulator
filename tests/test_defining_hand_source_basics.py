"""One native shifter persists independently of its current printed face."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

import test_stored_card_transform_basics as base
from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game,
    HandProgressSpec, PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TransformDefiningHandCard, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='38e9e10a23c883bcb464999f5260cee5d66b298fa28bd68a38d7e78a7ba98b40'
FORMS={'dh.zerus':base.CROC,'dh.blade':base.KNIFE,'dh.scroll':'st.newspell'}

def evidence():
    p=json.loads((ROOT/'data/support/defining-source-binding-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Defining-source evidence changed')
    return p

def binding(entity):
    return next((a for a in entity.abilities if a.kind=='defining_hand_source'),None)

def registry():
    r=base.registry()
    def operation(c):
        return TransformDefiningHandCard(CardReference.capture(c.state.entities[c.source_id]),
            FORMS.get(c.trigger.defining_card_id,base.CROC),c.trigger.id)
    def fail(c):raise ResolutionError('Diagnostic defining-source failure')
    r.register_behavior('dh.fail',fail)
    r.register_behavior('dh.shift',lambda c:(operation(c),))
    r.register_behavior('dh.wait',lambda c:(RequestChoice(c.player_id,(
        ChoiceOption('shift','Shift',(operation(c),)),
        ChoiceOption('fail','Fail',(operation(c),InvokeBehavior('dh.fail',c.source_id,c.player_id)))),c.source_id),))
    r.register_behavior('dh.bad_body',lambda c:(operation(c),InvokeBehavior('dh.fail',c.source_id,c.player_id)))
    r.register_behavior('dh.stale_body',lambda c:(MoveCard(CardReference.capture(c.state.entities[c.source_id]),
        c.player_id,Zone.DECK,'bottom',source_id=c.source_id),operation(c)))
    raw={x['id']:x for x in evidence()['records']}
    for name,raw_id in (('dh.zerus','OG_123'),('dh.blade','UNG_929'),('dh.scroll','LOOT_104')):
        x=raw[raw_id];kind=CardType(x['type'].lower());stats={}
        if kind==CardType.MINION:stats=dict(attack=x['attack'],health=x['health'])
        if kind==CardType.WEAPON:stats=dict(attack=x['attack'],durability=x['health'])
        cost=0 if x['cost'] is None else x['cost']
        r.register_card(CardDefinition(name,'Diagnostic native '+raw_id,kind,cost=cost,**stats,
            defining_hand_source=HandProgressSpec('event',on_complete='dh.shift',repeat=True,event='turn_started')))
    for name,body in (('dh.waiter','dh.wait'),('dh.bad','dh.bad_body'),('dh.stale','dh.stale_body')):
        r.register_card(CardDefinition(name,'Diagnostic native source',CardType.MINION,health=1,
            defining_hand_source=HandProgressSpec('event',on_complete=body,repeat=True,event='turn_started')))
    def ref(c):return CardReference.capture(c.state.entities[c.target_id])
    def return_held(c):return (MoveCard(CardReference.capture(c.state.entities[c.target_id]),1,Zone.HAND,source_id=c.source_id),)
    r.register_behavior('dh.return',return_held)
    def leave(c):return (MoveCard(ref(c),1,Zone.DECK,'bottom',source_id=c.source_id),InvokeBehavior('dh.return',c.source_id,1,c.target_id))
    def fetch(c):
        i=c.state.players[1].deck[0]
        return (MoveCard(CardReference.capture(c.state.entities[i]),1,Zone.HAND,source_id=c.source_id),)
    bodies={'leave':leave,'fetch':fetch,
        'current_copy':lambda c:(CopyCard(ref(c),1,source_id=c.source_id),),
        'transfer':lambda c:(MoveCard(ref(c),2,Zone.HAND,source_id=c.source_id),),
        'fake':lambda c:(TransformDefiningHandCard(ref(c),base.CROC,999999),)}
    for name,fn in bodies.items():
        r.register_behavior('dh.'+name,fn)
        fields={} if name=='fetch' else {'targeting':r.card('st.to_s').targeting}
        r.register_card(CardDefinition('dh.'+name,'Diagnostic '+name,CardType.SPELL,on_play='dh.'+name,**fields))
    return r

def rehash(s):
    keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame',
        'rewind_session','match_setup','generation_context','information')
    s['state_hash']=canonical_hash({k:s[k] for k in keys});return s

class DefiningHandSourceTests(unittest.TestCase):
    def game(self,hand=('dh.zerus',),deck=(base.CROC,)*20):
        return Game.from_scenario(Scenario((
            PlayerSetup('st.hero',hand=hand,deck=deck,max_mana=10,mana=10),
            PlayerSetup('st.hero',deck=(base.CROC,)*20,max_mana=10,mana=10)),seed=79),registry())
    def card(self,g,name):return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None):return g.apply(PlayCard(1,self.card(g,name),target))
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s);return s

    def test_six_complete_native_source_rows_are_pinned_without_claiming_full_adapters(self):
        p=evidence();raw={x['id']:x for x in p['records']};self.assertEqual(len(raw),6)
        for i in ('OG_123','UNG_929','LOOT_104'):
            self.assertEqual(raw[i+'e']['tags']['DEFINING_ENCHANTMENT'],raw[i]['dbf_id'])
        self.assertFalse(p['CN_calibrated']);self.assertFalse(p['full_card_adaptation'])
        self.assertEqual(p['new_real_card_adapters'],0)

    def test_minion_weapon_and_spell_repeat_after_losing_the_original_face(self):
        for name,face in FORMS.items():
            with self.subTest(source=name):
                g=self.game((name,));eid=self.card(g,name);initial=g.state.entities[eid];original=binding(initial)
                for count in range(1,4):
                    self.cycle(g);e=g.state.entities[eid];a=binding(e)
                    self.assertEqual(e.card_id,face);self.assertEqual(a.id,original.id)
                    self.assertEqual((a.defining_card_id,a.source_id,a.progress_completions),(name,eid,count))
                    self.assertEqual((e.id,e.owner,e.controller,e.zone,e.hand_entry_id),
                        (initial.id,initial.owner,initial.controller,initial.zone,initial.hand_entry_id))
                    self.assertEqual(e.zone_epoch,initial.zone_epoch+count);self.portable(g)

    def test_each_self_transform_clears_old_buffs_and_discounts_but_keeps_only_native_source(self):
        g=self.game(('dh.zerus','st.buff','st.buff'));eid=self.card(g,'dh.zerus');aid=binding(g.state.entities[eid]).id
        for count in range(1,3):
            self.play(g,'st.buff',eid);self.assertEqual(g.state.entities[eid].cost,0);self.cycle(g)
            e=g.state.entities[eid];d=g.registry.card(base.CROC)
            self.assertEqual((e.attack,e.max_health,e.cost),(d.attack,d.health,d.cost))
            self.assertEqual(e.enchantments,[]);self.assertEqual(binding(e).id,aid)
            self.assertEqual(binding(e).progress_completions,count)
        self.portable(g)

    def test_opponent_start_does_not_fire_the_owners_source(self):
        g=self.game();eid=self.card(g,'dh.zerus');g.apply(EndTurn(1))
        self.assertEqual(binding(g.state.entities[eid]).progress_completions,0)
        g.apply(EndTurn(2));self.assertEqual(binding(g.state.entities[eid]).progress_completions,1)
        self.assertEqual(sum(e.kind=='stored_card_transformed' for e in g.events),1)

    def test_source_is_private_and_transformation_does_not_allocate_or_play_the_face(self):
        g=self.game();next_id=g.state.next_entity_id;plays=len(g.state.play_history);self.cycle(g)
        self.assertEqual(g.state.next_entity_id,next_id);self.assertEqual(len(g.state.play_history),plays)
        self.assertFalse(any(e.kind in ('minion_summoned','card_played','spell_cast_accepted') for e in g.events))
        for seat in (1,2):
            self.assertNotIn('defining_card_id',json.dumps(g.for_player(seat).observe()))
            self.assertNotIn('defining_card_id',json.dumps(g.for_player(seat).events()))
        own=g.for_player(1).observe()['observation']['players'][0]['hand'][0]
        self.assertEqual(own['card_id'],base.CROC)

    def test_external_ordinary_transform_retires_the_old_original_source(self):
        g=self.game(('dh.zerus','st.to_s'));eid=self.card(g,'dh.zerus');self.cycle(g)
        self.play(g,'st.to_s',eid);self.assertIsNone(binding(g.state.entities[eid]));count=len(g.events)
        self.cycle(g);self.assertFalse(any(e.kind=='stored_card_transformed' for e in g.events[count:]));self.portable(g)

    def test_leaving_and_reentering_hand_does_not_resurrect_a_retired_source(self):
        g=self.game(('dh.zerus','dh.leave'));eid=self.card(g,'dh.zerus');self.cycle(g)
        entry=g.state.entities[eid].hand_entry_id;self.play(g,'dh.leave',eid)
        self.assertNotEqual(g.state.entities[eid].hand_entry_id,entry);self.assertIsNone(binding(g.state.entities[eid]))
        count=len(g.events);self.cycle(g);self.assertFalse(any(e.kind=='stored_card_transformed' for e in g.events[count:]));self.portable(g)

    def test_playing_the_current_minion_face_retires_the_hand_source(self):
        g=self.game();eid=self.card(g,'dh.zerus');self.cycle(g);g.apply(PlayCard(1,eid))
        self.assertIn(eid,g.state.players[1].board);self.assertIsNone(binding(g.state.entities[eid]));self.portable(g)

    def test_native_deck_card_waits_until_it_is_acquired_in_hand(self):
        g=self.game(('dh.fetch',),deck=('dh.zerus',base.CROC,base.CROC));eid=g.state.players[1].deck[0]
        self.assertEqual(binding(g.state.entities[eid]).progress_completions,0);self.play(g,'dh.fetch')
        self.assertEqual(binding(g.state.entities[eid]).progress_completions,0);self.cycle(g)
        self.assertEqual(binding(g.state.entities[eid]).progress_completions,1);self.portable(g)

    def test_pending_native_transform_restores_clones_replays_and_resumes(self):
        g=self.game(('dh.waiter',));eid=self.card(g,'dh.waiter');self.cycle(g);s=self.portable(g)
        choice=g.state.pending_choice;self.assertIsNotNone(choice)
        g.apply(SelectChoice(1,choice.id,('shift',)))
        restored=Game.from_snapshot(s,registry());restored.apply(SelectChoice(1,choice.id,('shift',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(binding(g.state.entities[eid]).progress_completions,1)
        self.cycle(g);self.portable(g);self.assertIsNotNone(g.state.pending_choice)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('shift',)))
        self.assertEqual(binding(g.state.entities[eid]).progress_completions,2);self.portable(g)

    def test_failed_direct_body_and_failed_choice_restore_all_original_state(self):
        g=self.game(('dh.bad',));g.apply(EndTurn(1));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic defining-source failure'):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),s)
        g=self.game(('dh.waiter',));self.cycle(g);s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic defining-source failure'):
            g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s)

    def test_departed_captured_self_is_skipped_and_native_source_is_retired(self):
        g=self.game(('dh.stale',));eid=self.card(g,'dh.stale');self.cycle(g)
        self.assertIsNone(binding(g.state.entities[eid]));self.assertEqual(g.state.entities[eid].zone,Zone.DECK)
        self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events));self.portable(g)

    def test_current_copy_and_hand_transfer_have_no_silent_lifecycle_fallback(self):
        for name in ('dh.current_copy','dh.transfer','dh.fake'):
            with self.subTest(operation=name):
                g=self.game(('dh.zerus',name));eid=self.card(g,'dh.zerus');self.cycle(g);s=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,name,eid)
                self.assertEqual(g.snapshot(),s)

    def test_snapshot_native_binding_and_witness_tampering_rejects_after_rehashing(self):
        g=self.game();eid=self.card(g,'dh.zerus');self.cycle(g);self.cycle(g);s=g.snapshot()
        for field,value in (('defining_card_id','dh.blade'),('source_id',g.state.players[1].hero_id),
                ('progress_completions',0),('progress_keys',['event:1','event:2'])):
            with self.subTest(field=field):
                altered=deepcopy(s);a=next(a for a in altered['state']['entities'][str(eid)]['abilities'] if a['kind']=='defining_hand_source')
                a[field]=value
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(altered),registry())
        old=deepcopy(s);old['schema_version']=232
        with self.assertRaisesRegex(SnapshotError,'Unsupported snapshot schema'):Game.from_snapshot(old,registry())

    def test_native_declaration_types_codec_and_pending_binding_are_strict(self):
        r=registry();g=self.game();eid=self.card(g,'dh.zerus');a=binding(g.state.entities[eid]);ref=CardReference.capture(g.state.entities[eid])
        for invalid in (replace(r.card('dh.zerus'),id='dh.invalid',kind=CardType.HERO),
                replace(r.card('dh.zerus'),id='dh.invalid',defining_hand_source=HandProgressSpec('event',on_complete='dh.shift',event='turn_started'))):
            with self.assertRaises(ValueError):r.register_card(invalid)
        codec=FrameCodec(g.mechanics,g.registry);effect=TransformDefiningHandCard(ref,base.CROC,a.id)
        wire=codec.encode(effect);self.assertEqual(codec.decode(wire),effect)
        wire['fields']['keep_enchantments']=True
        with self.assertRaises(ValueError):codec.decode(wire)
        with self.assertRaises(ValueError):TransformDefiningHandCard(ref,base.CROC,True)
        waiting=self.game(('dh.waiter',));self.cycle(waiting);s=waiting.snapshot()
        def corrupt(value):
            if isinstance(value,dict):
                if 'source_ability_id' in value:value['source_ability_id']=999999
                for item in value.values():corrupt(item)
            elif isinstance(value,list):
                for item in value:corrupt(item)
        corrupt(s['resolution_frame'])
        with self.assertRaisesRegex(SnapshotError,'native source'):Game.from_snapshot(rehash(s),registry())

if __name__=='__main__':unittest.main()
