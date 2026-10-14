"""Physical cost facts and shared payment clocks, through public pay entries.

These fixtures prove the quote/payment layer. Spell acceptance, original Rewind
anchors and complete cross-family queue proofs have separate integration gates.
"""
import copy
import unittest
from dataclasses import dataclass, replace

from hs_sim.engine import (CardDefinition, CardType, CostSpec, Game, IllegalAction,
    Keyword, PaymentType, PlayCard, PlayerSetup, Registry, ResolutionError,
    ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice, TriggerSpec,
    UseHeroPower, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_quote_fact,
    capture_spell_cost_facts, cost_quote_from_fact, quote_accepted_hand,
    quote_cost, quote_input)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Destroy, Effect,
    GainArmor, GrantCostAura, InvokeBehavior, ModifyCost, RequestChoice)
from hs_sim.engine.lifecycle import attachment_id
from hs_sim.engine.model import (AbilityInstance, CardAbilityCondition,
    CardClass, CostAuraSpec, CostModifier, CostQueryProfile, CostQuoteFact,
    CostQuoteInput, CostScope, Enchantment, HealthLossReplacementSpec,
    KeywordAuraSpec, RepeatCostFilter, RepeatMatchSpec, Resource,
    SpellRepeatSpec)
from hs_sim.engine.payment_projection import (consume_quoted_modifiers,
    payment_plan, project_payment, validate_cost_source_history,
    validate_cost_use_history)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.starships import LaunchStarshipEffect, construction
from hs_sim.engine.temporary_cards import CreateTemporaryCard


SPELLS = (CardType.SPELL,)


def fixture_registry():
    registry = Registry('physical-cost-facts-fixtures-v1')
    registry.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    registry.register_behavior('wait', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('ok', 'Resolve', (GainArmor(c.player_id, 1),)),),
        source_id=c.source_id)])
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    registry.register_card(CardDefinition('plain', 'Plain', CardType.MINION,
        cost=6, health=5))
    registry.register_card(CardDefinition('free', 'Free', CardType.MINION, health=5))
    registry.register_card(CardDefinition('spell', 'Spell', CardType.SPELL,
        cost=6, on_play='armor'))
    registry.register_card(CardDefinition('waiting', 'Waiting', CardType.SPELL,
        cost=6, on_play='wait'))
    registry.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER,
        cost=2, on_use='armor'))
    registry.register_card(CardDefinition('weapon', 'Weapon', CardType.WEAPON,
        cost=6, attack=1, durability=2))
    registry.register_card(CardDefinition('piece', 'Piece', CardType.MINION,
        health=2, keywords=(Keyword.STARSHIP_PIECE,)))
    registry.register_card(CardDefinition('ship', 'Ship', CardType.MINION,
        starship_for=(CardClass.NEUTRAL,)))
    return registry


def health_stage_watch(c):
    """Return distinct public effects only when the real event view is correct."""
    stage = c.event.kind
    if stage == 'max_health_gained':
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == 'plain')
    else:
        source = c.state.entities[c.event.source_id]
    if source.card_id != 'plain':
        return ()
    if source.zone != Zone.HAND or len(c.state.play_history) != 1:
        raise ResolutionError('Payment callback already contains the prepared play')
    modifiers = c.state.players[c.player_id].cost_modifiers
    before = stage in ('health_loss_replaced', 'max_health_gained')
    if bool(modifiers) != before or len(c.state.cost_use_history) != (1 if before else 2):
        raise ResolutionError('Payment callback has the wrong cost-use phase')
    if before and modifiers[0].uses_remaining != 1:
        raise ResolutionError('Early replacement event already consumed its discount')
    return [GainArmor(c.player_id, {'health_loss_replaced': 1,
        'max_health_gained': 2, 'health_spent': 4}[stage])]


@dataclass(frozen=True)
class PayWithDyingHandAura(Effect):
    """Registered extension exposes a transient pre-emit normalization boundary."""
    source_id: int
    target_id: int


