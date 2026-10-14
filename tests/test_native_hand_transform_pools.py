"""Restricted real shifters use the existing pool algebra and physical reset."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from random import Random
import unittest
from unittest.mock import patch

from hs_sim.engine import (CardClass,CardDefinition,CardType,EndTurn,Game,HandProgressSpec,
    PlayCard,PlayerSetup,ResolutionError,Scenario,SelectChoice,SnapshotError,
    TransformDefiningHandCardFromPool,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import DefiningHandTransformDraw
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.pools import (GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,sample_candidates)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry,metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='6f68b342d0d46989f8ce1233109a40238240c027b6f8644c32fb681402c2c402'
CONTEXT=GenerationContext('native-hand-transform-restricted-v1','experimental')
FACES=('CS2_120','CS2_182','CS2_106','CS2_080','CS2_029','CS2_024')

def evidence():
    p=json.loads((ROOT/'data/support/native-hand-transform-pool-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Native pool evidence changed')
    return p

def binding(e):return next((a for a in e.abilities if a.kind=='defining_hand_source'),None)

def registry(*,mode='direct',empty=False,strict_empty=False,unknown=False,nested=False,weighted=False):
    r=build_registry();raw={x['id']:x for x in evidence()['records']}
    suffix='.'.join(str(x) for x in (mode,empty,strict_empty,unknown,nested,weighted))
    def fail(c):raise ResolutionError('Diagnostic native pool failure')
    r.register_behavior('nh.fail',fail)
    for root in ('OG_123','UNG_929','LOOT_104'):
        body='nh.shift.'+root+'.'+suffix
        def shift(c):
            root_id=c.trigger.defining_card_id;kind=c.state.entities[c.source_id].kind
            query=PoolQuery(kinds=(kind,),collectible=True)
            if root_id=='LOOT_104':query=replace(query,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
            request=TransformDefiningHandCardFromPool(CardReference.capture(c.state.entities[c.source_id]),
                root_id,c.trigger.id,'nh.faces',query=query,empty='error' if strict_empty else 'skip')
            if mode=='wait':return (RequestChoice(c.player_id,(
                ChoiceOption('draw','Draw',(request,)),
                ChoiceOption('fail','Fail',(request,InvokeBehavior('nh.fail',c.source_id,c.player_id)))),c.source_id),)
            if mode=='fail':return (request,InvokeBehavior('nh.fail',c.source_id,c.player_id))
            if mode=='stale':return (MoveCard(request.target,c.player_id,Zone.DECK,'bottom',source_id=c.source_id),request)
            return (request,)
        r.register_behavior(body,shift)
        x=raw[root];kind=CardType(x['type'].lower());fields={}
        if kind==CardType.MINION:fields=dict(attack=x['attack'],health=x['health'])
        if kind==CardType.WEAPON:fields=dict(attack=x['attack'],durability=x['health'])
        r.register_card(CardDefinition(root,x['name'],kind,cost=0 if x['cost'] is None else x['cost'],
            metadata=metadata_from_record(x),manual_playable=root!='LOOT_104',**fields,
            defining_hand_source=HandProgressSpec('event',on_complete=body,repeat=True,event='turn_started')))
    for i in ('CS2_120','CS2_080'):
        x=raw[i];kind=CardType(x['type'].lower());fields=dict(attack=x['attack'])
        fields['health' if kind==CardType.MINION else 'durability']=x['health']
        r.register_card(CardDefinition(i,x['name'],kind,cost=x['cost'],metadata=metadata_from_record(x),**fields))
    for i in FACES:
        if i not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(i)))
    members=[] if empty else [PoolMember(i,3 if weighted and i=='CS2_182' else 1) for i in FACES]
    if unknown:
        absent=replace(r.card('CS2_182'),id='nh.unimplemented')
        r.register_pool_card(PoolCard.from_definition(absent));members.append(PoolMember(absent.id))
    if nested:
        other=replace(r.card('OG_123'),id='nh.other_native')
        r.register_card(other);r.register_pool_card(PoolCard.from_definition(other));members.append(PoolMember(other.id))
    r.register_pool(PoolDefinition('nh.faces','restricted-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(sorted(members,key=lambda m:m.card_id))))
    return r

def rehash(s):
    keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame',
        'rewind_session','match_setup','generation_context','information')
    s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:s[k] for k in keys});return s

class NativeHandTransformPoolTests(unittest.TestCase):
    def game(self,root='OG_123',**options):
        self.options=options
        return Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=(root,),deck=('CS2_182',)*12,max_mana=10,mana=10),
            PlayerSetup('HERO_08',deck=('CS2_182',)*12,max_mana=10,mana=10)),seed=103,generation_context=CONTEXT),registry(**options))
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def draws(self,g):
        codec=FrameCodec(g.mechanics,g.registry)
        return [codec.decode(dict(e.data)['draw']) for e in g.events if e.kind=='defining_hand_card_randomized']
    def portable(self,g):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry(**self.options)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(**self.options)).snapshot(),s);return s

    def test_complete_raw_and_three_restricted_sources_are_not_formal_pool_claims(self):
        p=evidence();self.assertEqual(len(p['records']),12)
        self.assertEqual(p['new_source_experimental_adapters'],3);self.assertEqual(p['new_production_adapters'],0)
        self.assertFalse(p['full_card_adaptation']);self.assertFalse(p['formal_pool_verified']);self.assertFalse(p['CN_calibrated'])

    def test_three_real_sources_draw_each_owner_turn_and_keep_physical_identity(self):
        for root,scope in evidence()['sources'].items():
            with self.subTest(source=root):
                g=self.game(root);eid=g.state.players[1].hand[0];original=g.state.entities[eid];a=binding(original)
                for n in (1,2,3):
                    self.cycle(g);e=g.state.entities[eid];draw=self.draws(g)[-1]
                    self.assertIn(e.card_id,scope['candidates']);self.assertEqual(draw.selected,(e.card_id,))
                    self.assertEqual((e.id,e.owner,e.controller,e.hand_entry_id),(original.id,original.owner,original.controller,original.hand_entry_id))
                    self.assertEqual((binding(e).id,binding(e).defining_card_id,binding(e).progress_completions),(a.id,root,n))
                self.assertEqual(len(self.draws(g)),3);self.portable(g)

    def test_scroll_uses_mage_spells_even_in_a_rogue_hand_and_original_is_unplayable(self):
        g=self.game('LOOT_104');eid=g.state.players[1].hand[0];s=g.snapshot()
        self.assertEqual(g.state.players[1].hero_class,CardClass.ROGUE)
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,eid))
        self.assertEqual(g.snapshot(),s);self.cycle(g);draw=self.draws(g)[0]
        self.assertEqual(draw.request.query.classes,(CardClass.MAGE,));self.assertIsNone(draw.hero_class)
        self.assertEqual({m.card_id for m in draw.candidates},{'CS2_029','CS2_024'});self.portable(g)

    def test_integer_weighted_draw_receipt_replays_locally_with_exact_rng(self):
        g=self.game(weighted=True);self.cycle(g);draw=self.draws(g)[0];probe=Random();probe.setstate(draw.rng_before)
        self.assertEqual([m.weight for m in draw.candidates],[1,3])
        self.assertEqual(sample_candidates(probe,draw.candidates,1,replacement=True),draw.selected)
        self.assertEqual(probe.getstate(),draw.rng_after);self.assertNotEqual(draw.rng_before,draw.rng_after)
        self.portable(g)

    def test_empty_pool_records_empty_draw_without_rng_or_face_change(self):
        g=self.game(empty=True);eid=g.state.players[1].hand[0];self.cycle(g);draw=self.draws(g)[0]
        self.assertEqual((draw.candidates,draw.selected),((),()));self.assertEqual(draw.rng_before,draw.rng_after)
        self.assertEqual(g.state.entities[eid].card_id,'OG_123');self.assertEqual(binding(g.state.entities[eid]).progress_completions,1)
        self.portable(g)

    def test_strict_empty_pool_rolls_back_accepted_turn_and_rng(self):
        g=self.game(empty=True,strict_empty=True);g.apply(EndTurn(1));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Empty native transformation pool'):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),s)

    def test_unknown_eligible_candidate_is_not_filtered_before_sampling(self):
        g=self.game(unknown=True);g.apply(EndTurn(1));s=g.snapshot()
        with patch('hs_sim.engine.cross_zone.sample_candidates') as sample:
            with self.assertRaises(ResolutionError):g.apply(EndTurn(2))
            sample.assert_not_called()
        self.assertEqual(g.snapshot(),s)

    def test_unsupported_native_candidate_lifecycle_rejects_whole_pool(self):
        g=self.game(nested=True);g.apply(EndTurn(1));s=g.snapshot()
        with patch('hs_sim.engine.cross_zone.sample_candidates') as sample:
            with self.assertRaisesRegex(ResolutionError,'unsupported source lifecycle'):g.apply(EndTurn(2))
            sample.assert_not_called()
        self.assertEqual(g.snapshot(),s)

    def test_pending_pool_request_restores_and_resumes_same_integer_draw(self):
        g=self.game(mode='wait');self.cycle(g);s=self.portable(g);choice=g.state.pending_choice
        self.assertEqual(self.draws(g),[])
        restored=Game.from_snapshot(s,registry(**self.options))
        g.apply(SelectChoice(1,choice.id,('draw',)));restored.apply(SelectChoice(1,choice.id,('draw',)))
        self.assertEqual(restored.snapshot(),g.snapshot());self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_failed_direct_or_choice_body_rolls_back_draw_receipt_face_and_rng(self):
        g=self.game(mode='fail');g.apply(EndTurn(1));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic native pool failure'):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),s)
        g=self.game(mode='wait');self.cycle(g);s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Diagnostic native pool failure'):
            g.apply(SelectChoice(1,g.state.pending_choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s)

    def test_stale_physical_reference_skips_without_consuming_rng(self):
        g=self.game(mode='stale');self.cycle(g);self.assertEqual(self.draws(g),[])
        self.assertTrue(any(e.kind=='zone_target_skipped' for e in g.events));self.portable(g)

    def test_self_consistent_truncated_pool_receipt_still_rejects_against_registry(self):
        g=self.game();self.cycle(g);s=g.snapshot();draw=self.draws(g)[0]
        reduced=draw.candidates[:1];probe=Random();probe.setstate(draw.rng_before)
        selected=sample_candidates(probe,reduced,1,replacement=True)
        altered=replace(draw,candidates=reduced,selected=selected,rng_after=probe.getstate())
        row=next(e for e in s['events'] if e['kind']=='defining_hand_card_randomized')
        row['data']['draw']=FrameCodec(g.mechanics,g.registry).encode(altered)
        with self.assertRaisesRegex(SnapshotError,'complete original pool'):Game.from_snapshot(rehash(s),registry())

    def test_private_draw_candidates_and_rng_do_not_reach_either_player(self):
        g=self.game();self.cycle(g)
        for seat in (1,2):
            port=g.for_player(seat);text=json.dumps([port.observe(),port.events()])
            for token in ('DefiningHandTransformDraw','rng_before','rng_after','source_ability_id','defining_hand_card_randomized'):
                self.assertNotIn(token,text)

    def test_typed_pool_request_codec_rejects_extra_fields_and_wrong_type_query(self):
        g=self.game(mode='wait');self.cycle(g);codec=FrameCodec(g.mechanics,g.registry)
        request=g._frame.options[0].effects[0];wire=codec.encode(request);self.assertEqual(codec.decode(wire),request)
        wire['fields']['allow_unknown_candidates']=True
        with self.assertRaises(ValueError):codec.decode(wire)
        with self.assertRaises(ValueError):replace(request,source_ability_id=True)
        from hs_sim.engine.cross_zone import native_pool_candidates
        with self.assertRaisesRegex(ResolutionError,'physical card type'):
            native_pool_candidates(g.registry,CONTEXT,replace(request,query=PoolQuery(kinds=(CardType.SPELL,))))

if __name__=='__main__':unittest.main()
