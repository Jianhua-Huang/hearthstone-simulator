"""One real timed Dormant material, its original clock and native entry policy."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.ammunae_card import CARD as AMMUNAE, register_ammunae_card
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, FIRST, SECOND, TEMPLATE
from hs_sim.cards.zombeast_native_dormant_parts import CARD, load_batch, register_zombeast_native_dormant_parts
from hs_sim.engine import (AbilityInstance, Attack, CardClass, CardDefinition,
    CardMetadata, CardType, EndTurn, Game, IllegalAction, Keyword, PlayerSetup,
    Registry, ResolutionError, Scenario, SnapshotError, TargetMode, TargetSpec,
    TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import (CraftedMinionRecipe, NATIVE_DORMANT_ENTRY,
    PREFIX, validate_dormant_carrier)
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Damage, Destroy,
    GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.summon_quantities import SummonCause, SummonByCard, SummonEntryMaterial
from hs_sim.targets import TargetValidationError
from test_nefarian_crafted_faces import rehash
from tools import card_batch as batch

P = 'k510.'
HERO, POWER, UNIT, KILL, QUIET, BOUNCE, COPY, BASE, REZ, REBORN, MORPH, SUMMON, HIT, WATCH, ORDINARY = (
    P+x for x in ('hero', 'power', 'unit', 'kill', 'quiet', 'bounce', 'copy', 'base',
        'rez', 'reborn', 'morph', 'summon', 'hit', 'watch', 'ordinary-dormant'))
BEETLE, MUKLA, WOLF, MOLE = 'CORE_LOOT_413', 'CORE_EX1_014', 'CORE_EX1_162', 'LOOT_258'
FIRST_PARTS = (BEETLE, MUKLA, WOLF)
UNREVIEWED = 'CORE_CS2_120'
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
CONTEXT = GenerationContext('explicit-k510-native-dormancy-fixture', 'experimental')


@lru_cache(None)
def originals():
    return build_registry()


def recipe(first=BEETLE, second=CARD):
    return CraftedMinionRecipe(TEMPLATE, first, second).card_id


@lru_cache(None)
def fixture(mode=BEETLE+'|normal', role='writer'):
    first, variant = mode.split('|'); original = originals(); r = Registry(P+mode)
    for cid in (*FIRST_PARTS, CARD, MOLE, UNREVIEWED, TAMER, QUEST, TEMPLATE, 'EX1_014t'):
        r.register_card(original.card(cid))
    for cid in (*FIRST_PARTS, MOLE):
        assert cid in original.crafted_minion_parts
        r.register_crafted_minion_part(cid)
    for body in (original.card(BEETLE).deathrattle, original.card(MUKLA).battlecry,
            TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward'):
        r.register_behavior(body, original.behavior(body))
    r.register_behavior(original.card('EX1_014t').on_play, original.behavior(original.card('EX1_014t').on_play))
    register_zombeast_native_dormant_parts(r)
    r.register_crafted_minion_blueprint(original.crafted_minion_blueprints[TEMPLATE])
    register_ammunae_card(r)
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=40, metadata=META))
    r.register_behavior(P+'ordinary', lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 1, c.source_id),))
    r.register_card(CardDefinition(ORDINARY, ORDINARY, CardType.MINION, health=4,
        dormant_turns=1, battlecry=P+'ordinary', metadata=META))
    def resurrect(c):
        row = next(row for row in reversed(c.state.death_history) if row.card_id.startswith(PREFIX))
        return (ResurrectMinion(c.player_id, row.id, source_id=c.source_id, cause=SummonCause.capture(c)),)
    def summon(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(recipe(first)),), SummonCause.capture(c)),)
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        REZ: resurrect,
        REBORN: lambda c: (GrantKeyword(c.target_id, Keyword.REBORN, c.source_id),),
        MORPH: lambda c: (Transform(c.target_id, recipe(first)),),
        SUMMON: summon,
        HIT: lambda c: tuple(Damage(i, 2, c.source_id) for i in tuple(c.state.players[c.player_id].board)),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=None if cid in (REZ, SUMMON, HIT) else TargetSpec(TargetMode.REQUIRED,
                kinds=(CardType.MINION,))))
    def fail(c):
        raise ResolutionError('K510 intentional native dormant continuation failure')
    def watch(c):
        eid = c.event.target_id if c.event.kind == 'minion_awakened' else c.event.source_id
        entity = c.state.entities.get(eid)
        if entity is None or not entity.card_id.startswith(PREFIX):
            return ()
        if (c.event.kind, variant) in (('minion_awakened', 'awakefail'), ('card_played', 'playfail')):
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if c.event.kind == 'minion_awakened' and variant == 'awakewait':
            return (RequestChoice(entity.controller, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100,
        triggers=(TriggerSpec('minion_awakened', P+'watch'), TriggerSpec('card_played', P+'watch')), metadata=META))
    for cid in (*FIRST_PARTS, CARD, UNREVIEWED):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for pool, ids in ((FIRST, (first,)), (SECOND, (CARD, UNREVIEWED) if variant == 'unreviewed' else (CARD,))):
        r.register_pool(PoolDefinition(pool, 'explicit-native-dormancy-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
            complete=not (variant == 'incomplete' and pool == SECOND)))
    r.validate(); return r


class ZombeastNativeDormantPartsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, first=BEETLE, *, player=1, hand=(), own=None, enemy=(UNIT,), variant='normal'):
        self.mode = first+'|'+variant
        if own is None:
            own = (recipe(first),)
        if variant in ('awakewait', 'awakefail', 'playfail'):
            own = (*own, WATCH)
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (), board=own if p == player else enemy,
            deck=(UNIT,)*9, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=510,
            generation_context=CONTEXT), fixture(self.mode))

    def body(self, game, player=1):
        return next(i for i in game.state.players[player].board if game.state.entities[i].card_id.startswith(PREFIX))

    def markers(self, game, eid):
        return tuple(a for a in game.state.entities[eid].abilities if a.kind == NATIVE_DORMANT_ENTRY)

    def cycle(self, game, player=1):
        game.apply(EndTurn(player)); game.apply(EndTurn(3-player))

    def pick(self, game, cid):
        option = next(o for o in game._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in o.effects))
        self.choose(game, option.id)

    def craft(self, game, first=BEETLE, player=1):
        self.play(game, TAMER, player=player); self.pick(game, first); self.pick(game, CARD)
        return self.entity(game, recipe(first), player).id

    def test_full_original_face_and_historical_policy_do_not_certify_current_CN_pool(self):
        data = load_batch(); raw = data['existing_dependencies'][0]['record']
        self.assertEqual(len(data['official_observations']), 2)
        for face in data['official_observations']:
            batch.check_face(raw, face['face'], face['locale'])
        self.assertIn(CARD, originals().crafted_minion_parts)
        self.assertFalse(data['entry_policy']['current_CN_verified'])
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in originals().pools))

    def test_paid_real_tamer_both_players_installs_one_original_clock_and_marker(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player, hand=(TAMER,), own=())
                eid = self.craft(game, player=player)
                self.assertIsNone(game.state.entities[eid].dormancy)
                self.assertEqual(len(self.markers(game, eid)), 1)
                self.play(game, recipe(), player=player)
                entity = game.state.entities[eid]
                self.assertEqual((game.state.players[player].mana, entity.attack, entity.max_health), (26, 6, 4))
                self.assertEqual(entity.dormancy.remaining_turns, 1)
                self.assertFalse(entity.keywords)
                self.assertEqual(entity.components, (BEETLE, CARD))
                self.portable(game)

    def test_real_standard_quest_reward_keeps_minus_three_and_enters_dormant(self):
        game = self.game(hand=(QUEST, MOLE, MOLE, MOLE), own=())
        self.play(game, QUEST)
        for _ in range(3):
            self.play(game, MOLE)
        self.pick(game, BEETLE); self.pick(game, CARD)
        self.play(game, recipe()); eid = self.body(game)
        self.assertEqual(game.state.players[1].mana, 26)
        self.assertEqual(game.state.entities[eid].dormancy.remaining_turns, 1)

    def test_controller_clock_awakens_same_body_then_rush_allows_minion_attack(self):
        game = self.game(); eid = self.body(game); enemy = game.state.players[2].board[0]
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, enemy))
        game.apply(EndTurn(1)); self.assertEqual(game.state.entities[eid].dormancy.remaining_turns, 1)
        game.apply(EndTurn(2)); self.assertIsNone(game.state.entities[eid].dormancy)
        self.assertIn(Keyword.RUSH, game.state.entities[eid].keywords)
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, game.state.players[2].hero_id))
        game.apply(Attack(1, eid, enemy))
        self.assertEqual((game.state.entities[enemy].damage, game.state.entities[eid].damage), (6, 2))
        self.portable(game)

    def test_historical_native_dormancy_suppresses_donated_battlecry_without_erasing_it(self):
        game = self.game(MUKLA, hand=(TAMER,), own=()); eid = self.craft(game, MUKLA)
        before = len(game.state.battlecry_history)
        self.play(game, recipe(MUKLA))
        self.assertTrue(game.registry.card(recipe(MUKLA)).battlecry)
        self.assertTrue(any(a.kind == 'battlecry' for a in game.state.entities[eid].abilities))
        self.assertFalse(active_abilities(game.state.entities[eid], 'battlecry'))
        self.assertEqual(len(game.state.battlecry_history), before)
        self.assertFalse(game.state.players[2].hand)
        self.cycle(game)
        self.assertTrue(active_abilities(game.state.entities[eid], 'battlecry'))
        self.assertFalse(any(game.state.entities[i].card_id == 'EX1_014t'
            for i in game.state.players[2].hand))
        self.assertEqual(len(game.state.battlecry_history), before)
        self.portable(game)

    def test_ordinary_dormant_battlecry_retains_the_preexisting_entry_contract(self):
        game = self.game(hand=(ORDINARY,), own=())
        eid = self.play(game, ORDINARY)
        self.assertEqual(game.state.entities[eid].dormancy.remaining_turns, 1)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 99)
        self.assertFalse(self.markers(game, eid))
        self.portable(game)

    def test_sleeping_body_blocks_normal_targeting_and_ordinary_damage(self):
        game = self.game(hand=(QUIET, HIT), own=(recipe(), UNIT)); eid = self.body(game)
        with self.assertRaises(IllegalAction):
            self.play(game, QUIET, eid)
        self.play(game, HIT)
        self.assertEqual(game.state.entities[eid].damage, 0)
        other = next(i for i in game.state.players[1].board if i != eid)
        self.assertEqual(game.state.entities[other].damage, 2)

    def test_printed_neighbor_aura_sleeps_then_returns_on_the_original_slots(self):
        game = self.game(WOLF, own=(UNIT, recipe(WOLF), UNIT)); ids = tuple(game.state.players[1].board)
        self.assertEqual([game.state.entities[i].attack for i in ids], [2, 6, 2])
        self.cycle(game)
        self.assertEqual([game.state.entities[i].attack for i in ids], [3, 6, 3])
        self.portable(game)

    def test_awake_current_copy_and_base_copy_keep_distinct_original_dormancy(self):
        game = self.game(hand=(COPY, BASE)); self.cycle(game); eid = self.body(game)
        self.play(game, COPY, eid); self.play(game, BASE, eid)
        ids = tuple(game.state.players[1].board)
        self.assertEqual([None if game.state.entities[i].dormancy is None else game.state.entities[i].dormancy.remaining_turns for i in ids], [None, None, 1])
        self.assertTrue(all(len(self.markers(game, i)) == 1 for i in ids))
        self.portable(game)

    def test_actual_ammunae_copies_the_played_dormant_deathrattle_with_fresh_clock_identity(self):
        game = self.game(hand=(AMMUNAE, TAMER), own=())
        self.play(game, AMMUNAE); self.craft(game); self.play(game, recipe())
        bodies = [game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id == recipe()]
        self.assertEqual(len(bodies), 2)
        self.assertTrue(all(e.dormancy.remaining_turns == 1 and e.components == (BEETLE, CARD) for e in bodies))
        self.assertNotEqual(bodies[0].dormancy.id, bodies[1].dormancy.id)
        self.portable(game)

    def test_typed_resurrection_reinstalls_one_clock_and_keeps_death_material(self):
        game = self.game(hand=(KILL, REZ)); self.cycle(game); old = self.body(game)
        self.play(game, KILL, old)
        death = next(row for row in game.state.death_history if row.entity_id == old)
        self.assertEqual(death.components, (BEETLE, CARD))
        self.assertEqual(sum(a.kind == NATIVE_DORMANT_ENTRY for a in death.abilities), 1)
        self.portable(game)
        self.play(game, REZ); eid = self.body(game)
        self.assertNotEqual(eid, old)
        self.assertEqual((game.state.entities[eid].health, game.state.entities[eid].dormancy.remaining_turns), (4, 1))
        self.portable(game)

    def test_reborn_preserves_one_health_and_reenters_original_printed_sleep(self):
        game = self.game(hand=(REBORN, KILL)); self.cycle(game); old = self.body(game)
        self.play(game, REBORN, old); self.play(game, KILL, old)
        eid = self.body(game); self.assertNotEqual(eid, old)
        self.assertEqual((game.state.entities[eid].health, game.state.entities[eid].dormancy.remaining_turns), (1, 1))
        self.cycle(game)
        self.assertEqual(game.state.entities[eid].health, 1)
        self.assertNotIn(Keyword.REBORN, game.state.entities[eid].keywords)
        self.portable(game)

    def test_silence_then_bounce_replay_rebuilds_printed_text_and_original_sleep(self):
        game = self.game(hand=(QUIET, BOUNCE)); self.cycle(game); eid = self.body(game)
        self.play(game, QUIET, eid); self.assertFalse(self.markers(game, eid))
        self.play(game, BOUNCE, eid); self.assertIsNone(game.state.entities[eid].dormancy)
        self.play(game, recipe())
        self.assertEqual((game.state.entities[eid].health, game.state.entities[eid].dormancy.remaining_turns), (4, 1))
        self.assertEqual(len(self.markers(game, eid)), 1)
        self.portable(game)

    def test_transform_and_named_summon_infer_full_recipe_and_printed_clock(self):
        game = self.game(hand=(MORPH, SUMMON), own=(UNIT,)); old = game.state.players[1].board[0]
        self.play(game, MORPH, old); self.play(game, SUMMON)
        bodies = [game.state.entities[i] for i in game.state.players[1].board]
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[0].id, old)
        self.assertTrue(all(e.card_id == recipe() and e.components == (BEETLE, CARD) and e.dormancy.remaining_turns == 1 for e in bodies))
        self.portable(game)

    def test_awakening_wait_restores_turn_tail_and_does_not_leak_internal_marker(self):
        game = self.game(variant='awakewait'); eid = self.body(game)
        self.cycle(game); self.assertIsNotNone(game.state.pending_choice)
        restored = self.portable(game)
        for player in (1, 2):
            self.assertNotIn(NATIVE_DORMANT_ENTRY, json.dumps(game.for_player(player).observe()))
        self.choose(game); self.choose(restored)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertIsNone(game.state.entities[eid].dormancy)
        self.portable(game)

    def test_failed_awakening_rolls_back_whole_turn_clock_and_rng(self):
        game = self.game(variant='awakefail'); game.apply(EndTurn(1)); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            game.apply(EndTurn(2))
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_late_paid_entry_failure_restores_hand_clock_and_original_payment(self):
        game = self.game(hand=(TAMER,), own=(), variant='playfail'); self.craft(game); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, recipe())
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_carrier_and_rehashed_save_reject_forged_or_removed_entry_policy(self):
        game = self.game(MUKLA); eid = self.body(game); entity = game.state.entities[eid]
        marker = self.markers(game, eid)[0]
        for change in ({'origin': 'granted'}, {'consumed': True}, {'expires_turn': 9}, {'source_id': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(marker, **change)
        for components in ((), tuple(reversed(entity.components)), list(entity.components)):
            with self.subTest(components=components), self.assertRaises(ValueError):
                validate_dormant_carrier(game.registry, entity.card_id, entity.kind, entity.abilities, components)
        with self.assertRaises(ValueError):
            validate_dormant_carrier(game.registry, CARD, CardType.MINION, (marker,))
        with self.assertRaises(ValueError):
            validate_dormant_carrier(game.registry, entity.card_id, entity.kind,
                (*entity.abilities, replace(marker, id=marker.id+10000)), entity.components)
        saved = deepcopy(game.snapshot()); row = saved['state']['entities'][str(eid)]
        row['abilities'] = [a for a in row['abilities'] if a['kind'] != NATIVE_DORMANT_ENTRY]
        rehash(saved)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, fixture(self.mode, 'independent-reader'))

    def test_unknown_or_incomplete_candidate_still_rejects_before_first_sampling(self):
        for variant in ('unreviewed', 'incomplete'):
            with self.subTest(variant=variant):
                game = self.game(hand=(TAMER,), own=(), variant=variant); saved = game.snapshot()
                with self.assertRaises(ResolutionError) as caught:
                    self.play(game, TAMER)
                self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
                self.assertEqual(game.snapshot(), saved)

    def test_new_capability_rejects_changed_original_face_and_previous_snapshot_schema(self):
        registry = Registry(P+'wrong'); registry.register_card(replace(originals().card(CARD), dormant_turns=2))
        with self.assertRaises(TargetValidationError):
            register_zombeast_native_dormant_parts(registry)
        self.assertNotIn(CARD, registry.crafted_minion_parts)
        game = self.game(); saved = game.snapshot(); saved['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, fixture(self.mode))
