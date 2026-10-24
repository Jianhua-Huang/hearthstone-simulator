"""A reviewed primary zero stays zero through real play and construction."""
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_zombeast_plain_legacy_parts import new_registry, originals
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_zero_penguin import (
    CARD, RETIRED_CORE, load_batch, register_zombeast_zero_penguin)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, PlayerSetup, ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, PREFIX
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k512.'
HERO, POWER, UNIT, WATCH = (P+x for x in ('hero', 'power', 'unit', 'watch'))
BEETLE, MOLE = 'CORE_LOOT_413', 'LOOT_258'
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
CONTEXT = GenerationContext('explicit-k512-zero-penguin-fixture', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    source = originals(); r = new_registry(); r._version = P+mode
    register_zombeast_zero_penguin(r)
    for body in (TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward',
            source.card(BEETLE).deathrattle):
        r.register_behavior(body, source.behavior(body))
    for cid in (BEETLE, TAMER, QUEST, TEMPLATE, RETIRED_CORE):
        r.register_card(source.card(cid))
    r.register_crafted_minion_part(BEETLE)
    r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    for cid in (BEETLE, RETIRED_CORE):
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for pool, ids in ((FIRST, (BEETLE,)),
            (SECOND, (CARD, RETIRED_CORE) if mode == 'unreviewed' else (CARD,))):
        r.register_pool(PoolDefinition(pool, 'explicit-zero-penguin-v1', CONTEXT.target_id,
            CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
            complete=not(mode == 'incomplete' and pool == SECOND)))
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=40, metadata=META))
    def fail(c):
        raise ResolutionError('K512 intentional final choice delivery failure')
    def watch(c):
        entity = c.state.entities.get(c.event.target_id)
        return (InvokeBehavior(P+'fail', c.source_id, c.player_id),) if (
            mode == 'fail' and entity is not None and entity.card_id.startswith(PREFIX)) else ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
        triggers=(TriggerSpec('card_added_to_hand', P+'watch'),)))
    r.validate(); return r


class ZombeastZeroPenguinTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self):
        return CraftedMinionRecipe(TEMPLATE, BEETLE, CARD).card_id

    def game(self, *, player=1, hand=(TAMER,), mana=30, variant='normal'):
        self.mode = variant
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (),
            board=(WATCH,) if p == player and variant == 'fail' else (),
            deck=(UNIT,)*9, mana=mana, max_mana=mana, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=512,
            generation_context=CONTEXT), fixture(self.mode))

    def pick(self, game, cid):
        option = next(o for o in game._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in o.effects))
        self.choose(game, option.id)

    def test_original_zero_requires_both_full_primary_faces_and_retired_core_is_evidence_only(self):
        data = load_batch(); raw = data['cards'][0]['record']
        self.assertIsNone(raw['cost']); self.assertNotIn('COST', raw['tags'])
        self.assertEqual(data['numeric_normalizations'], {CARD: {'cost': 0}})
        for face in data['official_observations']:
            batch.check_face(raw, face['face'], face['locale'], numeric_normalizations={'cost': 0})
        self.assertEqual(data['evidence_only'][0]['record']['card_set_id'], 1810)
        self.assertIn(CARD, originals().crafted_minion_parts)
        self.assertNotIn(RETIRED_CORE, originals().crafted_minion_parts)
        self.assertEqual(originals().card(CARD).cost, 0)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in originals().pools))

    def test_both_players_can_play_real_originals_at_zero_mana_without_resource_gain(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player, hand=(CARD, CARD), mana=0)
                eids = [self.play(game, CARD, player=player) for _ in range(2)]
                self.assertNotEqual(*eids)
                self.assertEqual(game.state.players[player].mana, 0)
                self.assertEqual([(game.state.entities[i].attack, game.state.entities[i].max_health,
                    game.state.entities[i].components) for i in eids], [(1, 1, ()), (1, 1, ())])

    def test_both_real_tamers_keep_zero_material_exact_identity_body_and_payment(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player); self.play(game, TAMER, player=player)
                self.pick(game, BEETLE); self.pick(game, CARD)
                card = game.registry.card(self.recipe())
                self.assertEqual((card.cost, card.attack, card.health), (2, 3, 4))
                eid = self.play(game, card.id, player=player)
                self.assertEqual(game.state.entities[eid].components, (BEETLE, CARD))
                self.assertEqual(game.state.players[player].mana, 27)

    def test_actual_quest_discount_floors_total_cost_without_negative_payment(self):
        game = self.game(hand=(QUEST, MOLE, MOLE, MOLE)); self.play(game, QUEST)
        for _ in range(3):
            self.play(game, MOLE)
        self.pick(game, BEETLE); self.pick(game, CARD)
        eid = self.entity(game, self.recipe()).id
        self.assertEqual((game.registry.card(self.recipe()).cost,
            quote_cost(game.state, game.registry, game.state.entities[eid]).amount), (2, 0))
        self.play(game, self.recipe()); self.assertEqual(game.state.players[1].mana, 26)
        self.portable(game)

    def test_both_real_menus_restore_clone_replay_and_keep_opponent_options_private(self):
        game = self.game(); self.play(game, TAMER)
        self.assertNotIn(CARD, json.dumps(game.for_player(2).observe()))
        restored = self.portable(game); self.pick(game, BEETLE); self.pick(restored, BEETLE)
        self.assertEqual(game.snapshot(), restored.snapshot())
        restored = self.portable(game); self.pick(game, CARD); self.pick(restored, CARD)
        self.assertEqual(game.snapshot(), restored.snapshot())

    def test_unknown_retired_core_and_incomplete_pool_fail_before_payment_or_rng(self):
        for variant in ('unreviewed', 'incomplete'):
            with self.subTest(variant=variant):
                game = self.game(variant=variant); saved = game.snapshot()
                with self.assertRaises(ResolutionError) as caught:
                    self.play(game, TAMER)
                self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
                self.assertEqual(game.snapshot(), saved)

    def test_late_delivery_failure_restores_original_choice_and_rng(self):
        game = self.game(variant='fail'); self.play(game, TAMER); self.pick(game, BEETLE)
        saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.pick(game, CARD)
        self.assertEqual(game.snapshot(), saved); self.portable(game)

    def test_exact_identity_collision_fails_without_partial_definition_or_approval(self):
        for collision in ('card', 'pool'):
            with self.subTest(collision=collision):
                registry = new_registry(); original = originals().card(CARD)
                if collision == 'card': registry.register_card(original)
                else: registry.register_pool_card(PoolCard.from_definition(original))
                before = (dict(registry.cards), dict(registry.pool_cards), set(registry.crafted_minion_parts))
                with self.assertRaises(TargetValidationError):
                    register_zombeast_zero_penguin(registry)
                self.assertEqual((dict(registry.cards), dict(registry.pool_cards),
                    set(registry.crafted_minion_parts)), before)
