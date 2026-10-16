"""Execute a finite real-card batch through the existing payment and combat APIs."""

from unittest.mock import patch
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hs_sim.cards.constructed import build_registry, load_batch, CONTENT_VERSION
from hs_sim.engine import CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup, Scenario
from hs_sim.engine.actions import Attack
from hs_sim.engine.effects import Buff, Damage, Destroy, ReturnToHand, Silence
from hs_sim.engine.errors import IllegalAction, SnapshotError
from hs_sim.engine.model import CardClass, DamageKind, Zone
from hs_sim.engine.construction import DeckPolicy, DeckSpec, validate_deck
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry as build_representative_registry
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError


class ConstructedKeywordCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry()
        cls.batch = load_batch()
        for name, body in (
            ("ping", lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),)),
            ("destroy", lambda c: (Destroy(c.target_id),)),
            ("silence", lambda c: (Silence(c.target_id),)),
            ("buff", lambda c: (Buff(c.target_id, 2, 3, source_id=c.source_id),)),
            ("bounce", lambda c: (ReturnToHand(c.target_id),)),
        ):
            cls.registry.register_behavior("cardbatch.test."+name, body)
            cls.registry.register_card(CardDefinition("cardbatch.test."+name, name,
                CardType.SPELL, requires_target=True, on_play="cardbatch.test."+name))

    def game(self, *, hand=(), board=(), enemy=(), mana=20):
        # An explicit test cap lets the 11-cost printed card execute without
        # changing the ordinary ten-mana rules or rewriting its printed cost.
        return Game.from_scenario(Scenario((
            PlayerSetup("test.hero", hand=hand, board=board, mana=mana, max_mana=mana, mana_cap=20),
            PlayerSetup("test.hero", board=enemy),
        )), self.registry)

    def play(self, game, cid, target=None):
        eid = next(e for e in game.state.players[1].hand if game.state.entities[e].card_id == cid)
        game.apply(PlayCard(1, eid, target_id=target))
        return eid

    def test_all_45_reviewed_cards_enter_with_printed_stats_and_one_payment(self):
        self.assertEqual(len(self.batch["cards"]), 45)
        for row in self.batch["cards"]:
            raw, recipe = row["record"], row["recipe"]
            with self.subTest(cid=raw["id"]):
                game = self.game(hand=(raw["id"],))
                eid = self.play(game, raw["id"])
                state = game.state
                entity = state.entities[eid]
                self.assertEqual(state.players[1].board, [eid])
                self.assertEqual((entity.attack, entity.health), (recipe["attack"], recipe["health"]))
                self.assertEqual(state.players[1].mana, 20-recipe["cost"])
                self.assertEqual(set(entity.keywords), set(Keyword(k) for k in recipe["keywords"]))
                self.assertEqual(sum(e.kind == "card_played" for e in game.events), 1)
                self.assertEqual(sum(e.kind == "minion_summoned" for e in game.events), 1)

    def test_low_and_high_cost_boundaries_preserve_printed_cost(self):
        for cid in ("CORE_CS2_231", "CORE_ICC_023"):
            game = self.game(hand=(cid,), mana=0)
            self.play(game, cid)
            self.assertEqual(game.state.players[1].mana, 0)
        game = self.game(hand=("TLC_248",), mana=10)
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(game, "TLC_248")
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(self.registry.card("TLC_248").cost, 11)

    def test_charge_can_attack_hero_and_plain_minion_cannot_on_entry(self):
        game = self.game(hand=("CORE_EX1_543", "CORE_CS2_182"))
        charge = self.play(game, "CORE_EX1_543")
        hero = game.state.players[2].hero_id
        game.apply(Attack(1, charge, hero))
        self.assertEqual(game.state.entities[hero].health, 22)
        plain = self.play(game, "CORE_CS2_182")
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, plain, hero))

    def test_rush_can_attack_minion_and_cannot_attack_hero_on_entry(self):
        game = self.game(hand=("CORE_CS3_030",), enemy=("CORE_CS2_182",))
        eid = self.play(game, "CORE_CS3_030")
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, game.state.players[2].hero_id))
        self.assertEqual(game.snapshot(), before)
        target = game.state.players[2].board[0]
        game.apply(Attack(1, eid, target))
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)

    def test_actual_alakir_two_attacks_consume_shield_and_hit_windfury_limit(self):
        game = self.game(hand=("CORE_NEW1_010",), enemy=("CORE_CS2_182", "CORE_CS2_182"))
        eid = self.play(game, "CORE_NEW1_010")
        target = game.state.players[2].board[0]
        game.apply(Attack(1, eid, target))
        self.assertEqual(game.state.entities[eid].health, 6)
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[eid].keywords)
        game.apply(Attack(1, eid, target))
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, game.state.players[2].hero_id))

    def test_taunt_redirects_legal_attack_and_stealth_blocks_targeting(self):
        game = self.game(board=("CORE_CS2_182",),
            enemy=("CORE_CS2_179", "CORE_EX1_010"), hand=("cardbatch.test.ping",))
        attacker = game.state.players[1].board[0]
        taunt, stealth = game.state.players[2].board
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, attacker, game.state.players[2].hero_id))
        with self.assertRaises(IllegalAction):
            self.play(game, "cardbatch.test.ping", stealth)
        game.apply(Attack(1, attacker, taunt))
        self.assertEqual(game.state.entities[taunt].health, 1)

    def test_elusive_rejects_spell_target_but_allows_normal_attack(self):
        game = self.game(board=("CORE_CS2_182",), enemy=("CATA_558",), hand=("cardbatch.test.ping",))
        target = game.state.players[2].board[0]
        with self.assertRaises(IllegalAction):
            self.play(game, "cardbatch.test.ping", target)
        game.apply(Attack(1, game.state.players[1].board[0], target))
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)

    def test_lifesteal_heals_for_actual_damage_and_poisonous_kills_large_body(self):
        game = self.game(board=("CORE_ICC_820",), enemy=("CORE_CS2_182",), hand=("CS2_029",))
        hero = game.state.players[1].hero_id
        self.play(game, "CS2_029", hero)
        game.apply(Attack(1, game.state.players[1].board[0], game.state.players[2].board[0]))
        self.assertEqual(game.state.entities[hero].health, 27)
        game = self.game(board=("CORE_ICC_032",), enemy=("TLC_248",))
        enemy = game.state.players[2].board[0]
        game.apply(Attack(1, game.state.players[1].board[0], enemy))
        self.assertEqual(game.state.entities[enemy].zone, Zone.GRAVEYARD)

    def test_reborn_creates_distinct_one_health_body_without_second_reborn(self):
        game = self.game(board=("CORE_ULD_723",), hand=("cardbatch.test.destroy", "cardbatch.test.destroy"))
        original = game.state.players[1].board[0]
        self.play(game, "cardbatch.test.destroy", original)
        returned = game.state.players[1].board[0]
        self.assertNotEqual(returned, original)
        self.assertEqual(game.state.entities[returned].health, 1)
        self.assertNotIn(Keyword.REBORN, game.state.entities[returned].keywords)
        self.play(game, "cardbatch.test.destroy", returned)
        self.assertEqual(game.state.players[1].board, [])

    def test_silence_and_return_use_existing_keyword_lifetime(self):
        game = self.game(board=("CORE_EX1_008",), hand=("cardbatch.test.buff", "cardbatch.test.silence", "cardbatch.test.bounce"))
        eid = game.state.players[1].board[0]
        self.play(game, "cardbatch.test.buff", eid)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (3, 4))
        self.play(game, "cardbatch.test.silence", eid)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (1, 1))
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[eid].keywords)
        self.play(game, "cardbatch.test.bounce", eid)
        self.play(game, "CORE_EX1_008")
        self.assertIn(Keyword.DIVINE_SHIELD, game.state.entities[eid].keywords)

    def test_core_copies_share_reviewed_deck_identity_with_original(self):
        policy = DeckPolicy("cardbatch.aliases", "test", "experimental",
            ("CORE_CS2_182", "CS2_182"), deck_size=3)
        deck = DeckSpec("HERO_08", "HERO_08bp", CardClass.MAGE,
            ("CORE_CS2_182", "CORE_CS2_182", "CS2_182"))
        issues = validate_deck(deck, self.registry, policy).issues
        self.assertTrue(any(issue.code == "copy_limit" for issue in issues), issues)

    def test_new_hand_identity_is_private_until_played(self):
        game = self.game(hand=("TIME_053",))
        own = game.observe(1)["players"][0]["hand"][0]
        hidden = game.observe(2)["players"][0]["hand"][0]
        self.assertEqual(own["card_id"], "TIME_053")
        self.assertEqual(set(hidden), {"ref", "card_id"})
        self.assertIsNone(hidden["card_id"])
        self.play(game, "TIME_053")
        public = game.observe(2)["players"][0]["board"][0]
        self.assertEqual(public["card_id"], "TIME_053")

    def test_new_content_restores_and_replays_with_separate_factory(self):
        registry = build_registry()
        game = Game.from_scenario(Scenario((
            PlayerSetup("test.hero", hand=("CORE_NEW1_010",), mana=10, max_mana=10),
            PlayerSetup("test.hero"),
        )), registry)
        self.play(game, "CORE_NEW1_010")
        game.apply(Attack(1, game.state.players[1].board[0], game.state.players[2].hero_id))
        restored = Game.from_snapshot(game.snapshot(), build_registry())
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(replay(build_replay(game), build_registry()).snapshot(), game.snapshot())
        self.assertEqual(registry.version, CONTENT_VERSION)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(game.snapshot(), build_representative_registry())

    def test_raw_tampering_and_unimplemented_cards_are_explicit_errors(self):
        changed = load_batch()
        changed["cards"][0]["record"]["text_en"] += " Battlecry: Draw a card."
        with TemporaryDirectory() as directory:
            path = Path(directory) / "changed-batch.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with patch("hs_sim.cards.constructed.BATCH_PATH", path):
                with self.assertRaises(TargetValidationError):
                    load_batch()
        with self.assertRaises(UnsupportedDefinitionError):
            self.registry.card("unimplemented.real-card")

    def test_old_representative_identity_and_count_are_preserved(self):
        registry = build_representative_registry()
        self.assertEqual((registry.version, len(registry.cards)), ("representative-m5-v65", 311))
        self.assertNotIn("CORE_CS2_182", registry.cards)
