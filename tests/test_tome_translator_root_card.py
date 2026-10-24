"""Real unresolved Tome Translator, its four bodies and ordinary held lifecycle."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards import tome_translator_cards as decoded
from hs_sim.cards.tome_translator_root_card import ROOT, BODY, load_batch, register_tome_translator_root_card
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    PlayerSetup, Rarity, Registry, ResolutionError, Scenario, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, Draw, InvokeBehavior, RequestChoice, ReturnToHand
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.zones import CardReference
from tools import card_batch as batch

P = 'k500.'
HERO, POWER, UNIT, DONOR, SPELL, GIVE, BUFF, RETURN, WATCH = (
    P+name for name in ('hero', 'power', 'unit', 'donor', 'spell', 'give', 'buff', 'return', 'watch'))
META = CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=(), factions=(), subtypes=())
NEUTRAL = replace(META, collectible=True, classes=(CardClass.NEUTRAL,), rarity=Rarity.COMMON)
CONTEXT = GenerationContext('complete-k500-experimental-deathrattle-domain', 'experimental')
SUMMON, DISCOUNT, SPLIT, GAIN = decoded.FORMS


@lru_cache(None)
def original_source():
    return build_registry()


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    original = original_source()
    registry = Registry(P+mode)
    # Copy immutable actual definitions and the original pure body callbacks,
    # rather than reimplementing the four bodies in this fixture.
    for cid in decoded.FORMS:
        registry.register_behavior(decoded.PREFIX+cid, original.behavior(decoded.PREFIX+cid))
        registry.register_card(original.card(cid))
        registry.register_pool_card(PoolCard.from_definition(original.card(cid)))
    register_tome_translator_root_card(registry)
    registry.register_behavior(P+'empty', lambda c: ())
    registry.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=50, metadata=META))
    registry.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, on_use=P+'empty', metadata=META))
    registry.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=3, health=12, metadata=META))
    registry.register_card(CardDefinition(DONOR, DONOR, CardType.MINION, cost=2, attack=1, health=2,
        deathrattle=P+'empty', metadata=NEUTRAL))
    registry.register_pool_card(PoolCard.from_definition(registry.card(DONOR)))
    member = DONOR
    if mode == 'unknown_pool':
        member = P+'unknown'
        registry.register_pool_card(replace(registry.pool_card(DONOR), card_id=member))
    registry.register_pool(PoolDefinition(decoded.POOL_ID, 'explicit-experimental-v1', CONTEXT.target_id,
        CONTEXT.mode, (PoolMember(member),), complete=True))

    def buff(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == ROOT)
        return (BuffStoredCard(CardReference.capture(target), 2, 3, c.source_id, cost=CostSpec(delta=-1)),)

    def returned(c):
        target = next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id in (ROOT, *decoded.FORMS))
        return (ReturnToHand(target),)

    operations = {SPELL: lambda c: (Draw(c.player_id, 1),), GIVE: lambda c: (AddToHand(c.player_id, ROOT, c.source_id),),
        BUFF: buff, RETURN: returned}
    for cid, body in operations.items():
        registry.register_behavior(cid, body)
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=5 if cid == SPELL else 0,
            on_play=cid, metadata=META))

    def fail(c):
        raise ResolutionError('Tome reveal fixture failure')

    def watch(c):
        event = c.event
        random = event.kind == 'random_choice' and dict(event.data).get('producer') == 'effect_branch'
        complete = event.kind == 'hand_progressed' and event.amount == 2
        if mode == 'fail_reveal' and random:
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        if (mode == 'wait_body' and random) or (mode == 'wait_progress' and complete):
            return (RequestChoice(event.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        return ()

    registry.register_behavior(P+'fail', fail)
    registry.register_behavior(P+'watch', watch)
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('random_choice', P+'watch'), TriggerSpec('hand_progressed', P+'watch'))))
    registry.validate()
    return registry


class TomeTranslatorRootTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, mode='normal', player=1, seed=6, hand=None, board=True):
        self.mode = mode
        hand = (ROOT, SPELL) if hand is None else hand
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else (), deck=(UNIT,)*8,
            board=((WATCH,) if mode in ('wait_body', 'wait_progress', 'fail_reveal') else (UNIT,))
                if p == player and board else ((UNIT,) if p != player and board else ()),
            mana=10, max_mana=10) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=seed,
            generation_context=CONTEXT), fixture(mode))

    def for_body(self, face, mode='normal', player=1):
        order = load_batch()['random_form_order']
        for seed in range(40):
            game = self.game(mode, player, seed)
            probe = Random(); probe.setstate(game._rng.getstate())
            if probe.choice(order) == face:
                return game
        self.fail('Actual finite random source did not cover its four explicit outcomes')

    def own_start(self, game):
        for _ in range(2):
            game.apply(EndTurn(game.state.active_player))

    def branch_events(self, game):
        return [event for event in game.events if dict(event.data).get('producer') == 'effect_branch']

    def test_full_original_root_faces_actual_four_children_and_registered_definition(self):
        data = load_batch()
        self.assertEqual(len(data['official_observations']), 2)
        self.assertEqual(set(data['random_form_order']), set(decoded.FORMS))
        for face in data['official_observations']:
            batch.check_face(data['cards'][0]['record'], face['face'], face['locale'], {'@': ''})
        registry = original_source(); card = registry.card(ROOT)
        self.assertEqual((card.cost, card.attack, card.health, card.battlecry), (4, 5, 4, BODY))
        self.assertEqual((card.hand_progress.goal, card.hand_progress.event, card.hand_progress.repeat),
            (2, 'turn_started', False))
        for row in data['existing_dependencies']:
            self.assertEqual(batch.canonical(asdict(registry.card(row['record']['id']))),
                row['definition_sha256'])

    def test_unresolved_real_paid_battlecry_each_actual_body_and_both_players(self):
        for player in (1, 2):
            for face in decoded.FORMS:
                with self.subTest(player=player, face=face):
                    game = self.for_body(face, player=player)
                    before_health = sum(game.state.entities[i].health for p in (1, 2)
                        for i in game.state.players[p].board)
                    source = self.play(game, ROOT, player=player)
                    self.assertEqual(game.state.players[player].mana, 6)
                    self.assertEqual(dict(self.branch_events(game)[0].data)['selected'], face)
                    self.assertEqual(len(self.branch_events(game)), 1)
                    if face == SUMMON:
                        self.assertEqual(sum(game.state.entities[i].card_id == DONOR
                            for i in game.state.players[player].board), 2)
                    elif face == DISCOUNT:
                        spell = self.entity(game, SPELL, player)
                        self.assertEqual(quote_cost(game.state, game.registry, spell).amount, 1)
                        self.play(game, SPELL, player=player)
                        self.assertEqual(game.state.players[player].mana, 5)
                    elif face == SPLIT:
                        self.assertEqual(sum(game.state.entities[i].health for p in (1, 2)
                            for i in game.state.players[p].board if i != source), before_health-6)
                        self.assertEqual(game.state.entities[source].health, 4)
                    else:
                        entity = game.state.entities[source]
                        self.assertEqual((entity.attack, entity.health), (8, 16))

    def test_only_two_owner_turn_starts_reveal_same_physical_held_card_once(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player); entity = self.entity(game, ROOT, player)
                entry = entity.hand_entry_id
                game.apply(EndTurn(player))
                self.assertEqual(progress_ability(game.state.entities[entity.id]).progress_value, 0)
                game.apply(EndTurn(3-player))
                self.assertEqual(progress_ability(game.state.entities[entity.id]).progress_value, 1)
                self.assertEqual(game.state.entities[entity.id].card_id, ROOT)
                self.own_start(game)
                final = game.state.entities[entity.id]
                self.assertIn(final.card_id, decoded.FORMS)
                self.assertEqual((final.zone, final.controller, final.hand_entry_id), (Zone.HAND, player, entry))
                self.assertEqual(len(self.branch_events(game)), 1)
                self.own_start(game)
                self.assertEqual(game.state.entities[entity.id].card_id, final.card_id)
                self.assertEqual(len(self.branch_events(game)), 1)

    def test_revealed_form_paid_battlecry_reuses_fixed_body_without_another_root_sample(self):
        game = self.game(); source = self.entity(game, ROOT).id
        self.own_start(game); self.own_start(game)
        self.assertIn(game.state.entities[source].card_id, decoded.FORMS)
        before = len(self.branch_events(game))
        self.play(game, game.state.entities[source].card_id)
        self.assertEqual(len(self.branch_events(game)), before)
        self.assertEqual(game.state.entities[source].zone, Zone.BOARD)

    def test_upgrade_keeps_current_hand_buffs_cost_and_original_entry(self):
        game = self.game(hand=(ROOT, BUFF)); entity = self.entity(game, ROOT); entry = entity.hand_entry_id
        self.play(game, BUFF); self.own_start(game); self.own_start(game)
        entity = game.state.entities[entity.id]
        self.assertEqual((entity.attack, entity.health, quote_cost(game.state, game.registry, entity).amount), (7, 7, 3))
        self.assertEqual(entity.hand_entry_id, entry)

    def test_newly_generated_root_starts_at_zero_and_does_not_borrow_past_turn_events(self):
        game = self.game(hand=(GIVE,)); self.own_start(game)
        self.play(game, GIVE); entity = self.entity(game, ROOT)
        self.assertEqual(progress_ability(entity).progress_value, 0)
        self.own_start(game)
        self.assertEqual(progress_ability(game.state.entities[entity.id]).progress_value, 1)
        self.own_start(game)
        self.assertIn(game.state.entities[entity.id].card_id, decoded.FORMS)

    def test_unresolved_board_source_stops_held_clock_and_return_uses_normal_new_hand_lifecycle(self):
        game = self.for_body(DISCOUNT); source = self.play(game, ROOT)
        self.own_start(game); self.own_start(game)
        self.assertEqual(game.state.entities[source].card_id, ROOT)
        # The fixture's zero-cost return spell is given through its normal setup
        # in a fresh scenario so no test state is mutated between real actions.
        game = self.game(hand=(ROOT, RETURN)); source = self.play(game, ROOT)
        self.play(game, RETURN)
        self.assertEqual(progress_ability(game.state.entities[source]).progress_value, 0)
        self.own_start(game); self.own_start(game)
        self.assertIn(game.state.entities[source].card_id, decoded.FORMS)

    def test_selected_body_wait_restore_clone_replay_keeps_original_branch(self):
        game = self.for_body(DISCOUNT, 'wait_body'); self.play(game, ROOT)
        selected = dict(self.branch_events(game)[0].data)['selected']
        for player in (1, 2):
            view = json.dumps(game.for_player(player).observe())
            for cid in decoded.FORMS:
                self.assertNotIn(cid, view)
        restored = self.portable(game)
        self.choose(game); self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual([dict(event.data)['selected'] for event in self.branch_events(game)], [selected])
        self.assertEqual(quote_cost(game.state, game.registry, self.entity(game, SPELL)).amount, 1)

    def test_completed_progress_wait_restores_before_original_reveal_sampling(self):
        game = self.game('wait_progress'); source = self.entity(game, ROOT).id
        self.own_start(game)
        game.apply(EndTurn(game.state.active_player)); game.apply(EndTurn(game.state.active_player))
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.entities[source].card_id, ROOT)
        self.assertEqual(len(self.branch_events(game)), 0)
        restored = self.portable(game)
        self.choose(game); self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertIn(game.state.entities[source].card_id, decoded.FORMS)

    def test_reveal_failure_rolls_back_owner_turn_counter_rng_and_start_draw(self):
        game = self.game('fail_reveal'); self.own_start(game)
        game.apply(EndTurn(game.state.active_player)); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            game.apply(EndTurn(game.state.active_player))
        self.assertEqual(game.snapshot(), saved)

    def test_selected_actual_summon_keeps_unknown_eligible_pool_error_and_payment_rollback(self):
        game = self.for_body(SUMMON, 'unknown_pool'); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, ROOT)
        self.assertEqual(game.snapshot(), saved)
