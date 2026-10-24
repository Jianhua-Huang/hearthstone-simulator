"""Existing Standard text bodies through real crafting and physical lifecycle."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_text_parts import (PARTS, CHILDREN, load_batch,
    register_zombeast_native_text_parts)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayerSetup, Registry, ResolutionError, Scenario, TargetMode,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, PREFIX
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import Buff, Damage, Destroy, InvokeBehavior, Silence
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k509.'
HERO, POWER, UNIT, HURT, KILL, QUIET, GROW, WATCH = (
    P+x for x in ('hero', 'power', 'unit', 'hurt', 'kill', 'quiet', 'grow', 'watch'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
SECOND_PART = 'LOOT_258'
SHADOWS = ('CORE_ICC_055', 'CORE_EX1_309')
UNREVIEWED = 'CORE_CS2_120'
CONTEXT = GenerationContext('explicit-k509-native-text-fixture', 'experimental')


@lru_cache(None)
def originals():
    return build_registry()


def native_registry(corrupt=None):
    source = originals(); r = Registry(P+'native')
    for cid in (*PARTS, *CHILDREN, TAMER, TEMPLATE, SECOND_PART, UNREVIEWED, *SHADOWS):
        card = source.card(cid)
        if cid == corrupt:
            card = replace(card, health=card.health+1)
        r.register_card(card)
    bodies = {TAMER_BODY, 'cards.black_empire_stats.imp_selected',
        'cards.hand_shuffle_turn_copy.copy'}
    for cid in (*PARTS, *CHILDREN, *SHADOWS):
        card = source.card(cid)
        bodies.update(x for x in (card.on_play, card.battlecry, card.deathrattle) if x)
        bodies.update(x.behavior_id for x in card.triggers)
    # Utility bodies use their real compiled stage IDs; no replacement bodies.
    for body in tuple(bodies):
        bodies.update(key for key in source._behaviors if key.startswith(body+'.'))
    for body in sorted(bodies):
        r.register_behavior(body, source.behavior(body))
    return r


@lru_cache(None)
def fixture(mode='CORE_EX1_014|normal', role='writer'):
    part, variant = mode.split('|'); source = originals(); r = native_registry()
    register_zombeast_native_text_parts(r)
    assert SECOND_PART in source.crafted_minion_parts
    r.register_crafted_minion_part(SECOND_PART)
    r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=2, health=30, metadata=META))
    for cid, body in {
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 40, c.source_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        GROW: lambda c: (Buff(c.target_id, attack=3, health=2, source_id=c.source_id),),
    }.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=None if cid == HURT else TargetSpec(TargetMode.REQUIRED,
                kinds=(CardType.MINION,))))
    def fail(c):
        raise ResolutionError('K509 intentional failure after native delivery')
    def watch(c):
        entity = c.state.entities.get(c.event.source_id)
        return (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if (
            entity is not None and entity.card_id.startswith(PREFIX)) else ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=100,
        triggers=(TriggerSpec('card_played', P+'watch'),), metadata=META))
    for cid in (*PARTS, SECOND_PART, UNREVIEWED):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    second = (SECOND_PART, UNREVIEWED) if variant == 'unreviewed' else (SECOND_PART,)
    for pool, ids in ((FIRST, (part,)), (SECOND, second)):
        r.register_pool(PoolDefinition(pool, 'explicit-native-text-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
            complete=not (variant == 'incomplete' and pool == SECOND)))
    r.validate(); return r


class ZombeastNativeTextPartsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, part):
        return CraftedMinionRecipe(TEMPLATE, part, SECOND_PART).card_id

    def game(self, part='CORE_EX1_014', *, player=1, hand=None, own=(), enemy=(UNIT,),
            variant='normal', opposing_hand=()):
        self.mode = part+'|'+variant
        if hand is None:
            hand = (TAMER,)
        if variant == 'fail':
            own = (*own, WATCH)
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else opposing_hand, board=own if p == player else enemy,
            deck=(UNIT,)*8, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=509,
            generation_context=CONTEXT), fixture(self.mode))

    def pick(self, game, cid):
        option = next(row for row in game._frame.options if any(
            type(effect) is ResolveCraft and effect.card_id == cid for effect in row.effects))
        self.choose(game, option.id)

    def craft(self, game, part, player=1):
        self.play(game, TAMER, player=player)
        self.pick(game, part); self.pick(game, SECOND_PART)
        return self.entity(game, self.recipe(part), player).id

    def body(self, game, player=1):
        return next(i for i in game.state.players[player].board
            if game.state.entities[i].card_id.startswith(PREFIX))

    def test_complete_fifteen_rows_thirty_faces_and_twelve_original_definitions(self):
        data = load_batch(); rows = {x['record']['id']: x['record'] for x in data['existing_dependencies']}
        self.assertEqual((len(rows), len(data['official_observations'])), (15, 30))
        for face in data['official_observations']:
            batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        registry = originals()
        boundary = batch.registration_prefix(build_registry,
            'hs_sim.cards.zombeast_native_text_parts.register_zombeast_native_text_parts',
            register_zombeast_native_text_parts, after=True)
        self.assertEqual(len(boundary.crafted_minion_parts), 35)
        self.assertTrue(set(PARTS) <= set(registry.crafted_minion_parts))
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in registry.pools))
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_every_real_native_text_part_passes_paid_tamer_and_original_body_entry(self):
        for index, part in enumerate(PARTS):
            with self.subTest(part=part):
                player = 1+index%2; game = self.game(part, player=player)
                eid = self.craft(game, part, player); native = originals().card(part)
                face = game.registry.card(self.recipe(part)); amount = native.cost+1
                self.assertEqual((face.cost, face.attack, face.health),
                    (amount, native.attack+1, native.health+3))
                target = game.state.players[3-player].board[0] if native.targeting else None
                self.play(game, face.id, target, player)
                if part == 'TLC_242':
                    self.choose(game, 'stats')
                self.assertEqual(game.state.players[player].mana, 29-amount)
                self.assertEqual(game.state.entities[eid].components, (part, SECOND_PART))
                if part == 'CORE_EX1_014':
                    self.assertEqual([game.state.entities[i].card_id for i in game.state.players[3-player].hand], ['EX1_014t']*2)
                elif part == 'CORE_EX1_162':
                    tamer = next(i for i in game.state.players[player].board if game.state.entities[i].card_id == TAMER)
                    self.assertEqual(game.state.entities[tamer].attack, 2)
                elif part == 'CORE_GIL_622':
                    self.assertEqual(game.state.entities[game.state.players[3-player].hero_id].health, 97)
                elif part == 'CORE_UNG_084':
                    self.assertEqual(game.state.entities[target].damage, 3)
                elif part == 'TIME_601':
                    self.assertEqual(len(game.state.players[player].hand), 3)
                elif part == 'EDR_492':
                    ducks = [game.state.entities[i] for i in game.state.players[player].board
                        if game.state.entities[i].card_id == 'EDR_492t']
                    self.assertEqual(len(ducks), 3)
                    self.assertTrue(all((e.attack, e.max_health) == (1, 1) and Keyword.RUSH in e.keywords for e in ducks))
                elif part == 'BE_255':
                    self.assertEqual(game.state.entities[eid].max_health, native.health+3)
                elif part == 'TIME_042':
                    self.assertEqual([game.state.entities[i].card_id for i in game.state.players[player].hand], ['TIME_042t'])

    def test_native_lifedrinker_keeps_separate_damage_and_real_hero_heal(self):
        part = 'CORE_GIL_622'; game = self.game(part, hand=(TAMER, HURT))
        self.play(game, HURT); self.craft(game, part); self.play(game, self.recipe(part))
        self.assertEqual([game.state.entities[game.state.players[p].hero_id].health for p in (1, 2)], [63, 97])
        self.portable(game)

    def test_original_beetle_death_grants_armor_once_and_silence_removes_it(self):
        part = 'CORE_LOOT_413'
        for silence in (False, True):
            with self.subTest(silence=silence):
                game = self.game(part, hand=(KILL, QUIET), own=(self.recipe(part),))
                eid = self.body(game)
                if silence:
                    self.play(game, QUIET, eid)
                self.play(game, KILL, eid)
                self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 0 if silence else 3)
                self.assertEqual(game.state.death_history[-1].components, (part, SECOND_PART))
                self.portable(game)

    def test_imp_samples_actual_held_shadow_spell_and_only_discounts_one_physical_card(self):
        part = 'BE_993'; game = self.game(part, hand=(*SHADOWS, KILL), own=(self.recipe(part),))
        held = tuple(game.state.players[1].hand[:2]); costs = [quote_cost(game.state, game.registry, game.state.entities[i]).amount for i in held]
        self.play(game, KILL, self.body(game))
        actual = [quote_cost(game.state, game.registry, game.state.entities[i]).amount for i in held]
        self.assertEqual(sorted(before-after for before, after in zip(costs, actual)), [0, 2])
        self.assertIsNone(game.state.pending_choice)
        self.portable(game)

    def test_draw_until_three_uses_remaining_physical_hand_and_does_not_overdraw(self):
        part = 'TIME_601'; game = self.game(part, hand=(TAMER, UNIT, UNIT, UNIT))
        self.craft(game, part); original = tuple(game.state.players[1].hand[:-1])
        deck = tuple(game.state.players[1].deck); self.play(game, self.recipe(part))
        self.assertEqual(tuple(game.state.players[1].hand), original)
        self.assertEqual(tuple(game.state.players[1].deck), deck)

    def test_three_ducklings_respect_actual_board_capacity(self):
        part = 'EDR_492'; game = self.game(part, own=(UNIT,)*4)
        self.craft(game, part); self.play(game, self.recipe(part))
        self.assertEqual(len(game.state.players[1].board), 7)
        self.assertEqual(sum(game.state.entities[i].card_id == 'EDR_492t' for i in game.state.players[1].board), 1)
        self.portable(game)

    def test_original_growth_counts_other_friendly_minion_plays_only(self):
        part = 'BE_255'; game = self.game(part, hand=(TAMER, UNIT, HURT), opposing_hand=(UNIT,))
        self.craft(game, part); self.play(game, self.recipe(part)); eid = self.body(game)
        self.assertEqual(game.state.entities[eid].max_health, 4)
        self.play(game, HURT); self.assertEqual(game.state.entities[eid].max_health, 4)
        self.play(game, UNIT); self.assertEqual(game.state.entities[eid].max_health, 5)
        game.apply(EndTurn(1)); self.play(game, UNIT, player=2)
        self.assertEqual(game.state.entities[eid].max_health, 5)
        self.portable(game)

    def test_native_wolf_aura_uses_current_physical_neighbors_and_silence(self):
        part = 'CORE_EX1_162'; game = self.game(part, hand=(QUIET,), own=(UNIT, self.recipe(part), UNIT, UNIT))
        ids = tuple(game.state.players[1].board)
        self.assertEqual([game.state.entities[i].attack for i in ids], [3, 3, 3, 2])
        self.play(game, QUIET, ids[1])
        self.assertEqual([game.state.entities[i].attack for i in ids], [2, 3, 2, 2])
        self.portable(game)

    def test_delayed_ooze_copy_keeps_current_stats_all_type_and_recipe_without_replaying_battlecry(self):
        part = 'BE_734'; game = self.game(part, hand=(TAMER, GROW))
        self.craft(game, part); self.play(game, self.recipe(part)); eid = self.body(game)
        self.play(game, GROW, eid); game.apply(EndTurn(1))
        copies = [game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id == self.recipe(part)]
        self.assertEqual(len(copies), 2)
        self.assertTrue(all((e.attack, e.max_health, e.components) == (7, 7, (part, SECOND_PART)) for e in copies))
        self.assertEqual(game.registry.card(self.recipe(part)).metadata.tribes, ('all',))
        self.portable(game)

    def test_silence_before_current_turn_end_cancels_native_ooze_copy(self):
        part = 'BE_734'; game = self.game(part, hand=(TAMER, QUIET))
        self.craft(game, part); self.play(game, self.recipe(part)); self.play(game, QUIET, self.body(game))
        game.apply(EndTurn(1))
        self.assertEqual(sum(game.state.entities[i].card_id == self.recipe(part) for i in game.state.players[1].board), 1)

    def test_maluk_discards_original_remaining_hand_then_infinite_banana_reuses_original_spell(self):
        part = 'TIME_042'; game = self.game(part, hand=(TAMER, UNIT, SHADOWS[0]))
        self.craft(game, part); discarded = tuple(game.state.players[1].hand[:-1])
        self.play(game, self.recipe(part)); eid = self.body(game)
        self.assertTrue(all(game.state.entities[i].zone == Zone.GRAVEYARD for i in discarded))
        banana = self.entity(game, 'TIME_042t').id
        self.play(game, 'TIME_042t', eid)
        self.assertNotEqual(self.entity(game, 'TIME_042t').id, banana)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].max_health), (7, 10))
        self.portable(game)

    def test_native_choice_wait_restores_both_real_keyword_branches(self):
        part = 'TLC_242'
        for option, keyword in (('taunt', Keyword.TAUNT), ('poisonous', Keyword.POISONOUS)):
            with self.subTest(option=option):
                game = self.game(part); self.craft(game, part); self.play(game, self.recipe(part))
                restored = self.portable(game)
                self.choose(game, option); self.choose(restored, option)
                self.assertEqual(game.snapshot(), restored.snapshot())
                self.assertIn(keyword, game.state.entities[self.body(game)].keywords)

    def test_failure_after_native_banana_delivery_rolls_back_payment_and_both_hands(self):
        part = 'CORE_EX1_014'; game = self.game(part, variant='fail')
        self.craft(game, part); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, self.recipe(part))
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_unreviewed_or_incomplete_original_offer_still_fails_before_sampling(self):
        for variant in ('unreviewed', 'incomplete'):
            with self.subTest(variant=variant):
                game = self.game(variant=variant); saved = game.snapshot()
                with self.assertRaises(ResolutionError) as caught:
                    self.play(game, TAMER)
                self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
                self.assertEqual(game.snapshot(), saved)

    def test_all_native_bodies_and_children_are_prevalidated_without_partial_approval(self):
        for corrupt in (PARTS[-1], CHILDREN[-1]):
            with self.subTest(corrupt=corrupt):
                registry = native_registry(corrupt)
                with self.assertRaises(TargetValidationError):
                    register_zombeast_native_text_parts(registry)
                self.assertFalse(set(PARTS) & set(registry.crafted_minion_parts))
