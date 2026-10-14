"""Real-ID adapters validated against pinned small snapshots and public actions."""
import json
from pathlib import Path
import unittest
from dataclasses import replace
from unittest.mock import patch

from hs_sim.targets import TargetValidationError, canonical_digest, load_baseline
from hs_sim.engine.actions import Attack, EndTurn, PlayCard, UseHeroPower, SelectChoice, action_from_dict
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.model import Keyword, Resource, SpellSchool, Zone
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine import CardClass, MatchSetup, Rarity, Runes, validate_deck
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import (CARD_LIMITATIONS, EXPECTED_CARD_HASHES,
                                         PACKAGE_LIMITATIONS, build_registry)


class RepresentativeTests(unittest.TestCase):
    def test_pinned_construction_metadata_classes_tribes_rarity_and_runes(self):
        r = build_registry()
        self.assertEqual(r.card('CS2_029').metadata.classes, (CardClass.MAGE,))
        self.assertEqual(r.card('EX1_012').metadata.rarity, Rarity.LEGENDARY)
        self.assertEqual(r.card('CS2_203').metadata.tribes, ('beast',))
        self.assertEqual(r.card('RLK_051').metadata.runes, Runes(3))
        self.assertFalse(r.card('GAME_005').metadata.collectible)
        self.assertIsNone(r.card('test.hero').metadata)
        self.assertTrue(all(r.card(i).metadata is not None for i in EXPECTED_CARD_HASHES))

    def test_starting_heroes_have_correct_default_powers(self):
        r = build_registry()
        raw = {row['id']: row['data'] for row in load_baseline().support['cards']}
        for hero, power, card_class in (('HERO_08', 'HERO_08bp', CardClass.MAGE),
                                        ('HERO_01', 'HERO_01bp', CardClass.WARRIOR)):
            c = r.card(hero)
            self.assertEqual((c.health, c.initial_hero_power, c.metadata.classes), (30, power, (card_class,)))
            self.assertEqual(raw[hero]['tags']['HERO_POWER'], raw[power]['dbf_id'])

    def test_real_deck_example_starts_and_rejects_cross_class_card(self):
        root = Path(__file__).resolve().parents[1]
        config = MatchSetup.from_dict(json.loads((root / 'examples/matches/constructed.json').read_text(encoding='utf-8')))
        r = build_registry()
        self.assertTrue(all(validate_deck(d, r, config.policy).valid for d in config.decks))
        wrong = replace(config.decks[1], cards=('CS2_029',) + config.decks[1].cards[1:])
        self.assertIn('class', [i.code for i in validate_deck(wrong, r, config.policy).issues])
        g = Game.from_decks(config, r)
        self.assertEqual([len(p.hand) for p in g.state.players.values()], [3, 4])
        self.assert_replay(g)
        g = Game.from_snapshot(g.snapshot(), r)
        for action in json.loads((root / 'examples/actions/constructed.json').read_text(encoding='utf-8')):
            g.apply(action_from_dict(action))
        self.assertEqual(g.state.opening.stage, 'complete')
        self.assertEqual(g.state.players[2].mana, 2)
        self.assertEqual(g.state.players[2].max_mana, 1)
        self.assert_replay(g)

    def test_real_deck_example_runs_to_terminal_and_replays(self):
        from examples.play_constructed import play_match
        g = play_match()
        self.assertIn(g.state.status, ('finished', 'draw'))
        self.assertGreater(g.state.action_number, 10)
        self.assertEqual(g.state.opening.stage, 'complete')

    def test_nourish_mana_branch_fills_only_gained_crystals_after_one_payment(self):
        g = self.game(('EX1_164',), mana=5, max_mana=5)
        self.cast(g, 'EX1_164', branch='mana')
        self.assertEqual(g.state.players[1].mana, 2)
        self.assert_replay(g)
        g = Game.from_snapshot(g.snapshot(), build_registry())
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (7, 2))
        self.assertEqual([e.kind for e in g.events].count('card_played'), 1)
        self.assert_replay(g)

    def test_nourish_draw_branch_uses_common_burn_and_fatigue(self):
        g = self.game(('EX1_164',) + ('CS2_182',) * 9, deck=('CS2_182',) * 2)
        self.cast(g, 'EX1_164', branch='draw')
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 29)
        self.assertEqual(g.state.players[1].max_mana, 10)
        self.assertEqual([e.kind for e in g.events].count('card_burned'), 1)
        self.assert_replay(g)

    def test_nourish_mana_branch_obeys_existing_mana_cap_without_refresh(self):
        for maximum, expected in ((9, (10, 5)), (10, (10, 5))):
            with self.subTest(maximum=maximum):
                g = self.game(('EX1_164',), mana=maximum, max_mana=maximum)
                self.cast(g, 'EX1_164', branch='mana')
                self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), expected)

    def test_checked_in_choice_example_saves_between_atomic_plays(self):
        root = Path(__file__).resolve().parents[1]
        scenario = Scenario.from_dict(json.loads((root / 'examples/scenarios/choices.json').read_text(encoding='utf-8')))
        actions = json.loads((root / 'examples/actions/choices.json').read_text(encoding='utf-8'))
        g = Game.from_scenario(scenario, build_registry())
        g.apply(action_from_dict(actions[0]))
        self.assertIsNone(g.state.pending_choice)
        self.assert_replay(g)
        g = Game.from_snapshot(g.snapshot(), build_registry())
        for raw in actions[1:]:
            g.apply(action_from_dict(raw))
        self.assertEqual(g.state.players[1].max_mana, 10)
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertEqual(len(g.state.players[1].hand), 3)
        self.assert_replay(g)

    def game(self, hand=(), board=(), enemy_board=(), deck=(), weapon=None, power=None, mana=10, max_mana=10, corpses=0):
        return Game.from_scenario(Scenario(players=(
            PlayerSetup("test.hero", hand=hand, board=board, deck=deck, mana=mana, max_mana=max_mana,
                        weapon_card_id=weapon, hero_power_card_id=power, corpses=corpses),
            PlayerSetup("test.hero", board=enemy_board, mana=10, max_mana=10),
        ), seed=73), build_registry())

    def cast(self, game, card_id, target=None, branch=None):
        state = game.state
        entity = next(i for i in state.players[1].hand if state.entities[i].card_id == card_id)
        return game.apply(PlayCard(1, entity, target, branch_id=branch))

    def assert_replay(self, game):
        restored = replay(build_replay(game), build_registry())
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(restored.history, game.history)

    def test_pinned_real_cards_plus_explicit_test_hero(self):
        registry = build_registry()
        self.assertEqual(registry.version, "representative-m5-v65")
        self.assertEqual(len(EXPECTED_CARD_HASHES), 305)
        self.assertEqual(set(registry.cards), set(EXPECTED_CARD_HASHES) |
            {"test.hero", "CS2_118", "CS2_125", "CS2_127", "EDR_105", "FIR_900"})
        extensions = load_baseline().support['extensions']
        # M0 extensions are the historical audit baseline, not the current adapter.
        self.assertEqual(extensions['runtime_package'], 'representative-m5-v64')
        self.assertEqual(set(extensions['executable_card_ids']), set(EXPECTED_CARD_HASHES))
        self.assertEqual(registry.card("test.hero").health, 30)
        self.assertTrue(PACKAGE_LIMITATIONS)
        self.assertIn("CS2_029", CARD_LIMITATIONS)

    def test_real_spell_schools_are_explicitly_mapped(self):
        registry = build_registry()
        for card, school in (('CS2_029', SpellSchool.FIRE), ('CS2_024', SpellSchool.FROST),
                            ('EX1_238', SpellSchool.NATURE), ('CS2_007', SpellSchool.NATURE),
                            ('CS1_112', SpellSchool.HOLY)):
            self.assertEqual(registry.card(card).spell_school, school)
        self.assertIsNone(registry.card('GAME_005').spell_school)

    def test_velen_doubles_fireball_after_spell_damage(self):
        g = self.game(('CS2_029',), board=('EX1_350', 'EX1_012'))
        self.cast(g, 'CS2_029', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 16)
        self.assert_replay(g)

    def test_velen_doubles_fireblast(self):
        g = self.game(board=('EX1_350',), power='HERO_08bp')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 28)

    def test_velen_healing_touch_restores_missing_health(self):
        g = self.game(('CS2_029', 'CS2_007'), board=('EX1_350',))
        self.cast(g, 'CS2_029', g.state.players[1].hero_id)
        result = self.cast(g, 'CS2_007', g.state.players[1].hero_id)
        healed = next(e for e in result.events if e.kind == 'healed')
        self.assertEqual((healed.amount, dict(healed.data)['modified_amount']), (12, 16))
        self.assert_replay(g)

    def test_auchenai_turns_healing_touch_into_damage(self):
        g = self.game(('CS2_007',), board=('EX1_591',))
        self.cast(g, 'CS2_007', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)
        self.assert_replay(g)

    def test_auchenai_earthen_ring_battlecry_and_silence(self):
        g = self.game(('CS2_117', 'EX1_332', 'CS2_117'), board=('EX1_591',))
        target = g.state.players[2].hero_id
        self.cast(g, 'CS2_117', target)
        self.assertEqual(g.state.entities[target].health, 27)
        self.cast(g, 'EX1_332', g.state.players[1].board[0])
        self.cast(g, 'CS2_117', target)
        self.assertEqual(g.state.entities[target].health, 30)

    def test_moarg_doubles_spell_damage_to_minions_only(self):
        g = self.game(('EX1_238', 'EX1_238'), board=('BT_733',), enemy_board=('CS2_182',))
        self.cast(g, 'EX1_238', g.state.players[2].board[0])
        self.assertFalse(g.state.players[2].board)
        self.cast(g, 'EX1_238', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.assert_replay(g)

    def test_animated_armor_limits_hero_damage_and_silence_removes_it(self):
        g = self.game(('CS2_029', 'EX1_332', 'CS2_029'), enemy_board=('LOE_119',))
        hero = g.state.players[2].hero_id
        self.cast(g, 'CS2_029', hero)
        self.assertEqual(g.state.entities[hero].health, 29)
        self.cast(g, 'EX1_332', g.state.players[2].board[0])
        self.cast(g, 'CS2_029', hero)
        self.assertEqual(g.state.entities[hero].health, 23)

    def test_bolf_receives_hero_damage_then_dies_without_overflow(self):
        g = self.game(('CS2_029', 'CS2_029'), enemy_board=('AT_124',))
        hero = g.state.players[2].hero_id
        bolf = g.state.players[2].board[0]
        self.cast(g, 'CS2_029', hero)
        self.assertEqual((g.state.entities[hero].health, g.state.entities[bolf].health), (30, 3))
        self.cast(g, 'CS2_029', hero)
        self.assertEqual(g.state.entities[hero].health, 30)
        self.assertEqual(g.state.entities[bolf].zone, Zone.GRAVEYARD)
        self.assert_replay(g)

    def test_holy_nova_uses_enemy_minions_and_friendly_character_batches(self):
        g = self.game(('EX1_238', 'CS1_112'), board=('CS2_182',), enemy_board=('EX1_096',))
        self.cast(g, 'EX1_238', g.state.players[1].board[0])
        self.cast(g, 'CS1_112')
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health, 4)
        self.assertFalse(g.state.players[2].board)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 29)  # Loot Hoarder fatigue
        self.assert_replay(g)

    def test_auchenai_lifesteal_chillblade_conversion_is_bounded(self):
        g = self.game(('ICC_820',), board=('EX1_591',))
        self.cast(g, 'ICC_820')
        result = g.apply(Attack(1, g.state.players[1].board[-1], g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 27)
        self.assertEqual(sum(e.kind == 'lifesteal' for e in result.events), 1)
        self.assert_replay(g)

    def test_coin_and_innervate_grant_only_temporary_mana(self):
        for card_id in ('GAME_005', 'EX1_169'):
            with self.subTest(card=card_id):
                g = self.game((card_id,), mana=1, max_mana=1)
                self.cast(g, card_id)
                self.assertEqual((g.state.players[1].mana, g.state.players[1].max_mana), (2, 1))
                g.apply(EndTurn(1))
                self.assertEqual((g.state.players[1].mana, g.state.players[1].temporary_mana), (1, 0))
                self.assert_replay(g)

    def test_preparation_discounts_next_spell_not_minion(self):
        g = self.game(('EX1_145', 'CS2_182', 'CS2_029'))
        self.cast(g, 'EX1_145')
        self.cast(g, 'CS2_182')
        self.cast(g, 'CS2_029', g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana, 4)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assert_replay(g)

    def test_preparation_is_used_by_coin_even_though_coin_is_free(self):
        g = self.game(('EX1_145', 'GAME_005', 'CS2_029'), mana=5)
        self.cast(g, 'EX1_145')
        self.cast(g, 'GAME_005')
        self.cast(g, 'CS2_029', g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana, 2)

    def test_preparation_expires_at_end_of_turn(self):
        g = self.game(('EX1_145', 'CS2_029'))
        self.cast(g, 'EX1_145')
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.cast(g, 'CS2_029', g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana, 6)

    def test_apprentice_current_floor_preserves_zero_spell(self):
        g = self.game(('EX1_238', 'GAME_005'), board=('EX1_608', 'EX1_608'))
        ids = {g.state.entities[i].card_id: i for i in g.state.players[1].hand}
        self.assertEqual(g.quote_cost(ids['EX1_238']).amount, 1)
        self.assertEqual(g.quote_cost(ids['GAME_005']).amount, 0)
        self.cast(g, 'EX1_238', g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assert_replay(g)

    def test_lightning_bolt_spell_damage_and_next_turn_overload(self):
        g = self.game(('EX1_238',), board=('EX1_012',), mana=3, max_mana=3, deck=('CS2_182',))
        self.cast(g, 'EX1_238', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual(g.state.players[1].overload_owed, 1)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana, g.state.players[1].overload_locked), (4, 3, 1))
        self.assert_replay(g)

    def test_vampiric_blood_without_corpses_remains_playable(self):
        g = self.game(('RLK_051',), corpses=2, deck=('CS2_182',))
        self.cast(g, 'RLK_051')
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.max_health, hero.health), (35, 35))
        self.assertEqual((g.state.players[1].resources[Resource.CORPSES], len(g.state.players[1].deck)), (2, 1))
        self.assert_replay(g)

    def test_vampiric_blood_spends_exactly_three_and_draws_once(self):
        g = self.game(('RLK_051',), corpses=4, deck=('CS2_182', 'CS2_179'))
        self.cast(g, 'RLK_051')
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.max_health, hero.health), (40, 40))
        p = g.state.players[1]
        self.assertEqual((p.resources[Resource.CORPSES], len(p.deck), len(p.hand)), (1, 1, 1))
        self.assert_replay(g)

    def test_vampiric_blood_gains_health_before_fatigue(self):
        g = self.game(('CS2_029', 'RLK_051'), corpses=3)
        self.cast(g, 'CS2_029', g.state.players[1].hero_id)
        self.cast(g, 'RLK_051')
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.max_health, hero.health, hero.damage), (40, 33, 7))

    def test_reviewed_numeric_data_and_explicit_missing_tag_defaults(self):
        registry = build_registry()
        expected = {
            "CS2_182": (4, 4, 5), "CS2_179": (4, 3, 5), "CS2_029": (4, 0, 0),
            "CS2_009": (2, 0, 0), "EX1_332": (0, 0, 0), "CS2_203": (3, 2, 1),
            "EX1_581": (2, 0, 0), "EX1_096": (2, 2, 1), "FP1_007": (2, 0, 2),
            "FP1_007t": (4, 4, 4), "CS2_122": (3, 2, 3), "ULD_205": (3, 3, 2),
            "ULD_208": (6, 3, 4), "CS2_188": (1, 1, 1), "EX1_019": (3, 3, 2),
            "EX1_012": (2, 1, 1),
            "CS2_024": (2, 0, 0), "ICC_820": (4, 3, 2), "EX1_010": (1, 2, 1), "CS2_222": (7, 7, 7),
            "CS1_129": (1, 0, 0), "CS2_236": (2, 0, 0), "EX1_059": (2, 2, 2),
        }
        for card_id, numbers in expected.items():
            with self.subTest(card_id=card_id):
                card = registry.card(card_id)
                self.assertEqual((card.cost, card.attack, card.health), numbers)

    def test_unimplemented_effect_is_not_registered_as_blank_card(self):
        registry = build_registry()
        for card_id in ("ULD_209", "unknown.card"):
            with self.subTest(card_id=card_id), self.assertRaises(UnsupportedDefinitionError):
                registry.card(card_id)

    def test_changed_snapshot_requires_adapter_version_review(self):
        baseline = load_baseline()
        row = next(r for r in baseline.support["cards"] if r["id"] == "CS2_029")
        row["data"]["text_en"] = "Deal $7 damage."
        # Even someone updating both raw data and its digest cannot silently change this adapter.
        row["data_sha256"] = canonical_digest(row["data"])
        with patch("hs_sim.engine.representative.load_baseline", return_value=baseline):
            with self.assertRaisesRegex(TargetValidationError, "pinned card version"):
                build_registry()

    def test_missing_whitelist_record_is_not_silently_removed(self):
        baseline = load_baseline()
        baseline.support["cards"] = [r for r in baseline.support["cards"] if r["id"] != "ULD_205"]
        with patch("hs_sim.engine.representative.load_baseline", return_value=baseline):
            with self.assertRaises(TargetValidationError):
                build_registry()

    def test_mark_uses_current_plus_two_plus_three_and_silence_removes_it(self):
        game = self.game(hand=("CS2_009", "EX1_332"), board=("CS2_182",))
        yeti = game.state.players[1].board[0]
        self.cast(game, "CS2_009", yeti)
        entity = game.state.entities[yeti]
        self.assertEqual((entity.attack, entity.max_health), (6, 8))
        self.assertIn(Keyword.TAUNT, entity.keywords)
        self.assertTrue(entity.enchantments)
        self.cast(game, "EX1_332", yeti)
        entity = game.state.entities[yeti]
        self.assertEqual((entity.attack, entity.max_health), (4, 5))
        self.assertNotIn(Keyword.TAUNT, entity.keywords)
        self.assertFalse(entity.enchantments)
        self.assert_replay(game)

    def test_sap_resets_stats_but_preserves_entity_identity(self):
        game = self.game(hand=("CS2_009", "EX1_581"), enemy_board=("CS2_182",))
        target = game.state.players[2].board[0]
        self.cast(game, "CS2_009", target)
        self.cast(game, "EX1_581", target)
        entity = game.state.entities[target]
        self.assertEqual(game.state.players[2].hand, [target])
        self.assertEqual(entity.zone, Zone.HAND)
        self.assertEqual((entity.attack, entity.health), (4, 5))
        self.assertFalse(entity.enchantments)
        self.assertNotIn(Keyword.TAUNT, entity.keywords)
        self.assert_replay(game)

    def test_sap_rejects_friendly_minion_without_mutation(self):
        game = self.game(hand=("EX1_581",), board=("CS2_182",))
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.cast(game, "EX1_581", game.state.players[1].board[0])
        self.assertEqual(game.snapshot(), before)

    def test_egg_uses_last_known_position_to_summon_reachable_token(self):
        game = self.game(hand=("CS2_029",), board=("CS2_182", "FP1_007", "CS2_179"))
        old_board = game.state.players[1].board
        self.cast(game, "CS2_029", old_board[1])
        state = game.state
        self.assertEqual([state.entities[i].card_id for i in state.players[1].board], ["CS2_182", "FP1_007t", "CS2_179"])
        token = state.entities[state.players[1].board[1]]
        self.assertEqual((token.attack, token.health), (4, 4))
        self.assertNotEqual(token.id, old_board[1])
        self.assert_replay(game)

    def test_loot_hoarder_draws_for_controller(self):
        game = self.game(hand=("CS2_029",), board=("EX1_096",), deck=("CS2_182",))
        deck_card = game.state.players[1].deck[0]
        self.cast(game, "CS2_029", game.state.players[1].board[0])
        self.assertEqual(game.state.players[1].hand, [deck_card])
        self.assertEqual(game.state.players[1].deck, [])

    def test_reborn_candletaker_discards_buff_and_consumes_reborn(self):
        game = self.game(hand=("CS2_009", "CS2_029"), board=("ULD_205",))
        old = game.state.players[1].board[0]
        self.cast(game, "CS2_009", old)
        self.cast(game, "CS2_029", old)
        state = game.state
        new = state.entities[state.players[1].board[0]]
        self.assertNotEqual(new.id, old)
        self.assertEqual(new.origin_entity_id, old)
        self.assertEqual((new.attack, new.max_health, new.health), (3, 2, 1))
        self.assertNotIn(Keyword.REBORN, new.keywords)
        self.assertNotIn(Keyword.TAUNT, new.keywords)
        self.assertFalse(new.enchantments)
        self.assertEqual(state.entities[old].zone, Zone.GRAVEYARD)
        self.assert_replay(game)

    def test_khartut_heals_on_each_death_but_reborn_only_once(self):
        game = self.game(hand=("CS2_029", "CS2_029"), board=("CS2_182",), enemy_board=("ULD_208",))
        hero = game.state.players[2].hero_id
        original = game.state.players[2].board[0]
        self.cast(game, "CS2_029", hero)
        self.assertEqual(game.state.entities[hero].health, 24)
        self.cast(game, "CS2_029", original)
        self.assertEqual(game.state.entities[hero].health, 27)
        reborn = game.state.players[2].board[0]
        self.assertIn(Keyword.TAUNT, game.state.entities[reborn].keywords)
        game.apply(Attack(1, game.state.players[1].board[0], reborn))
        self.assertEqual(game.state.players[2].board, [])
        self.assertEqual(game.state.entities[hero].health, 30)
        self.assertEqual(sum(e.kind == "minion_reborn" for e in game.events), 1)
        self.assertEqual(sum(e.kind == "healed" for e in game.events), 2)
        self.assert_replay(game)

    def test_silence_owl_removes_printed_reborn_before_death(self):
        game = self.game(hand=("CS2_203", "CS2_029"), enemy_board=("ULD_205",))
        target = game.state.players[2].board[0]
        self.cast(game, "CS2_203", target)
        self.cast(game, "CS2_029", target)
        self.assertEqual(game.state.players[2].board, [])
        self.assertFalse(any(e.kind == "minion_reborn" for e in game.events))

    def test_sergeant_buff_expires_at_turn_boundary(self):
        game = self.game(hand=("CS2_188",), board=("CS2_182",))
        yeti = game.state.players[1].board[0]
        self.cast(game, "CS2_188", yeti)
        self.assertEqual(game.state.entities[yeti].attack, 6)
        game.apply(EndTurn(1))
        self.assertEqual(game.state.entities[yeti].attack, 4)
        self.assert_replay(game)

    def test_cleric_targets_existing_friendly_minion(self):
        game = self.game(hand=("EX1_019",), board=("CS2_182",), enemy_board=("CS2_182",))
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.cast(game, "EX1_019", game.state.players[2].board[0])
        self.assertEqual(game.snapshot(), before)
        yeti = game.state.players[1].board[0]
        self.cast(game, "EX1_019", yeti)
        self.assertEqual((game.state.entities[yeti].attack, game.state.entities[yeti].health), (5, 6))

    def test_targetless_battlecries_can_be_played_without_legal_targets(self):
        for card_id in ('CS2_203', 'CS2_188', 'EX1_019'):
            with self.subTest(card_id=card_id):
                game = self.game(hand=(card_id,))
                entity = game.state.players[1].hand[0]
                self.assertIn(PlayCard(1, entity, position=0), game.legal_actions())
                self.cast(game, card_id)
                self.assertEqual(game.state.players[1].board, [entity])
                self.assertFalse(game.state.entities[entity].enchantments)
                self.assert_replay(game)

    def test_raid_leader_aura_is_removed_by_silence(self):
        game = self.game(hand=("EX1_332",), board=("CS2_122", "CS2_182"))
        leader, yeti = game.state.players[1].board
        self.assertEqual(game.state.entities[yeti].attack, 5)
        self.cast(game, "EX1_332", leader)
        self.assertEqual(game.state.entities[yeti].attack, 4)

    def test_bloodmage_stacks_fireball_bonus_and_silence_removes_one_source(self):
        game = self.game(hand=('CS2_029', 'EX1_332', 'CS2_029'), board=('EX1_012', 'EX1_012'))
        enemy = game.state.players[2].hero_id
        self.cast(game, 'CS2_029', enemy)
        self.assertEqual(game.state.entities[enemy].health, 22)
        self.cast(game, 'EX1_332', game.state.players[1].board[0])
        self.cast(game, 'CS2_029', enemy)
        self.assertEqual(game.state.entities[enemy].health, 15)
        self.assert_replay(game)

    def test_bloodmage_death_draws_and_disables_bonus_for_following_spell(self):
        game = self.game(hand=('CS2_029', 'CS2_029'), board=('EX1_012',), deck=('CS2_182',))
        source = game.state.players[1].board[0]
        result = self.cast(game, 'CS2_029', source)
        self.assertEqual(next(e.amount for e in result.events if e.kind == 'damage_dealt'), 7)
        self.assertIn('CS2_182', [game.state.entities[i].card_id for i in game.state.players[1].hand])
        self.assertEqual(game.state.players[1].deck, [])
        enemy = game.state.players[2].hero_id
        self.cast(game, 'CS2_029', enemy)
        self.assertEqual(game.state.entities[enemy].health, 24)
        self.assert_replay(game)

    def test_targeted_battlecry_cannot_omit_target_when_available(self):
        for card_id in ('CS2_203', 'CS2_188', 'EX1_019'):
            with self.subTest(card_id=card_id):
                game = self.game(hand=(card_id,), board=('CS2_182',))
                before = game.snapshot()
                with self.assertRaises(IllegalAction):
                    self.cast(game, card_id)
                self.assertEqual(game.snapshot(), before)

    def test_checked_in_spell_damage_example(self):
        root = Path(__file__).resolve().parents[1]
        scenario = Scenario.from_dict(json.loads((root / 'examples/scenarios/spell-damage.json').read_text(encoding='utf-8')))
        actions = json.loads((root / 'examples/actions/spell-damage.json').read_text(encoding='utf-8'))
        game = Game.from_scenario(scenario, build_registry())
        for action in actions:
            game.apply(action_from_dict(action))
        self.assertEqual([e.amount for e in game.events if e.kind == 'damage_dealt'], [7, 6])
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 17)
        self.assert_replay(game)

    def test_chillblade_champion_charge_lifesteal(self):
        game = self.game(hand=('CS2_029', 'ICC_820'))
        hero, enemy = game.state.players[1].hero_id, game.state.players[2].hero_id
        self.cast(game, 'CS2_029', hero)
        self.cast(game, 'ICC_820')
        champion = game.state.players[1].board[0]
        game.apply(Attack(1, champion, enemy))
        self.assertEqual(game.state.entities[hero].health, 27)
        self.assertEqual(game.state.entities[enemy].health, 27)
        self.assert_replay(game)

    def test_frostbolt_damage_and_opponent_thaw(self):
        game = self.game(hand=('CS2_024',), enemy_board=('CS2_182',))
        target = game.state.players[2].board[0]
        self.cast(game, 'CS2_024', target)
        self.assertEqual(game.state.entities[target].health, 2)
        self.assertTrue(game.state.entities[target].frozen)
        game.apply(EndTurn(1))
        with self.assertRaises(IllegalAction):
            game.apply(Attack(2, target, game.state.players[1].hero_id))
        game.apply(EndTurn(2))
        self.assertFalse(game.state.entities[target].frozen)
        self.assert_replay(game)

    def test_worgen_infiltrator_cannot_be_selected_until_attacking(self):
        game = self.game(hand=('CS2_024',), enemy_board=('EX1_010',))
        target = game.state.players[2].board[0]
        with self.assertRaises(IllegalAction):
            self.cast(game, 'CS2_024', target)
        game.apply(EndTurn(1))
        game.apply(Attack(2, target, game.state.players[1].hero_id))
        self.assertNotIn(Keyword.STEALTH, game.state.entities[target].keywords)
        game.apply(EndTurn(2))
        self.cast(game, 'CS2_024', target)
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.assert_replay(game)

    def test_stormwind_champion_aura_silence_and_last_health(self):
        game = self.game(hand=('CS2_024', 'EX1_332'), board=('CS2_222', 'CS2_182'))
        champion, yeti = game.state.players[1].board
        self.assertEqual((game.state.entities[yeti].attack, game.state.entities[yeti].health), (5, 6))
        self.cast(game, 'CS2_024', yeti)
        self.cast(game, 'EX1_332', champion)
        self.assertEqual((game.state.entities[yeti].attack, game.state.entities[yeti].health), (4, 3))
        self.assert_replay(game)

    def test_checked_in_combat_status_example(self):
        root = Path(__file__).resolve().parents[1]
        scenario = Scenario.from_dict(json.loads((root / 'examples/scenarios/combat-status.json').read_text(encoding='utf-8')))
        actions = json.loads((root / 'examples/actions/combat-status.json').read_text(encoding='utf-8'))
        game = Game.from_scenario(scenario, build_registry())
        for action in actions:
            game.apply(action_from_dict(action))
        self.assertEqual(game.state.entities[1].health, 30)
        self.assertEqual(game.state.entities[7].health, 23)
        self.assertTrue(game.state.entities[8].frozen)
        self.assertNotIn(Keyword.STEALTH, game.state.entities[6].keywords)
        self.assertEqual((game.state.entities[4].attack, game.state.entities[4].max_health), (4, 3))
        self.assert_replay(game)

    def test_divine_spirit_and_inner_fire_use_injured_remaining_health(self):
        game = self.game(hand=('CS2_024', 'CS2_236', 'CS1_129'), board=('CS2_182',))
        target = game.state.players[1].board[0]
        for card in ('CS2_024', 'CS2_236', 'CS1_129'):
            self.cast(game, card, target)
        entity = game.state.entities[target]
        self.assertEqual((entity.attack, entity.health, entity.max_health, entity.damage), (4, 4, 7, 3))
        self.assert_replay(game)

    def test_alchemist_swaps_remaining_health_and_resets_damage(self):
        game = self.game(hand=('CS2_024', 'EX1_059'), board=('CS2_179',))
        target = game.state.players[1].board[0]
        self.cast(game, 'CS2_024', target)
        self.cast(game, 'EX1_059', target)
        entity = game.state.entities[target]
        self.assertEqual((entity.attack, entity.health, entity.max_health, entity.damage), (2, 3, 3, 0))
        self.assertTrue(entity.frozen)
        self.assert_replay(game)

    def test_alchemist_zero_attack_kills_egg_and_runs_deathrattle(self):
        game = self.game(hand=('EX1_059',), enemy_board=('FP1_007',))
        target = game.state.players[2].board[0]
        self.cast(game, 'EX1_059', target)
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[2].board], ['FP1_007t'])
        self.assertEqual(game.state.death_history[0].max_health, 0)
        self.assert_replay(game)

    def test_alchemist_can_be_played_without_another_minion(self):
        game = self.game(hand=('EX1_059',))
        card = game.state.players[1].hand[0]
        self.assertEqual(game.legal_targets(card), ())
        self.cast(game, 'EX1_059')
        self.assertEqual(game.state.players[1].board, [card])
        self.assertFalse(game.state.entities[card].enchantments)

    def test_stat_spells_and_alchemist_reject_heroes_atomically(self):
        for card in ('CS1_129', 'CS2_236', 'EX1_059'):
            with self.subTest(card=card):
                game = self.game(hand=(card,), board=('CS2_182',))
                before = game.snapshot()
                with self.assertRaises(IllegalAction):
                    self.cast(game, card, game.state.players[1].hero_id)
                self.assertEqual(before, game.snapshot())

    def test_stat_spell_aura_order_and_silence_follow_provisional_contract(self):
        game = self.game(hand=('CS1_129', 'EX1_332'), board=('CS2_222', 'CS2_182'))
        target = game.state.players[1].board[1]
        self.cast(game, 'CS1_129', target)
        self.assertEqual((game.state.entities[target].attack, game.state.entities[target].health), (7, 6))
        self.cast(game, 'EX1_332', target)
        self.assertEqual((game.state.entities[target].attack, game.state.entities[target].health), (5, 6))

    def test_checked_in_stat_operations_example(self):
        root = Path(__file__).resolve().parents[1]
        scenario = Scenario.from_dict(json.loads((root / 'examples/scenarios/stat-operations.json').read_text(encoding='utf-8')))
        actions = json.loads((root / 'examples/actions/stat-operations.json').read_text(encoding='utf-8'))
        game = Game.from_scenario(scenario, build_registry())
        for raw, expected in zip(actions, ((3, 2, 5), (3, 4, 7), (4, 3, 3), (3, 3, 3), (3, 5, 5)), strict=True):
            game.apply(action_from_dict(raw))
            entity = game.state.entities[7]
            self.assertEqual((entity.attack, entity.health, entity.max_health), expected)
        self.assertFalse(game.state.entities[7].enchantments)
        self.assertFalse(game.state.entities[7].frozen)
        self.assert_replay(game)

    def test_weapon_data_maps_health_tag_to_durability(self):
        registry = build_registry()
        for card, cost, attack, durability in (('CS2_106',2,3,2), ('CS2_082',1,1,2), ('FP1_021',4,4,2)):
            with self.subTest(card=card):
                definition = registry.card(card)
                self.assertEqual((definition.cost,definition.attack,definition.health,definition.durability),
                                 (cost,attack,0,durability))

    def test_fireblast_uses_hero_power_action_and_ignores_spell_damage(self):
        game = self.game(power='HERO_08bp', board=('EX1_012',))
        player, enemy = game.state.players[1], game.state.players[2]
        game.apply(UseHeroPower(1, player.hero_power_id, enemy.hero_id))
        self.assertEqual(game.state.entities[enemy.hero_id].health, 29)
        self.assertEqual(game.state.players[1].mana, 8)
        self.assert_replay(game)

    def test_dagger_mastery_generates_pinned_weapon_and_allows_hero_attack(self):
        game = self.game(power='HERO_03bp')
        player, enemy = game.state.players[1], game.state.players[2]
        game.apply(UseHeroPower(1, player.hero_power_id))
        dagger_id = game.state.players[1].weapon_id
        self.assertEqual(game.state.entities[dagger_id].card_id, 'CS2_082')
        game.apply(Attack(1, player.hero_id, enemy.hero_id))
        self.assertEqual(game.state.entities[dagger_id].durability, 1)
        self.assertEqual(game.state.entities[enemy.hero_id].health, 29)
        self.assert_replay(game)

    def test_deaths_bite_replacement_deals_simultaneous_damage_to_both_boards(self):
        game = self.game(weapon='FP1_021', hand=('CS2_106',), board=('EX1_096',),
                         enemy_board=('EX1_096',), deck=('CS2_182',))
        old_weapon = game.state.players[1].weapon_id
        self.cast(game, 'CS2_106')
        self.assertEqual(game.state.players[1].board, [])
        self.assertEqual(game.state.players[2].board, [])
        history = game.state.death_history
        self.assertEqual(history[0].entity_id, old_weapon)
        self.assertEqual(history[1].batch, history[2].batch)
        self.assertEqual(len(game.state.players[1].hand), 1)
        self.assert_replay(game)

    def test_reinforce_produces_pinned_recruit_and_rejects_full_board(self):
        game = self.game(power='HERO_04bp')
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        recruit = game.state.entities[game.state.players[1].board[0]]
        self.assertEqual((recruit.card_id,recruit.attack,recruit.health), ('CS2_101t',1,1))
        full = self.game(power='HERO_04bp', board=('CS2_182',)*7)
        before = full.snapshot()
        with self.assertRaises(IllegalAction):
            full.apply(UseHeroPower(1, full.state.players[1].hero_power_id))
        self.assertEqual(before, full.snapshot())

    def test_shapeshift_attack_expires_but_armor_remains(self):
        game = self.game(power='HERO_06bp')
        player = game.state.players[1]
        game.apply(UseHeroPower(1, player.hero_power_id))
        hero = game.state.entities[player.hero_id]
        self.assertEqual((hero.attack,hero.armor), (1,1))
        game.apply(EndTurn(1))
        hero = game.state.entities[player.hero_id]
        self.assertEqual((hero.attack,hero.armor), (0,1))
        self.assert_replay(game)

    def test_armor_up_gains_two_armor(self):
        game = self.game(power='HERO_01bp')
        player = game.state.players[1]
        game.apply(UseHeroPower(1, player.hero_power_id))
        self.assertEqual(game.state.entities[player.hero_id].armor, 2)

    def test_checked_in_equipment_power_example_and_replay(self):
        root = Path(__file__).resolve().parents[1]
        scenario = Scenario.from_dict(json.loads((root / 'examples/scenarios/equipment-powers.json').read_text(encoding='utf-8')))
        actions = json.loads((root / 'examples/actions/equipment-powers.json').read_text(encoding='utf-8'))
        game = Game.from_scenario(scenario, build_registry())
        for raw in actions:
            game.apply(action_from_dict(raw))
        self.assertEqual(game.state.entities[1].health, 26)
        self.assertEqual(game.state.entities[6].health, 25)
        self.assertEqual(game.state.entities[6].armor, 0)
        self.assertEqual(len(game.state.players[1].board), 0)
        self.assertEqual(game.state.entities[game.state.players[1].weapon_id].card_id, 'CS2_082')
        self.assertEqual(game.state.entities[game.state.players[1].weapon_id].durability, 1)
        self.assert_replay(game)

    def test_checked_in_reborn_example_and_replay(self):
        root = Path(__file__).resolve().parents[1]
        scenario = Scenario.from_dict(json.loads((root / "examples/scenarios/reborn.json").read_text(encoding="utf-8")))
        actions = json.loads((root / "examples/actions/reborn.json").read_text(encoding="utf-8"))
        game = Game.from_scenario(scenario, build_registry())
        for raw in actions:
            game.apply(action_from_dict(raw))
        self.assertEqual(game.state.players[2].board, [])
        self.assertEqual(sum(e.kind == "minion_reborn" for e in game.events), 1)
        self.assertEqual(len(game.history), 3)
        self.assert_replay(game)


if __name__ == "__main__":
    unittest.main()
