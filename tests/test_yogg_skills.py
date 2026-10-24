"""Native four-ability entry and shared effects; the real AI Battlecry stays pending."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin, event_player
from hs_sim.cards import build_registry
from hs_sim.cards.yogg_skills import (ROOT, WITS, MADNESS, ASCENT, DOMAIN, SKILLS,
    load_batch, register_yogg_skills, skill_specs)
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Keyword, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    TriggerSpec, UseHeroPower, UseMinionAbility)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import ChoiceOption, Damage, InvokeBehavior, RequestChoice
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec, DamageKind, SpellRepeatModifier, SpellRepeatSpec, TargetMode, TargetSpec
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.zones import CardReference
from tools import card_batch as batch

P = 'k501.'
GOD, HERO, POWER, UNIT, BONUS, WATCH = (P+x for x in ('god-skills-only', 'hero', 'power', 'unit', 'bonus', 'watch'))
A, B, ZERO = (P+x for x in ('two', 'four', 'zero'))
F3, F4, F5, F7 = (P+'destination-'+str(i) for i in (3, 4, 5, 7))
META = CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=(), factions=(), subtypes=())
SPELL_META = replace(META, collectible=True, rarity=Rarity.COMMON)
CTX = GenerationContext('complete-k501-experimental-spell-domain', 'experimental')
TARGET = TargetSpec(TargetMode.REQUIRED, kinds=(CardType.HERO, CardType.MINION), relation='any')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = Registry(P+mode); register_yogg_skills(registry)
    # This necessary representative tests only four native skills. It is not
    # an executable replacement for BE_009's missing controlled-turn Battlecry.
    registry.register_card(CardDefinition(GOD, 'Four Yogg skills only', CardType.MINION,
        cost=9, attack=7, health=5, keywords=(Keyword.OLD_GOD,), metadata=META,
        activated_abilities=skill_specs()))
    registry.register_behavior(P+'empty', lambda c: ())
    registry.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=50, metadata=META))
    def power(c):
        if mode == 'discount':
            target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
                if c.state.entities[i].card_id == A)
            return (BuffStoredCard(CardReference.capture(target), source_id=c.source_id,
                cost=CostSpec(delta=-1)),)
        return (CastSpell(c.player_id, A, c.source_id),)
    registry.register_behavior(P+'cast', power)
    registry.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER, cost=2, on_use=P+'cast', metadata=META))
    registry.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=30, metadata=META))
    registry.register_card(CardDefinition(BONUS, BONUS, CardType.MINION, health=8, spell_damage=4, metadata=META))
    registry.register_behavior(P+'hit', lambda c: (Damage(c.target_id,
        1 if c.source.card_id == ZERO else 2, c.source_id, DamageKind.SPELL),))
    for cid, cost in ((A, 2), (B, 4), (ZERO, 0)):
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost,
            on_play=P+'hit', targeting=TARGET, metadata=SPELL_META))
    for cid, cost in ((F3, 3), (F4, 4), (F5, 5), (F7, 7)):
        card = CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play=P+'empty',
            metadata=replace(SPELL_META, classes=(CardClass.WARRIOR,)))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    members = (F3, F4, F5, F7)
    if mode == 'unknown':
        unknown = P+'unknown'
        registry.register_pool_card(replace(registry.pool_card(F5), card_id=unknown))
        members += (unknown,)
    if mode != 'missing':
        registry.register_pool(PoolDefinition('constructed.cards', 'explicit-fixture-v1', CTX.target_id,
            CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))

    def fail(c):
        raise ResolutionError('Yogg skill fixture failure')

    def watch(c):
        player = event_player(c)
        if mode == 'expiry_wait' and c.event.kind == 'spell_modifier_expired':
            return (RequestChoice(player, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        if c.event.kind == 'stored_card_transformed':
            if mode == 'fail':
                return (InvokeBehavior(P+'fail', c.source_id, c.player_id),)
            remaining = [c.state.entities[i] for i in c.state.players[player].hand
                if c.state.entities[i].card_id == A]
            if mode == 'transform_wait' and remaining:
                effect = BuffStoredCard(CardReference.capture(remaining[0]), source_id=c.source_id,
                    cost=CostSpec(delta=10))
                return (RequestChoice(player, (ChoiceOption('continue', 'Continue', (effect,)),), c.source_id),)
        if mode == 'draw_wait' and c.event.kind == 'card_drawn' and len(c.state.players[player].hand) == 1:
            return (RequestChoice(player, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        return ()

    registry.register_behavior(P+'fail', fail); registry.register_behavior(P+'watch', watch)
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('stored_card_transformed', P+'watch'), TriggerSpec('card_drawn', P+'watch'),
            TriggerSpec('spell_modifier_expired', P+'watch'))))
    registry.validate(); return registry


class YoggSkillsTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, mode='normal', player=1, hand=(), deck=None, bonus=False):
        self.mode = mode; deck = (UNIT,)*8 if deck is None else deck
        board = (GOD,) + ((WATCH,) if mode in ('transform_wait', 'draw_wait', 'fail', 'expiry_wait') else ())
        if bonus:
            board += (BONUS,)
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            board=board if p == player else (UNIT,), hand=hand if p == player else (A,),
            deck=deck if p == player else (UNIT,)*8, mana=10, max_mana=10) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=501,
            generation_context=CTX), fixture(mode))

    def use(self, game, skill, target=None, player=1):
        game.apply(UseMinionAbility(player, self.entity(game, GOD, player, 'board').id, skill, target))

    def hero(self, game, player):
        return game.state.players[player].hero_id

    def accepted_casts(self, game):
        return [event for event in game.events if event.kind == 'spell_cast_accepted']

    def test_five_full_rows_ten_primary_faces_and_nonplayable_labels_keep_real_root_pending(self):
        data = load_batch(); rows = {r['record']['id']: r['record']
            for r in data['choice_only']+data['evidence_only']}
        self.assertEqual((len(rows), len(data['official_observations'])), (5, 10))
        for observation in data['official_observations']:
            cid = observation['card_id']
            batch.check_face(rows[cid], observation['face'], observation['locale'],
                numeric_normalizations={'cost': 0} if cid in SKILLS else None)
        registry = build_registry()
        for cid in SKILLS:
            self.assertTrue(registry.card(cid).choice_only)
            self.assertFalse(registry.card(cid).hand_playable)
            self.assertNotIn(cid, registry.pool_cards)
        with self.assertRaises(UnsupportedDefinitionError):
            registry.card(ROOT)
        with self.assertRaisesRegex(ResolutionError, 'Choice-only'):
            self.game(hand=(WITS,))

    def test_wits_next_paid_spell_casts_twice_with_one_payment_then_budget_is_consumed(self):
        game = self.game(hand=(A, A)); enemy = self.hero(game, 2)
        self.use(game, WITS); self.assertEqual(len(self.accepted_casts(game)), 0)
        self.play(game, A, enemy)
        self.assertEqual((game.state.entities[enemy].health, game.state.players[1].mana), (46, 8))
        self.assertEqual(len(self.accepted_casts(game)), 2)
        self.play(game, A, enemy)
        self.assertEqual((game.state.entities[enemy].health, game.state.players[1].mana), (44, 6))
        self.assertEqual(len(self.accepted_casts(game)), 3)

    def test_wits_broad_automatic_policy_keeps_one_use_two_casts_and_original_turn(self):
        spec = SpellRepeatSpec(2, 'any')
        AddSpellRepeatModifier(1, spec, 1, uses=1, expires_turn=1, automatic=True)
        SpellRepeatModifier(1, spec, 1, GOD, 1, uses_remaining=1, expires_turn=1, automatic=True)
        for changes in ({'uses': None}, {'uses': 2}, {'uses': True}, {'source_id': None},
                {'expires_turn': None}, {'spec': SpellRepeatSpec(3, 'any')},
                {'spec': SpellRepeatSpec(2, 'other')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                values = dict(player_id=1, spec=spec, source_id=1, uses=1, expires_turn=1, automatic=True)
                AddSpellRepeatModifier(**dict(values, **changes))
        with self.assertRaises(ValueError):
            SpellRepeatModifier(1, spec, 1, GOD, 1, uses_remaining=1, expires_turn=2, automatic=True)

    def test_wits_zero_cost_spell_consumes_budget_and_original_turn_expiry_is_respected(self):
        game = self.game(hand=(ZERO, A)); enemy = self.hero(game, 2)
        self.use(game, WITS); self.play(game, ZERO, enemy); self.play(game, A, enemy)
        self.assertEqual((game.state.entities[enemy].health, game.state.players[1].mana), (46, 8))
        game = self.game(hand=(A,)); self.use(game, WITS)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.play(game, A, self.hero(game, 2))
        self.assertEqual(len(self.accepted_casts(game)), 1)

    def test_wits_automatic_effect_cast_is_doubled_without_second_power_payment(self):
        game = self.game(); self.use(game, WITS)
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        self.assertEqual(len(self.accepted_casts(game)), 2)
        self.assertEqual(game.state.players[1].mana, 8)

    def test_wits_budget_restore_clone_and_replay_then_actual_paid_cast(self):
        game = self.game(hand=(A,)); self.use(game, WITS); restored = self.portable(game)
        self.play(game, A, self.hero(game, 2)); self.play(restored, A, self.hero(restored, 2))
        self.assertEqual(restored.snapshot(), game.snapshot())

    def test_wits_unused_expiry_wait_before_handoff_restores_without_reviving_budget(self):
        game = self.game('expiry_wait', hand=(A,)); self.use(game, WITS)
        game.apply(EndTurn(1)); self.assertIsNotNone(game.state.pending_choice)
        restored = self.portable(game)
        self.choose(game); self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        game.apply(EndTurn(2)); self.play(game, A, self.hero(game, 2))
        self.assertEqual(len(self.accepted_casts(game)), 1)

    def test_madness_targets_either_hero_with_native_ten_damage_not_spell_damage(self):
        for player in (1, 2):
            for target_player in (1, 2):
                with self.subTest(player=player, target_player=target_player):
                    game = self.game(player=player, bonus=True); target = self.hero(game, target_player)
                    self.use(game, MADNESS, target, player)
                    self.assertEqual(game.state.entities[target].health, 40)
                    self.assertEqual(game.state.players[player].mana, 10)
                    self.assertFalse(self.accepted_casts(game))

    def test_ascent_transforms_all_original_spells_keeps_physical_slots_and_costs(self):
        game = self.game(hand=(A, UNIT, A, B, ZERO)); ids = tuple(game.state.players[1].hand)
        entries = {i: game.state.entities[i].hand_entry_id for i in ids}
        enemy = tuple(game.state.players[2].hand)
        self.use(game, ASCENT)
        self.assertEqual(tuple(game.state.players[1].hand), ids)
        self.assertEqual([game.state.entities[i].card_id for i in ids], [F5, UNIT, F5, F7, F3])
        self.assertEqual([quote_cost(game.state, game.registry, game.state.entities[i]).amount
            for i in (ids[0], ids[2], ids[3], ids[4])], [2, 2, 4, 0])
        self.assertEqual({i: game.state.entities[i].hand_entry_id for i in ids}, entries)
        self.assertEqual(tuple(game.state.players[2].hand), enemy)
        self.assertEqual(game.state.players[1].mana, 10)

    def test_ascent_full_hand_has_no_addition_or_burn(self):
        game = self.game(hand=(A,)*10); original = tuple(game.state.players[1].hand)
        self.use(game, ASCENT)
        self.assertEqual(tuple(game.state.players[1].hand), original)
        self.assertTrue(all(game.state.entities[i].card_id == F5 for i in original))
        self.assertFalse(any(event.kind == 'card_burned' for event in game.events))

    def test_ascent_current_local_discount_sets_original_tier_and_retained_cost(self):
        game = self.game('discount', hand=(A,)); original = game.state.players[1].hand[0]
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        self.use(game, ASCENT)
        entity = game.state.entities[original]
        self.assertEqual(entity.card_id, F4)
        self.assertEqual(quote_cost(game.state, game.registry, entity).amount, 1)

    def test_ascent_empty_exact_tier_keeps_original_without_sampling(self):
        game = self.game(hand=(F7,)); original = game.state.players[1].hand[0]
        before = game._rng.getstate(); self.use(game, ASCENT)
        self.assertEqual(game.state.entities[original].card_id, F7)
        self.assertEqual(game._rng.getstate(), before)

    def test_ascent_notification_wait_keeps_original_later_costs_and_restores_remaining_plan(self):
        game = self.game('transform_wait', hand=(A, A)); ids = tuple(game.state.players[1].hand)
        self.use(game, ASCENT)
        self.assertEqual([game.state.entities[i].card_id for i in ids], [F5, A])
        restored = self.portable(game)
        self.choose(game); self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual([game.state.entities[i].card_id for i in ids], [F5, F5])
        self.assertEqual(quote_cost(game.state, game.registry, game.state.entities[ids[1]]).amount, 2)

    def test_ascent_empty_hand_does_not_need_an_unused_pool(self):
        game = self.game('missing'); before = game._rng.getstate(); self.use(game, ASCENT)
        self.assertEqual(game._rng.getstate(), before)

    def test_ascent_unknown_eligible_or_late_failure_rolls_back_use_material_and_rng(self):
        for mode in ('unknown', 'fail'):
            with self.subTest(mode=mode):
                game = self.game(mode, hand=(A, A)); saved = game.snapshot()
                with self.assertRaises(ResolutionError):
                    self.use(game, ASCENT)
                self.assertEqual(game.snapshot(), saved)

    def test_domain_draws_five_physical_spells_preserves_other_deck_cards_and_both_actors(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player, deck=(UNIT, A, B, UNIT, A, ZERO, B))
                spells = {i for i in game.state.players[player].deck
                    if game.registry.card(game.state.entities[i].card_id).kind == CardType.SPELL}
                self.use(game, DOMAIN, player=player)
                self.assertEqual(set(game.state.players[player].hand), spells)
                self.assertTrue(all(game.state.entities[i].card_id == UNIT for i in game.state.players[player].deck))
                self.assertEqual(game.state.players[player].mana, 10)

    def test_domain_five_draw_chain_restores_after_first_real_draw(self):
        game = self.game('draw_wait', deck=(A, A, A, A, A)); self.use(game, DOMAIN)
        self.assertEqual(len(game.state.players[1].hand), 1)
        restored = self.portable(game)
        self.choose(game); self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(len(game.state.players[1].hand), 5)

    def test_domain_empty_matching_pool_uses_existing_skip_policy(self):
        for deck in ((), (UNIT, UNIT)):
            with self.subTest(deck=deck):
                game = self.game(deck=deck); before = game._rng.getstate(); self.use(game, DOMAIN)
                self.assertEqual(len(game.state.players[1].hand), 0)
                self.assertEqual(game._rng.getstate(), before)
                self.assertEqual(game.state.entities[self.hero(game, 1)].health, 50)

    def test_domain_full_hand_still_draws_and_burns_all_remaining_spells(self):
        game = self.game(hand=(UNIT,)*9, deck=(A,)*5); self.use(game, DOMAIN)
        self.assertEqual(len(game.state.players[1].hand), 10)
        self.assertEqual(len(game.state.players[1].deck), 0)
        self.assertEqual(sum(event.kind == 'card_burned' for event in game.events), 4)