def pay_with_dying_hand_aura(r, effect):
    from hs_sim.engine.costs import pay_quote
    source = r.state.entities[effect.source_id]
    target = r.state.entities[effect.target_id]
    target.damage = target.max_health
    target.death_cause = None
    source.hand_aura_keywords.clear()
    quote = quote_cost(r.state, r.registry, source)
    before = copy.deepcopy(r.state)
    projected = project_payment(before, quote, cause_reason=type(effect).__name__,
        cause_source=copy.deepcopy(source), cause_target_id=target.id)
    pay_quote(r, r.player(source.controller), source, quote)
    if r.state != projected.final_state:
        raise ResolutionError('Detached payment does not match the real per-emit projection')


def normalized_payment_watch(c):
    if c.state.entities[c.event.source_id].card_id != 'spell':
        return ()
    target = next(c.state.entities[i] for i in c.state.players[1].board
        if c.state.entities[i].card_id == 'hand.aura')
    cause = target.death_cause
    source = c.state.entities[c.event.source_id]
    if (cause is None or cause.reason != 'PayWithDyingHandAura' or
            cause.source_id != source.id or cause.source_card_id != source.card_id or
            Keyword.ECHO not in source.hand_aura_keywords or source.zone != Zone.HAND):
        raise ResolutionError('Spent event froze stale death/hand-derived state')
    return [GainArmor(c.player_id, 1)]


