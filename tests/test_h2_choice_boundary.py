"""Required genuine choice proof: full empty boundary, event link, and privacy."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
import test_m5_owner_turn_history as fixtures
from hs_sim.engine import Game, SnapshotError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.paid_hand_acceptance import (PaidHandChoiceBoundaryProof,
    CHOICE_DIGEST, validate_choice_boundary)

class ChoiceBoundaryTests(unittest.TestCase):
    setUp = fixtures.OwnerTurnActionTests.setUp
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    choose = fixtures.OwnerTurnActionTests.choose

    def reject(self,saved):
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised: Game.from_snapshot(saved,self.r)
        self.assertNotIn('digest mismatch',str(raised.exception))

    def test_empty_boundary_is_complete_typed_and_required_and_private(self):
        g=self.game(('choice',)); self.play(g,'choice')
        proof=g._frame.paid_hand_choice_boundary
        self.assertIs(type(proof),PaidHandChoiceBoundaryProof)
        self.assertTrue(proof.work)
        self.assertEqual(proof.state.pending_choice,g.state.pending_choice)
        self.assertEqual(g._frame.paid_hand_acceptances,())
        event=g.events[proof.event.sequence-1]
        self.assertEqual(len(dict(event.data)[CHOICE_DIGEST]),64)
        validate_choice_boundary(g)
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,self.r).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved)
        for pid in (1,2):
            port=g.for_player(pid)
            public=json.dumps((port.observe(),port.legal_actions(),port.events()))
            self.assertNotIn(CHOICE_DIGEST,public)
            self.assertNotIn('paid_hand_choice_boundary',public)
        missing=deepcopy(saved); del missing['resolution_frame']['fields']['paid_hand_choice_boundary']
        self.reject(missing)
        null=deepcopy(saved); null['resolution_frame']['fields']['paid_hand_choice_boundary']=None
        self.reject(null)
        self.choose(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())

    def test_request_identity_and_event_digest_cannot_be_borrowed_or_erased(self):
        g=self.game(('choice',)); self.play(g,'choice'); saved=g.snapshot()
        proof=g._frame.paid_hand_choice_boundary
        fields=saved['resolution_frame']['fields']['paid_hand_choice_boundary']['fields']
        self.assertEqual(fields['event']['event']['sequence'],proof.event.sequence)
        borrowed=deepcopy(saved)
        borrowed['resolution_frame']['fields']['paid_hand_choice_boundary']['fields']['event']['event']['sequence']+=1
        self.reject(borrowed)
        from hs_sim.engine.continuations import FrameCodec
        from hs_sim.engine.paid_hand_acceptance import validate_choice_boundary_proof
        changed=replace(proof,event=replace(proof.event,sequence=proof.event.sequence+1))
        validate_choice_boundary_proof(changed,self.r)
        frame=replace(g._frame,paid_hand_choice_boundary=changed)
        borrowed=g.snapshot(); borrowed['resolution_frame']=FrameCodec(g.mechanics,self.r).encode(frame)
        self.reject(borrowed)
        self.assertEqual(g.snapshot(),saved)
        self.choose(g)

    def test_nonwork_values_and_a_later_waiting_action_are_rejected(self):
        from hs_sim.engine.continuations import FrameCodec
        from hs_sim.engine.paid_hand_acceptance import validate_choice_boundary_proof
        g=self.game(('choice',)); self.play(g,'choice')
        proof=g._frame.paid_hand_choice_boundary
        codec=FrameCodec(g.mechanics,self.r)
        for nonwork in (0,'not interpreter work',g.state.pending_choice):
            with self.subTest(nonwork_type=type(nonwork).__name__):
                with self.assertRaisesRegex(ValueError,'genuine interpreter work'):
                    validate_choice_boundary_proof(replace(proof,work=(*proof.work,nonwork)),self.r)
                wire=deepcopy(codec.encode(proof))
                wire['fields']['work']['tuple'].append(codec.encode(nonwork))
                with self.assertRaisesRegex(ValueError,'genuine interpreter work'): codec.decode(wire)
        original=g.snapshot()
        for increment in (1,2):
            bad=deepcopy(original); bad['state']['action_number']+=increment
            self.reject(bad)
        self.assertEqual(g.snapshot(),original)
        self.choose(g)
        self.assertIsNone(g.state.pending_choice)

if __name__=='__main__': unittest.main()
