"""Current Core native adjacency through real crafting and ordinary combat."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_cleave_parts import CARD, LEGACY, load_batch, register_zombeast_native_cleave_parts
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, Keyword, PlayerSetup, Registry, ResolutionError,
    Scenario, SnapshotError, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.cleave import validate_carrier
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, PREFIX, recipe_from_id
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (Buff, ChoiceOption, CopyMinion, Damage, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.targets import TargetValidationError
from test_nefarian_crafted_faces import rehash
from tools import card_batch as batch

P = 'k508.'
HERO, POWER, UNIT, SHIELD, IMMUNE, STEALTH, SLEEP, WATCH = (
    P+x for x in ('hero', 'power', 'unit', 'shield', 'immune', 'stealth', 'sleep', 'watch'))
HURT, KILL, QUIET, BOUNCE, COPY, BASE, REZ, BUFF = (
    P+x for x in ('hurt', 'kill', 'quiet', 'bounce', 'copy', 'base', 'rez', 'buff'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
SECONDS = ('GIL_562', 'ICC_905', 'BE_193', 'NX2_050', 'LOOT_258')
UNREVIEWED = 'CORE_CS2_120'
CONTEXT = GenerationContext('explicit-k508-native-adjacency-fixture', 'experimental')


@lru_cache(None)
def originals():
    return build_registry()


@lru_cache(None)
def fixture(mode='GIL_562|normal', role='writer'):
    part, variant = mode.split('|')
    source = originals()
    registry = Registry(P+mode)
    for cid in (CARD, *SECONDS, TEMPLATE, TAMER, QUEST, UNREVIEWED):
        registry.register_card(source.card(cid))
    for cid in SECONDS:
        if cid not in source.crafted_minion_parts:
            raise ValueError('Fixture cannot invent a reviewed ordinary donor')
        registry.register_crafted_minion_part(cid)
    register_zombeast_native_cleave_parts(registry)
    registry.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    for body in (TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward'):
        registry.register_behavior(body, source.behavior(body))
    registry.register_behavior(P+'noop', lambda c: ())
    registry.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    registry.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    for cid, keywords, args in ((UNIT, (), {}), (SHIELD, (Keyword.DIVINE_SHIELD,), {}),
            (IMMUNE, (Keyword.IMMUNE,), {}), (STEALTH, (Keyword.STEALTH,), {}),
            (SLEEP, (), {'dormant_turns': 2})):
        registry.register_card(CardDefinition(cid, cid, CardType.MINION, attack=2,
            health=30, metadata=META, keywords=keywords, **args))
    def resurrect(c):
        death = next(row for row in reversed(c.state.death_history) if row.card_id.startswith(PREFIX))
        return (ResurrectMinion(c.player_id, death.id, source_id=c.source_id,
            cause=SummonCause.capture(c)),)
    scripts = {
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 40, c.source_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        REZ: resurrect,
        BUFF: lambda c: (Buff(c.target_id, 2, 0, c.source_id),),
    }
    for cid, body in scripts.items():
        registry.register_behavior(cid, body)
        targeting = None if cid in (HURT, REZ) else TargetSpec(TargetMode.REQUIRED,
            kinds=(CardType.MINION,))
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL,
            on_play=cid, targeting=targeting, metadata=META))
    for cid in (CARD, *SECONDS, UNREVIEWED):
        registry.register_pool_card(PoolCard.from_definition(registry.card(cid)))
    second = (part, UNREVIEWED) if variant == 'unreviewed' else (part,)
    for pool, ids in ((FIRST, (CARD,)), (SECOND, second)):
        registry.register_pool(PoolDefinition(pool, 'explicit-native-adjacency-v1',
            CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
            complete=not(variant == 'incomplete' and pool == SECOND)))
    def fail(c):
        raise ResolutionError('K508 intentional combat continuation failure')
    registry.register_behavior(P+'fail', fail)
    def watch(c):
        attacker = c.state.entities.get(c.event.source_id)
        if attacker is None or not attacker.card_id.startswith(PREFIX):
            return ()
        if c.event.kind == 'attack_finished' and variant == 'fail':
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if c.event.kind == 'damage_dealt' and variant == 'batch':
            enemies = c.state.players[3-attacker.controller].board
            if not all(c.state.entities[eid].damage == attacker.attack for eid in enemies):
                raise ValueError('Crafted adjacency escaped the original simultaneous damage batch')
        if c.event.kind == 'attack_declared' and variant == 'wait':
            enemy = c.state.players[3-attacker.controller].board
            return (RequestChoice(attacker.controller, (
                ChoiceOption('continue', 'Continue'),
                ChoiceOption('remove-left', 'Remove left', (Destroy(enemy[0]),)),
                ChoiceOption('silence', 'Silence attacker', (Silence(attacker.id),)),
            ), c.source_id),)
        return ()
    registry.register_behavior(P+'watch', watch)
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100,
        metadata=META, triggers=tuple(TriggerSpec(kind, P+'watch') for kind in
            ('attack_declared', 'damage_dealt', 'attack_finished'))))
    registry.validate()
    return registry


class ZombeastNativeCleavePartsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, part='GIL_562'):
        return CraftedMinionRecipe(TEMPLATE, CARD, part).card_id

    def game(self, part='GIL_562', player=1, hand=None, own=None, enemy=(UNIT, UNIT, UNIT),
            variant='normal', source=TAMER):
        self.mode = part+'|'+variant
        if hand is None:
            hand = ()
        if own is None:
            own = (self.recipe(part),)
        if variant in ('wait', 'batch', 'fail'):
            own = (*own, WATCH)
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (), board=own if p == player else enemy,
            deck=(UNIT,)*8, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=508,
            generation_context=CONTEXT), fixture(self.mode))

    def pick(self, game, cid):
        option = next(option for option in game._frame.options if any(
            type(effect) is ResolveCraft and effect.card_id == cid for effect in option.effects))
        self.choose(game, option.id)

    def craft(self, game, part, player=1):
        self.play(game, TAMER, player=player)
        self.pick(game, CARD); self.pick(game, part)
        return next(i for i in game.state.players[player].hand
            if game.state.entities[i].card_id.startswith(PREFIX))

    def body(self, game, player=1):
        return next(i for i in game.state.players[player].board
            if game.state.entities[i].card_id.startswith(PREFIX))

    def attack(self, game, index=1, player=1, source=None):
        ids = tuple(game.state.players[3-player].board)
        game.apply(Attack(player, source or self.body(game, player), ids[index]))
        return ids

    def cleaves(self, game, eid):
        return [row for row in game.state.entities[eid].abilities if row.kind == 'cleave']

    def test_complete_current_core_and_legacy_evidence_do_not_claim_a_complete_curated_pool(self):
        data = load_batch()
        rows = {row['record']['id']: row['record'] for row in data['existing_dependencies']+data['evidence_only']}
        self.assertEqual(len(data['official_observations']), 4)
        for face in data['official_observations']:
            batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        registry = originals()
        self.assertIn(CARD, registry.crafted_minion_parts)
        self.assertNotIn(LEGACY, registry.crafted_minion_parts)
        self.assertEqual(registry.card(CARD).metadata.deck_identity, CARD)
        self.assertEqual(len(registry.crafted_minion_parts), 23)
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in registry.pools))

    def test_paid_actual_tamer_both_actors_two_choices_and_one_ten_mana_crafted_body(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player, hand=(TAMER,), own=())
                eid = self.craft(game, 'GIL_562', player)
                entity = game.state.entities[eid]
                face = game.registry.card(entity.card_id)
                self.assertEqual((face.cost, face.attack, face.health, face.cleave), (10, 5, 9, True))
                self.assertEqual(quote_cost(game.state, game.registry, entity).amount, 10)
                self.play(game, entity.card_id, player=player)
                self.assertEqual(len(self.cleaves(game, eid)), 1)
                self.assertEqual(game.state.players[player].mana, 19)
                self.assertEqual(game.state.entities[eid].components, (CARD, 'GIL_562'))

    def test_real_sidequest_reward_keeps_the_same_cleave_face_with_original_discount(self):
        game = self.game(part='BE_193', hand=(QUEST, 'LOOT_258', 'LOOT_258', 'LOOT_258'), own=())
        self.play(game, QUEST)
        for _ in range(3):
            self.play(game, 'LOOT_258')
        self.pick(game, CARD); self.pick(game, 'BE_193')
        eid = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id.startswith(PREFIX))
        self.assertEqual(quote_cost(game.state, game.registry, game.state.entities[eid]).amount, 3)
        self.play(game, game.state.entities[eid].card_id)
        self.assertEqual((game.state.players[1].mana, len(self.cleaves(game, eid))), (23, 1))

    def test_three_poisonous_hits_share_one_combat_only_primary_retaliates(self):
        game = self.game(variant='batch')
        eid = self.body(game); ids = self.attack(game)
        self.assertTrue(all(game.state.entities[i].zone == Zone.GRAVEYARD for i in ids))
        self.assertEqual((game.state.entities[eid].damage, game.state.entities[eid].attacks_this_turn), (2, 1))
        self.assertEqual(sum(event.kind == 'attack_finished' for event in game.events), 1)
        self.portable(game)

    def test_lifesteal_uses_all_three_actual_adjacent_damage_packets(self):
        game = self.game(part='ICC_905', hand=(HURT,))
        self.play(game, HURT)
        ids = self.attack(game)
        hero = game.state.entities[game.state.players[1].hero_id]
        self.assertEqual(hero.health, 84)
        self.assertEqual([game.state.entities[i].damage for i in ids], [8, 8, 8])
        self.assertEqual(game.state.entities[self.body(game)].damage, 2)

    def test_adjacent_shield_immunity_and_stealth_keep_original_damage_rules(self):
        for enemy, expected in (((SHIELD, UNIT, IMMUNE), (Zone.BOARD, Zone.GRAVEYARD, Zone.BOARD)),
                ((STEALTH, UNIT, UNIT), (Zone.GRAVEYARD,)*3)):
            with self.subTest(enemy=enemy):
                game = self.game(enemy=enemy); ids = self.attack(game)
                self.assertEqual(tuple(game.state.entities[i].zone for i in ids), expected)
                if enemy[0] == SHIELD:
                    self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[ids[0]].keywords)

    def test_dormant_physical_neighbor_does_not_bridge_to_a_distant_minion(self):
        game = self.game(enemy=(UNIT, SLEEP, UNIT, UNIT))
        ids = self.attack(game, index=2)
        self.assertEqual(tuple(game.state.entities[i].zone for i in ids),
            (Zone.BOARD, Zone.BOARD, Zone.GRAVEYARD, Zone.GRAVEYARD))
        self.assertEqual([game.state.entities[i].damage for i in ids[:2]], [0, 0])

    def test_attacking_hero_has_no_extra_board_recipients(self):
        game = self.game(); ids = tuple(game.state.players[2].board)
        game.apply(Attack(1, self.body(game), game.state.players[2].hero_id))
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 95)
        self.assertTrue(all(game.state.entities[i].damage == 0 for i in ids))

    def test_waiting_combat_restores_then_recomputes_real_physical_neighbors(self):
        game = self.game(variant='wait'); original = tuple(game.state.players[2].board)
        self.attack(game); restored = self.portable(game)
        self.choose(game, 'remove-left'); self.choose(restored, 'remove-left')
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(game.state.entities[original[0]].damage, 0)
        self.assertTrue(all(game.state.entities[i].zone == Zone.GRAVEYARD for i in original))
        self.portable(game)

    def test_waiting_silence_removes_extra_hits_without_changing_the_printed_cleave_face(self):
        game = self.game(variant='wait'); ids = tuple(game.state.players[2].board)
        self.attack(game); self.choose(game, 'silence')
        self.assertEqual([game.state.entities[i].damage for i in ids], [0, 5, 0])
        self.assertFalse(self.cleaves(game, self.body(game)))
        self.assertTrue(game.registry.card(self.recipe()).cleave)
        self.portable(game)

    def test_silenced_current_copy_base_copy_and_bounce_keep_original_recipe(self):
        game = self.game(hand=(QUIET, COPY, BASE, BOUNCE))
        eid = self.body(game); self.play(game, QUIET, eid)
        self.play(game, COPY, eid); self.play(game, BASE, eid)
        copies = [i for i in game.state.players[1].board if game.state.entities[i].card_id == self.recipe()]
        self.assertEqual([len(self.cleaves(game, i)) for i in copies], [0, 0, 1])
        self.play(game, BOUNCE, eid); self.play(game, self.recipe())
        self.assertEqual(len(self.cleaves(game, eid)), 1)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].max_health), (5, 9))
        self.portable(game)

    def test_death_record_and_typed_resurrection_keep_native_cleave_and_full_components(self):
        game = self.game(hand=(KILL, REZ))
        eid = self.body(game); self.play(game, KILL, eid)
        death = next(row for row in game.state.death_history if row.entity_id == eid)
        self.assertEqual(death.components, (CARD, 'GIL_562'))
        self.portable(game)
        self.play(game, REZ)
        raised = self.body(game)
        self.assertNotEqual(raised, eid)
        self.assertEqual(len(self.cleaves(game, raised)), 1)
        self.assertEqual(game.state.entities[raised].components, (CARD, 'GIL_562'))
        self.portable(game)

    def test_late_combat_failure_restores_damage_deaths_attack_count_and_rng(self):
        game = self.game(variant='fail'); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.attack(game)
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_native_carrier_requires_exact_recipe_bounded_declarations_and_minion_kind(self):
        game = self.game(); eid = self.body(game); entity = game.state.entities[eid]
        rows = tuple(entity.abilities); cleave = self.cleaves(game, eid)[0]
        for components in ((), list(entity.components), tuple(reversed(entity.components))):
            with self.subTest(components=components), self.assertRaises(ValueError):
                validate_carrier(game.registry, entity.card_id, entity.kind, rows, components)
        with self.assertRaises(ValueError):
            validate_carrier(game.registry, entity.card_id, entity.kind,
                (*rows, replace(cleave, id=cleave.id+10000)), entity.components)
        with self.assertRaises(ValueError):
            validate_carrier(game.registry, entity.card_id, CardType.WEAPON, rows, entity.components)
        saved = game.snapshot(); malformed = deepcopy(saved)
        record = malformed['state']['entities'][str(eid)]
        record['components'].reverse()
        rehash(malformed)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(malformed, fixture(self.mode, 'independent-reader'))

    def test_both_crafting_menus_restore_and_keep_other_player_options_private(self):
        game = self.game(hand=(TAMER,), own=())
        self.play(game, TAMER)
        self.assertNotIn(CARD, json.dumps(game.for_player(2).observe()))
        restored = self.portable(game)
        self.pick(game, CARD); self.pick(restored, CARD)
        self.assertEqual(game.snapshot(), restored.snapshot())
        restored = self.portable(game)
        self.pick(game, 'GIL_562'); self.pick(restored, 'GIL_562')
        self.assertEqual(game.snapshot(), restored.snapshot())

    def test_unreviewed_or_incomplete_second_pool_still_fails_before_first_sampling(self):
        for variant in ('unreviewed', 'incomplete'):
            with self.subTest(variant=variant):
                game = self.game(hand=(TAMER,), own=(), variant=variant); saved = game.snapshot()
                with self.assertRaises(ResolutionError) as caught:
                    self.play(game, TAMER)
                self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
                self.assertEqual(game.snapshot(), saved)

    def test_new_native_declaration_rejects_wrong_body_and_previous_wire_schema(self):
        registry = Registry(P+'wrong-native')
        registry.register_card(replace(originals().card(CARD), cleave=False))
        with self.assertRaises(TargetValidationError):
            register_zombeast_native_cleave_parts(registry)
        self.assertNotIn(CARD, registry.crafted_minion_parts)
        game = self.game(); saved = game.snapshot(); saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, fixture(self.mode))
