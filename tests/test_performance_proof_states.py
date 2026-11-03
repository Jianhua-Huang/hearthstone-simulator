"""Private proof ownership never leaks into public or executable state."""
import unittest
from unittest.mock import patch
from hs_sim.engine import Game,PlayCard,PlayerSetup,Scenario,SelectChoice
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.model import GameState
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.resolver import BehaviorCall,default_mechanics
from hs_sim.engine.serialization import state_to_dict
from test_performance_frame_metadata import game


class ProofStateOwnershipTests(unittest.TestCase):
    def test_rewind_checkpoint_captures_detach_mutable_state_in_both_modes(self):
        from hs_sim.engine.resolver import Resolution
        from hs_sim.engine.rewind import RewindSession, capture_hand_spell_session
        for mode in ('release', 'debug'):
            with self.subTest(mode=mode):
                match=self.waiting();match.runtime_mode=mode
                checkpoint=match.clone()._state
                source=checkpoint.players[1].hero_id
                match._rewind=RewindSession(PlayCard(1,source),checkpoint,match._information,0)
                resolver=Resolution(match)
                anchor=capture_hand_spell_session(resolver,source)
                restored=resolver.capture_state(anchor.before)
                self.assertIsNot(anchor.before,checkpoint)
                self.assertIsNot(restored,anchor.before)
                anchor.before.players[1].mana=-91
                restored.entities[source].damage=17
                self.assertNotEqual(checkpoint.players[1].mana,-91)
                self.assertNotEqual(restored.players[1].mana,-91)
                self.assertNotEqual(anchor.before.entities[source].damage,17)
                self.assertNotEqual(checkpoint.entities[source].damage,17)
                if mode=='release':
                    self.assertIs(anchor.before.play_history[0],checkpoint.play_history[0])
                else:
                    self.assertIsNot(anchor.before.play_history[0],checkpoint.play_history[0])

    def test_native_callback_detaches_state_but_reuses_frozen_records_only(self):
        from hs_sim.engine.resolver import Resolution
        from hs_sim.engine.choose_one import DISPATCH
        match=self.waiting();resolver=Resolution(match)
        call=resolver.call(DISPATCH,match._state.players[1].hero_id,1)
        self.assertIsNot(call.context.state,match._state)
        self.assertIs(call.context.state.play_history[0],match._state.play_history[0])
        call.context.state.players[1].hand.append(999999)
        self.assertNotIn(999999,match._state.players[1].hand)
        match.runtime_mode='debug'
        call=Resolution(match).call(DISPATCH,match._state.players[1].hero_id,1)
        self.assertIsNot(call.context.state.play_history[0],match._state.play_history[0])

    def test_external_callback_cannot_claim_native_ownership_with_module_label(self):
        from hs_sim.engine.resolver import Resolution
        from hs_sim.engine.runtime_copy import native_callback
        spoof=lambda context: ()
        spoof.__module__='hs_sim.engine.registry'
        self.assertFalse(native_callback(spoof))
        match=self.waiting()
        with patch.dict(match.registry._behaviors,{'ask':spoof}):
            call=Resolution(match).call('ask',match._state.players[1].hero_id,1)
        self.assertIsNot(call.context.state.play_history[0],match._state.play_history[0])

    def test_scalar_wire_pairs_do_not_exhaust_immutable_record_budget(self):
        from hs_sim.engine.effects import GainArmor
        from hs_sim.engine.runtime_copy import ImmutableRecords, deepcopy
        fields = tuple(('field' + str(i), i) for i in range(1000))
        record = GainArmor(1, 2)
        object.__setattr__(record, 'wire', fields)
        cache = ImmutableRecords(limit=3)
        self.assertTrue(cache.contains(record))
        self.assertLessEqual(len(cache._entries), 3)
        self.assertIs(deepcopy(record, _immutable=cache), record)
        self.assertIsNot(deepcopy(record), record)

    def test_finished_encoding_does_not_retain_captured_state_until_gc(self):
        import gc,weakref
        from hs_sim.engine.runtime_copy import deepcopy
        match=game();codec=FrameCodec(match.mechanics,match.registry)
        enabled=gc.isenabled();gc.disable()
        try:
            state=deepcopy(match._state);reference=weakref.ref(state)
            wire=codec.encode_runtime(state,readonly=True)
            del state
            self.assertIsNone(reference())
            self.assertEqual(wire,codec.encode(match._state))
        finally:
            if enabled:gc.enable()

    def test_private_capture_reuses_only_immutable_records_and_callbacks_detach(self):
        from hs_sim.engine.resolver import Resolution
        match=self.waiting();resolver=Resolution(match)
        left,right=resolver.capture_state(),resolver.capture_state()
        self.assertIsNot(left,right)
        self.assertIsNot(left.play_history,right.play_history)
        self.assertTrue(left.play_history)
        self.assertIs(left.play_history[0],right.play_history[0])
        self.assertIs(left.play_history[0],match._state.play_history[0])
        left.players[1].hand.clear();left.entities[1].keywords.add('private')
        self.assertNotIn('private',right.entities[1].keywords)
        call=resolver.call('ask',match._state.players[1].hero_id,1)
        self.assertIsNot(call.context.state.play_history[0],match._state.play_history[0])
        match.runtime_mode='debug'
        debug=Resolution(match).capture_state()
        self.assertIsNot(debug.play_history[0],match._state.play_history[0])

    def test_frozen_wrapper_with_mutable_children_and_cycles_is_not_shared(self):
        from hs_sim.engine.effects import GainArmor
        from hs_sim.engine.runtime_copy import deepcopy,ImmutableRecords
        immutable=GainArmor(1,2);mutable=GainArmor(1,3)
        child=[];object.__setattr__(mutable,'extra',child);child.append(mutable)
        source=[immutable,mutable,child,mutable]
        cache=ImmutableRecords();copied=deepcopy(source,_immutable=cache)
        self.assertIs(copied[0],immutable)
        self.assertIsNot(copied[1],mutable)
        self.assertIs(copied[1],copied[3]);self.assertIs(copied[1].extra,copied[2])
        self.assertIs(copied[2][0],copied[1])
        self.assertIsNot(deepcopy(immutable),immutable)
        bounded=ImmutableRecords(limit=1)
        self.assertFalse(bounded.contains((immutable,)))
        self.assertEqual(len(bounded._entries),1)

    def test_private_capture_disables_record_reuse_for_external_handlers(self):
        from hs_sim.engine.resolver import Resolution
        from hs_sim.engine.spell_acceptance import FinishSpellAcceptance,finish
        match=self.waiting();mechanics=default_mechanics('private-capture-extension-v1')
        mechanics.replace(FinishSpellAcceptance,lambda r,e:finish(r,e));mechanics.freeze()
        match.mechanics=mechanics;captured=Resolution(match).capture_state()
        self.assertIsNot(captured.play_history[0],match._state.play_history[0])

    def test_private_copy_keeps_extension_copy_protocols(self):
        from hs_sim.engine.effects import GainArmor
        from hs_sim.engine.runtime_copy import deepcopy,ImmutableRecords
        frozen=GainArmor(1,2)
        with patch.object(GainArmor,'__deepcopy__',lambda self,memo:'hook',create=True):
            self.assertEqual(deepcopy([frozen],_immutable=ImmutableRecords()),['hook'])

    def waiting(self):
        match=game();match.apply(PlayCard(1,match._state.players[1].hand[0]));return match

    def test_transaction_reuses_private_proofs_but_public_clone_is_detached(self):
        match=self.waiting();saved=match.snapshot()
        transaction=match._clone(transfer_proofs=True);public=match.clone()
        proof=match._frame.paid_hand_choice_boundary
        self.assertIs(transaction._frame.paid_hand_choice_boundary.state,proof.state)
        self.assertIsNot(transaction._state,match._state)
        self.assertIsNot(public._frame.paid_hand_choice_boundary.state,proof.state)
        self.assertEqual(transaction.snapshot(),saved)
        public._frame.paid_hand_choice_boundary.state.players[1].hand.clear()
        self.assertEqual(match.snapshot(),saved)

    def test_callback_occurrences_detach_even_when_given_a_proof_state(self):
        match=self.waiting();proof=match._frame.paid_hand_choice_boundary
        context=RuleContext(proof.state,proof.state.players[1].hero_id,1)
        work=BehaviorCall('ask',context)
        codec=FrameCodec(match.mechanics,match.registry)
        retained,left,right=codec.copy_owned_runtime((proof,work,work))
        self.assertIs(retained.state,proof.state)
        self.assertIsNot(left.context.state,proof.state)
        self.assertIsNot(left.context.state,right.context.state)
        left.context.state.players[1].mana=-100
        self.assertNotEqual(right.context.state.players[1].mana,-100)
        self.assertNotEqual(proof.state.players[1].mana,-100)

    def test_ordinary_codec_still_copies_each_proof_occurrence(self):
        match=self.waiting();proof=match._frame.paid_hand_choice_boundary
        codec=FrameCodec(match.mechanics,match.registry)
        left,right=codec.copy_runtime((proof,proof))
        self.assertIsNot(left.state,right.state)
        self.assertIsNot(left.state,proof.state)
        self.assertEqual(codec.encode(left),codec.encode(proof))

    def test_replaced_handler_keeps_original_detached_copy_path(self):
        from hs_sim.engine.spell_acceptance import FinishSpellAcceptance,finish
        mechanics=default_mechanics('proof-owner-extension-v1')
        mechanics.replace(FinishSpellAcceptance,lambda r,e:finish(r,e))
        match=self.waiting();proof=match._frame.paid_hand_choice_boundary
        copied=FrameCodec(mechanics,match.registry).copy_owned_runtime(proof)
        self.assertIsNot(copied.state,proof.state)
        self.assertEqual(state_to_dict(copied.state),state_to_dict(proof.state))

    def test_internal_log_prefixes_are_read_only_and_public_exports_detach(self):
        match=self.waiting();saved=match.snapshot();history=match.history
        transaction=match._clone(transfer_proofs=True);public=match.clone()
        self.assertIs(transaction._origin,match._origin)
        self.assertIsNot(transaction._events,match._events)
        self.assertIs(transaction._events[0],match._events[0])
        self.assertIs(transaction._history[0],match._history[0])
        self.assertIsNot(public._origin,match._origin)
        self.assertIsNot(public._history[0],match._history[0])
        transaction._history.append({'private':True})
        transaction._events.clear()
        exported=transaction.snapshot();exported['information']['players']['1']['events'].clear()
        history[0]['action']['player_id']=99
        self.assertEqual(match.snapshot(),saved)

    def test_external_handler_transaction_detaches_log_prefixes(self):
        from hs_sim.engine.spell_acceptance import FinishSpellAcceptance,finish
        match=self.waiting();mechanics=default_mechanics('proof-log-extension-v1')
        mechanics.replace(FinishSpellAcceptance,lambda r,e:finish(r,e));mechanics.freeze()
        match.mechanics=mechanics
        transaction=match._clone(transfer_proofs=True)
        self.assertIsNot(transaction._origin,match._origin)
        self.assertIsNot(transaction._events[0],match._events[0])
        self.assertIsNot(transaction._history[0],match._history[0])

    def test_choice_continuation_leaves_all_retained_proof_states_unchanged(self):
        from dataclasses import fields,is_dataclass
        match=self.waiting();held=[]
        def visit(value):
            if type(value)is GameState:held.append((value,state_to_dict(value)))
            elif type(value)is tuple:
                for child in value:visit(child)
            elif is_dataclass(value):
                for field in fields(value):visit(getattr(value,field.name))
        visit(match._frame)
        self.assertTrue(held)
        choice=match._state.pending_choice
        match.apply(SelectChoice(1,choice.id,('ok',)))
        self.assertIsNone(match._frame)
        for state,saved in held:self.assertEqual(state_to_dict(state),saved)

    def test_native_receipts_keep_strict_bytes_and_debug_full_state_audit(self):
        from hs_sim.engine import continuations
        match=game();codec=FrameCodec(match.mechanics,match.registry)
        expected=codec.encode(match._state)
        with patch.object(continuations,'validate_invariants',side_effect=ValueError('audit marker')):
            self.assertEqual(continuations.encode_produced(match,match._state),expected)
            with self.assertRaisesRegex(ValueError,'audit marker'):codec.encode(match._state)
            match.runtime_mode='debug'
            with self.assertRaisesRegex(ValueError,'audit marker'):
                continuations.encode_produced(match,match._state)

    def test_release_does_not_reaudit_just_captured_paid_and_combo_proofs(self):
        from hs_sim.engine import paid_hand_acceptance,combo_acceptance
        from hs_sim.engine.errors import ResolutionError
        registry=game().registry
        setup=Scenario((PlayerSetup('hero',hand=('plain',),mana=10,max_mana=10),PlayerSetup('hero')),seed=13)
        for module,name in ((paid_hand_acceptance,'validate_tail'),(combo_acceptance,'validate_acceptance')):
            release=Game.from_scenario(setup,registry)
            debug=Game.from_scenario(setup,registry,mode='debug')
            saved=debug.snapshot()
            with patch.object(module,name,side_effect=ValueError('audit marker')):
                release.apply(PlayCard(1,release._state.players[1].hand[0]))
                with self.assertRaises(ResolutionError):debug.apply(PlayCard(1,debug._state.players[1].hand[0]))
            self.assertEqual(debug.snapshot(),saved)


if __name__=='__main__':unittest.main()