class PhysicalCostQuoteTests(unittest.TestCase):
    def setUp(self):
        self.registry = fixture_registry()
        self.entries = []
        self.custom = False

    def register(self, kind, *values):
        getattr(self.registry, 'register_' + kind)(*values)
        self.entries.append((kind, values))

    def fresh_registry(self):
        registry = fixture_registry()
        for kind, values in self.entries:
            getattr(registry, 'register_' + kind)(*values)
        self.assertEqual(registry.fingerprint(), self.registry.fingerprint())
        return registry

    def mechanics(self):
        if not self.custom:
            return None
        mechanics = default_mechanics('physical-cost-facts-transient-fixture-v1')
        mechanics.register(PayWithDyingHandAura, pay_with_dying_hand_aura)
        return mechanics

    def minion(self, name, body=None, **fields):
        fields.setdefault('health', 5)
        if body is not None:
            self.register('behavior', name, body)
            fields['battlecry'] = name
        self.register('card', CardDefinition(name, name, CardType.MINION, **fields))

    def prepare(self, *effects, name='prepare'):
        self.minion(name, lambda c: effects)

    def game(self, hand=(), board=(), enemy_board=(), rules=None, **setup):
        fields = dict(max_mana=10, mana=10, hero_power_card_id='power')
        fields.update(setup)
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, **fields),
            PlayerSetup('hero', board=enemy_board, max_mana=10, mana=10),
        )), self.registry, ruleset=rules, mechanics=self.mechanics())

    def hand(self, game, name):
        return next(i for i in game.state.players[1].hand
            if game.state.entities[i].card_id == name)

    def play(self, game, name):
        return game.apply(PlayCard(1, self.hand(game, name)))

    def fact(self, game, name='spell', *, profile=None):
        state = game.state
        source = state.entities[self.hand(game, name)]
        return capture_quote_fact(state, self.registry,
            capture_cost_input(source), profile)

    def portable(self, game):
        snapshot = game.snapshot()
        registry = self.fresh_registry()
        self.assertEqual(Game.from_snapshot(snapshot, registry,
            mechanics=self.mechanics()).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.fresh_registry(),
            mechanics=self.mechanics()).snapshot(), snapshot)

    def test_physical_quote_is_pure_and_uses_model_alias(self):
        from hs_sim.engine.model import CostQuoteInput as ModelInput
        game = self.game(('spell',))
        before = game.snapshot()
        fact = self.fact(game)
        self.assertIs(CostQuoteInput, ModelInput)
        self.assertEqual((fact.local_amount, fact.amount, fact.payment),
            (6, 6, PaymentType.MANA))
        self.assertEqual(game.quote_cost(self.hand(game, 'spell')), cost_quote_from_fact(fact))
        self.assertEqual(game.snapshot(), before)

    def test_complete_local_order_precedes_global_aura_policy_order(self):
        self.minion('aura', cost_auras=(CostAuraSpec(CostSpec(delta=3)),))
        self.prepare(AddCostModifier(1, CostSpec(set_to=2), uses_remaining=1))
        game = self.game(('prepare', 'spell'), board=('aura',))
        self.play(game, 'prepare')
        state = game.state
        source = state.entities[self.hand(game, 'spell')]
        first = Enchantment(attachment_id(state), cost=1)
        second = Enchantment(attachment_id(state), set_cost=4)
        source.enchantments.extend((first, second))
        fact = capture_quote_fact(state, self.registry, capture_cost_input(source))
        self.assertEqual((fact.local_amount, fact.amount), (4, 2))
        self.assertEqual(tuple(c.kind for c in fact.contributions),
            ('local_enchantment', 'local_enchantment', 'cost_aura', 'player_modifier'))
        self.assertEqual(tuple(c.enchantment for c in fact.contributions[:2]), (first, second))
        self.assertEqual(fact.modifier_ids, tuple(c.id for c in fact.contributions[2:]))
        validate_cost_quote_fact(self.registry, fact)

    def test_global_ids_determine_noncommutative_payment_and_price(self):
        self.prepare(AddCostModifier(1, CostSpec(set_to=2, payment=PaymentType.ARMOR,
            card_types=SPELLS)), AddCostModifier(1, CostSpec(delta=3,
            payment=PaymentType.CORPSES, card_types=SPELLS)))
        self.minion('late.aura', lambda c: [GrantCostAura(c.source_id,
            CostAuraSpec(CostSpec(delta=-1)))])
        game = self.game(('prepare', 'late.aura', 'spell'))
        self.play(game, 'prepare')
        self.play(game, 'late.aura')
        fact = self.fact(game)
        self.assertEqual((fact.amount, fact.payment), (4, PaymentType.CORPSES))
        self.assertEqual(tuple(c.kind for c in fact.contributions),
            ('player_modifier', 'player_modifier', 'cost_aura'))
        self.assertEqual(fact.modifier_ids, tuple(sorted(fact.modifier_ids)))

    def test_external_layers_include_enemy_any_aura_with_actual_owner(self):
        self.minion('enemy.aura', cost_auras=(CostAuraSpec(CostSpec(delta=2), 'enemy'),))
        self.minion('any.aura', cost_auras=(CostAuraSpec(CostSpec(delta=-1), 'any'),))
        game = self.game(('spell',), enemy_board=('enemy.aura', 'any.aura'))
        fact = self.fact(game)
        self.assertEqual(fact.amount, 7)
        self.assertEqual(tuple(c.player_id for c in fact.contributions), (2, 2))
        self.assertEqual(fact.quote_input.player_id, 1)

    def test_unknown_face_and_kind_mismatch_are_explicit_errors(self):
        game = self.game(('spell',))
        value = self.fact(game).quote_input
        with self.assertRaises(ValueError):
            capture_quote_fact(game.state, self.registry, replace(value, kind=CardType.MINION))
        with self.assertRaises(ValueError):
            capture_quote_fact(game.state, self.registry, replace(value, card_id='missing'))

    def test_named_profile_requires_registered_policy_and_spell(self):
        self.register('cost_query_profile', CostQueryProfile('custom.accepted.hand'))
        game = self.game(('spell', 'plain'))
        fact = self.fact(game, profile='custom.accepted.hand')
        self.assertEqual(fact.profile_id, 'custom.accepted.hand')
        with self.assertRaises(ValueError):
            self.fact(game, profile='unknown.profile')
        with self.assertRaises(ValueError):
            self.fact(game, 'plain', profile='repeat.cost.accepted_hand')

    def test_compact_fact_recomputes_full_amount_and_payment(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2, payment=PaymentType.HEALTH)))
        game = self.game(('prepare', 'spell'))
        self.play(game, 'prepare')
        fact = self.fact(game)
        validate_cost_quote_fact(self.registry, fact)
        with self.assertRaises(ValueError):
            validate_cost_quote_fact(self.registry, replace(fact, amount=fact.amount + 1))
        with self.assertRaises(ValueError):
            validate_cost_quote_fact(self.registry, replace(fact, payment=PaymentType.MANA))

    def test_compact_fact_does_not_reprice_changed_live_state(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2), uses_remaining=1))
        game = self.game(('prepare', 'spell'))
        self.play(game, 'prepare')
        fact = self.fact(game)
        self.play(game, 'spell')
        self.assertEqual(game.state.players[1].cost_modifiers, [])
        self.assertEqual(fact.amount, 4)
        validate_cost_quote_fact(self.registry, fact)
        self.portable(game)

    def test_cost_aura_current_battlecry_uses_captured_abilities(self):
        self.minion('body', lambda c: [])
        self.minion('aura', cost_auras=(CostAuraSpec(CostSpec(delta=-2,
            ability=CardAbilityCondition(basis='current'))),))
        game = self.game(('body',), board=('aura',))
        state = game.state
        source = state.entities[self.hand(game, 'body')]
        first = capture_quote_fact(state, self.registry, capture_cost_input(source))
        source.abilities = [a for a in source.abilities if a.kind != 'battlecry']
        second = capture_quote_fact(state, self.registry, capture_cost_input(source))
        self.assertEqual((len(first.modifier_ids), len(second.modifier_ids)), (1, 0))

    def test_all_false_inactive_cost_sources_still_validate(self):
        self.minion('aura', cost_auras=(CostAuraSpec(CostSpec(card_types=(CardType.WEAPON,))),))
        game = self.game(('spell',), board=('aura',))
        state = game.state
        aura = state.entities[state.players[1].board[0]]
        ability = aura.abilities[0]
        object.__setattr__(ability.cost_aura.cost, 'minimum', True)
        aura.doomed = True
        with self.assertRaises(ValueError):
            capture_quote_fact(state, self.registry,
                capture_cost_input(state.entities[self.hand(game, 'spell')]))

    def test_all_false_opponent_cost_policy_still_validates(self):
        game = self.game(('spell',))
        state = game.state
        modifier = CostModifier(attachment_id(state), CostSpec(card_types=(CardType.WEAPON,)))
        object.__setattr__(modifier, 'uses_remaining', False)
        state.players[2].cost_modifiers.append(modifier)
        with self.assertRaises(ValueError):
            capture_quote_fact(state, self.registry,
                capture_cost_input(state.entities[self.hand(game, 'spell')]))

    def test_reduction_minimum_does_not_raise_already_zero_price(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2, minimum=3), uses_remaining=1))
        game = self.game(('prepare', 'free'))
        self.play(game, 'prepare')
        fact = self.fact(game, 'free')
        self.assertEqual(fact.amount, 0)
        self.assertEqual(len(fact.consumable_ids), 1)
        self.play(game, 'free')
        self.assertFalse(game.state.players[1].cost_modifiers)
        self.assertEqual(game.state.cost_use_history[-1].amount, 0)
        self.portable(game)

    def test_quote_accounts_show_local_before_external_replacement(self):
        self.prepare(AddCostModifier(1, CostSpec(payment=PaymentType.CORPSES)))
        game = self.game(('prepare', 'spell'))
        self.play(game, 'prepare')
        state = game.state
        source = state.entities[self.hand(game, 'spell')]
        source.enchantments.append(Enchantment(attachment_id(state), payment=PaymentType.ARMOR))
        fact = capture_quote_fact(state, self.registry, capture_cost_input(source))
        self.assertEqual((fact.local_payment, fact.payment),
            (PaymentType.ARMOR, PaymentType.CORPSES))
        validate_cost_quote_fact(self.registry, fact)

    def test_physical_same_face_inputs_keep_distinct_identity(self):
        game = self.game(('spell', 'spell'))
        state = game.state
        values = tuple(capture_quote_fact(state, self.registry,
            capture_cost_input(state.entities[i])) for i in state.players[1].hand)
        self.assertEqual(tuple(v.amount for v in values), (6, 6))
        self.assertNotEqual(values[0].quote_input.source_id, values[1].quote_input.source_id)

    def test_saved_hand_floor_survives_real_paid_spell_in_graveyard(self):
        self.minion('create', lambda c: [CreateTemporaryCard(c.player_id, 'waiting',
            c.state.turn, minimum_cost=1, source_id=c.source_id, cost=CostSpec(delta=-10))])
        game = self.game(('create',))
        self.play(game, 'create')
        source_id = self.hand(game, 'waiting')
        self.play(game, 'waiting')
        state = game.state
        play = state.play_history[-1]
        self.assertEqual((state.entities[source_id].zone, play.cost), (Zone.GRAVEYARD, 1))
        before = game.snapshot()
        fact = quote_accepted_hand(state, self.registry, play)
        self.assertEqual((fact.local_amount, fact.amount, fact.quote_input.minimum_cost), (0, 1, 1))
        self.assertEqual(quote_cost(state, self.registry, state.entities[source_id]).amount, 0)
        self.assertEqual(game.snapshot(), before)
        self.portable(game)
        game.apply(SelectChoice(1, game.state.pending_choice.id, ('ok',)))
        self.portable(game)

    def test_spell_facts_capture_sorted_distinct_registered_window_profiles(self):
        self.register('cost_query_profile', CostQueryProfile('z.hand'))
        self.register('cost_query_profile', CostQueryProfile('a.hand'))
        game = self.game(('waiting',))
        self.play(game, 'waiting')
        play = game.state.play_history[-1]
        specs = tuple(SpellRepeatSpec(match=RepeatMatchSpec(recipient_cost=
            RepeatCostFilter('window_quote', maximum=6, quote_profile_id=p)))
            for p in ('z.hand', 'a.hand', 'z.hand'))
        facts = capture_spell_cost_facts(game.state, self.registry, play, specs)
        self.assertEqual(tuple(q.profile_id for q in facts.window_quotes), ('a.hand', 'z.hand'))
        self.assertTrue(all(q.quote_input == facts.cost_input for q in facts.window_quotes))

    def test_missing_submitted_receipt_and_changed_accepted_face_reject(self):
        game = self.game(('waiting',))
        self.play(game, 'waiting')
        play = game.state.play_history[-1]
        with self.assertRaises(ValueError):
            quote_accepted_hand(game.state, self.registry, replace(play, submitted_cost=None))
        state = game.state
        state.entities[play.source_id].card_id = 'spell'
        with self.assertRaises(ValueError):
            quote_accepted_hand(state, self.registry, play)
        malformed = copy.deepcopy(play)
        object.__setattr__(malformed, 'hand_entry_id', play.hand_entry_id + 1)
        with self.assertRaises(ValueError):
            quote_accepted_hand(game.state, self.registry, malformed)

    def test_finite_cost_use_consumes_once_per_paid_root_and_saved_fact_survives(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-4, card_types=(CardType.MINION,)), 2))
        game = self.game(('prepare', 'plain', 'plain'))
        self.play(game, 'prepare')
        original = game.state
        fact = self.fact(game, 'plain')
        self.play(game, 'plain')
        self.assertEqual(game.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.play(game, 'plain')
        state = game.state
        self.assertEqual(state.players[1].mana, 6)
        self.assertEqual(tuple(r.player_modifiers[0].uses_remaining
            for r in state.cost_use_history[1:]), (2, 1))
        self.assertFalse(state.players[1].cost_modifiers)
        validate_cost_source_history(original, state, self.registry)
        validate_cost_quote_fact(self.registry, fact)
        self.portable(game)

    def test_shared_policy_clock_includes_nonspell_hand_and_manual_hero_power(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-1,
            card_types=(CardType.MINION, CardType.HERO_POWER)), 2))
        game = self.game(('prepare', 'plain'))
        self.play(game, 'prepare')
        original = game.state
        self.play(game, 'plain')
        power_id = game.state.players[1].hero_power_id
        game.apply(UseHeroPower(1, power_id))
        state = game.state
        receipts = state.cost_use_history[1:]
        self.assertEqual(tuple(r.source_card_id for r in receipts), ('plain', 'power'))
        self.assertEqual(tuple(r.player_modifiers[0].uses_remaining for r in receipts), (2, 1))
        self.assertEqual(state.players[1].mana, 4)
        validate_cost_source_history(original, state, self.registry)
        self.portable(game)

    def test_effect_launch_has_distinct_free_origin_and_consumes_launch_policy(self):
        self.minion('create.ship', lambda c: [Destroy(c.state.players[1].board[0]),
            AddCostModifier(1, CostSpec(delta=-2), 1, scope=CostScope.STARSHIP_LAUNCH)])
        self.minion('launch', lambda c: [LaunchStarshipEffect(1, construction(c.state, 1).id)])
        game = self.game(('create.ship', 'launch'), board=('piece',))
        self.play(game, 'create.ship')
        original = game.state
        mana_before = original.players[1].mana
        spent_before = sum(e.kind == 'mana_spent' for e in game.events)
        self.play(game, 'launch')
        state = game.state
        receipt = state.cost_use_history[-1]
        self.assertEqual((receipt.origin, receipt.amount, receipt.source_card_id),
            ('effect_launch', 3, 'ship'))
        self.assertEqual(state.players[1].mana, mana_before)
        self.assertEqual(sum(e.kind == 'mana_spent' for e in game.events), spent_before + 1)
        self.assertFalse(state.players[1].cost_modifiers)
        validate_cost_source_history(original, state, self.registry)
        self.portable(game)

    def test_false_policy_later_last_use_cannot_change_when_current_source_is_gone(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2, card_types=(CardType.WEAPON,)), 1))
        game = self.game(('prepare', 'weapon'))
        self.play(game, 'prepare')
        original = game.state
        self.play(game, 'weapon')
        state = game.state
        self.assertFalse(state.players[1].cost_modifiers)
        validate_cost_source_history(original, state, self.registry)
        receipt = state.cost_use_history[-1]
        changed = replace(receipt.player_modifiers[0], spec=CostSpec(delta=-3,
            card_types=(CardType.WEAPON,)))
        state.cost_use_history[-1] = replace(receipt, player_modifiers=(changed,))
        with self.assertRaises(ValueError):
            validate_cost_source_history(original, state, self.registry)

    def test_global_clock_rejects_equal_preuse_after_real_first_consumption(self):
        self.prepare(AddCostModifier(1, CostSpec(set_to=1), 2))
        game = self.game(('prepare', 'plain', 'plain'))
        self.play(game, 'prepare')
        original = game.state
        self.play(game, 'plain')
        self.play(game, 'plain')
        state = game.state
        receipt = state.cost_use_history[-1]
        state.cost_use_history[-1] = replace(receipt,
            player_modifiers=(replace(receipt.player_modifiers[0], uses_remaining=2),))
        with self.assertRaises(ValueError):
            validate_cost_use_history(state, self.registry)
        with self.assertRaises(ValueError):
            validate_cost_source_history(original, state, self.registry)

    def test_original_ledger_prefix_cannot_be_deleted_or_rewritten(self):
        game = self.game(('free', 'free'))
        self.play(game, 'free')
        original = game.state
        self.play(game, 'free')
        state = game.state
        validate_cost_source_history(original, state, self.registry)
        state.cost_use_history[0] = replace(state.cost_use_history[0], amount=1)
        with self.assertRaises(ValueError):
            validate_cost_source_history(original, state, self.registry)
        state = game.state
        state.cost_use_history.pop(0)
        with self.assertRaises(ValueError):
            validate_cost_source_history(original, state, self.registry)

    def test_finite_source_cannot_shrink_without_accepted_payment_receipt(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2), 2))
        game = self.game(('prepare', 'plain'))
        self.play(game, 'prepare')
        original = game.state
        state = game.state
        state.players[1].cost_modifiers[0] = replace(state.players[1].cost_modifiers[0], uses_remaining=1)
        with self.assertRaises(ValueError):
            validate_cost_source_history(original, state, self.registry)
        validate_cost_source_history(original, original, self.registry)

    def test_foreign_attachment_id_cannot_be_borrowed_by_later_consumed_policy(self):
        game = self.game(('spell',), board=('plain',))
        original = game.state
        carrier = original.entities[original.players[1].board[0]]
        foreign = Enchantment(attachment_id(original), health=1)
        carrier.enchantments.append(foreign)
        state = copy.deepcopy(original)
        state.entities[carrier.id].enchantments.clear()
        modifier = CostModifier(foreign.id, CostSpec(delta=-1), uses_remaining=1)
        state.players[1].cost_modifiers.append(modifier)
        source = state.entities[self.hand(game, 'spell')]
        quote = quote_cost(state, self.registry, source)
        consume_quoted_modifiers(state, quote, origin='payment')
        self.assertFalse(state.players[1].cost_modifiers)
        validate_cost_use_history(state, self.registry)
        with self.assertRaises(ValueError):
            validate_cost_source_history(original, state, self.registry)

    def test_aura_static_source_keeps_physical_carrier_but_not_control_or_zone(self):
        self.minion('aura', cost_auras=(CostAuraSpec(CostSpec(delta=-1)),))
        game = self.game(('spell',), board=('aura', 'plain'))
        original = game.state
        state = game.state
        aura = state.entities[state.players[1].board[0]]
        aura.controller = 2
        validate_cost_source_history(original, state, self.registry)
        other = state.entities[state.players[1].board[1]]
        other.abilities.extend(aura.abilities)
        aura.abilities.clear()
        with self.assertRaises(ValueError):
            validate_cost_source_history(original, state, self.registry)

    def test_global_cost_identity_detects_false_duplicate_sources(self):
        game = self.game(('spell',), board=('plain',))
        state = game.state
        identity = attachment_id(state)
        state.entities[state.players[1].board[0]].enchantments.append(Enchantment(identity, health=1))
        state.players[2].cost_modifiers.append(CostModifier(identity,
            CostSpec(card_types=(CardType.WEAPON,))))
        with self.assertRaises(ValueError):
            quote_cost(state, self.registry, state.entities[self.hand(game, 'spell')])

    def test_mana_payment_spends_temporary_mana_before_crystals(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2, card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'plain'), max_mana=7, temporary_mana=3, mana=10)
        self.play(game, 'prepare')
        self.play(game, 'plain')
        player = game.state.players[1]
        self.assertEqual((player.mana, player.temporary_mana, player.mana_spent), (6, 0, 1))
        self.assertEqual(game.state.cost_use_history[-1].amount, 4)
        self.portable(game)

    def test_health_quote_is_nominal_with_armor_and_growth_replacement(self):
        self.minion('replacement', health_loss_replacements=(HealthLossReplacementSpec(),))
        self.prepare(AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH,
            card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'plain'), board=('replacement',), armor=2)
        self.play(game, 'prepare')
        self.play(game, 'plain')
        hero = game.state.entities[game.state.players[1].hero_id]
        receipt = game.state.cost_use_history[-1]
        self.assertEqual((hero.health, hero.max_health, hero.armor), (34, 34, 0))
        self.assertEqual((receipt.amount, receipt.payment), (6, PaymentType.HEALTH))
        self.portable(game)

    def test_armor_payment_changes_only_armor_and_consumes_discount(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2, payment=PaymentType.ARMOR,
            card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'plain'), armor=7)
        self.play(game, 'prepare')
        self.play(game, 'plain')
        state = game.state
        hero = state.entities[state.players[1].hero_id]
        self.assertEqual((hero.armor, hero.health, state.players[1].mana), (3, 30, 10))
        self.assertFalse(state.players[1].cost_modifiers)
        self.portable(game)

    def test_corpses_payment_changes_only_corpses_and_consumes_discount(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2, payment=PaymentType.CORPSES,
            card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'plain'), corpses=7)
        self.play(game, 'prepare')
        self.play(game, 'plain')
        self.assertEqual((game.state.players[1].resources[Resource.CORPSES],
            game.state.players[1].mana), (3, 10))
        self.assertFalse(game.state.players[1].cost_modifiers)
        self.portable(game)

    def test_payment_plan_is_pure_detached_and_projects_real_nonspell_payment(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-2, card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'plain'))
        self.play(game, 'prepare')
        state = game.state
        before = copy.deepcopy(state)
        quote = game.quote_cost(self.hand(game, 'plain'))
        plan = payment_plan(state, quote)
        projected = project_payment(state, quote, cause_reason='PlayFromHand')
        self.assertEqual(state, before)
        self.assertEqual(projected.final_state.players[1].mana, 6)
        self.assertFalse(projected.final_state.players[1].cost_modifiers)
        self.assertEqual(len(plan.health_events), 0)
        self.play(game, 'plain')
        actual = game.state.cost_use_history[-1]
        self.assertEqual((actual.amount, actual.modifier_ids, actual.player_modifiers),
            (projected.final_state.cost_use_history[-1].amount,
             projected.final_state.cost_use_history[-1].modifier_ids,
             projected.final_state.cost_use_history[-1].player_modifiers))

    def test_health_event_views_keep_early_discount_and_late_consumption(self):
        self.minion('replacement', health_loss_replacements=(HealthLossReplacementSpec(),))
        self.register('behavior', 'health.watch', health_stage_watch)
        self.minion('watch', triggers=tuple(TriggerSpec(event, 'health.watch')
            for event in ('health_loss_replaced', 'max_health_gained', 'health_spent')))
        self.prepare(AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH,
            card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'plain'), board=('replacement', 'watch'), armor=2)
        self.play(game, 'prepare')
        start = len(game.events)
        self.play(game, 'plain')
        hero = game.state.entities[game.state.players[1].hero_id]
        self.assertEqual((hero.health, hero.max_health, hero.armor), (34, 34, 7))
        self.assertEqual(tuple(e.kind for e in game.events[start:] if e.kind in
            ('health_loss_replaced', 'max_health_gained', 'health_spent')),
            ('health_loss_replaced', 'max_health_gained', 'health_spent'))
        self.portable(game)

    def test_each_spent_emit_normalizes_dying_cause_and_hand_aura_cache(self):
        self.custom = True
        self.minion('hand.aura', keyword_auras=(KeywordAuraSpec(Keyword.ECHO, 'friendly_hand_spells'),))
        self.register('behavior', 'normalize.watch', normalized_payment_watch)
        self.minion('watch', triggers=(TriggerSpec('mana_spent', 'normalize.watch'),))
        self.minion('transient.pay', lambda c: [PayWithDyingHandAura(
            next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == 'spell'),
            next(i for i in c.state.players[1].board if c.state.entities[i].card_id == 'hand.aura'))])
        game = self.game(('transient.pay', 'spell'), board=('hand.aura', 'watch'))
        self.play(game, 'transient.pay')
        state = game.state
        source = state.entities[self.hand(game, 'spell')]
        self.assertEqual((state.players[1].mana, state.entities[state.players[1].hero_id].armor), (4, 1))
        self.assertNotIn(Keyword.ECHO, source.hand_aura_keywords)
        death = next(d for d in state.death_history if d.card_id == 'hand.aura')
        self.assertEqual((death.cause.reason, death.cause.source_id),
            ('PayWithDyingHandAura', source.id))
        self.portable(game)

    def test_impossible_payment_rolls_back_complete_snapshot_and_cost_clock(self):
        self.prepare(AddCostModifier(1, CostSpec(delta=-1, card_types=(CardType.MINION,)), 2))
        game = self.game(('prepare', 'plain'), mana=2)
        self.play(game, 'prepare')
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(game, 'plain')
        self.assertEqual(game.snapshot(), before)
        self.portable(game)

    def test_payload_exception_after_payment_rolls_back_cost_receipt(self):
        def fail(c):
            raise ValueError('deliberate paid body failure')
        self.minion('bad', fail, cost=6)
        self.prepare(AddCostModifier(1, CostSpec(delta=-4, card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'bad'))
        self.play(game, 'prepare')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'bad')
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.portable(game)

    def test_resolution_budget_after_payment_rolls_back_cost_receipt(self):
        self.minion('many', lambda c: [GainArmor(1, 1)] * 100, cost=6)
        self.prepare(AddCostModifier(1, CostSpec(delta=-4, card_types=(CardType.MINION,)), 1))
        game = self.game(('prepare', 'many'), rules=Ruleset(max_resolution_steps=60))
        self.play(game, 'prepare')
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(game, 'many')
        self.assertEqual(game.snapshot(), before)
        self.portable(game)


if __name__ == '__main__':
    unittest.main()
