"""Native proof reuse keeps live rules, extension isolation and external audits."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hs_sim.engine import EndTurn, Game, SelectChoice
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.end_turns import FinishEndTurnBatch, finish_batch
from hs_sim.engine.end_turn_acceptance import _reference_window
from hs_sim.engine.model import EndTurnRecord
from hs_sim.engine.replay import build_replay, replay
import test_m5_end_turns as end_fixtures
import test_assemble_offers as assembly_fixtures


def ending():
    fixture = end_fixtures.EndTurnTests(); fixture.setUp()
    return fixture.game(board=('waiting', 'end'))


def tail(game):
    return next(w for w in game._frame.continuation if type(w) is FinishEndTurnBatch)


class EndTurnProofPerformanceTests(unittest.TestCase):
    def test_release_debug_waiting_restore_replay_and_random_state_equal(self):
        release = ending(); debug = release.clone(); debug.runtime_mode = 'debug'
        self.assertEqual(release.apply(EndTurn(1)), debug.apply(EndTurn(1)))
        saved = release.snapshot(); self.assertEqual(saved, debug.snapshot())
        restored = Game.from_snapshot(saved, end_fixtures.fixture_registry())
        choice = release._state.pending_choice
        action = SelectChoice(1, choice.id, ('three',))
        result = release.apply(action)
        self.assertEqual(result, debug.apply(action))
        self.assertEqual(result, restored.apply(action))
        self.assertEqual(release.snapshot(), debug.snapshot())
        self.assertEqual(release.snapshot(), restored.snapshot())
        self.assertEqual(release.snapshot(), replay(build_replay(release), end_fixtures.fixture_registry()).snapshot())
        self.assertEqual(len(debug.debug_records), 2)

    def test_reference_catalogue_matches_full_copy_and_detaches_its_appended_lists(self):
        game = ending(); game.apply(EndTurn(1)); proof = tail(game)
        original = deepcopy(proof.context.state)
        actual = _reference_window(proof)
        expected = deepcopy(original); group = proof.batch
        expected.end_turn_batches.append(group)
        from hs_sim.engine.end_turn_acceptance import _captures
        expected.end_turn_history.extend(EndTurnRecord(c) for c in _captures(group))
        self.assertEqual(actual, expected)
        actual.end_turn_batches.clear(); actual.end_turn_history.clear()
        self.assertEqual(proof.context.state, original)

    def test_mutating_external_condition_cannot_change_live_state_or_later_callback(self):
        fixture = end_fixtures.EndTurnTests(); fixture.setUp(); seen = []
        def condition(context):
            seen.append(context.state.players[1].mana)
            context.state.players[1].mana = 0
            context.state.entities[context.source_id].damage = 1
            return True
        fixture.r.register_trigger_condition('isolated', condition)
        fixture.minion('isolated', condition='isolated')
        game = fixture.game(board=('isolated',)); source = game._state.players[1].board[0]
        health = game._state.entities[source].health
        game.apply(EndTurn(1))
        self.assertEqual(seen, [10])
        self.assertEqual(game._state.entities[source].health, health)
        self.assertEqual(game._state.entities[game._state.players[1].hero_id].armor, 1)

    def test_completion_rejects_unfinished_subjects_in_release(self):
        game = ending(); game.apply(EndTurn(1)); proof = tail(game)
        r = SimpleNamespace(game=game, state=game._state, registry=game.registry,
                            rules=game.ruleset, _work_queue=())
        with self.assertRaisesRegex(ValueError, 'unfinished subjects'):
            finish_batch(r, proof)

    def test_explicit_proof_validation_still_rejects_tampering(self):
        from hs_sim.engine.end_turns import validate_acceptance
        game = ending(); game.apply(EndTurn(1)); proof = tail(game)
        altered = deepcopy(proof)
        altered.context.state.players[1].board.clear()
        with self.assertRaises(ValueError):
            validate_acceptance(altered, game.registry)
        validate_acceptance(proof, game.registry)

    def test_owned_end_turn_proof_public_copy_and_extension_boundary(self):
        game = ending(); game.apply(EndTurn(1)); proof = tail(game)
        codec = FrameCodec(game.mechanics, game.registry)
        owned = codec.copy_owned_runtime(proof)
        self.assertIs(owned.context.state, proof.context.state)
        public = codec.copy_runtime(proof)
        self.assertIsNot(public.context.state, proof.context.state)
        handler = game.mechanics._handlers[FinishEndTurnBatch]
        with patch.dict(game.mechanics._handlers,
                        {FinishEndTurnBatch: lambda r, w: handler(r, w)}):
            foreign = codec.copy_owned_runtime(proof)
        self.assertIsNot(foreign.context.state, proof.context.state)
        self.assertEqual(foreign, proof)

    def test_assembly_choices_share_only_owned_proof_and_public_branch_is_detached(self):
        fixture = assembly_fixtures.AssembleOfferTests(); game = fixture.game(); fixture.play(game, 'assemble')
        saved = game.snapshot(); offers = [o.effects[0].offer for o in game._frame.options]
        self.assertTrue(all(o.before is offers[0].before for o in offers))
        branch = game.clone(); branch._frame.options[0].effects[0].offer.before.players[1].hand.clear()
        self.assertEqual(game.snapshot(), saved)
        restored = Game.from_snapshot(saved, assembly_fixtures.registry())
        choice = game._state.pending_choice; action = SelectChoice(1, choice.id, (choice.options[0].id,))
        self.assertEqual(game.apply(action), restored.apply(action))
        self.assertEqual(game.snapshot(), restored.snapshot())


if __name__ == '__main__':
    unittest.main()
