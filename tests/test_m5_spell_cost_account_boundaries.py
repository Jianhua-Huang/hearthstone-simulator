"""Paid Spell account proofs, strict false-source queries and true retry clocks.

Only public effects create the growth/allocator/retry facts. Malformed copies
first retain valid model structure, then fail their original payment proof.
"""
import copy
import unittest
from dataclasses import replace

import test_m5_spell_cost_acceptance as base
from hs_sim.engine import (CardClass, CardMetadata, CardType, CostSpec, Game,
    PaymentType, PlayerSetup, Registry, ResolutionError, Scenario, SpellRepeatSpec)
from hs_sim.engine.effects import (AddCostModifier, Buff, ChoiceOption, Destroy,
    GainArmor, GrantSpellDamage, InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.lifecycle import refresh_entity
from hs_sim.engine.model import (ChoicePurpose, HealthLossReplacementSpec,
    RecipientMetadataFilter, RepeatCostFilter, RepeatMatchSpec,
    RepeatSourceEligibility, Resource, SpellSchool, validate_invariants)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rewind import COUNTERS
from hs_sim.engine.spell_acceptance import validate_acceptance
from hs_sim.engine.spell_cost_proof import validate_hand_cost_proof
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier


def highwater_body(c):
    return [Summon(c.player_id, 'fee.highwater.token'),
        InvokeBehavior('fee.highwater.discard', c.source_id, c.player_id),
        RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue attempt',
            (GainArmor(c.player_id, 1),)),), source_id=c.source_id)]


def highwater_discard(c):
    target = next(i for i in c.state.players[c.player_id].board
        if c.state.entities[i].card_id == 'fee.highwater.token'
        and not c.state.entities[i].doomed)
    return [Buff(target, health=1, source_id=c.source_id),
        GrantSpellDamage(target, 1, source_id=c.source_id),
        Destroy(target, c.source_id)]


def configure(fixture, case):
    if case[0] == 'account':
        payment, replacement = case[1:]
        fixture.granter('fee.account.prepare', (
            AddCostModifier(1, CostSpec(payment=payment, card_types=(CardType.SPELL,)),
                uses_remaining=1),
            AddSpellRepeatModifier(1, fixture.fee(maximum=3, casts=2), uses=2)))
        if replacement:
            fixture.minion('fee.account.replacement', health=5,
                health_loss_replacements=(HealthLossReplacementSpec(),))
    elif case[0] == 'witness':
        match = RepeatMatchSpec(
            RecipientMetadataFilter(spell_schools=(SpellSchool.FIRE,)),
            RepeatSourceEligibility('repeat.witness.controlled', tribes_any=('dragon',),
                exclude_carrier=True),
            RepeatCostFilter('window_quote', maximum=0,
                quote_profile_id='repeat.cost.accepted_hand'))
        metadata = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
        fixture.minion('fee.query.source', health=5, metadata=metadata,
            spell_repeats=(SpellRepeatSpec(4, 'other', match),))
        for name, value in (('fee.query.unknown', None),
                ('fee.query.unknown.tribes', CardMetadata(False, (CardClass.NEUTRAL,), None)),
                ('fee.query.known.false', CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('beast',))),
                ('fee.query.known.true', CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('dragon',)))):
            fixture.minion(name, health=5, metadata=value)
        fixture.r.register_behavior('fee.query.prepare', lambda c: [AddCostModifier(1,
            CostSpec(delta=-1, card_types=(CardType.SPELL,)), uses_remaining=1)])
        fixture.minion('fee.query.prepare', health=5, metadata=metadata,
            battlecry='fee.query.prepare')
    elif case[0] == 'highwater':
        fixture.minion('fee.highwater.token', health=2)
        fixture.r.register_behavior('fee.highwater.discard', highwater_discard)
        fixture.rewind_cards(case[1], body=highwater_body)
    else:
        raise ValueError('Unknown explicit account-boundary fixture')


