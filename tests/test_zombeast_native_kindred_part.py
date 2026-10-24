"""Real Kindred construction retains the original complete query and plan."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_zombeast_plain_legacy_parts import new_registry, originals
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_kindred_part import (
    CARD, load_batch, register_zombeast_native_kindred_part)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, PlayerSetup, ResolutionError, Scenario, SnapshotError,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, PREFIX
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k513.'
HERO, POWER, UNIT, WATCH, BUFF, FORGE = (P+x for x in
    ('hero', 'power', 'unit', 'watch', 'buff', 'forge'))
BEETLE, MOLE, CHALLENGER = 'CORE_LOOT_413', 'LOOT_258', 'TLC_251'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CONTEXT = GenerationContext('explicit-k513-native-kindred-fixture', 'experimental')


def donor_registry(corrupt=False):
    source = originals(); r = new_registry(); card = source.card(CARD)
    if corrupt: card = replace(card, attack=card.attack+1)
    r.register_card(card)
    profile = source.kindred_profiles[CARD]
    for key in (profile.wrapper, profile.active):
        r.register_behavior(key, source.behavior(key))
    r.register_kindred_profile(profile)
    return r


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    source = originals(); r = donor_registry(); r._version = P+mode
    register_zombeast_native_kindred_part(r)
    for body in (TAMER_BODY, source.card(BEETLE).deathrattle, source.card(CHALLENGER).battlecry):
        r.register_behavior(body, source.behavior(body))
    for cid in (TAMER, TEMPLATE, BEETLE, CHALLENGER):
        r.register_card(source.card(cid))
    r.register_player_effect(source.player_effect('cards.kindred_components.next'))
    r.register_crafted_minion_part(BEETLE)
    r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    for cid in (CARD, BEETLE):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for pool, cid in ((FIRST, CARD), (SECOND, BEETLE)):
        r.register_pool(PoolDefinition(pool, 'explicit-native-kindred-v1', CONTEXT.target_id,
            CONTEXT.mode, (PoolMember(cid),), complete=True))
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=40, metadata=META))
    r.register_behavior(BUFF, lambda c: (BuffStoredCard(
        CardReference.capture(c.state.entities[c.target_id]), 3, 4, c.source_id),))
    r.register_card(CardDefinition(BUFF, BUFF, CardType.SPELL, on_play=BUFF, metadata=META,
        targeting=TargetSpec(TargetMode.REQUIRED, kinds=(CardType.MINION,), zones=(Zone.HAND,))))
    r.register_behavior(FORGE, lambda c: (InvokeBehavior(source.card(CARD).on_play, c.target_id, c.player_id),))
    r.register_card(CardDefinition(FORGE, FORGE, CardType.SPELL, on_play=FORGE, metadata=META,
        targeting=TargetSpec(TargetMode.REQUIRED, kinds=(CardType.MINION,))))
    def fail(c):
        raise ResolutionError('K513 intentional copy notification failure')
    def watch(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or not target.card_id.startswith(PREFIX): return ()
        copies = [i for i in c.state.players[target.controller].board
            if c.state.entities[i].card_id == target.card_id]
        if len(copies) < 2: return ()
        if mode == 'fail': return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if mode in ('wait', 'depart'):
            options = (ChoiceOption('continue', 'Continue'),)
            if mode == 'depart':
                options += (ChoiceOption('bounce', 'Return original', (ReturnToHand(copies[0]),)),)
            return (RequestChoice(target.controller, options, c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('minion_summoned', P+'watch'),)))
    r.validate(); return r


class ZombeastNativeKindredTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self):
        return CraftedMinionRecipe(TEMPLATE, CARD, BEETLE).card_id

    def game(self, *, player=1, hand=(MOLE, TAMER), own=(), variant='normal'):
        self.mode = variant
        if variant in ('wait', 'depart', 'fail'): own = (*own, WATCH)
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (), board=own if p == player else (),
            deck=(UNIT,)*12, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=513,
            generation_context=CONTEXT), fixture(self.mode))

    def cycle(self, game, player=1):
        game.apply(EndTurn(player)); game.apply(EndTurn(3-player))

    def pick(self, game, cid):
        option = next(o for o in game._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in o.effects))
        self.choose(game, option.id)

    def craft(self, game, player=1):
        self.play(game, TAMER, player=player); self.pick(game, CARD); self.pick(game, BEETLE)
        return self.entity(game, self.recipe(), player).id

    def copies(self, game, player=1):
        return [game.state.entities[i] for i in game.state.players[player].board
            if game.state.entities[i].card_id == self.recipe()]

    def qualified(self, *, player=1, hand=(), own=(), variant='normal'):
        game = self.game(player=player, hand=(MOLE, TAMER, *hand), own=own, variant=variant)
        self.play(game, MOLE, player=player); self.cycle(game, player)
        return game

    def test_full_faces_and_native_profile_keep_reported_bug_and_pool_uncertainty_explicit(self):
        data = load_batch(); raw = data['existing_dependencies'][0]['record']
        for face in data['official_observations']:
            batch.check_face(raw, face['face'], face['locale'])
        self.assertTrue(data['historical_composition_observation']['reported_battlecry_failure'])
        self.assertFalse(data['historical_composition_observation']['correct_resolution_confirmed'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertIn(CARD, originals().crafted_minion_parts)
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in originals().pools))

    def test_both_real_tamers_make_one_full_current_copy_and_pay_only_for_original(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.qualified(player=player); self.craft(game, player)
                face = game.registry.card(self.recipe())
                self.assertEqual((face.cost, face.attack, face.health, face.metadata.tribes), (7, 5, 7, ('all',)))
                self.play(game, self.recipe(), player=player)
                self.assertEqual(len(self.copies(game, player)), 2)
                self.assertTrue(all(e.components == (CARD, BEETLE) for e in self.copies(game, player)))
                self.assertEqual(game.state.players[player].mana, 22)
                row, = game.state.kindred_history
                self.assertEqual((row.card_id, row.source.card_id, row.repetitions, row.completed),
                    (CARD, self.recipe(), 1, True))

    def test_last_empty_own_turn_overwrites_an_older_matching_turn(self):
        game = self.qualified(); self.cycle(game); self.craft(game); self.play(game, self.recipe())
        self.assertEqual(len(self.copies(game)), 1)
        row, = game.state.kindred_history
        self.assertFalse(row.condition.matched); self.assertEqual(row.plan, ()); self.assertTrue(row.completed)

    def test_current_turn_submission_does_not_replace_the_previous_own_turn(self):
        game = self.game(); self.play(game, MOLE); self.craft(game); self.play(game, self.recipe())
        self.assertEqual(len(self.copies(game)), 1)
        self.assertFalse(game.state.kindred_history[0].condition.matched)

    def test_real_next_kindred_source_repeats_components_without_recursive_copy_entries(self):
        game = self.qualified(hand=(CHALLENGER,)); self.play(game, CHALLENGER)
        self.craft(game); self.play(game, self.recipe())
        self.assertEqual(len(self.copies(game)), 3)
        row, = game.state.kindred_history
        self.assertEqual((row.repetitions, row.plan, row.finished), (2, ('active', 'active'), (0, 1)))
        self.assertFalse(game.state.players[1].player_effects)
        self.assertEqual(game.state.players[1].mana, 19)

    def test_actual_copy_keeps_current_hand_buff_and_both_native_materials(self):
        game = self.qualified(hand=(BUFF,)); eid = self.craft(game)
        self.play(game, BUFF, eid)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].max_health), (8, 11))
        self.play(game, self.recipe())
        self.assertEqual([(e.attack, e.max_health) for e in self.copies(game)], [(8, 11), (8, 11)])
        self.portable(game)

    def test_full_board_consumes_real_component_without_creating_an_eighth_minion(self):
        game = self.qualified(own=(UNIT,)*4); self.craft(game); self.play(game, self.recipe())
        self.assertEqual(len(game.state.players[1].board), 7)
        self.assertEqual(len(self.copies(game)), 1)
        row, = game.state.kindred_history
        self.assertEqual((row.plan, row.finished, row.completed), (('active',), (0,), True))

    def test_waiting_inside_copy_restores_clone_replay_and_keeps_native_plan_private(self):
        game = self.qualified(hand=(CHALLENGER,), variant='wait'); self.play(game, CHALLENGER)
        self.craft(game); self.play(game, self.recipe())
        self.assertIsNotNone(game.state.pending_choice)
        restored = self.portable(game)
        for player in (1, 2):
            view = json.dumps(game.for_player(player).observe())
            for key in ('kindred_history', 'KindredActivation', 'original', 'repetitions', 'kindred_sources'):
                self.assertNotIn('"'+key+'"', view)
        while game.state.pending_choice is not None:
            self.choose(game); self.choose(restored)
            self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(len(self.copies(game)), 3)

    def test_original_departure_during_wait_does_not_copy_a_later_residence(self):
        game = self.qualified(hand=(CHALLENGER,), variant='depart'); self.play(game, CHALLENGER)
        self.craft(game); self.play(game, self.recipe()); self.choose(game, 'bounce')
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual(len(self.copies(game)), 1)
        self.assertEqual(len([i for i in game.state.players[1].hand
            if game.state.entities[i].card_id == self.recipe()]), 1)
        self.assertTrue(game.state.kindred_history[0].completed)
        self.portable(game)

    def test_late_copy_notification_failure_rolls_back_payment_sources_and_native_history(self):
        game = self.qualified(hand=(CHALLENGER,), variant='fail'); self.play(game, CHALLENGER)
        self.craft(game); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, self.recipe())
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_foreign_composition_cannot_borrow_a_native_kindred_wrapper(self):
        other = CraftedMinionRecipe(TEMPLATE, MOLE, BEETLE).card_id
        game = self.game(hand=(FORGE,), own=(other,)); target = game.state.players[1].board[0]
        saved = game.snapshot()
        with self.assertRaises(ResolutionError) as caught: self.play(game, FORGE, target)
        self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
        self.assertEqual(game.snapshot(), saved)

    def test_changed_original_face_fails_before_approval_and_schema584_is_rejected(self):
        registry = donor_registry(corrupt=True); parts = set(registry.crafted_minion_parts)
        with self.assertRaises(TargetValidationError): register_zombeast_native_kindred_part(registry)
        self.assertEqual(set(registry.crafted_minion_parts), parts)
        game = self.game(); saved = game.snapshot(); saved['schema_version'] = 584
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture(self.mode))
