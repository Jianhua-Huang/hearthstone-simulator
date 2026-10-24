"""Dormant native entry blocks its targeting as well as its printed bodies."""
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_dispatch_kodo_card import fixture as base_fixture, originals, HERO, POWER, UNIT, CONTEXT
from hs_sim.cards.dispatch_kodo_card import CARD as KODO, BODY
from hs_sim.cards.storm_gates_card import TEMPLATE
from hs_sim.cards.zombeast_native_dormant_parts import CARD as PELICAN, register_zombeast_native_dormant_parts
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, PlayerSetup, ResolutionError, Scenario,
    SnapshotError, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, NATIVE_DORMANT_ENTRY, PREFIX
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice, ReturnToHand
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference

P = 'k515.'
ORDINARY, BOUNCE, TRIGGER, WATCH = (P+x for x in ('ordinary-dormant', 'bounce', 'trigger', 'watch'))
LIFE = 'CORE_GIL_558'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__(); r._version = P+mode
    r.register_card(originals().card(PELICAN)); register_zombeast_native_dormant_parts(r)
    r.register_card(CardDefinition(ORDINARY, ORDINARY, CardType.MINION, cost=3,
        attack=2, health=4, dormant_turns=1, battlecry=BODY, metadata=META,
        targeting=TargetSpec(TargetMode.IF_AVAILABLE, kinds=(CardType.MINION, CardType.HERO))))
    r.register_behavior(BOUNCE, lambda c: (ReturnToHand(c.target_id),))
    r.register_behavior(TRIGGER, lambda c: (TriggerBattlecry(
        MinionReference.capture(c.state.entities[c.target_id]), c.source_id,
        c.state.players[3-c.player_id].hero_id, targeting='explicit'),))
    for cid in (BOUNCE, TRIGGER):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED, kinds=(CardType.MINION,))))
    def fail(c): raise ResolutionError('K515 intentional dormant entry notification failure')
    def watch(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or not target.card_id.startswith(PREFIX): return ()
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if mode == 'wait': return (RequestChoice(c.player_id,
            (ChoiceOption('continue', 'Continue'),), c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('minion_summoned', P+'watch'),)))
    r.validate(); return r


class CraftedDormantPlayTargetTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, reverse=False):
        return CraftedMinionRecipe(TEMPLATE, *( (PELICAN, KODO) if reverse else (KODO, PELICAN) )).card_id

    def game(self, *, player=1, hand=None, mode='normal', reverse=False):
        self.mode = mode
        if hand is None: hand = (self.recipe(reverse),)
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (), board=(WATCH,) if p == player and mode != 'normal' else (),
            deck=(UNIT,)*12, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=515,
            generation_context=CONTEXT), fixture(mode))

    def cycle(self, game): game.apply(EndTurn(1)); game.apply(EndTurn(2))

    def assert_no_kodo_battlecry(self, game):
        self.assertFalse(any(row.payload.card_id == KODO for row in game.state.battlecry_history))
        self.assertTrue(all(game.state.entities[game.state.players[p].hero_id].health == 100 for p in (1, 2)))

    def test_targetless_paid_entry_keeps_dormancy_and_skips_native_battlecry(self):
        game = self.game(); eid = self.play(game, self.recipe())
        self.assertEqual(game.state.players[1].mana, 25)
        self.assertIsNotNone(game.state.entities[eid].dormancy)
        self.assertEqual(game.state.entities[eid].components, (KODO, PELICAN))
        self.assert_no_kodo_battlecry(game)

    def test_both_controllers_and_both_material_orders_use_targetless_entry(self):
        for player in (1, 2):
            for reverse in (False, True):
                with self.subTest(player=player, reverse=reverse):
                    game = self.game(player=player, reverse=reverse)
                    eid = self.play(game, self.recipe(reverse), player=player)
                    self.assertEqual(game.state.players[player].mana, 25)
                    self.assertIsNotNone(game.state.entities[eid].dormancy)
                    self.assert_no_kodo_battlecry(game)

    def test_host_and_player_target_queries_are_pure_and_do_not_publish_native_marker(self):
        game = self.game(); eid = self.entity(game, self.recipe()).id; saved = game.snapshot()
        self.assertEqual(game.legal_targets(eid), ())
        for _ in range(2):
            data = game.for_player(1).legal_actions()
            plays = [a for a in data['actions'] if a['type'] == 'play_card']
            self.assertEqual(len(plays), 1); self.assertIsNone(plays[0]['target'])
            self.assertNotIn(NATIVE_DORMANT_ENTRY, json.dumps(data['observation']))
        self.assertEqual(game.snapshot(), saved)

    def test_spurious_target_rejects_before_payment_then_targetless_play_succeeds(self):
        game = self.game(); saved = game.snapshot()
        with self.assertRaises(IllegalAction): self.play(game, self.recipe(), game.state.players[2].hero_id)
        self.assertEqual(game.snapshot(), saved)
        self.play(game, self.recipe()); self.assert_no_kodo_battlecry(game)

    def test_non_dormant_crafted_battlecry_still_requires_its_real_target(self):
        cid = CraftedMinionRecipe(TEMPLATE, LIFE, KODO).card_id
        game = self.game(hand=(cid,)); saved = game.snapshot()
        with self.assertRaises(IllegalAction): self.play(game, cid)
        self.assertEqual(game.snapshot(), saved)
        hero = game.state.players[2].hero_id; self.play(game, cid, hero)
        self.assertEqual(game.state.entities[hero].health, 96)

    def test_ordinary_dormant_battlecry_keeps_target_and_existing_entry_behavior(self):
        game = self.game(hand=(ORDINARY,)); saved = game.snapshot()
        with self.assertRaises(IllegalAction): self.play(game, ORDINARY)
        self.assertEqual(game.snapshot(), saved)
        hero = game.state.players[2].hero_id; eid = self.play(game, ORDINARY, hero)
        self.assertEqual(game.state.entities[hero].health, 98)
        self.assertIsNotNone(game.state.entities[eid].dormancy)

    def test_bounce_after_awakening_restores_same_targetless_native_entry(self):
        game = self.game(hand=(self.recipe(), BOUNCE)); eid = self.play(game, self.recipe())
        self.cycle(game); self.assertIsNone(game.state.entities[eid].dormancy)
        self.play(game, BOUNCE, eid); self.assertEqual(game.legal_targets(eid), ())
        self.play(game, self.recipe()); self.assertIsNotNone(game.state.entities[eid].dormancy)
        self.assert_no_kodo_battlecry(game); self.portable(game)

    def test_awakened_indirect_battlecry_retains_target_domain_and_current_attack(self):
        game = self.game(hand=(self.recipe(), TRIGGER)); eid = self.play(game, self.recipe())
        self.cycle(game); self.assertIsNone(game.state.entities[eid].dormancy)
        self.play(game, TRIGGER, eid)
        rows = [row for row in game.state.battlecry_history if row.payload.card_id == KODO]
        self.assertEqual(len(rows), 1)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 94)

    def test_waiting_entry_restore_clone_replay_keeps_targetless_payment_and_clock(self):
        game = self.game(mode='wait'); eid = self.play(game, self.recipe())
        self.assertIsNotNone(game.state.pending_choice)
        restored = self.portable(game); self.choose(game); self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(game.state.players[1].mana, 25)
        self.assertIsNotNone(game.state.entities[eid].dormancy); self.assert_no_kodo_battlecry(game)

    def test_late_entry_failure_restores_hand_payment_rng_and_native_material(self):
        game = self.game(mode='fail'); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, self.recipe())
        self.assertEqual(game.snapshot(), saved); self.portable(game)

    def test_unreviewed_recipe_is_not_admitted_by_target_suppression(self):
        cid = CraftedMinionRecipe(TEMPLATE, 'CORE_CS2_120', PELICAN).card_id
        with self.assertRaises(UnsupportedDefinitionError): fixture().card(cid)

    def test_previous_snapshot_schema_is_rejected(self):
        game = self.game(); saved = game.snapshot(); saved['schema_version'] = 585
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture())
