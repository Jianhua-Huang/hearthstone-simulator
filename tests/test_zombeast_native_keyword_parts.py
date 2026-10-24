"""Real two-stage sources, native keyword donors and the current Core deathrattle."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import CARD as QUEST, TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_keyword_parts import (
    PARTS, CORE_PORCUPINE, BASE_PORCUPINE, load_batch, register_zombeast_native_keyword_parts)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, PlayerSetup, Registry, ResolutionError, Scenario,
    TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, PREFIX, recipe_from_id
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (Buff, Damage, Destroy, InvokeBehavior,
    ReturnToHand, Silence)
from hs_sim.engine.model import ChoicePurpose
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k507.'
HERO, POWER, UNIT, KILL, HURT, HIT, BUFF, QUIET, BOUNCE, COPY, WATCH = (
    P+x for x in ('hero', 'power', 'unit', 'kill', 'hurt', 'hit', 'buff', 'quiet', 'bounce', 'copy', 'watch'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None)
CONTEXT = GenerationContext('explicit-k507-native-donor-fixture', 'experimental')
SECONDS = tuple(cid for cid in PARTS if cid != CORE_PORCUPINE)
UNREVIEWED = 'CORE_CS2_120'


@lru_cache(None)
def originals():
    return build_registry()


def part_registry(changed=None):
    source = originals()
    registry = Registry(P+'parts')
    body = source.card(BASE_PORCUPINE).deathrattle
    registry.register_behavior(body, source.behavior(body))
    for cid in (BASE_PORCUPINE, *PARTS):
        card = source.card(cid)
        registry.register_card(changed(card) if changed else card)
    registry.register_crafted_minion_part(BASE_PORCUPINE)
    return registry


@lru_cache(None)
def fixture(mode='BE_193|normal', role='writer'):
    part, variant = mode.split('|')
    registry = part_registry()
    registry._version = P+mode
    register_zombeast_native_keyword_parts(registry)
    source = originals()
    for body in (TAMER_BODY, 'cards.storm_gates.progress', 'cards.storm_gates.reward'):
        registry.register_behavior(body, source.behavior(body))
    for cid in (TEMPLATE, TAMER, QUEST, UNREVIEWED):
        registry.register_card(source.card(cid))
    registry.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    registry.register_behavior(P+'noop', lambda c: ())
    registry.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    registry.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2,
        on_use=P+'noop', metadata=META))
    registry.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, cost=1,
        attack=1, health=30, metadata=META))
    scripts = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 20, c.source_id),),
        HIT: lambda c: (Damage(c.target_id, 1, c.source_id),),
        BUFF: lambda c: (Buff(c.target_id, 2, 0, c.source_id),),
        QUIET: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        COPY: lambda c: (CopyCard(CardReference.capture(c.state.entities[c.target_id]),
            c.player_id, mode='base', source_id=c.source_id),),
    }
    for cid, body in scripts.items():
        registry.register_behavior(cid, body)
        targeting = None if cid == HURT else TargetSpec(TargetMode.REQUIRED,
            zones=(Zone.HAND,) if cid == COPY else (Zone.BOARD,), kinds=(CardType.MINION,))
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=targeting, metadata=META))
    for cid in (*PARTS, BASE_PORCUPINE, UNREVIEWED):
        registry.register_pool_card(PoolCard.from_definition(registry.card(cid)))
    second = (part, UNREVIEWED) if variant == 'unreviewed' else (part,)
    for pool, ids in ((FIRST, (CORE_PORCUPINE,)), (SECOND, second)):
        registry.register_pool(PoolDefinition(pool, 'explicit-native-fixture-v1',
            CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in ids),
            complete=not(variant == 'incomplete' and pool == SECOND)))
    def fail(c):
        raise ResolutionError('K507 intentional ordinary delivery failure')
    registry.register_behavior(P+'fail', fail)
    def watch(c):
        entity = c.state.entities.get(c.event.target_id)
        if variant == 'fail' and entity is not None and entity.card_id.startswith(PREFIX):
            return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        return ()
    registry.register_behavior(P+'watch', watch)
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
        metadata=META, triggers=(TriggerSpec('card_added_to_hand', P+'watch'),)))
    registry.validate()
    return registry


class ZombeastNativeKeywordPartsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, part='BE_193', player=1, source=TAMER, hand=None, own=(), enemy=(),
            active=None, enemy_hand=(), variant='normal'):
        self.mode = part+'|'+variant
        if hand is None:
            hand = (source,)
        if variant == 'fail':
            enemy = (*enemy, WATCH)
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else enemy_hand, board=own if p == player else enemy,
            deck=(UNIT,)*8, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=active or player, seed=507,
            generation_context=CONTEXT), fixture(self.mode))

    def pick(self, game, cid):
        option = next(option for option in game._frame.options
            if any(type(effect) is ResolveCraft and effect.card_id == cid for effect in option.effects))
        self.choose(game, option.id)

    def craft(self, game, part, player=1):
        self.play(game, TAMER, player=player)
        self.pick(game, CORE_PORCUPINE)
        self.pick(game, part)
        return self.creation(game, player).id

    def creation(self, game, player=1):
        return next(game.state.entities[i] for i in game.state.players[player].hand
            if game.state.entities[i].card_id.startswith(PREFIX))

    def health(self, game, player):
        return game.state.entities[game.state.players[player].hero_id].health

    def test_complete_source_all_twenty_eight_faces_and_fourteen_actual_donation_declarations(self):
        data = load_batch()
        rows = {item['record']['id']: item['record'] for item in data['existing_dependencies']}
        self.assertEqual(len(rows), 15)
        self.assertEqual(len(data['official_observations']), 28)
        self.assertEqual(set(PARTS), {face['card_id'] for face in data['official_observations']})
        for face in data['official_observations']:
            batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        registry = originals()
        self.assertTrue(set(PARTS) <= set(registry.crafted_minion_parts))
        self.assertEqual(len(registry.crafted_minion_parts), 22)
        self.assertEqual(registry.card(CORE_PORCUPINE).metadata.deck_identity, BASE_PORCUPINE)
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in registry.pools))

    def test_each_plain_part_passes_actual_paid_tamer_both_choices_and_one_native_minion_play(self):
        for index, part in enumerate(SECONDS):
            player = 1+index%2
            with self.subTest(part=part, player=player):
                game = self.game(part, player)
                eid = self.craft(game, part, player)
                entity = game.state.entities[eid]
                face = game.registry.card(entity.card_id)
                first, second = (game.registry.card(cid) for cid in (CORE_PORCUPINE, part))
                self.assertEqual((face.cost, face.attack, face.health),
                    (first.cost+second.cost, first.attack+second.attack, first.health+second.health))
                self.assertEqual(set(face.keywords), set(second.keywords))
                self.assertEqual(recipe_from_id(face.id).parts, (CORE_PORCUPINE, part))
                self.assertEqual(quote_cost(game.state, game.registry, entity).amount, face.cost)
                self.play(game, face.id, player=player)
                entity = game.state.entities[eid]
                self.assertEqual((entity.attack, entity.health, entity.components),
                    (face.attack, face.health, (CORE_PORCUPINE, part)))
                self.assertEqual(sum(a.kind == 'deathrattle' for a in entity.abilities), 1)
                self.assertEqual(game.state.players[player].mana, 29-face.cost)

    def test_real_standard_sidequest_reward_uses_new_core_donor_and_keeps_original_minus_three(self):
        game = self.game('TIME_053', source=QUEST, hand=(QUEST, 'LOOT_258', 'LOOT_258', 'LOOT_258'))
        self.play(game, QUEST)
        for _ in range(3):
            self.play(game, 'LOOT_258')
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.CRAFT)
        self.pick(game, CORE_PORCUPINE)
        self.pick(game, 'TIME_053')
        entity = self.creation(game)
        self.assertEqual((game.registry.card(entity.card_id).cost,
            quote_cost(game.state, game.registry, entity).amount), (6, 3))
        self.play(game, entity.card_id)
        self.assertEqual(game.state.players[1].mana, 23)

    def test_core_native_deathrattle_reads_summed_current_attack_and_real_death_record(self):
        game = self.game('TIME_053', hand=(TAMER, BUFF, KILL))
        eid = self.craft(game, 'TIME_053')
        self.play(game, game.state.entities[eid].card_id)
        self.play(game, BUFF, eid)
        self.assertEqual(game.state.entities[eid].attack, 11)
        self.play(game, KILL, eid)
        self.assertEqual(self.health(game, 2), 89)
        self.assertEqual(game.state.entities[eid].zone, Zone.GRAVEYARD)
        self.portable(game)

    def test_lifesteal_is_inherited_by_original_native_porcupine_deathrattle_damage(self):
        game = self.game('ICC_905', hand=(HURT, TAMER, KILL))
        self.play(game, HURT)
        eid = self.craft(game, 'ICC_905')
        self.play(game, game.state.entities[eid].card_id)
        self.play(game, KILL, eid)
        self.assertEqual((self.health(game, 1), self.health(game, 2)), (86, 94))

    def test_rush_and_poisonous_use_normal_attack_legality_and_actual_damage_death(self):
        game = self.game('GIL_562', enemy=(UNIT,))
        eid = self.craft(game, 'GIL_562')
        self.play(game, game.state.entities[eid].card_id)
        saved = game.snapshot()
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, game.state.players[2].hero_id))
        self.assertEqual(game.snapshot(), saved)
        target = self.entity(game, UNIT, player=2, zone='board').id
        game.apply(Attack(1, eid, target))
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.entities[eid].zone, Zone.BOARD)

    def test_windfury_allows_two_real_attacks_after_summoning_sickness_and_rejects_third(self):
        game = self.game('CS2_169')
        eid = self.craft(game, 'CS2_169')
        self.play(game, game.state.entities[eid].card_id)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        for _ in range(2):
            game.apply(Attack(1, eid, game.state.players[2].hero_id))
        self.assertEqual(self.health(game, 2), 94)
        saved = game.snapshot()
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, eid, game.state.players[2].hero_id))
        self.assertEqual(game.snapshot(), saved)

    def test_stealth_blocks_enemy_target_until_the_crafted_body_actually_attacks(self):
        cid = CraftedMinionRecipe(TEMPLATE, CORE_PORCUPINE, 'CORE_EX1_028').card_id
        game = self.game('CORE_EX1_028', own=(cid,), active=2, enemy_hand=(HIT,))
        eid = self.entity(game, cid, zone='board').id
        saved = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(game, HIT, eid, player=2)
        self.assertEqual(game.snapshot(), saved)
        game.apply(EndTurn(2)); game.apply(Attack(1, eid, game.state.players[2].hero_id))
        game.apply(EndTurn(1)); self.play(game, HIT, eid, player=2)
        self.assertEqual(game.state.entities[eid].health, 8)

    def test_taunt_donation_blocks_hero_attack_and_accepts_attack_into_the_original_body(self):
        cid = CraftedMinionRecipe(TEMPLATE, CORE_PORCUPINE, 'CS2_125').card_id
        game = self.game('CS2_125', own=(cid,), enemy=(UNIT,), active=2)
        eid = self.entity(game, cid, zone='board').id
        attacker = self.entity(game, UNIT, player=2, zone='board').id
        saved = game.snapshot()
        with self.assertRaises(IllegalAction):
            game.apply(Attack(2, attacker, game.state.players[1].hero_id))
        self.assertEqual(game.snapshot(), saved)
        game.apply(Attack(2, attacker, eid))
        self.assertEqual((self.health(game, 1), game.state.entities[eid].health), (100, 6))

    def test_all_type_base_copy_silence_and_bounce_keep_recipe_and_one_native_deathrattle(self):
        game = self.game('NX2_050', hand=(TAMER, COPY, BUFF, QUIET, BOUNCE))
        eid = self.craft(game, 'NX2_050')
        cid = game.state.entities[eid].card_id
        self.assertEqual(game.registry.card(cid).metadata.tribes, ('all',))
        self.play(game, COPY, eid)
        self.play(game, cid); self.play(game, cid)
        copies = [i for i in game.state.players[1].board if game.state.entities[i].card_id == cid]
        self.assertEqual(len(copies), 2)
        self.play(game, BUFF, eid); self.play(game, QUIET, eid)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (3, 7))
        self.assertFalse(any(a.kind == 'deathrattle' for a in game.state.entities[eid].abilities))
        self.play(game, BOUNCE, eid); self.play(game, cid)
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].health), (3, 7))
        self.assertEqual(sum(a.kind == 'deathrattle' for a in game.state.entities[eid].abilities), 1)
        self.assertEqual(game.state.entities[eid].components, (CORE_PORCUPINE, 'NX2_050'))
        self.portable(game)

    def test_two_actual_menus_restore_clone_replay_and_hide_other_players_options(self):
        game = self.game('CORE_GIL_558')
        self.play(game, TAMER)
        self.assertNotIn(CORE_PORCUPINE, json.dumps(game.for_player(2).observe()))
        restored = self.portable(game)
        self.pick(game, CORE_PORCUPINE); self.pick(restored, CORE_PORCUPINE)
        self.assertEqual(game.snapshot(), restored.snapshot())
        restored = self.portable(game)
        self.pick(game, 'CORE_GIL_558'); self.pick(restored, 'CORE_GIL_558')
        self.assertEqual(game.snapshot(), restored.snapshot())
        opponent = next(player for player in game.for_player(2).observe()['observation']['players']
            if player['id'] == 1)
        self.assertTrue(all(card['card_id'] is None for card in opponent['hand']))

    def test_unknown_or_incomplete_host_content_is_not_silently_dropped_before_first_menu(self):
        for variant in ('unreviewed', 'incomplete'):
            with self.subTest(variant=variant):
                game = self.game(variant=variant)
                saved = game.snapshot()
                with self.assertRaises(ResolutionError) as caught:
                    self.play(game, TAMER)
                self.assertIsInstance(caught.exception.__cause__, UnsupportedDefinitionError)
                self.assertEqual(game.snapshot(), saved)

    def test_failed_ordinary_delivery_rolls_back_the_original_second_choice_and_rng(self):
        game = self.game(variant='fail')
        self.play(game, TAMER); self.pick(game, CORE_PORCUPINE)
        saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.pick(game, 'BE_193')
        self.assertEqual(game.snapshot(), saved)
        self.portable(game)

    def test_registration_prevalidates_every_complete_face_without_partial_capability_install(self):
        for cid, field in (('BE_193', 'attack'), (CORE_PORCUPINE, 'attack'), ('BE_193', 'extra_text')):
            with self.subTest(cid=cid, field=field):
                def changed(card):
                    if card.id != cid:
                        return card
                    if field == 'attack':
                        return replace(card, attack=card.attack+1)
                    return replace(card, deathrattle=originals().card(BASE_PORCUPINE).deathrattle)
                registry = part_registry(changed)
                before = set(registry.crafted_minion_parts)
                with self.assertRaises(TargetValidationError):
                    register_zombeast_native_keyword_parts(registry)
                self.assertEqual(set(registry.crafted_minion_parts), before)
        registry = part_registry()
        register_zombeast_native_keyword_parts(registry)
        with self.assertRaises(TargetValidationError):
            register_zombeast_native_keyword_parts(registry)
