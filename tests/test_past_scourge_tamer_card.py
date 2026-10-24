"""Real paid Scourge Tamer and original two-stage physical crafting boundaries."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD, BODY, EXISTING, load_batch
from hs_sim.cards.storm_gates_card import TEMPLATE, FIRST, SECOND
from hs_sim.engine import (CardDefinition, CardType, Game, IllegalAction, Keyword,
    PlayerSetup, ResolutionError, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import PREFIX, recipe_from_id
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand, Destroy, InvokeBehavior
from hs_sim.engine.model import ChoicePurpose
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from tools import card_batch as batch

P = 'k499.'
UNIT, WATCH, UNKNOWN, KILL = (P+x for x in ('unit', 'watch', 'unknown', 'kill'))
FIRST_PARTS = ('UNG_803', 'BT_201')
BOAR = 'CS2_171'
CONTEXT = GenerationContext('explicit-scourge-tamer-fixture', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = build_registry()
    meta = replace(registry.card(BOAR).metadata, collectible=False, tribes=())
    registry.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=30, metadata=meta))
    def kill(context):
        target = next(i for i in context.state.players[context.player_id].board
            if context.state.entities[i].card_id.startswith(PREFIX))
        return (Destroy(target, context.source_id),)
    registry.register_behavior(KILL, kill)
    registry.register_card(CardDefinition(KILL, KILL, CardType.SPELL, on_play=KILL, metadata=meta))
    first, second = FIRST_PARTS, (BOAR,)
    if mode in ('unknown', 'high_unknown'):
        registry.register_pool_card(replace(registry.pool_card(BOAR), card_id=UNKNOWN,
            cost=5 if mode == 'unknown' else 6))
        first = (*first, UNKNOWN)
    if mode == 'unreviewed':
        # Young Dragonhawk now has a reviewed native donation declaration.
        first = (*first, 'CORE_CS2_120')
    if mode == 'wrong_role':
        first = (*first, UNIT)
        registry.register_pool_card(PoolCard.from_definition(registry.card(UNIT)))
    if mode != 'missing':
        for pool, ids in ((FIRST, first), (SECOND, second)):
            registry.register_pool(PoolDefinition(pool, 'explicit-fixture-v1', CONTEXT.target_id,
                CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
                complete=not(mode == 'incomplete' and pool == SECOND)))

    def fail(context):
        raise ResolutionError('Scourge Tamer delivery fixture failure')

    def watch(context):
        event = context.event
        if event.kind == 'craft_offer_accepted' and dict(event.data)['stage'] == 1:
            if mode == 'overflow':
                return tuple(AddToHand(event.player_id, UNIT, context.source_id)
                    for _ in range(10-len(context.state.players[event.player_id].hand)))
            if mode == 'source_gone':
                return (Destroy(event.source_id, context.source_id),)
        if event.kind == 'card_added_to_hand' and mode == 'fail':
            entity = context.state.entities.get(event.target_id)
            if entity is not None and entity.card_id.startswith(PREFIX):
                return (InvokeBehavior(P+'fail', context.source_id, context.player_id),)
        return ()

    registry.register_behavior(P+'fail', fail)
    registry.register_behavior(P+'watch', watch)
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        metadata=meta, triggers=(TriggerSpec('craft_offer_accepted', P+'watch'),
            TriggerSpec('card_added_to_hand', P+'watch'))))
    registry.validate()
    return registry


class ScourgeTamerTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, mode='normal', player=1, hand=None):
        self.mode = mode
        hand = (CARD,) if hand is None else hand
        players = tuple(PlayerSetup('HERO_08', hand=hand if p == player else (BOAR,),
            deck=(UNIT,)*5, board=(WATCH,) if p == player and mode in
                ('overflow', 'source_gone', 'fail') else (), mana=10, max_mana=10)
            for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=49,
            generation_context=CONTEXT), fixture(mode))

    def offer(self, game):
        return game._frame.options[0].effects[0].offer

    def pick(self, game, card_id=None):
        options = game._frame.options
        selected = next((option for option in options if any(type(effect) is ResolveCraft and
            effect.card_id == card_id for effect in option.effects)), None) if card_id else None
        self.choose(game, (selected or options[0]).id)

    def creation(self, game, player=1):
        return next(game.state.entities[i] for i in game.state.players[player].hand
            if game.state.entities[i].card_id.startswith(PREFIX))

    def test_full_source_primary_faces_original_dependencies_and_actual_registered_body(self):
        data = load_batch(); registry = fixture()
        self.assertEqual(tuple(row['record']['id'] for row in data['existing_dependencies']), EXISTING)
        self.assertEqual(len(data['official_observations']), 2)
        for face in data['official_observations']:
            batch.check_face(data['dependencies'][0]['record'], face['face'], face['locale'])
        card = registry.card(CARD)
        self.assertEqual((card.cost, card.attack, card.health, card.battlecry), (1, 1, 2, BODY))
        self.assertEqual(card.metadata.tribes, ('undead',))
        original = build_registry()
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in original.pools))
        self.assertEqual(original.card(TEMPLATE).metadata.tribes, ('beast', 'undead'))

    def test_paid_native_battlecry_both_actors_and_final_creation_has_no_sidequest_discount(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player); source = self.play(game, CARD, player=player)
                self.assertEqual(game.state.players[player].mana, 9)
                self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.CRAFT)
                self.assertEqual(game.state.pending_choice.player_id, player)
                self.assertEqual(self.offer(game).spec.source_id, source)
                self.assertEqual((self.offer(game).spec.max_part_cost,
                    self.offer(game).spec.discount_amount, self.offer(game).discount), (5, 0, 0))
                self.pick(game, FIRST_PARTS[0]); self.pick(game, BOAR)
                entity = self.creation(game, player); card = game.registry.card(entity.card_id)
                recipe = recipe_from_id(entity.card_id)
                self.assertEqual((recipe.template_card_id, recipe.first_card_id, recipe.second_card_id),
                    (TEMPLATE, FIRST_PARTS[0], BOAR))
                self.assertEqual((card.cost, card.attack, card.health), (2, 3, 2))
                self.assertEqual(quote_cost(game.state, game.registry, entity).amount, 2)
                self.assertEqual(game.state.players[player].mana, 9)
                self.assertEqual(len([event for event in game.events if event.kind == 'craft_offer_accepted']), 2)

    def test_crafted_native_battlecry_and_charge_execute_on_one_real_body(self):
        game = self.game(); self.play(game, CARD)
        self.pick(game, FIRST_PARTS[0]); self.pick(game, BOAR)
        entity = self.creation(game); cid = entity.card_id
        self.play(game, cid)
        final = game.state.entities[entity.id]
        self.assertEqual((final.attack, final.health), (3, 2))
        self.assertEqual([game.state.entities[game.state.players[p].hero_id].health for p in (1, 2)], [29, 29])
        self.assertTrue(any(ability.keyword == Keyword.CHARGE for ability in final.abilities))
        self.assertEqual(game.state.players[1].mana, 7)

    def test_porcupine_uses_summed_attack_through_existing_native_deathrattle(self):
        game = self.game(hand=(CARD, KILL)); self.play(game, CARD)
        self.pick(game, 'BT_201'); self.pick(game, BOAR)
        final = self.creation(game)
        self.assertEqual((game.registry.card(final.card_id).cost,
            game.registry.card(final.card_id).attack, game.registry.card(final.card_id).health), (4, 3, 5))
        self.play(game, final.card_id)
        self.assertTrue(any(ability.keyword == Keyword.CHARGE for ability in game.state.entities[final.id].abilities))
        self.play(game, KILL)
        self.assertEqual(game.state.entities[final.id].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 27)

    def test_both_actual_menus_restore_clone_and_replay_then_continue_original_choices(self):
        game = self.game(); self.play(game, CARD)
        first = self.portable(game)
        self.pick(game, FIRST_PARTS[0]); self.pick(first, FIRST_PARTS[0])
        self.assertEqual(first.snapshot(), game.snapshot())
        second = self.portable(game)
        self.pick(game, BOAR); self.pick(second, BOAR)
        self.assertEqual(second.snapshot(), game.snapshot())
        self.assertIsNone(game.state.pending_choice)

    def test_unknown_incomplete_or_invalid_eligible_part_rolls_back_paid_play_and_rng(self):
        for mode, error in (('missing', UnsupportedDefinitionError),
                ('incomplete', UnsupportedDefinitionError), ('unknown', UnsupportedDefinitionError),
                ('unreviewed', UnsupportedDefinitionError), ('wrong_role', ValueError)):
            with self.subTest(mode=mode):
                game = self.game(mode); saved = game.snapshot()
                with self.assertRaises(ResolutionError) as caught:
                    self.play(game, CARD)
                self.assertIsInstance(caught.exception.__cause__, error)
                self.assertEqual(game.snapshot(), saved)

    def test_real_five_cost_cap_excludes_above_cap_before_execution_lookup(self):
        game = self.game('high_unknown'); self.play(game, CARD)
        self.assertEqual(set(self.offer(game).candidates), set(FIRST_PARTS))
        self.assertNotIn(UNKNOWN, self.offer(game).candidates)
        self.pick(game); self.pick(game)
        self.assertEqual(len([i for i in game.state.players[1].hand
            if game.state.entities[i].card_id.startswith(PREFIX)]), 1)

    def test_source_death_during_original_first_offer_does_not_cancel_accepted_crafting(self):
        game = self.game('source_gone'); source = self.play(game, CARD)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.pick(game, FIRST_PARTS[0]); self.pick(game, BOAR)
        self.assertEqual(self.creation(game).controller, 1)

    def test_full_hand_reaction_keeps_two_choices_and_burns_only_final_ordinary_delivery(self):
        game = self.game('overflow'); self.play(game, CARD)
        self.assertEqual(len(game.state.players[1].hand), 10)
        self.pick(game, FIRST_PARTS[0]); self.pick(game, BOAR)
        self.assertEqual(len(game.state.players[1].hand), 10)
        creations = [entity for entity in game.state.entities.values() if entity.card_id.startswith(PREFIX)]
        self.assertEqual(len(creations), 1)
        self.assertEqual(creations[0].zone, Zone.GRAVEYARD)

    def test_invalid_choice_and_delivery_failure_preserve_exact_original_second_menu(self):
        game = self.game('fail'); self.play(game, CARD); self.pick(game, FIRST_PARTS[0])
        saved = game.snapshot(); pending = game.state.pending_choice
        with self.assertRaises(IllegalAction):
            game.apply(SelectChoice(2, pending.id, (pending.options[0].id,)))
        self.assertEqual(game.snapshot(), saved)
        with self.assertRaises(ResolutionError):
            self.pick(game, BOAR)
        self.assertEqual(game.snapshot(), saved)

    def test_two_paid_sources_each_keep_their_own_acceptance_and_one_creation(self):
        game = self.game(hand=(CARD, CARD))
        sources = []
        for first in FIRST_PARTS:
            sources.append(self.play(game, CARD)); self.pick(game, first); self.pick(game, BOAR)
        accepted = [event for event in game.events if event.kind == 'craft_offer_accepted']
        self.assertEqual([event.source_id for event in accepted], [sources[0]]*2+[sources[1]]*2)
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertEqual(len([i for i in game.state.players[1].hand
            if game.state.entities[i].card_id.startswith(PREFIX)]), 2)
