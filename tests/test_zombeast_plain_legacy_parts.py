"""Exact plain dependency faces through real construction and shared keywords."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_zombeast_native_keyword_parts import part_registry
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_keyword_parts import (
    CORE_PORCUPINE, register_zombeast_native_keyword_parts)
from hs_sim.cards.zombeast_plain_legacy_parts import (
    PARTS, DEFINITIONS, EXISTING, load_batch, register_zombeast_plain_legacy_parts)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, Keyword, PlayerSetup, Registry, ResolutionError,
    Scenario, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, PREFIX
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (CopyMinion, Damage, Destroy, InvokeBehavior,
    ReturnToHand, Silence)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k511.'
HERO, POWER, UNIT, HURT, HIT, KILL, QUIET, COPY, BASE, BOUNCE, WATCH = (
    P+x for x in ('hero', 'power', 'unit', 'hurt', 'hit', 'kill', 'quiet', 'copy', 'base', 'bounce', 'watch'))
BEETLE, MOLE, UNREVIEWED = 'CORE_LOOT_413', 'LOOT_258', 'CORE_CS2_120'
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
CONTEXT = GenerationContext('explicit-k511-plain-dependency-fixture', 'experimental')


@lru_cache(None)
def originals():
    return build_registry()


def new_registry(corrupt=None):
    source = originals(); r = part_registry(); register_zombeast_native_keyword_parts(r)
    for cid in EXISTING:
        card = source.card(cid)
        r.register_card(replace(card, attack=card.attack+1) if cid == corrupt else card)
        r.register_pool_card(source.pool_card(cid))
    return r


@lru_cache(None)
def fixture(mode='CS2_119|normal|'+BEETLE, role='writer'):
    part, variant, first = mode.split('|'); source = originals(); r = new_registry()
    r._version = P+mode
    register_zombeast_plain_legacy_parts(r)
    for body in (TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward',
            source.card(BEETLE).deathrattle):
        r.register_behavior(body, source.behavior(body))
    for cid in (BEETLE, TAMER, QUEST, TEMPLATE, UNREVIEWED):
        r.register_card(source.card(cid))
    assert BEETLE in source.crafted_minion_parts
    r.register_crafted_minion_part(BEETLE)
    r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=40, metadata=META))
    for cid, body in {
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 40, c.source_id),),
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        BASE: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
    }.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=None if cid == HURT else TargetSpec(TargetMode.REQUIRED,
                kinds=(CardType.MINION,))))
    for cid in (BEETLE, CORE_PORCUPINE, UNREVIEWED):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for pool, ids in ((FIRST, (first,)), (SECOND, (part, UNREVIEWED) if variant == 'unreviewed' else (part,))):
        r.register_pool(PoolDefinition(pool, 'explicit-plain-legacy-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
            complete=not(variant == 'incomplete' and pool == SECOND)))
    def fail(c):
        raise ResolutionError('K511 intentional final choice delivery failure')
    def watch(c):
        entity = c.state.entities.get(c.event.target_id)
        return (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if (
            variant == 'fail' and entity is not None and entity.card_id.startswith(PREFIX)) else ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('card_added_to_hand', P+'watch'),)))
    r.validate(); return r


class ZombeastPlainLegacyPartsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, part, first=BEETLE):
        return CraftedMinionRecipe(TEMPLATE, first, part).card_id

    def game(self, part='CS2_119', *, player=1, first=BEETLE, hand=None, own=(),
            enemy=(UNIT,), opposing_hand=(), variant='normal'):
        self.mode = '|'.join((part, variant, first))
        if hand is None:
            hand = (TAMER,)
        if variant == 'fail':
            own = (*own, WATCH)
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else opposing_hand, board=own if p == player else enemy,
            deck=(UNIT,)*9, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=511,
            generation_context=CONTEXT), fixture(self.mode))

    def pick(self, game, cid):
        option = next(o for o in game._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in o.effects))
        self.choose(game, option.id)

    def craft(self, game, part, player=1, first=BEETLE):
        self.play(game, TAMER, player=player); self.pick(game, first); self.pick(game, part)
        return self.entity(game, self.recipe(part, first), player).id

    def body(self, game, player=1):
        return next(i for i in game.state.players[player].board if game.state.entities[i].card_id.startswith(PREFIX))

    def cycle(self, game):
        game.apply(EndTurn(1)); game.apply(EndTurn(2))

    def test_fifteen_exact_full_sources_and_thirty_faces_keep_native_scope_explicit(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['cards']+data['existing_dependencies']}
        self.assertEqual((len(data['cards']), len(data['existing_dependencies']), len(data['official_observations'])), (13, 2, 30))
        for face in data['official_observations']:
            batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        self.assertTrue(set(PARTS) <= originals().crafted_minion_parts)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in originals().pools))
        self.assertNotIn(UNREVIEWED, originals().crafted_minion_parts)

    def test_all_fifteen_real_tamer_parts_preserve_raw_body_payment_and_keywords(self):
        data = load_batch(); raws = {x['record']['id']: x['record'] for x in data['cards']+data['existing_dependencies']}
        for index, part in enumerate(PARTS):
            with self.subTest(part=part):
                player = 1+index%2; raw = raws[part]; game = self.game(part, player=player)
                eid = self.craft(game, part, player); face = game.registry.card(self.recipe(part))
                self.assertEqual((face.cost, face.attack, face.health), (2+raw['cost'], 2+raw['attack'], 3+raw['health']))
                self.play(game, face.id, player=player)
                self.assertEqual(game.state.players[player].mana, 27-raw['cost'])
                self.assertEqual(game.state.entities[eid].components, (BEETLE, part))
                self.assertEqual({k.value for k in game.state.entities[eid].keywords}, set(data['native_keywords'][part]))
                self.assertEqual(sum(a.kind == 'deathrattle' for a in game.state.entities[eid].abilities), 1)

    def test_thirteen_new_dependency_definitions_have_real_standalone_paid_entry(self):
        rows = {x['record']['id']: x['record'] for x in load_batch()['cards']}
        for part in DEFINITIONS:
            with self.subTest(part=part):
                game = self.game(part, hand=(part,)); raw = rows[part]
                eid = self.play(game, part); entity = game.state.entities[eid]
                self.assertEqual((entity.attack, entity.max_health), (raw['attack'], raw['health']))
                self.assertEqual(game.state.players[1].mana, 30-raw['cost'])
                self.assertFalse(entity.components)

    def test_real_sidequest_keeps_printed_cost_and_original_zero_floor_discount(self):
        part = 'GIL_558'; game = self.game(part, hand=(QUEST, MOLE, MOLE, MOLE))
        self.play(game, QUEST)
        for _ in range(3):
            self.play(game, MOLE)
        self.pick(game, BEETLE); self.pick(game, part)
        eid = self.entity(game, self.recipe(part)).id
        self.assertEqual((game.registry.card(self.recipe(part)).cost, quote_cost(game.state, game.registry, game.state.entities[eid]).amount), (3, 0))
        self.play(game, self.recipe(part))
        self.assertEqual(game.state.players[1].mana, 26)
        self.portable(game)

    def test_new_rush_lifesteal_pair_uses_immediate_minion_attack_and_actual_heal(self):
        part = 'GIL_143'; game = self.game(part, hand=(TAMER, HURT))
        self.play(game, HURT); eid = self.craft(game, part); self.play(game, self.recipe(part))
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, game.state.players[2].hero_id))
        game.apply(Attack(1, eid, game.state.players[2].board[0]))
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 63)
        self.assertEqual(game.state.entities[eid].damage, 1)
        self.portable(game)

    def test_new_windfury_donor_consumes_two_attacks_and_rejects_a_third(self):
        part = 'DMF_190'; game = self.game(part); eid = self.craft(game, part); self.play(game, self.recipe(part)); self.cycle(game)
        target = game.state.players[2].board[0]
        game.apply(Attack(1, eid, target)); game.apply(Attack(1, eid, target))
        self.assertEqual((game.state.entities[eid].attacks_this_turn, game.state.entities[target].damage), (2, 10))
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, target))

    def test_actual_rush_taunt_donor_keeps_both_distinct_combat_rules(self):
        part = 'DRG_065'; game = self.game(part); eid = self.craft(game, part); self.play(game, self.recipe(part))
        enemy = game.state.players[2].board[0]; game.apply(Attack(1, eid, enemy)); game.apply(EndTurn(1))
        with self.assertRaises(IllegalAction):
            game.apply(Attack(2, enemy, game.state.players[1].hero_id))
        game.apply(Attack(2, enemy, eid))
        self.assertEqual(game.state.entities[eid].damage, 2)

    def test_actual_stealth_poisonous_donor_hides_until_attack_and_kills_the_hit_minion(self):
        part = 'UNG_814'; game = self.game(part, opposing_hand=(HIT,)); eid = self.craft(game, part); self.play(game, self.recipe(part))
        game.apply(EndTurn(1))
        with self.assertRaises(IllegalAction):
            self.play(game, HIT, eid, player=2)
        game.apply(EndTurn(2)); enemy = game.state.players[2].board[0]
        game.apply(Attack(1, eid, enemy)); self.assertEqual(game.state.entities[enemy].zone, Zone.GRAVEYARD)
        self.assertNotIn(Keyword.STEALTH, game.state.entities[eid].keywords)
        game.apply(EndTurn(1)); self.play(game, HIT, eid, player=2)
        self.portable(game)

    def test_legacy_lifesteal_transfers_to_original_core_porcupine_death_damage(self):
        part = 'GIL_558'; first = CORE_PORCUPINE
        game = self.game(part, first=first, hand=(TAMER, HURT, KILL))
        self.play(game, HURT); eid = self.craft(game, part, first=first); self.play(game, self.recipe(part, first))
        self.play(game, KILL, eid)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 64)
        enemy = game.state.entities[game.state.players[2].board[0]]
        self.assertEqual(enemy.damage+game.state.entities[game.state.players[2].hero_id].damage, 4)
        self.portable(game)

    def test_silence_current_and_base_copy_and_bounce_keep_the_exact_legacy_recipe(self):
        part = 'UNG_814'; cid = self.recipe(part)
        game = self.game(part, hand=(QUIET, COPY, BASE, BOUNCE), own=(cid,)); eid = self.body(game)
        self.play(game, QUIET, eid); self.play(game, COPY, eid); self.play(game, BASE, eid)
        ids = tuple(game.state.players[1].board)
        self.assertEqual([bool(game.state.entities[i].keywords) for i in ids], [False, False, True])
        self.assertTrue(all(game.state.entities[i].components == (BEETLE, part) for i in ids))
        self.play(game, BOUNCE, eid); self.play(game, cid)
        self.assertEqual(game.state.entities[eid].keywords, {Keyword.STEALTH, Keyword.POISONOUS})
        self.portable(game)

    def test_dual_type_source_and_existing_core_aliases_never_change_exact_recipe_ids(self):
        registry = fixture(); self.assertEqual(registry.card('DMF_190').metadata.tribes, ('elemental', 'beast'))
        self.assertEqual(registry.card(self.recipe('DMF_190')).metadata.tribes, registry.card(TEMPLATE).metadata.tribes)
        for legacy, core in (('EX1_028', 'CORE_EX1_028'), ('GIL_558', 'CORE_GIL_558')):
            old, current = registry.card(self.recipe(legacy)), registry.card(self.recipe(core))
            self.assertNotEqual(old.id, current.id)
            self.assertEqual((old.cost, old.attack, old.health, old.keywords), (current.cost, current.attack, current.health, current.keywords))
        self.assertNotIn(UNREVIEWED, registry.crafted_minion_parts)

    def test_both_actual_menus_restore_clone_replay_without_opponent_recipe_options(self):
        part = 'CS2_172'; game = self.game(part); self.play(game, TAMER)
        self.assertNotIn(part, json.dumps(game.for_player(2).observe()))
        restored = self.portable(game); self.pick(game, BEETLE); self.pick(restored, BEETLE)
        self.assertEqual(game.snapshot(), restored.snapshot())
        restored = self.portable(game); self.pick(game, part); self.pick(restored, part)
        self.assertEqual(game.snapshot(), restored.snapshot())

    def test_core_crocodile_is_not_silently_approved_or_dropped_after_legacy_approval(self):
        for variant in ('unreviewed', 'incomplete'):
            with self.subTest(variant=variant):
                game = self.game('CS2_120', variant=variant); saved = game.snapshot()
                with self.assertRaises(ResolutionError) as caught:
                    self.play(game, TAMER)
                self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
                self.assertEqual(game.snapshot(), saved)

    def test_late_second_choice_failure_restores_the_original_choice_payment_and_rng(self):
        part = 'EX1_170'; game = self.game(part, variant='fail')
        self.play(game, TAMER); self.pick(game, BEETLE); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.pick(game, part)
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_complete_batch_is_prevalidated_before_any_new_definition_or_capability(self):
        registry = new_registry(EXISTING[-1]); before_cards = set(registry.cards); before_parts = set(registry.crafted_minion_parts)
        with self.assertRaises(TargetValidationError):
            register_zombeast_plain_legacy_parts(registry)
        self.assertEqual(set(registry.cards), before_cards)
        self.assertEqual(set(registry.crafted_minion_parts), before_parts)
        self.assertFalse(set(DEFINITIONS) & set(registry.pool_cards))
