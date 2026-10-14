"""Independent ordinary targets, original host intent and actual magnetic paths."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

import examples.magnetic_root_targets as fixture
from hs_sim.engine import Game, IllegalAction, PlayCard, SelectChoice, SnapshotError
from hs_sim.engine.body_target_origin import origin_hash
from hs_sim.engine.model import Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class MagneticRootTargetTests(unittest.TestCase):
    def game(self, mode='accepted', *, full=False, reverse=False, enemy_card='enemy'):
        game = Game.from_scenario(fixture.scenario(mode, full=full, reverse=reverse, enemy_card=enemy_card), fixture.registry(mode))
        source = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == 'setup')
        game.apply(PlayCard(1, source))
        return game

    def paid(self, game, position=0):
        command = fixture.command(game, position)
        result = game.for_player(1).submit(command)
        self.assertTrue(result['accepted'], result)
        return command

    def roundtrip(self, game, mode):
        snapshot = game.snapshot()
        for other in (Game.from_snapshot(snapshot, fixture.registry(mode)), game.clone(), replay(build_replay(game), fixture.registry(mode))):
            self.assertEqual(other.snapshot(), snapshot)
            for player in (1, 2): self.assertEqual(other.for_player(player).observe(), game.for_player(player).observe())

    def rehash(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def test_accepted_host_retains_independent_ordinary_enemy_and_complete_body_receipt(self):
        game = self.game(); host = game.state.players[1].board[0]; enemy = game.state.players[2].board[0]
        command = self.paid(game); play = game.state.play_history[-1]
        self.assertEqual(play.minion_result, 'magnetized'); self.assertEqual(play.magnetic_target_id, host)
        self.assertEqual(play.target_id, enemy); self.assertNotEqual(play.target_id, play.magnetic_target_id)
        self.assertIsNotNone(command['action']['target']); self.assertEqual(len(play.body_targets.selected), 5)
        self.assertEqual(game.state.entities[enemy].damage, 0); self.assertFalse(game.state.battlecry_history)
        self.assertEqual(game.state.players[1].mana, 4); self.assertIsNotNone(play.paid_hand_close)
        self.roundtrip(game, 'accepted')

    def test_original_host_departure_executes_ordinary_root_and_each_own_body_target(self):
        game = self.game('departure'); host = game.state.players[1].board[0]; enemy = game.state.players[2].board[0]
        self.paid(game); play = game.state.play_history[-1]
        self.assertEqual(play.minion_result, 'summoned'); self.assertEqual(play.magnetic_target_id, host)
        self.assertEqual(play.target_id, enemy); self.assertEqual(game.state.entities[enemy].damage, 2)
        self.assertEqual(game.state.entities[enemy].attack, 2)
        records = (*game.state.battlecry_history, *game.state.combo_history)
        self.assertEqual([r.target_id for r in records], [v.target_id for v in play.body_targets.selected])
        self.assertEqual([r.failure is not None for r in records], [True, False, False, True, False])
        self.assertEqual(game.state.players[1].mana, 4); self.roundtrip(game, 'departure')

    def test_pre_entry_wait_preserves_original_two_targets_and_can_choose_either_path(self):
        for option, expected in (('keep', 'magnetized'), ('depart', 'summoned')):
            game = self.game('choose'); self.paid(game)
            self.assertIsNotNone(game.state.pending_choice); self.roundtrip(game, 'choose')
            original = game.state.play_history[-1].body_targets
            choice = game.state.pending_choice; game.apply(SelectChoice(choice.player_id, choice.id, (option,)))
            play = game.state.play_history[-1]
            self.assertEqual(play.minion_result, expected); self.assertEqual(play.body_targets, original)
            self.assertEqual(game.state.entities[play.target_id].damage, 2 if option == 'depart' else 0)
            self.roundtrip(game, 'choose')

    def test_each_fallback_body_wait_restores_clone_and_action_replay(self):
        game = self.game('body_wait'); self.paid(game); waits = 0
        while game.state.pending_choice is not None:
            waits += 1; self.roundtrip(game, 'body_wait')
            choice = game.state.pending_choice; game.apply(SelectChoice(choice.player_id, choice.id, ('go',)))
        self.assertEqual(waits, 3); self.assertEqual(game.state.play_history[-1].minion_result, 'summoned')
        self.roundtrip(game, 'body_wait')

    def test_full_board_live_host_can_merge_with_reserved_ordinary_target(self):
        game = self.game(full=True); self.paid(game)
        play = game.state.play_history[-1]
        self.assertEqual(play.minion_result, 'magnetized'); self.assertEqual(len(game.state.players[1].board), 7)
        self.assertIsNotNone(play.target_id); self.assertEqual(game.state.players[1].mana, 4)

    def test_full_board_late_ineligible_host_preserves_targets_and_fails_entry(self):
        game = self.game('blocked', full=True); self.paid(game)
        play = game.state.play_history[-1]
        self.assertEqual(play.minion_result, 'board_full'); self.assertIsNotNone(play.target_id)
        self.assertEqual(len(game.state.players[1].board), 7)
        self.assertEqual(game.state.entities[play.source_id].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.entities[play.target_id].damage, 0); self.assertFalse(game.state.battlecry_history)
        self.assertEqual(game.state.players[1].mana, 4); self.roundtrip(game, 'blocked')

    def test_normal_position_without_host_uses_the_same_independent_ordinary_target(self):
        game = self.game(); self.paid(game, position=1); play = game.state.play_history[-1]
        self.assertIsNone(play.magnetic_target_id); self.assertEqual(play.minion_result, 'summoned')
        self.assertEqual(game.state.entities[play.target_id].damage, 2)
        self.assertEqual(len(game.state.battlecry_history), 3)

    def test_conditional_ordinary_root_none_does_not_disable_enemy_body_target(self):
        game = self.game('conditional'); command = self.paid(game); play = game.state.play_history[-1]
        self.assertIsNone(command['action']['target']); self.assertIsNone(play.target_id)
        self.assertEqual(play.minion_result, 'summoned')
        enemy_body = next(r for r in game.state.battlecry_history if r.payload.card_id == 'enemy_body')
        self.assertIn(enemy_body.target_id, game.state.players[2].board)
        self.assertEqual(game.state.entities[enemy_body.target_id].attack, 2)

    def test_ordinary_target_none_cannot_erase_required_fallback_before_payment(self):
        game = self.game(); command = fixture.command(game); command['action']['target'] = None
        snapshot = game.snapshot(); self.assertFalse(game.for_player(1).submit(command)['accepted'])
        self.assertEqual(game.snapshot(), snapshot)

    def test_shared_legacy_action_cannot_bypass_the_complete_independent_vector(self):
        game = self.game(); source = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == 'material')
        snapshot = game.snapshot()
        with self.assertRaises(IllegalAction): game.apply(PlayCard(1, source, game.state.players[2].board[0], 0))
        self.assertEqual(game.snapshot(), snapshot)

    def test_invalid_magnetic_hint_does_not_replace_independent_ordinary_target(self):
        game = self.game(); command = fixture.command(game)
        command['action']['magnetic_target'] = command['action']['target']
        snapshot = game.snapshot(); self.assertFalse(game.for_player(1).submit(command)['accepted'])
        self.assertEqual(game.snapshot(), snapshot)

    def test_merge_reaction_failure_rolls_back_payment_rng_host_receipt_and_player_handles(self):
        game = self.game('fail'); command = fixture.command(game); snapshot = game.snapshot(); history = game.history
        self.assertFalse(game.for_player(1).submit(command)['accepted'])
        self.assertEqual(game.snapshot(), snapshot); self.assertEqual(game.history, history)

    def test_original_board_geometry_is_complete_and_retains_order(self):
        game = self.game('choose', reverse=True); board = tuple(game.state.players[1].board)
        self.paid(game, position=1)
        self.assertEqual(game.state.play_history[-1].body_targets.origin.board, board)
        self.assertEqual(game.state.play_history[-1].magnetic_target_id, board[1])

    def test_missing_duplicate_foreign_board_facts_reject_after_real_rehash(self):
        game = self.game('departure'); self.paid(game)
        for transform in (lambda v: v.pop(), lambda v: v.append(v[0]),
                          lambda v: v.__setitem__(0, game.state.players[2].board[0])):
            snapshot = game.snapshot(); receipt = snapshot['state']['play_history'][-1]['body_targets']
            transform(receipt['origin']['board']); receipt['origin_hash'] = canonical_hash(receipt['origin'])
            self.rehash(snapshot)
            with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, fixture.registry('departure'))

    def test_original_host_omission_or_substitution_rejects_without_current_board_requery(self):
        game = self.game('departure'); self.paid(game)
        for replacement in (None, game.state.players[2].board[0]):
            snapshot = game.snapshot(); snapshot['state']['play_history'][-1]['magnetic_target_id'] = replacement
            self.rehash(snapshot)
            with self.assertRaisesRegex(SnapshotError, 'position-selected magnetic host'):
                Game.from_snapshot(snapshot, fixture.registry('departure'))

    def test_nonpaid_record_cannot_keep_ordinary_target_with_a_magnetic_host(self):
        game = self.game(); self.paid(game); play = game.state.play_history[-1]
        with self.assertRaisesRegex(ValueError, 'Invalid magnetic play branch'):
            replace(play, body_targets=None)

    def test_player_projection_keeps_host_and_ordinary_target_distinct_and_private_origin_hidden(self):
        first = self.game(); second = self.game(enemy_card='fodder')
        self.assertEqual(first.for_player(1).observe(), second.for_player(1).observe())
        self.assertEqual(fixture.command(first), fixture.command(second))
        self.paid(first)
        for player in (1, 2):
            raw = json.dumps(first.for_player(player).observe()) + json.dumps(first.for_player(player).events())
            for private in ('origin_hash', 'source_json', 'original_state_hash', 'body_target_profile_id', 'registry_fingerprint'):
                self.assertNotIn(private, raw)
