"""Pure actual spell-source units use the existing settled damage history."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import EndTurn, ResolutionError, SelectChoice, UseHeroPower
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import canonical_digest
import hs_sim.engine.damage_history as history
import test_actual_damage_history_basics as old

SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/spell-damage-query-basics.json'
PIN = '96759d87018f69a48e48490f051f4124eec9e0c143c2662b8aee5ee441d260e4'


class SpellDamageQueryTests(unittest.TestCase):
    game = old.ActualDamageTests.game
    play = old.ActualDamageTests.play
    rows = old.ActualDamageTests.rows
    check = old.ActualDamageTests.check

    def units(self, g, player=1, **scope):
        return history.spell_damage_dealt(g.state, g.registry, player, **scope)

    def test_complete_real_requirements_are_pinned_without_white_adapters(self):
        value = json.loads(SUPPORT.read_bytes())
        self.assertEqual(canonical_digest(value), PIN)
        source = {row['id']: row for row in json.loads((SUPPORT.parents[1] / 'extracted/cards.json').read_bytes())}
        self.assertEqual(value['new_real_card_adapters'], [])
        for row in value['records']:
            self.assertEqual(row['data'], source[row['id']])
            self.assertEqual(canonical_digest(row['data']), row['data_sha256'])
            with self.assertRaises(UnsupportedDefinitionError):
                old.registry().card(row['id'])

    def test_empty_query_is_zero_and_public_export_uses_same_function(self):
        from hs_sim.engine import spell_damage_dealt
        g = self.game()
        self.assertIs(spell_damage_dealt, history.spell_damage_dealt)
        self.assertEqual(self.units(g), 0)

    def test_actual_units_include_armor_not_just_health_lost(self):
        g = self.game(('hurt',), armor=3)
        self.play(g, 'hurt')
        result = self.rows(g)[0].health_result
        self.assertEqual((result.damage_dealt, result.health_lost, self.units(g)), (5, 2, 5))
        self.check(g)

    def test_whole_batch_counts_friendly_enemy_hero_and_minion_once(self):
        g = self.game(('batch',))
        self.play(g, 'batch')
        self.assertEqual((self.units(g), len(self.rows(g))), (10, 3))
        self.assertEqual(self.units(g, before_id=3), 7)
        self.check(g)

    def test_original_spell_face_not_damage_kind_determines_credit(self):
        g = self.game(('hurt', 'body.source'))
        self.play(g, 'hurt')
        self.play(g, 'body.source')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual(self.rows(g)[0].health_result.damage_kind, old.DamageKind.EFFECT.value)
        self.assertEqual((self.units(g), history.hero_power_damage(g.state, g.registry, 1)), (5, 1))
        self.check(g)

    def test_prevented_immune_and_shield_packets_add_no_units(self):
        for hand, board in ((('zero',), ('plain',)), (('body.hit',), ('immune',)),
                            (('body.hit',), ('shield',)), (('hurt',), ('plain', 'prevent'))):
            with self.subTest(board=board):
                g = self.game(hand, board=board)
                self.play(g, hand[0])
                self.assertEqual((self.units(g), len(self.rows(g))), (0, 1))
                self.check(g)

    def test_damage_converted_to_healing_adds_no_damage_units(self):
        g = self.game(('hurt', 'enable', 'two'))
        for card in ('hurt', 'enable', 'two'):
            self.play(g, card)
        self.assertEqual([row.health_result.damage_dealt for row in self.rows(g)], [5, 0])
        self.assertEqual(self.units(g), 5)
        self.check(g)

    def test_healing_converted_to_actual_spell_damage_counts_final_units(self):
        g = self.game(('heal',), board=('plain', 'heal.to.damage'))
        self.play(g, 'heal')
        self.assertEqual(self.rows(g)[0].health_result.original_flow, 'healing')
        self.assertEqual(self.units(g), 5)
        self.check(g)

    def test_healing_lifesteal_and_stat_growth_do_not_duplicate_spell_damage(self):
        g = self.game(('hurt', 'body.source', 'heal', 'grow'), board=('life',))
        for card in ('hurt', 'body.source', 'heal', 'grow'):
            self.play(g, card)
        self.assertEqual(self.units(g), 5)
        self.check(g)

    def test_original_player_and_global_turn_boundaries_are_independent(self):
        g = self.game(('hurt', 'two'), enemy_hand=('hurt',))
        self.play(g, 'hurt')
        g.apply(EndTurn(1))
        self.play(g, 'hurt')
        g.apply(EndTurn(2))
        self.play(g, 'two')
        self.assertEqual((self.units(g), self.units(g, 2), self.units(g, turn=1),
            self.units(g, turn=2), self.units(g, turn=3)), (7, 5, 5, 0, 2))
        self.check(g)

    def test_exclusive_prefix_ignores_later_unknown_credit(self):
        g = self.game(('hurt', 'unknown'))
        self.play(g, 'hurt')
        self.play(g, 'unknown')
        self.assertEqual(self.units(g, before_id=2), 5)
        with self.assertRaises(UnsupportedDefinitionError):
            self.units(g)
        self.check(g)

    def test_unknown_positive_source_rejects_but_outside_turn_is_not_guessed(self):
        g = self.game(('unknown',))
        self.play(g, 'unknown')
        with self.assertRaises(UnsupportedDefinitionError):
            self.units(g)
        self.assertEqual((self.units(g, turn=2), self.units(g, before_id=1)), (0, 0))

    def test_systemic_fatigue_and_unknown_zero_do_not_receive_card_credit(self):
        g = self.game(('zero', 'fatigue'))
        self.play(g, 'zero')
        self.play(g, 'fatigue')
        self.assertEqual(self.units(g), 0)
        self.assertEqual(history.hero_damage_taken(g.state, 1), 1)
        self.check(g)

    def test_target_transform_control_and_return_do_not_rewrite_original_units(self):
        g = self.game(('body.hit', 'transform.target', 'transfer.target'))
        for card in ('body.hit', 'transform.target', 'transfer.target'):
            self.play(g, card)
        self.assertEqual(self.units(g), 5)
        self.check(g)
        g = self.game(('body.hit', 'bounce.target'))
        for card in ('body.hit', 'bounce.target'):
            self.play(g, card)
        self.assertEqual(self.units(g), 5)
        self.check(g)

    def test_stale_target_skip_has_no_query_credit(self):
        g = self.game(('stale',))
        self.play(g, 'stale')
        self.assertEqual((self.units(g), self.rows(g)), (0, ()))
        self.check(g)

    def test_typed_waiting_restore_clone_and_replay_preserve_one_original_result(self):
        g = self.game(('wait',), typed=True)
        self.play(g, 'wait')
        self.assertEqual(self.units(g), 5)
        self.check(g, typed=True)
        for branch in (g.clone(), old.Game.from_snapshot(g.snapshot(), old.registry(), mechanics=old.mechanics()),
                       old.replay(old.build_replay(g), old.registry(), mechanics=old.mechanics())):
            q = branch.state.pending_choice
            branch.apply(SelectChoice(q.player_id, q.id, ('accept',)))
            self.assertEqual((self.units(branch), len(self.rows(branch))), (5, 1))
            self.check(branch, typed=True)

    def test_failed_transaction_and_delayed_choice_keep_original_units(self):
        g = self.game(('fail',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'fail')
        self.assertEqual((g.snapshot(), self.units(g)), (before, 0))
        g = self.game(('wait',), typed=True)
        self.play(g, 'wait')
        before = g.snapshot()
        q = g.state.pending_choice
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(q.player_id, q.id, ('fault',)))
        self.assertEqual((g.snapshot(), self.units(g)), (before, 5))

    def test_real_rewind_retires_attempt_without_double_counting(self):
        g = self.game(('retry.hit',))
        self.play(g, 'retry.hit')
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('retry',)))
        self.assertEqual((self.units(g), len(self.rows(g))), (5, 1))
        self.check(g)

    def test_query_is_pure_and_private_history_is_not_player_output(self):
        g = self.game(('batch',))
        self.play(g, 'batch')
        before = deepcopy(g.snapshot())
        views = [g.observe(player) for player in (1, 2)]
        for _ in range(3):
            self.assertEqual(self.units(g), 10)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual([g.observe(player) for player in (1, 2)], views)
        for view in views:
            self.assertNotIn('damage_history', json.dumps(view))
            self.assertNotIn('next_damage_id', json.dumps(view))

    def test_query_rejects_boolean_invalid_player_turn_and_prefix(self):
        g = self.game()
        for player in (True, 0, 3, '1'):
            with self.subTest(player=player), self.assertRaises(ValueError):
                self.units(g, player)
        for key in ('turn', 'before_id'):
            for value in (True, 0, -1, '1', 1.5):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.units(g, **{key: value})