class SpellCostAccountBoundaryTests(unittest.TestCase):
    def setup_case(self, case):
        self.case = case
        self.fixture = base.SpellCostAcceptanceTests()
        self.fixture.setUp()
        configure(self.fixture, case)
        self.registry = self.fixture.r

    def fresh_registry(self):
        fixture = base.SpellCostAcceptanceTests()
        fixture.setUp()
        configure(fixture, self.case)
        self.assertEqual(fixture.r.fingerprint(), self.registry.fingerprint())
        return fixture.r

    def game(self, hand, board=(), *, hero='HERO_01', armor=0, corpses=0):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=('plain',) * 8,
                mana=10, max_mana=10, armor=armor, corpses=corpses),
            PlayerSetup('HERO_08', deck=('plain',) * 8, mana=10, max_mana=10)),
            seed=916), self.registry)

    def portable(self, game):
        snapshot = game.snapshot()
        registry = self.fresh_registry()
        self.assertEqual(Game.from_snapshot(snapshot, registry).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.fresh_registry()).snapshot(), snapshot)
        for seat in (1, 2):
            before = game.observe(seat)
            detached = game.observe(seat)
            detached.clear()
            self.assertEqual(game.observe(seat), before)

    def account_waiting(self, payment, *, replacement=False):
        self.setup_case(('account', payment, replacement))
        game = self.game(('fee.account.prepare', 'fee.ask'),
            board=('fee.account.replacement',) if replacement else (),
            armor=2 if replacement else (3 if payment == PaymentType.ARMOR else 0),
            corpses=3 if payment == PaymentType.CORPSES else 0)
        self.fixture.play(game, 'fee.account.prepare')
        self.fixture.play(game, 'fee.ask')
        proof = self.fixture.proof(game)
        validate_acceptance(proof, self.registry)
        play = game.state.play_history[-1]
        self.assertEqual((play.cost, play.payment), (3, payment))
        self.assertEqual(play.submitted_cost.quote.payment, payment)
        self.assertEqual(play.spell_payload.casts, 2)
        self.assertFalse(game.state.players[1].cost_modifiers)
        self.assertEqual(game.state.players[1].spell_modifiers[0].uses_remaining, 1)
        self.assertEqual(game.state.players[1].mana, 10)
        self.portable(game)
        return game, proof

    def complete_account(self, game):
        restored = Game.from_snapshot(game.snapshot(), self.fresh_registry())
        while game.state.pending_choice:
            self.fixture.choose(game, 'ok')
            self.fixture.choose(restored, 'ok')
            self.assertEqual(restored.snapshot(), game.snapshot())
            self.portable(game)
        play = game.state.play_history[-1]
        self.assertTrue(play.completed and play.spell_acceptance_closed)
        self.assertEqual(len([row for row in game.state.cost_use_history
            if row.source_id == play.source_id]), 1)

    def test_real_paid_spell_armor_account_has_portable_full_cost_proof(self):
        game, _ = self.account_waiting(PaymentType.ARMOR)
        self.assertEqual(self.fixture.hero(game).armor, 0)
        self.assertEqual(self.fixture.hero(game).health, 30)
        self.complete_account(game)
        self.assertEqual(self.fixture.hero(game).armor, 2)

    def test_real_paid_spell_corpses_account_has_portable_full_cost_proof(self):
        game, _ = self.account_waiting(PaymentType.CORPSES)
        self.assertEqual(game.state.players[1].resources[Resource.CORPSES], 0)
        self.assertEqual(self.fixture.hero(game).health, 30)
        self.complete_account(game)
        self.assertEqual(game.state.players[1].resources[Resource.CORPSES], 0)

    def test_real_paid_spell_health_replacement_growth_has_portable_full_cost_proof(self):
        game, proof = self.account_waiting(PaymentType.HEALTH, replacement=True)
        hero = self.fixture.hero(game)
        self.assertEqual((hero.armor, hero.health, hero.max_health), (0, 31, 31))
        growth = [e for e in hero.enchantments if e.label == 'max_health_gain']
        self.assertEqual(len(growth), 1)
        self.assertEqual(growth[0].health, 1)
        validate_hand_cost_proof(proof.cost_proof, self.registry,
            submission_state=proof.submission.state)
        self.complete_account(game)

    def test_postpay_armor_and_corpses_resource_rewrites_are_structurally_valid_but_rejected(self):
        for payment in (PaymentType.ARMOR, PaymentType.CORPSES):
            with self.subTest(payment=payment):
                game, proof = self.account_waiting(payment)
                bad = copy.deepcopy(proof.submission.state)
                if payment == PaymentType.ARMOR:
                    bad.entities[bad.players[1].hero_id].armor += 1
                else:
                    bad.players[1].resources[Resource.CORPSES] += 1
                validate_invariants(bad, self.registry)
                before = game.snapshot()
                with self.assertRaises(ValueError):
                    validate_hand_cost_proof(proof.cost_proof, self.registry,
                        submission_state=bad)
                self.assertEqual(game.snapshot(), before)
                self.complete_account(game)

    def test_health_growth_full_value_rewrite_is_structurally_valid_but_rejected(self):
        game, proof = self.account_waiting(PaymentType.HEALTH, replacement=True)
        bad = copy.deepcopy(proof.submission.state)
        hero = bad.entities[bad.players[1].hero_id]
        index = next(i for i, e in enumerate(hero.enchantments) if e.label == 'max_health_gain')
        hero.enchantments[index] = replace(hero.enchantments[index], health=2)
        refresh_entity(hero)
        validate_invariants(bad, self.registry)
        before = game.snapshot()
        with self.assertRaises(ValueError):
            validate_hand_cost_proof(proof.cost_proof, self.registry, submission_state=bad)
        self.assertEqual(game.snapshot(), before)
        self.complete_account(game)

    def test_health_growth_allocation_rewrite_is_structurally_valid_but_rejected(self):
        game, proof = self.account_waiting(PaymentType.HEALTH, replacement=True)
        bad = copy.deepcopy(proof.submission.state)
        hero = bad.entities[bad.players[1].hero_id]
        index = next(i for i, e in enumerate(hero.enchantments) if e.label == 'max_health_gain')
        old = hero.enchantments[index]
        hero.enchantments[index] = replace(old, id=bad.next_attachment_id)
        bad.next_attachment_id += 1
        validate_invariants(bad, self.registry)
        before = game.snapshot()
        with self.assertRaises(ValueError):
            validate_hand_cost_proof(proof.cost_proof, self.registry, submission_state=bad)
        self.assertEqual(game.snapshot(), before)
        self.complete_account(game)

    def test_fee_class_and_school_false_do_not_short_circuit_unknown_witness_metadata(self):
        self.setup_case(('witness',))
        for witness in ('fee.query.unknown', 'fee.query.unknown.tribes'):
            with self.subTest(witness=witness):
                game = self.game(('fee.query.prepare', 'fee.ask'),
                    board=('fee.query.source', witness), hero='HERO_08')
                self.fixture.play(game, 'fee.query.prepare')
                before = game.snapshot()
                self.assertEqual(game.quote_cost(next(i for i in game.state.players[1].hand
                    if game.state.entities[i].card_id == 'fee.ask')).amount, 2)
                with self.assertRaises((ValueError, ResolutionError)):
                    self.fixture.play(game, 'fee.ask')
                self.assertEqual(game.snapshot(), before)
                self.assertEqual(game.state.players[1].cost_modifiers[0].uses_remaining, 1)
                self.portable(game)

    def test_fee_class_and_school_false_with_known_witnesses_is_portable(self):
        self.setup_case(('witness',))
        for witness in ('fee.query.known.false', 'fee.query.known.true'):
            with self.subTest(witness=witness):
                game = self.game(('fee.query.prepare', 'fee.ask'),
                    board=('fee.query.source', witness), hero='HERO_08')
                self.fixture.play(game, 'fee.query.prepare')
                self.fixture.play(game, 'fee.ask')
                play = game.state.play_history[-1]
                self.assertEqual(play.cost, 2)
                self.assertEqual(play.spell_payload.casts, 1)
                self.assertEqual(play.spell_payload.contributors, ())
                self.assertEqual(play.spell_payload.cost_facts.window_quotes[0].amount, 3)
                self.portable(game)
                self.fixture.choose(game, 'ok')
                self.portable(game)

    def test_true_fee_retries_preserve_real_entity_attachment_and_death_highwaters(self):
        for retries in (1, 2):
            with self.subTest(retries=retries):
                self.setup_case(('highwater', retries))
                game = self.game(('fee.retry.prepare', 'fee.retry'))
                self.fixture.play(game, 'fee.retry.prepare')
                self.fixture.play(game, 'fee.retry')
                source_id = game.state.play_history[-1].source_id
                original_before = copy.deepcopy(game._rewind.before)
                previous_discarded_entities = set()
                previous_discarded_deaths = set()
                for attempt in range(retries + 1):
                    self.portable(game)
                    proof = self.fixture.proof(game)
                    validate_acceptance(proof, self.registry)
                    self.assertEqual(proof.cost_proof.prepared_play.cost, 1)
                    # The repeated Spell span defers deaths until its last iteration.
                    self.assertEqual(len(game.state.death_history), 0)
                    staged = next(game.state.entities[i] for i in game.state.players[1].board
                        if game.state.entities[i].card_id == 'fee.highwater.token')
                    self.assertTrue(staged.doomed)
                    self.assertNotIn(staged.id, previous_discarded_entities)
                    self.assertGreaterEqual(len(staged.enchantments), 1)
                    self.assertTrue(any(a.kind == 'spell_damage' for a in staged.abilities))
                    while game.state.pending_choice and game.state.pending_choice.purpose != ChoicePurpose.REWIND:
                        self.fixture.choose(game, 'ok')
                        self.portable(game)
                    current = game.state
                    self.assertEqual(len(current.death_history), 2)
                    for allocated in current.death_history:
                        self.assertNotIn(allocated.entity_id, previous_discarded_entities)
                        self.assertNotIn(allocated.id, previous_discarded_deaths)
                        self.assertGreaterEqual(len(allocated.enchantments), 1)
                        self.assertTrue(any(a.kind == 'spell_damage' for a in allocated.abilities))
                    for name in COUNTERS:
                        self.assertGreaterEqual(getattr(current, name), getattr(original_before, name))
                    for name in ('next_entity_id', 'next_order', 'next_attachment_id', 'next_death_id', 'next_death_batch'):
                        self.assertGreater(getattr(current, name), getattr(original_before, name))
                    previous_discarded_entities.update(d.entity_id for d in current.death_history)
                    previous_discarded_deaths.update(d.id for d in current.death_history)
                    if attempt < retries:
                        highwater = {name: getattr(current, name) for name in COUNTERS}
                        self.assertEqual(current.pending_choice.purpose, ChoicePurpose.REWIND)
                        self.fixture.choose(game, 'retry')
                        for name, value in highwater.items():
                            self.assertGreaterEqual(getattr(game.state, name), value)
                        self.assertTrue(previous_discarded_entities.isdisjoint(game.state.entities))
                self.assertIsNone(game.state.pending_choice)
                self.assertEqual(game.state.play_history[-1].card_id, 'fee.retry.last')
                self.assertEqual(game.state.players[1].cost_modifiers[0].uses_remaining, 1)
                self.assertEqual(len([r for r in game.state.cost_use_history if r.source_id == source_id]), 1)
                self.assertEqual(len([e for e in game.events if e.kind == 'mana_spent' and e.source_id == source_id]), retries + 1)
                self.assertEqual(len([e for e in game.events if e.kind == 'timeline_rewound']), retries)
                self.portable(game)


if __name__ == '__main__':
    unittest.main()
