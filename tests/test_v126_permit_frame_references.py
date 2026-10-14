"""New state-reference repair cases; previous TestCase stays module-only."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
import tests.test_v126_printed_attack_permits as base_fixture
from hs_sim.engine import (EndTurn, Game, GrantPrintedAttackPermit, ResolutionError,
    SelectChoice, SnapshotError)
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, EquipWeapon, RequestChoice,
    ReturnToHand, Transform)
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.continuations import FrameCodec


class PermitFrameReferenceTests(unittest.TestCase):
    def setUp(self):
        self.f=base_fixture.PrintedAttackPermitTests(methodName='runTest');self.f.setUp()

    def waiting(self,location='option',board=('watch','watch')):
        f=self.f
        def wait(c):
            grant=tuple(f.permit(c,c.target_id))
            if location=='continuation':
                return [RequestChoice(1,(ChoiceOption('go','Go'),),source_id=c.source_id),*grant]
            if location=='nested':
                inner=RequestChoice(1,(ChoiceOption('inner','Inner',grant),),source_id=c.source_id)
                return [RequestChoice(1,(ChoiceOption('go','Go',(inner,)),),source_id=c.source_id)]
            return [RequestChoice(1,(ChoiceOption('go','Go',grant),),source_id=c.source_id)]
        f.spell('wait',wait,True)
        g=f.game(board=board,hand=('wait',));f.cast(g,'wait',f.unit(g).id)
        return g

    def request_rows(self,value):
        if isinstance(value,dict):
            if value.get('type')=='hs_sim.engine.model.PrintedAttackPermitRequest': yield value['fields']
            for child in value.values():yield from self.request_rows(child)
        elif isinstance(value,list):
            for child in value:yield from self.request_rows(child)

    def rehash(self,snapshot):
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def rejected(self,g,mutator,message):
        snap=deepcopy(g.snapshot());rows=list(self.request_rows(snap['resolution_frame']));self.assertTrue(rows)
        for row in rows:mutator(row)
        self.rehash(snap)
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(snap,self.f.r)
        self.assertIn(message,str(error.exception));self.assertNotIn('digest mismatch',str(error.exception).lower())

    def test_future_owner_option_is_rejected_at_restore_before_any_choice(self):
        g=self.waiting();self.f.check(g)
        self.rejected(g,lambda row:row.update(expires_owner_turn_id=2),'Unknown printed permission owner interval')

    def test_future_printed_row_and_residence_ids_are_rejected_at_restore(self):
        g=self.waiting()
        for field,future in (('ability_id',g.state.next_attachment_id),('presence_id',g.state.next_order)):
            with self.subTest(field=field):
                def change(row):
                    ref=row['reference']['fields']
                    if field=='ability_id':ref[field]=future
                    else:ref['carrier']['fields'][field]=future
                self.rejected(g,change,'has not been allocated')

    def test_foreign_allocated_row_and_residence_do_not_become_known_stale(self):
        g=self.waiting();foreign=self.f.unit(g,1)
        row_id=next(a.id for a in foreign.abilities if a.kind=='attack_policy')
        for field,value in (('ability_id',row_id),('presence_id',foreign.board_presence_id)):
            with self.subTest(field=field):
                def change(row):
                    ref=row['reference']['fields']
                    if field=='ability_id':ref[field]=value
                    else:ref['carrier']['fields'][field]=value
                self.rejected(g,change,'belongs to another physical carrier')

    def test_wrong_local_trigger_row_is_rejected_without_late_stale_fallback(self):
        g=self.waiting();wrong=next(a.id for a in self.f.unit(g).abilities if a.kind=='trigger')
        self.rejected(g,lambda row:row['reference']['fields'].update(ability_id=wrong),'different local declaration')

    def test_future_requests_are_checked_in_real_continuation_and_nested_options(self):
        from hs_sim.engine.printed_attack_permits import validate_frame_references
        for location in ('continuation','nested'):
            with self.subTest(location=location):
                self.setUp();g=self.waiting(location)
                # The real paid continuation has an earlier complete-work digest
                # gate; prove rejection there and also exercise this new semantic
                # visitor directly against the same genuine continuation.
                message=('Suspended choice payment boundary differs' if location=='continuation'
                         else 'Unknown printed permission owner interval')
                self.rejected(g,lambda row:row.update(expires_owner_turn_id=2),message)
                if location=='continuation':
                    work=tuple(replace(item,request=replace(item.request,expires_owner_turn_id=2))
                        if type(item) is GrantPrintedAttackPermit else item for item in g._frame.continuation)
                    with self.assertRaisesRegex(ValueError,'Unknown printed permission owner interval'):
                        validate_frame_references(g.state,self.f.r,work)
                restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.f.r)
                self.f.choose(g);self.f.choose(restored)
                if location=='nested':self.f.choose(g);self.f.choose(restored)
                self.assertEqual(g.snapshot(),restored.snapshot());self.f.check(g)

    def test_future_request_in_private_prefix_is_checked_with_same_live_state(self):
        g=self.waiting();snap=deepcopy(g.snapshot())
        req=self.f.request(type('Context',(),{'state':g.state})(),self.f.unit(g).id)
        forged=GrantPrintedAttackPermit(replace(req,expires_owner_turn_id=2))
        codec=FrameCodec(g.mechanics,self.f.r,origin_state=g.state)
        snap['resolution_frame']['fields']['prefix']['tuple'].insert(0,codec.encode(forged))
        self.rehash(snap)
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(snap,self.f.r)
        self.assertIn('Unknown printed permission owner interval',str(error.exception))

    def test_known_stale_transformed_and_bounced_request_restores_and_skips(self):
        for mode in ('transform','bounce'):
            with self.subTest(mode=mode):
                self.setUp();f=self.f
                def driver(c):
                    req=f.request(c,c.target_id)
                    change=Transform(c.target_id,'watch') if mode=='transform' else ReturnToHand(c.target_id)
                    return [change,RequestChoice(1,(ChoiceOption('go','Go',(GrantPrintedAttackPermit(req),)),),source_id=c.source_id)]
                f.spell('driver',driver,True);g=f.game(hand=('driver',));eid=f.unit(g).id;f.cast(g,'driver',eid)
                f.check(g);cloned=g.clone();restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),f.r)
                for candidate in (g,cloned,restored):f.choose(candidate)
                self.assertEqual(g.snapshot(),cloned.snapshot());self.assertEqual(g.snapshot(),restored.snapshot())
                self.assertEqual(f.permits(g,eid),[]);f.check(g)

    def test_known_closed_original_owner_is_legal_stale_and_choice_failure_rolls_back(self):
        f=self.f
        def wait(c):
            req=replace(f.request(c,c.target_id),expires_owner_turn_id=1)
            return [RequestChoice(1,(ChoiceOption('bad','Bad',(GrantPrintedAttackPermit(req),
                CopyMinion(c.target_id,1),EquipWeapon(1,'plain'))),
                ChoiceOption('go','Go',(GrantPrintedAttackPermit(req),))),source_id=c.source_id)]
        f.spell('wait',wait,True);g=f.game(hand=('wait',));eid=f.unit(g).id
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertTrue(g.state.owner_turn_history[0].closed)
        f.cast(g,'wait',eid);f.check(g);original=g.snapshot()
        restored=Game.from_snapshot(json.loads(json.dumps(original)),f.r);cloned=g.clone()
        for candidate in (g,restored,cloned):
            choice=candidate.state.pending_choice
            with self.assertRaises(ResolutionError) as error:candidate.apply(SelectChoice(1,choice.id,('bad',)))
            self.assertIn('weapon',str(error.exception).lower());self.assertEqual(candidate.snapshot(),original)
            candidate.apply(SelectChoice(1,choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),cloned.snapshot())
        self.assertEqual(f.permits(g,eid),[]);f.check(g)
