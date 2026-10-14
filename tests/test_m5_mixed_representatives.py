"""R-148: one pinned real carrier over the four existing repeat families."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from hs_sim.targets import TargetValidationError, canonical_digest, load_baseline
from hs_sim.engine import (CardClass, CardType, EndTurn, Game, GenerationContext,
    PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice, UseHeroPower)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (BattlecryRepeatSpec, DeathrattleRepeatSpec,
    EndTurnRepeatSpec, HeroPowerRepeatSpec)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import CARD_LIMITATIONS, EXPECTED_CARD_HASHES, build_registry


ROOT = Path(__file__).resolve().parents[1]
CARD = 'TIME_064'
PIN = '3a188816fe1329124fa54e420b4a5161a0ca3fedb8194b107d18d7f7fbe5e00d'
ENCHANTMENT_PIN = '41e133293cd64d26818aa28d0ee284448d64740544c6bce47fd4993c48344f13'
OLD_ROWS_PIN = '9161dc4e04a7ef99cd77b79edeef0183aad7ec31f64138e624bef5e85c402beb'
FAMILIES = ('battlecry_repeat', 'deathrattle_repeat', 'hero_power_repeat', 'end_turn_repeat')


class MixedRepresentativeTests(unittest.TestCase):
    def setUp(self): self.registry = build_registry()

    def game(self, board=(CARD, 'BOT_107'), hand=(), weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', board=board, hand=hand, weapon_card_id=weapon,
                hero_power_card_id='HERO_08bp', deck=('CS2_182',) * 10, mana=10, max_mana=10),
            PlayerSetup('HERO_01', deck=('CS2_182',) * 10, mana=10, max_mana=10)),
            seed=148, generation_context=GenerationContext('local-2026-09-23', 'experimental')), self.registry)

    def play(self, game, card, target=None):
        owner = game.state.active_player
        entity = next(i for i in game.state.players[owner].hand if game.state.entities[i].card_id == card)
        game.apply(PlayCard(owner, entity, target)); return entity

    def source(self, game):
        return next(game.state.entities[i] for i in game.state.players[1].board
            if game.state.entities[i].card_id == CARD)

    def check(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, build_registry()).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), build_registry()).snapshot(), snapshot)

    def choices(self, game):
        count = 0
        while game.state.pending_choice is not None:
            self.check(game)
            snapshot = game.snapshot(); restored = Game.from_snapshot(snapshot, build_registry())
            choice = game.state.pending_choice
            action = SelectChoice(choice.player_id, choice.id, (choice.options[0].id,))
            game.apply(action); restored.apply(action)
            self.assertEqual(restored.snapshot(), game.snapshot())
            count += 1
        return count

    def test_complete_primary_raw_and_pin_match_independent_extracted_and_frozen_audit(self):
        raw = next(x for x in json.loads((ROOT / 'data/extracted/cards.json').read_text(encoding='utf-8'))
            if x['id'] == CARD)
        audit = json.loads((ROOT / 'outputs/v107-mixed-repeat-pre-audit.json').read_text(encoding='utf-8'))
        saved = next(x['raw'] for x in audit['catalog'] if x['raw']['id'] == CARD)
        row = next(x for x in load_baseline().support['cards'] if x['id'] == CARD)
        self.assertEqual(row['data'], raw); self.assertEqual(raw, saved)
        self.assertEqual((canonical_digest(raw), row['data_sha256'], EXPECTED_CARD_HASHES[CARD]), (PIN,) * 3)

    def test_old_three_hundred_three_complete_support_rows_are_unchanged(self):
        rows = [x for x in load_baseline().support['cards'] if x['id'] not in (CARD, 'RLK_541')]
        self.assertEqual(len(rows), 303); self.assertEqual(canonical_digest(rows), OLD_ROWS_PIN)

    def test_enchantment_remains_independently_pinned_evidence_without_executable_adapter(self):
        raw = next(x for x in json.loads((ROOT / 'data/extracted/cards.json').read_text(encoding='utf-8'))
            if x['id'] == 'TIME_064e')
        self.assertEqual(canonical_digest(raw), ENCHANTMENT_PIN)
        self.assertEqual((raw['type'], raw['collectible'], raw['reference_tags'], raw['related_dbf_ids']),
            ('ENCHANTMENT', False, [], []))
        self.assertNotIn('TIME_064e', self.registry.cards)
        self.assertNotIn('TIME_064e', EXPECTED_CARD_HASHES)

    def test_data_references_do_not_invent_own_bodies_or_dragon_tribe(self):
        card = self.registry.card(CARD)
        self.assertEqual((card.kind, card.cost, card.attack, card.health), (CardType.MINION, 7, 4, 8))
        self.assertEqual((card.metadata.classes, card.metadata.rarity, card.metadata.collectible, card.metadata.tribes),
            ((CardClass.NEUTRAL,), Rarity.LEGENDARY, True, ()))
        self.assertEqual((card.on_play, card.battlecry, card.deathrattle, card.triggers), (None, None, None, ()))

    def test_four_explicit_typed_declarations_keep_independent_family_scopes(self):
        card = self.registry.card(CARD)
        self.assertEqual(card.battlecry_repeats, (BattlecryRepeatSpec(2),))
        self.assertEqual(card.deathrattle_repeats, (DeathrattleRepeatSpec(2,
            (CardType.MINION, CardType.WEAPON, CardType.LOCATION), 'friendly', ('printed', 'granted')),))
        self.assertEqual(card.hero_power_repeats, (HeroPowerRepeatSpec(2),))
        self.assertEqual(card.end_turn_repeats, (EndTurnRepeatSpec(2, 'all'),))

    def test_one_physical_carrier_installs_four_unique_printed_attachment_identities(self):
        game = self.game(board=(CARD,))
        source = self.source(game)
        policies = [active_abilities(source, family)[0] for family in FAMILIES]
        self.assertEqual(len({p.id for p in policies}), 4)
        self.assertTrue(all(p.origin == 'printed' and p.source_id == source.id for p in policies))
        self.assertEqual(tuple(p.kind for p in policies), FAMILIES)
        self.check(game)

    def test_normal_paid_source_play_has_empty_battlecry_receipt_and_no_actual_body(self):
        game = self.game(board=(), hand=(CARD,))
        self.play(game, CARD)
        self.assertEqual(game.state.players[1].mana, 3)
        receipt = game.state.play_history[0].battlecry_acceptance
        self.assertEqual((receipt.payloads, receipt.plan), ((), None))
        self.assertFalse(game.state.battlecry_history); self.assertFalse(game.state.deathrattle_history)
        self.assertFalse(game.state.end_turn_history)
        self.check(game)

    def test_source_alone_is_not_an_end_turn_body(self):
        game = self.game(board=(CARD,))
        game.apply(EndTurn(1))
        self.assertEqual(game.state.end_turn_batches[0].total, 0)
        self.assertFalse(game.state.end_turn_history)
        self.check(game)

    def test_real_scarab_two_choices_roundtrip_with_only_battlecry_source_identity(self):
        game = self.game(board=(CARD,), hand=('LOE_029',))
        self.play(game, 'LOE_029')
        expected = active_abilities(self.source(game), 'battlecry_repeat')[0].id
        self.assertEqual(game.state.battlecry_batches[0].plan.contributors, (expected,))
        self.assertEqual(self.choices(game), 2)
        self.assertEqual([r.repeat_index for r in game.state.battlecry_history], [1, 2])
        self.assertEqual(len(game.state.play_history), 1)
        self.check(game)

    def test_duplicate_real_mixed_sources_merge_max_without_multiplying_any_family(self):
        game = self.game(board=(CARD, CARD, 'BOT_107'), hand=('LOE_029', 'CS2_106'), weapon='CATA_472')
        self.play(game, 'LOE_029'); self.assertEqual(self.choices(game), 2)
        self.assertEqual((game.state.battlecry_batches[0].plan.repetitions,
            len(game.state.battlecry_batches[0].plan.contributors)), (2, 2))
        self.play(game, 'CS2_106')
        outer = game.state.deathrattle_batches[0]
        self.assertEqual((outer.plan.repetitions, len(outer.plan.contributors), outer.total), (2, 2, 2))
        self.assertEqual([b.total for b in game.state.end_turn_batches], [2, 2])
        self.assertTrue(all(len(b.plans[0].contributors) == 2 for b in game.state.end_turn_batches))
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id, game.state.players[2].hero_id))
        self.assertEqual((game.state.hero_power_history[0].repeat_plan.repetitions,
            len(game.state.hero_power_history[0].repeat_plan.contributors)), (2, 2))
        self.check(game)

    def test_real_maul_outer_deathrattles_select_independent_roots_with_inner_end_max_two(self):
        game = self.game(hand=('CS2_106',), weapon='CATA_472')
        self.play(game, 'CS2_106')
        self.assertEqual([r.capture.repeat_index for r in game.state.deathrattle_history], [1, 2])
        groups = game.state.end_turn_batches
        self.assertEqual([b.total for b in groups], [2, 2])
        self.assertTrue(all(b.activation.selection.selected.card_id == 'BOT_107' for b in groups))
        self.assertNotEqual(groups[0].activation.selection.rng_before, groups[1].activation.selection.rng_before)
        self.assertEqual(self.source(game).health, 4)
        self.check(game)

    def test_manual_real_fireblast_pays_and_uses_once_for_two_fresh_payloads(self):
        game = self.game(board=(CARD,))
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id, game.state.players[2].hero_id))
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertEqual(len(game.state.hero_power_history), 1)
        self.assertEqual(len(game.state.hero_power_payload_history), 2)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 28)
        self.assertEqual(game.state.hero_power_history[0].repeat_plan.contributors[0].ability.kind, 'hero_power_repeat')
        self.check(game)

    def test_real_silence_removes_all_four_sources_and_new_family_roots_accept_one(self):
        game = self.game(hand=('EX1_332', 'LOE_029', 'CS2_106'), weapon='CATA_472')
        self.play(game, 'EX1_332', self.source(game).id)
        self.assertTrue(all(not active_abilities(self.source(game), f) for f in FAMILIES))
        self.play(game, 'LOE_029'); self.assertEqual(self.choices(game), 1)
        self.play(game, 'CS2_106')
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id, game.state.players[2].hero_id))
        game.apply(EndTurn(1))
        self.assertEqual(game.state.battlecry_batches[0].plan.repetitions, 1)
        self.assertEqual(game.state.deathrattle_batches[0].plan.repetitions, 1)
        self.assertEqual(game.state.hero_power_history[0].repeat_plan.repetitions, 1)
        self.assertEqual([b.total for b in game.state.end_turn_batches], [1, 1])
        self.check(game)

    def test_tampered_new_raw_fails_pin_even_when_its_row_digest_is_recomputed(self):
        baseline = load_baseline()
        row = next(x for x in baseline.support['cards'] if x['id'] == CARD)
        row['data']['health'] = 9; row['data_sha256'] = canonical_digest(row['data'])
        with patch('hs_sim.engine.representative.load_baseline', return_value=baseline):
            with self.assertRaises(TargetValidationError): build_registry()

    def test_package_counts_and_partial_support_do_not_claim_formal_cn_legality(self):
        support = load_baseline().support
        self.assertEqual((self.registry.version, len(self.registry.cards), len(EXPECTED_CARD_HASHES)),
            ('representative-m5-v65', 311, 305))
        self.assertEqual(sum(c.choice_only for c in self.registry.cards.values()), 14)
        row = next(x for x in support['cards'] if x['id'] == CARD)
        self.assertEqual((row['implementation'], row['stage'], row['mode_legality']),
            ('partial', 'M5', {'standard': None, 'wild': None}))
        self.assertEqual(row['reachable_cards'], [])
        self.assertIn('uncalibrated', CARD_LIMITATIONS[CARD])
        self.assertIn('fixed end-turn producer rounds', CARD_LIMITATIONS[CARD])

    def test_native_example_exercises_four_families_waiting_restore_and_default_replay(self):
        from examples.mixed_repeats import run
        game, summary = run()
        accepted = [event for event in game.events if event.kind == 'spell_cast_accepted']
        self.assertEqual(len(accepted), 1)
        self.assertEqual([(dict(event.data)['cast_id'], event.source_id, event.target_id, event.player_id)
            for event in accepted],
            [(cast.id, cast.source_id, cast.target_id, cast.player_id) for cast in game.state.cast_history])
        self.assertEqual(accepted[0].amount, 1)
        self.assertEqual((summary['actions'], summary['events'] - len(accepted), summary['choices']), (10, 97, 2))
        self.assertEqual((summary['battlecry_positions'], summary['deathrattle_positions'],
            summary['hero_power_roots'], summary['hero_power_positions'], summary['end_turn_positions']), (2, 2, 1, 2, 7))
        self.assertEqual(summary['end_turn_totals'], [2, 0, 2, 2, 1])
        self.assertTrue(summary['shared_source_silenced']); self.assertTrue(summary['restored_and_replayed'])
        self.check(game)


if __name__ == '__main__': unittest.main()
