"""The real current-Attack Battlecry through ordinary and crafted paid entry."""
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_zombeast_native_kindred_part import donor_registry, originals
from hs_sim.cards.dispatch_kodo_card import CARD, BODY, COLLECTIBLE_ROOTS, load_batch, register_dispatch_kodo_card
from hs_sim.cards.past_scourge_tamer_card import CARD as TAMER, BODY as TAMER_BODY
from hs_sim.cards.storm_gates_card import TEMPLATE, FIRST, SECOND
from hs_sim.cards.zombeast_native_kindred_part import register_zombeast_native_kindred_part
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    DamageKind, EndTurn, Game, IllegalAction, Keyword, PlayerSetup, ResolutionError,
    Scenario, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.battlecries import battlecry_record
from hs_sim.engine.crafted_faces import CraftedMinionRecipe, PREFIX
from hs_sim.engine.crafted_offers import ResolveCraft
from hs_sim.engine.effects import (Buff, ChoiceOption, CopyMinion, Damage,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

P = 'k514.'
HERO, POWER, UNIT, WATCH, HAND_BUFF, HAND_ZERO, COPY, SUMMON, HURT, ARMOR, SPELLPOWER, HIDDEN, DORMANT = (
    P+x for x in ('hero', 'power', 'unit', 'watch', 'hand-buff', 'hand-zero', 'copy',
        'summon', 'hurt', 'armor', 'spellpower', 'hidden', 'dormant'))
DINO, MOLE, CHALLENGER, LIFE = 'DINO_435', 'LOOT_258', 'TLC_251', 'CORE_GIL_558'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
CONTEXT = GenerationContext('explicit-k514-real-kodo-fixture', 'experimental')


@lru_cache(None)
def fixture(mode='normal|'+DINO, role='writer'):
    variant, first = mode.split('|'); source = originals(); r = donor_registry(); r._version = P+mode
    register_zombeast_native_kindred_part(r); register_dispatch_kodo_card(r)
    for key in (TAMER_BODY, source.card(CHALLENGER).battlecry):
        r.register_behavior(key, source.behavior(key))
    for cid in (TAMER, TEMPLATE, CHALLENGER): r.register_card(source.card(cid))
    r.register_player_effect(source.player_effect('cards.kindred_components.next'))
    r.register_crafted_minion_blueprint(source.crafted_minion_blueprints[TEMPLATE])
    for cid in (DINO, LIFE):
        if cid not in r.pool_cards: r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for pool, cid in ((FIRST, first), (SECOND, CARD)):
        r.register_pool(PoolDefinition(pool, 'explicit-real-kodo-v1', CONTEXT.target_id,
            CONTEXT.mode, (PoolMember(cid),), complete=True))
    r.register_behavior(P+'noop', lambda c: ())
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=100, metadata=META))
    r.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2, on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=40, metadata=META))
    r.register_card(CardDefinition(SPELLPOWER, SPELLPOWER, CardType.MINION, health=4, spell_damage=5, metadata=META))
    r.register_card(CardDefinition(HIDDEN, HIDDEN, CardType.MINION, health=40, keywords=(Keyword.STEALTH,), metadata=META))
    r.register_card(CardDefinition(DORMANT, DORMANT, CardType.MINION, health=40, dormant_turns=1, metadata=META))
    scripts = {
        HAND_BUFF: lambda c: (BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]), 3, 4, c.source_id),),
        HAND_ZERO: lambda c: (BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]), -2, 0, c.source_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id),),
        SUMMON: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(CARD),), SummonCause.capture(c)),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 40, c.source_id, DamageKind.EFFECT),),
        ARMOR: lambda c: (GainArmor(3-c.player_id, 3),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        target = None if cid in (SUMMON, HURT, ARMOR) else TargetSpec(TargetMode.REQUIRED,
            kinds=(CardType.MINION,), zones=(Zone.HAND,) if cid in (HAND_BUFF, HAND_ZERO) else (Zone.BOARD,))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, targeting=target, metadata=META))
    def fail(c): raise ResolutionError('K514 intentional late native damage failure')
    def watch(c):
        if c.event.kind == 'battlecry_started' and variant == 'wait':
            row = battlecry_record(c.state, dict(c.event.data)['battlecry_id'])
            if row.payload.card_id != CARD: return ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('continue', 'Continue'),
                ChoiceOption('grow', 'Grow live source', (Buff(row.source_id, 7, 0, c.source_id),)),
                ChoiceOption('bounce', 'Return live source', (ReturnToHand(row.source_id),)),
            ), c.source_id),)
        if c.event.kind == 'minion_summoned' and variant == 'pretarget':
            target = c.state.entities.get(c.event.target_id)
            copies = [i for i in c.state.players[c.player_id].board
                if c.state.entities[i].card_id.startswith(PREFIX)]
            enemy = c.state.players[3-c.player_id].board
            if target is not None and target.card_id.startswith(PREFIX) and len(copies) > 1 and enemy:
                return (ReturnToHand(enemy[0]),)
        if c.event.kind == 'damage_dealt' and variant == 'latefail':
            actor = c.state.entities.get(c.event.source_id)
            if actor is not None and (actor.card_id == CARD or actor.card_id.startswith(PREFIX)):
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
        return ()
    r.register_behavior(P+'fail', fail); r.register_behavior(P+'watch', watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=40, metadata=META,
        triggers=tuple(TriggerSpec(kind, P+'watch') for kind in ('battlecry_started', 'minion_summoned', 'damage_dealt'))))
    r.validate(); return r


class DispatchKodoTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def recipe(self, first=DINO): return CraftedMinionRecipe(TEMPLATE, first, CARD).card_id

    def game(self, *, player=1, hand=(CARD,), own=(), enemy=(UNIT,), opposing_hand=(), first=DINO, variant='normal'):
        self.mode = variant+'|'+first
        if variant != 'normal': own = (*own, WATCH)
        setups = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=hand if p == player else opposing_hand, board=own if p == player else enemy,
            deck=(UNIT,)*12, mana=30, max_mana=30, mana_cap=30) for p in (1, 2))
        return Game.from_scenario(Scenario(setups, active_player=player, seed=514,
            generation_context=CONTEXT), fixture(self.mode))

    def cycle(self, game, player=1): game.apply(EndTurn(player)); game.apply(EndTurn(3-player))

    def pick(self, game, cid):
        option = next(o for o in game._frame.options if any(
            type(e) is ResolveCraft and e.card_id == cid for e in o.effects))
        self.choose(game, option.id)

    def craft(self, game, first=DINO, player=1):
        self.play(game, TAMER, player=player); self.pick(game, first); self.pick(game, CARD)
        return self.entity(game, self.recipe(first), player).id

    def qualified(self, *, hand=(), variant='normal'):
        game = self.game(hand=(MOLE, TAMER, *hand), variant=variant)
        self.play(game, MOLE); self.cycle(game); return game

    def copies(self, game, first=DINO):
        return [game.state.entities[i] for i in game.state.players[1].board
            if game.state.entities[i].card_id == self.recipe(first)]

    def kodo_rows(self, game): return [r for r in game.state.battlecry_history if r.payload.card_id == CARD]

    def test_full_original_faces_and_historical_context_do_not_declare_standard_root_or_complete_pool(self):
        data = load_batch(); raw = data['cards'][0]['record']
        for face in data['official_observations']: batch.check_face(raw, face['face'], face['locale'])
        card = originals().card(CARD)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.tribes), (4, 2, 4, ('beast',)))
        self.assertEqual(card.battlecry, BODY); self.assertIsNone(card.on_play)
        self.assertIn(CARD, originals().crafted_minion_parts); self.assertEqual(COLLECTIBLE_ROOTS, ())
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        self.assertTrue(data['historical_composition_observation']['reported_battlecry_failure'])
        self.assertFalse(any(key[0] in (FIRST, SECOND) for key in originals().pools))

    def test_both_players_pay_four_and_can_damage_friendly_minion_or_either_hero(self):
        for player in (1, 2):
            for kind in ('friendly-minion', 'friendly-hero', 'enemy-hero'):
                with self.subTest(player=player, target=kind):
                    game = self.game(player=player, own=(UNIT,))
                    target = (game.state.players[player].board[0] if kind == 'friendly-minion' else
                        game.state.players[player if kind == 'friendly-hero' else 3-player].hero_id)
                    before = game.state.entities[target].health
                    eid = self.play(game, CARD, target, player)
                    self.assertEqual(game.state.entities[target].health, before-2)
                    self.assertEqual(game.state.players[player].mana, 26)
                    self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].max_health), (2, 4))
                    self.assertEqual(len(self.kodo_rows(game)), 1)

    def test_current_hand_attack_ignores_spell_power_and_uses_ordinary_hero_armor(self):
        game = self.game(hand=(CARD, HAND_BUFF, ARMOR), own=(SPELLPOWER,)); eid = self.entity(game, CARD).id
        self.play(game, HAND_BUFF, eid); self.play(game, ARMOR)
        hero = game.state.players[2].hero_id; self.play(game, CARD, hero)
        self.assertEqual((game.state.entities[hero].health, game.state.entities[hero].armor), (98, 0))
        self.assertEqual((game.state.entities[eid].attack, game.state.entities[eid].max_health), (5, 8))

    def test_zero_current_attack_does_not_fall_back_to_printed_damage(self):
        game = self.game(hand=(CARD, HAND_ZERO)); eid = self.entity(game, CARD).id
        self.play(game, HAND_ZERO, eid); self.assertEqual(game.state.entities[eid].attack, 0)
        hero = game.state.players[2].hero_id; self.play(game, CARD, hero)
        self.assertEqual(game.state.entities[hero].health, 100); self.assertTrue(self.kodo_rows(game)[0].completed)

    def test_missing_hand_stealthed_and_dormant_targets_reject_before_payment(self):
        game = self.game(enemy=(HIDDEN, DORMANT), opposing_hand=(UNIT,)); saved = game.snapshot()
        targets = (None, self.entity(game, CARD).id, *game.state.players[2].board,
            self.entity(game, UNIT, 2).id)
        for target in targets:
            with self.subTest(target=target), self.assertRaises(IllegalAction): self.play(game, CARD, target)
            self.assertEqual(game.snapshot(), saved)

    def test_direct_current_copy_and_named_summon_do_not_trigger_battlecry(self):
        game = self.game(hand=(CARD, COPY, SUMMON)); hero = game.state.players[2].hero_id
        eid = self.play(game, CARD, hero); self.play(game, COPY, eid); self.play(game, SUMMON)
        self.assertEqual(len(game.state.players[1].board), 3)
        self.assertEqual(game.state.entities[hero].health, 98); self.assertEqual(len(self.kodo_rows(game)), 1)

    def test_real_reported_native_pair_copies_current_body_and_only_original_battlecry_deals_damage(self):
        game = self.qualified(); self.craft(game); face = game.registry.card(self.recipe())
        self.assertEqual((face.cost, face.attack, face.health, face.metadata.tribes), (9, 5, 8, ('all',)))
        hero = game.state.players[2].hero_id; self.play(game, self.recipe(), hero)
        self.assertEqual(len(self.copies(game)), 2); self.assertEqual(game.state.entities[hero].health, 95)
        row, = self.kodo_rows(game); self.assertEqual((row.card_id, row.payload.card_id), (self.recipe(), CARD))
        self.assertEqual(game.state.players[1].mana, 20)

    def test_next_kindred_repeats_only_copy_component_and_keeps_one_targeted_battlecry(self):
        game = self.qualified(hand=(CHALLENGER,)); self.play(game, CHALLENGER); self.craft(game)
        hero = game.state.players[2].hero_id; self.play(game, self.recipe(), hero)
        self.assertEqual(len(self.copies(game)), 3); self.assertEqual(len(self.kodo_rows(game)), 1)
        self.assertEqual(game.state.entities[hero].health, 95); self.assertEqual(game.state.players[1].mana, 17)
        self.assertFalse(game.state.players[1].player_effects)

    def test_native_lifesteal_damage_uses_complete_current_source_not_printed_kodo(self):
        game = self.game(hand=(TAMER, HURT), first=LIFE); self.play(game, HURT); self.craft(game, LIFE)
        hero = game.state.players[2].hero_id; self.play(game, self.recipe(LIFE), hero)
        self.assertEqual(game.state.entities[hero].health, 96)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 64)
        self.assertEqual(game.state.players[1].mana, 24)

    def test_waiting_battlecry_keeps_frozen_attack_after_live_growth_or_departure(self):
        for choice in ('grow', 'bounce'):
            with self.subTest(choice=choice):
                game = self.game(hand=(CARD, HAND_BUFF), variant='wait'); eid = self.entity(game, CARD).id
                self.play(game, HAND_BUFF, eid); hero = game.state.players[2].hero_id
                self.play(game, CARD, hero); self.assertIsNotNone(game.state.pending_choice)
                restored = self.portable(game); self.choose(game, choice); self.choose(restored, choice)
                self.assertEqual(game.snapshot(), restored.snapshot())
                self.assertEqual(game.state.entities[hero].health, 95)
                self.assertEqual(game.state.entities[eid].zone, Zone.BOARD if choice == 'grow' else Zone.HAND)
                self.assertEqual(game.state.entities[eid].attack, 12 if choice == 'grow' else 2)

    def test_target_departure_during_native_copy_fizzles_damage_without_retargeting(self):
        game = self.qualified(variant='pretarget'); target = game.state.players[2].board[0]
        self.craft(game); self.play(game, self.recipe(), target)
        self.assertEqual(game.state.entities[target].zone, Zone.HAND); self.assertEqual(len(self.copies(game)), 2)
        row, = self.kodo_rows(game)
        self.assertEqual(row.target_id, target); self.assertIsNone(row.failure)
        self.assertTrue(row.payload_started); self.assertTrue(row.completed)
        self.assertEqual(game.state.entities[target].health, 40)
        self.assertFalse(any(e.kind == 'damage_dealt' and e.target_id == target for e in game.events))
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 100)

    def test_late_native_damage_failure_rolls_back_payment_copy_budget_and_history(self):
        game = self.qualified(hand=(CHALLENGER,), variant='latefail'); self.play(game, CHALLENGER)
        self.craft(game); saved = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, self.recipe(), game.state.players[2].hero_id)
        self.assertEqual(game.snapshot(), saved); self.portable(game)

    def test_identity_collisions_fail_before_behavior_definition_or_donor_is_added(self):
        for collision in ('card', 'pool'):
            with self.subTest(collision=collision):
                registry = donor_registry(); original = originals().card(CARD)
                if collision == 'card': registry.register_card(original)
                else: registry.register_pool_card(PoolCard.from_definition(original))
                before = (dict(registry.cards), dict(registry.pool_cards), dict(registry._behaviors), set(registry.crafted_minion_parts))
                with self.assertRaises(TargetValidationError): register_dispatch_kodo_card(registry)
                self.assertEqual((dict(registry.cards), dict(registry.pool_cards),
                    dict(registry._behaviors), set(registry.crafted_minion_parts)), before)
