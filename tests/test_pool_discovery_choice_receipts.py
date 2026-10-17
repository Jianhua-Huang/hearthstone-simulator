"""Original ordinary pool selections survive deferred delivery and real waits."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import Game, SelectChoice, SnapshotError, Zone
from hs_sim.engine import discovery
from hs_sim.engine.card_discoveries import require_original_result
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discovery import ContinuePoolDiscovery, validate_batch, validate_receipt_history
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoiceResult
from hs_sim.engine.discovery_summons import picks
from test_card_discoveries import (A, B, AUTO, BOARD, BURN, DISC, TWICE,
    game, play, choose, portable, rehash, registry)


def branch(g, cid=None):
    return next(o.effects[0] for o in g._frame.options if cid is None or o.card_id == cid)


class PoolDiscoveryChoiceReceiptTests(unittest.TestCase):
    def test_a0_pending_offer_does_not_preclaim_any_committed_result(self):
        g = game(); play(g, DISC)
        self.assertEqual(g.state.card_discovery_history, [])
        for option in g._frame.options:
            work = option.effects[0]
            self.assertIsNone(work.choice_result)
            self.assertIsNone(work.selection.result)
            self.assertEqual(work.batch.selections, ())
        fake = ChoiceResult(g.state.pending_choice, (g.state.pending_choice.options[0].id,))
        with self.assertRaisesRegex(ValueError, 'original committed'):
            require_original_result(g.state, fake)
        portable(self, g)

    def test_a1_second_wait_keeps_full_first_choice_and_same_original_history(self):
        g = game((TWICE,)); play(g, TWICE)
        first = g.state.pending_choice
        choose(g, A)
        row, = g.state.card_discovery_history
        pick, = branch(g).batch.selections
        self.assertEqual(pick.result, row.result)
        self.assertEqual(pick.result.choice, first)
        self.assertEqual(len(pick.result.choice.options), 3)
        self.assertEqual(g.state.players[1].hand, [])
        self.assertEqual(require_original_result(g.state, pick.result), row)
        for pid in (1, 2):
            visible = json.dumps(g.for_player(pid).observe()) + json.dumps(g.player_events(pid))
            for key in ('card_discovery_history', 'resolution_frame', 'rng_state', 'receipt'):
                self.assertNotIn('"' + key + '"', visible)
        restored = portable(self, g)
        for match in (g, restored): choose(match, B)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.card_discovery_history[0], row)

    def test_a2_two_same_faces_keep_distinct_original_results_at_each_deferred_recipe(self):
        g = game((TWICE,))
        with patch.object(discovery, 'deliver_pick', wraps=discovery.deliver_pick) as deliver:
            play(g, TWICE); choose(g, A); choose(g, A)
        received = [call.args[1] for call in deliver.call_args_list]
        self.assertEqual([p.card_id for p in received], [A, A])
        self.assertEqual([p.result for p in received], [r.result for r in g.state.card_discovery_history])
        self.assertEqual(len({p.result.choice.id for p in received}), 2)
        hand = g.state.players[1].hand
        self.assertEqual(len(hand), 2)
        self.assertEqual([g.state.entities[i].card_id for i in hand], [A, A])
        self.assertNotEqual(hand[0], hand[1])

    def test_a3_after_each_and_other_actor_bind_the_actual_complete_selection(self):
        g = game(pid=2)
        with patch.object(discovery, 'deliver_pick', wraps=discovery.deliver_pick) as deliver:
            play(g, DISC); choose(g, B)
        pick = deliver.call_args.args[1]
        row, = g.state.card_discovery_history
        self.assertEqual(pick.result, row.result)
        self.assertEqual(pick.result.choice.player_id, 2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand], [B])
        self.assertEqual(g.state.players[1].hand, [])
        portable(self, g)

    def test_a4_automatic_spell_uses_the_same_binding_without_an_extra_choice(self):
        g = game((AUTO,))
        with patch.object(discovery, 'deliver_pick', wraps=discovery.deliver_pick) as deliver:
            play(g, AUTO)
        row, = g.state.card_discovery_history
        self.assertEqual(deliver.call_args.args[1].result, row.result)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.events[row.selection_event - 1].kind, 'spell_choice_automatic')
        portable(self, g)

    def test_a5_full_hand_burn_does_not_rebind_or_erase_the_original_selection(self):
        g = game((BURN, A))
        with patch.object(discovery, 'deliver_pick', wraps=discovery.deliver_pick) as deliver:
            play(g, BURN); choose(g, B)
        row, = g.state.card_discovery_history
        self.assertEqual(deliver.call_args.args[1].result, row.result)
        burned = [e.target_id for e in g.events if e.kind == 'card_burned']
        self.assertEqual(len(burned), 1)
        self.assertEqual((g.state.entities[burned[0]].card_id, g.state.entities[burned[0]].zone), (B, Zone.GRAVEYARD))
        self.assertEqual(len(g.state.players[1].hand), 10)

    def test_a6_failed_final_recipe_rolls_back_only_new_selection_and_keeps_first_wait(self):
        g = game((TWICE,)); play(g, TWICE); choose(g, A)
        saved = g.snapshot(); first, = g.state.card_discovery_history
        with patch.object(discovery, 'deliver_pick', side_effect=ValueError('deliberate recipe failure')):
            with self.assertRaises(ResolutionError): choose(g, B)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(g.state.card_discovery_history, [first])
        choose(g, B)
        self.assertEqual(g.state.card_discovery_history[0], first)
        portable(self, g)

    def test_b0_prior_progress_rejects_missing_duplicate_and_wrong_actor_results(self):
        g = game((TWICE,)); play(g, TWICE); choose(g, A)
        batch = branch(g).batch; pick, = batch.selections
        bad = (
            replace(batch, selections=(replace(pick, result=None),)),
            replace(batch, selections=(pick, pick)),
            replace(batch, selections=(replace(pick, result=replace(pick.result,
                choice=replace(pick.result.choice, player_id=2))),)),
        )
        for value in bad:
            with self.assertRaises(ValueError):
                validate_batch(g.registry, g._generation_context, value)
        with self.assertRaisesRegex(ValueError, 'preclaim'):
            replace(branch(g, A), selection=pick)

    def test_b1_complete_result_codec_is_typed_but_state_requires_the_actual_original(self):
        g = game((TWICE,)); play(g, TWICE); choose(g, A)
        batch = branch(g).batch; pick, = batch.selections
        codec = FrameCodec(g.mechanics, g.registry)
        encoded = json.loads(json.dumps(codec.encode(batch)))
        self.assertEqual(codec.decode(encoded), batch)
        future = replace(pick.result, choice=replace(pick.result.choice, id=g.state.next_choice_id + 10))
        borrowed = replace(batch, selections=(replace(pick, result=future),))
        validate_batch(g.registry, g._generation_context, borrowed)
        with self.assertRaisesRegex(ValueError, 'original committed'):
            validate_receipt_history(g.state, borrowed)
        validate_receipt_history(g.state, batch)

    def test_b2_rehashed_snapshot_cannot_change_a_queued_original_result(self):
        g = game((TWICE,)); play(g, TWICE); choose(g, A)
        saved = json.loads(json.dumps(g.snapshot()))
        # Change every serialized copy of the queued immutable pick, leaving the
        # actual state discovery history/publications untouched.
        changed = 0
        def rewrite(value):
            nonlocal changed
            if isinstance(value, dict):
                if value.get('type') == 'hs_sim.engine.discovery.DiscoveryPick':
                    changed += 1
                    value['fields']['result'] = None
                else:
                    for child in value.values(): rewrite(child)
            elif isinstance(value, list):
                for child in value: rewrite(child)
        rewrite(saved)
        self.assertGreater(changed, 0)
        with self.assertRaises((SnapshotError, ValueError)):
            Game.from_snapshot(rehash(saved), registry('all', 'reader'))

    def test_c0_attributed_board_progress_reuses_the_actual_original_offer_result(self):
        g = game((BOARD,)); play(g, BOARD); choose(g, A)
        root, = g.state.discovery_summon_history
        row, = g.state.card_discovery_history
        pick, = picks(root)
        self.assertEqual(pick.result, root.offers[0].result)
        self.assertEqual(pick.result, row.result)
        self.assertEqual(require_original_result(g.state, pick.result), row)
        portable(self, g)


if __name__ == '__main__':
    unittest.main()
