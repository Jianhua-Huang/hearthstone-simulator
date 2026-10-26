"""Real constructed entries using the reviewed local special-pool host."""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.cards.drestagath_card import CARD, GODS, POOL
from hs_sim.engine import CardClass, DeckSpec, Game, PlayerSetup, Scenario, SelectChoice, SnapshotError, Zone
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.local_pool_format import build_cn37_local_pool_format, load_bindings
from hs_sim.targets import TargetValidationError
from card_batch_testkit import CardBatchTestMixin
from test_launch_candidate_format import fillers


KILL = 'CATA_EVENT_402'
FILLER = 'CORE_EX1_028'


@lru_cache(maxsize=2)
def format_for(role='writer'):
    if role not in ('writer', 'independent-reader'):
        raise ValueError('Unknown local-pool fixture role')
    return build_cn37_local_pool_format()


def fixture(mode=None, role='writer'):
    if mode is not None:
        raise ValueError('Unknown local-pool fixture mode')
    return format_for(role).registry


class LocalPoolFormatTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)
    mode = None

    def game(self, *, seed=544, deck_ids=(FILLER,), hand=(CARD, KILL)):
        fmt = format_for()
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03', hand=hand, deck=deck_ids, mana=10, max_mana=10),
            PlayerSetup('HERO_08', deck=(FILLER,) * 8),
        ), seed=seed, generation_context=fmt.context), fmt.registry)

    def kill_paid_source(self, game):
        source = self.play(game, CARD)
        self.play(game, KILL, source)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.players[1].mana, 3)
        return source

    def test_original_domains_and_exact_four_gods_share_one_new_target(self):
        fmt = format_for()
        old = build_cn37_launch_candidate_format()
        self.assertNotEqual(fmt.target_id, old.target_id)
        self.assertEqual(fmt.root_card_ids, old.root_card_ids)
        self.assertEqual(fmt.policy.allowed_card_ids, old.policy.allowed_card_ids)
        self.assertEqual(fmt.policy.banned_card_ids, old.policy.banned_card_ids)
        self.assertEqual(fmt.unimplemented_root_card_ids, ())
        self.assertEqual(fmt.policy.target_id, fmt.context.target_id)
        self.assertFalse(fmt.formal_pool_complete)
        self.assertFalse(fmt.cn_bans_verified)
        for pool_id in ('constructed.cards', 'constructed.minions'):
            current = fmt.registry.pool(pool_id, fmt.context)
            original = old.registry.pool(pool_id, old.context)
            self.assertEqual((current.members, current.excluded_card_ids, current.complete),
                (original.members, original.excluded_card_ids, original.complete))
        special = fmt.registry.pool(POOL, fmt.context)
        self.assertEqual(tuple(m.card_id for m in special.members), GODS)
        self.assertEqual(tuple(m.weight for m in special.members), (1, 1, 1, 1))
        self.assertTrue(special.complete)
        with self.assertRaises(UnsupportedDefinitionError):
            old.registry.pool(POOL, old.context)

    def test_real_paid_death_can_generate_each_of_all_four_native_old_gods(self):
        pool = format_for().registry.pool(POOL, format_for().context)
        candidates = tuple(sorted(pool.members, key=lambda m: m.card_id))
        for desired in GODS:
            # Probe only the original RNG state; no card is removed to force a result.
            for seed in range(100):
                game = self.game(seed=seed)
                probe = Random()
                probe.setstate(game._rng.getstate())
                chosen = sample_candidates(probe, candidates, 1, replacement=True)[0]
                if chosen == desired:
                    break
            else:
                self.fail('No deterministic native seed for ' + desired)
            self.kill_paid_source(game)
            actual = [game.state.entities[i].card_id for i in game.state.players[1].hand
                if game.state.entities[i].card_id in GODS]
            self.assertEqual(actual, [desired])
            # The real Rogue removal also gives the opponent a Coin and,
            # after the paid minion, accepts its ordinary Combo Coin.
            self.assertEqual(len(game.state.players[1].hand), 2)
            self.assertEqual(len(game.state.players[2].hand), 1)
            self.assertEqual(game._rng.getstate(), probe.getstate())
            self.assertFalse(game.state.draw_history)
            self.assertEqual(len(game.state.players[1].deck), 1)
            self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)
        self.portable(game)

    def test_actual_original_yogg_uses_physical_draw_rng_without_generation(self):
        game = self.game(deck_ids=(FILLER, 'BE_009'))
        original = game.state.players[1].deck[-1]
        probe = Random()
        probe.setstate(game._rng.getstate())
        probe.choice((original,))  # DrawMatching uses its own physical random choice.
        self.kill_paid_source(game)
        self.assertIn(original, game.state.players[1].hand)
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].hand
            if game.state.entities[i].card_id in GODS], ['BE_009'])
        self.assertEqual(game.state.draw_history[-1].entity_id, original)
        self.assertEqual(game._rng.getstate(), probe.getstate())
        self.portable(game)

    def test_unresolved_rajh_domain_does_not_fall_back_to_normal_cards(self):
        fmt = format_for()
        for pool_id in load_bindings()['unresolved_pool_ids']:
            self.assertNotIn((pool_id, fmt.target_id, fmt.context.mode), fmt.registry.pools)
        game = self.game(hand=('BE_004',))
        saved = game.snapshot()
        with self.assertRaisesRegex((ResolutionError, UnsupportedDefinitionError), 'constructed.assemble.rajh'):
            self.play(game, 'BE_004')
        self.assertEqual(game.snapshot(), saved)

    def test_full_constructed_start_mulligan_and_restore_keep_new_context(self):
        fmt = format_for()
        power = fmt.registry.card('HERO_03').initial_hero_power
        first = DeckSpec('HERO_03', power, CardClass.ROGUE, (CARD, *fillers(fmt, 29)))
        other = DeckSpec('HERO_03', power, CardClass.ROGUE, fillers(fmt, 30))
        game = fmt.new_game((first, other), seed=544, first_player=1)
        restored = self.portable(game)
        while game.state.pending_choice is not None:
            for current in (game, restored):
                choice = current.state.pending_choice
                current.apply(SelectChoice(choice.player_id, choice.id, ()))
            self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(game.snapshot()['generation_context']['target_id'], fmt.target_id)
        self.assertEqual(game.state.players[1].original_deck, first.cards)

    def test_old_and_local_formats_reject_cross_restoration(self):
        fmt = format_for()
        old = build_cn37_launch_candidate_format()
        current = self.game(hand=(CARD,))
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(current.snapshot(), old.registry)
        previous = Game.from_scenario(Scenario((PlayerSetup('HERO_08'),
            PlayerSetup('HERO_08')), generation_context=old.context), old.registry)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(previous.snapshot(), fmt.registry)

    def test_manifest_and_source_inventory_changes_are_rejected(self):
        data = load_bindings()
        data['bindings'][0]['member_ids'].remove('BE_009')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'changed.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('hs_sim.local_pool_format.MANIFEST_PATH', path):
                with self.assertRaises(TargetValidationError):
                    build_cn37_local_pool_format()
        altered = build_cn37_launch_candidate_format()
        source_key = next(key for key in altered.registry.pools if key[0] == POOL)
        source = altered.registry.pools[source_key]
        altered.registry._pools[source_key] = replace(source, members=source.members[1:])
        with patch('hs_sim.local_pool_format.build_cn37_launch_candidate_format', return_value=altered):
            with self.assertRaisesRegex(TargetValidationError, 'original full inventory'):
                build_cn37_local_pool_format()

    def test_missing_executable_member_is_not_filtered_out_of_reviewed_pool(self):
        altered = build_cn37_launch_candidate_format()
        del altered.registry._cards['BE_009']
        with patch('hs_sim.local_pool_format.build_cn37_launch_candidate_format', return_value=altered):
            with self.assertRaisesRegex(UnsupportedDefinitionError, 'BE_009'):
                build_cn37_local_pool_format()


if __name__ == '__main__':
    unittest.main()
