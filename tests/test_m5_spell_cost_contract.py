"""Fee declarations, complete frozen operands and public/private separation."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest

from hs_sim.engine import (CostQueryProfile, CostQuoteInput, CostContribution,
    CostQuoteFact, HandPlayCostReceipt, SpellCostFacts, RepeatCostFilter,
    RepeatMatchSpec, Registry)
from hs_sim.engine.model import (AbilityInstance, CardClass, CardDefinition, CardMetadata, CardType,
    CostModifier, CostSpec, Enchantment, PaymentType, RecipientMetadataFilter,
    SpellRepeatModifier, SpellRepeatSpec, SpellSchool)
from hs_sim.engine.model import (
    IntrinsicCostStageFact, OwnerTurnQueryBoundaryFact, OwnerTurnRecord,
)
from hs_sim.engine.repeat_matching import (repeat_match_from_dict, repeat_match_to_dict,
    repeat_match_public_from_dict, repeat_match_public_to_dict,
    spell_repeat_recipient_matches, validate_cost_quote_fact,
    validate_repeat_cost_declaration, validate_spell_cost_facts)
from hs_sim.engine.serialization import _cost_quote_fact_from_dict, _spell_cost_facts_from_dict
from hs_sim.engine.spell_modifiers import public_modifier
from hs_sim.engine.information import VIEW_VERSION, validate_spell_modifier_view


class SpellCostContractTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('fee-contract-v1')
        self.definition = CardDefinition('fee.spell', 'Fee Spell', CardType.SPELL,
            cost=10, metadata=CardMetadata(False, (CardClass.MAGE,), None),
            spell_school=SpellSchool.ARCANE)
        self.registry.register_card(self.definition)

    def empty_intrinsic(self, value):
        # Pure frozen-algebra scenario fixture, without Game/event provenance.
        interval = OwnerTurnRecord(1, 1, 1, 1, None, 0, 0, 'scenario')
        boundary = OwnerTurnQueryBoundaryFact(1, 0, 'playing', 1, 0,
            interval, None, None)
        return IntrinsicCostStageFact('cost.intrinsic.before-local-v1',
            value.player_id, value.card_id, value.kind, 10,
            value.base_cost, value.base_cost, boundary, (), (), ())

    def quote(self, *, delta=-8, profile=None, modifier=None):
        enchantment = Enchantment(1, cost=delta)
        value = CostQuoteInput(7, 1, self.definition.id, CardType.SPELL,
            10, (enchantment,), (), 0)
        contributions = [CostContribution('local_enchantment', 1, 7, enchantment=enchantment)]
        local = max(0, 10 + delta)
        amount = local
        if modifier is not None:
            contributions.append(CostContribution('player_modifier', 1, None, modifier=modifier))
            from hs_sim.engine.costs import apply_cost
            amount = apply_cost(amount, modifier.spec.delta, modifier.spec.set_to, modifier.spec.minimum)
        ids = () if modifier is None else (modifier.id,)
        uses = ids if modifier is not None and modifier.uses_remaining is not None else ()
        return CostQuoteFact(profile, value, local, PaymentType.MANA, amount,
            PaymentType.MANA, tuple(contributions), ids, uses, intrinsic=self.empty_intrinsic(value))

    def facts(self, quote=None):
        quote = quote or self.quote(profile='repeat.cost.accepted_hand')
        return SpellCostFacts(10, quote.quote_input, quote.local_amount,
            quote.local_payment, intrinsic=quote.intrinsic, window_quotes=(quote,))

    def spec(self, basis='window_quote', **bounds):
        profile = 'repeat.cost.accepted_hand' if basis == 'window_quote' else None
        return SpellRepeatSpec(2, 'any', RepeatMatchSpec(recipient_cost=
            RepeatCostFilter(basis, quote_profile_id=profile, **bounds)))

    def test_inclusive_zero_and_range_bounds_reject_untyped_values(self):
        for minimum, maximum in ((0, 0), (1, 2), (None, 2), (2, None)):
            with self.subTest(bounds=(minimum, maximum)):
                RepeatCostFilter('printed', minimum, maximum)
        for kwargs in ({}, {'minimum': True}, {'maximum': -1},
                {'minimum': 3, 'maximum': 2}, {'maximum': 2.0}):
            with self.subTest(invalid=kwargs), self.assertRaises(ValueError):
                RepeatCostFilter('printed', **kwargs)

    def test_payment_and_unnamed_price_bases_are_not_numeric_cost_aliases(self):
        for basis in ('actual_payment', 'current_quote', 'paid', '', True):
            with self.subTest(basis=basis), self.assertRaises(ValueError):
                RepeatCostFilter(basis, maximum=2)
        with self.assertRaises(ValueError):
            RepeatCostFilter('window_quote', maximum=2)
        with self.assertRaises(ValueError):
            RepeatCostFilter('submitted_quote', maximum=2, quote_profile_id='repeat.cost.accepted_hand')

    def test_registered_cost_profile_is_immutable_and_fingerprinted(self):
        before = self.registry.fingerprint()
        self.registry.register_cost_query_profile(CostQueryProfile('fee.other'))
        self.assertNotEqual(before, self.registry.fingerprint())
        self.assertEqual(self.registry.cost_query_profile('fee.other').minimum_basis, 'submitted_hand')
        with self.assertRaises(TypeError):
            self.registry.cost_query_profiles['fake'] = CostQueryProfile('fake')
        with self.assertRaises(ValueError):
            CostQueryProfile('bad', external_basis='ignore_auras')
        self.registry.freeze()
        with self.assertRaises(ValueError):
            self.registry.register_cost_query_profile(CostQueryProfile('fee.later'))

    def test_unknown_profile_is_rejected_for_an_otherwise_false_declaration(self):
        spec = SpellRepeatSpec(2, 'any', RepeatMatchSpec(
            RecipientMetadataFilter(spell_schools=(SpellSchool.FIRE,)),
            recipient_cost=RepeatCostFilter('window_quote', maximum=0, quote_profile_id='missing')))
        with self.assertRaises(ValueError):
            validate_repeat_cost_declaration(self.registry, spec)
        with self.assertRaises(ValueError):
            self.registry.register_card(CardDefinition('bad.source', 'Bad Source', CardType.MINION,
                attack=1, health=2, spell_repeats=(spec,)))
        frozen_input = replace(self.facts().cost_input,
            abilities=(AbilityInstance(4, 'spell_repeat', spell_repeat=spec),))
        facts = SpellCostFacts(10, frozen_input, 2, PaymentType.MANA, intrinsic=self.empty_intrinsic(frozen_input))
        with self.assertRaises(ValueError):
            validate_spell_cost_facts(self.registry, facts)

    def test_printed_local_submitted_and_window_prices_remain_distinct(self):
        window = self.quote(delta=-7, profile='repeat.cost.accepted_hand',
            modifier=CostModifier(3, CostSpec(delta=-1), uses_remaining=1))
        facts = self.facts(window)
        submitted = HandPlayCostReceipt('current_hand', 1, 1, 1, 1, 10,
            self.quote(delta=-9))
        for basis, price in (('printed', 10), ('local', 3), ('submitted_quote', 1), ('window_quote', 2)):
            with self.subTest(basis=basis):
                self.assertTrue(spell_repeat_recipient_matches(self.spec(basis, minimum=price, maximum=price),
                    recipient_definition=self.definition, hero_class=CardClass.WARRIOR,
                    submitted_cost=submitted, cost_facts=facts))
                self.assertFalse(spell_repeat_recipient_matches(self.spec(basis, maximum=price-1),
                    recipient_definition=self.definition, hero_class=CardClass.WARRIOR,
                    submitted_cost=submitted, cost_facts=facts))

    def test_school_and_class_intersect_the_cost_filter(self):
        spec = SpellRepeatSpec(2, 'other', RepeatMatchSpec(
            RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,)),
            recipient_cost=RepeatCostFilter('window_quote', maximum=2,
                quote_profile_id='repeat.cost.accepted_hand')))
        self.assertTrue(spell_repeat_recipient_matches(spec, recipient_definition=self.definition,
            hero_class=CardClass.WARRIOR, cost_facts=self.facts()))
        self.assertFalse(spell_repeat_recipient_matches(spec, recipient_definition=self.definition,
            hero_class=CardClass.MAGE, cost_facts=self.facts()))
        fire = replace(spec, match=replace(spec.match,
            recipient_metadata=RecipientMetadataFilter(spell_schools=(SpellSchool.FIRE,))))
        self.assertFalse(spell_repeat_recipient_matches(fire, recipient_definition=self.definition,
            hero_class=CardClass.WARRIOR, cost_facts=self.facts()))

    def test_cost_fact_absence_is_an_error_even_when_school_is_false(self):
        spec = replace(self.spec(maximum=2), match=replace(self.spec(maximum=2).match,
            recipient_metadata=RecipientMetadataFilter(spell_schools=(SpellSchool.FIRE,))))
        with self.assertRaises(ValueError):
            spell_repeat_recipient_matches(spec, recipient_definition=self.definition,
                hero_class=CardClass.WARRIOR)
        with self.assertRaises(ValueError):
            spell_repeat_recipient_matches(self.spec('submitted_quote', maximum=2),
                recipient_definition=self.definition, hero_class=CardClass.WARRIOR, cost_facts=self.facts())

    def test_complete_frozen_quote_rejects_result_and_source_mutation(self):
        quote = self.quote(profile='repeat.cost.accepted_hand',
            modifier=CostModifier(3, CostSpec(delta=-1), uses_remaining=2))
        validate_cost_quote_fact(self.registry, quote)
        for altered in (replace(quote, amount=9), replace(quote, local_amount=9)):
            with self.subTest(amount=altered.amount), self.assertRaises(ValueError):
                validate_cost_quote_fact(self.registry, altered)
        source = replace(quote.contributions[-1], modifier=replace(quote.contributions[-1].modifier,
            spec=CostSpec(delta=-1, card_ids=('another.face',))))
        with self.assertRaises(ValueError):
            validate_cost_quote_fact(self.registry, replace(quote,
                contributions=(*quote.contributions[:-1], source)))

    def test_complete_contribution_order_and_finite_source_set_are_exact(self):
        quote = self.quote(modifier=CostModifier(3, CostSpec(delta=-1), uses_remaining=2))
        with self.assertRaises(ValueError):
            replace(quote, contributions=tuple(reversed(quote.contributions)))
        with self.assertRaises(ValueError):
            replace(quote, consumable_ids=())
        with self.assertRaises(ValueError):
            replace(quote, modifier_ids=(3, 3))
        with self.assertRaises(ValueError):
            replace(quote.contributions[-1], enchantment=quote.quote_input.enchantments[0])

    def test_exact_private_wire_preserves_facts_and_rejects_missing_new_fields(self):
        raw = json.loads(json.dumps(asdict(self.facts())))
        self.assertEqual(_spell_cost_facts_from_dict(raw), self.facts())
        broken = deepcopy(raw)
        broken['window_quotes'][0].pop('contributions')
        with self.assertRaises(ValueError):
            _spell_cost_facts_from_dict(broken)
        broken = deepcopy(raw)
        broken['cost_input']['minimum_cost'] = True
        with self.assertRaises(ValueError):
            _spell_cost_facts_from_dict(broken)
        broken = json.loads(json.dumps(asdict(self.quote())))
        broken['payment'] = 'paid'
        with self.assertRaises(ValueError):
            _cost_quote_fact_from_dict(broken)

    def test_private_declaration_requires_the_cost_field_and_roundtrips(self):
        match = self.spec(maximum=2).match
        wire = repeat_match_to_dict(match)
        self.assertEqual(repeat_match_from_dict(wire), match)
        wire.pop('recipient_cost')
        with self.assertRaises(ValueError):
            repeat_match_from_dict(wire)

    def test_public_fee_parameters_exclude_private_cost_sources_and_receipts(self):
        modifier = SpellRepeatModifier(9, self.spec(maximum=2), 17, 'hidden.source', 1, uses_remaining=2)
        public = public_modifier(modifier)
        self.assertEqual(VIEW_VERSION, 'player-view-v122')
        validate_spell_modifier_view(public, 'spell_modifier_added')
        self.assertEqual(public['match'], {'recipient_metadata': None, 'recipient_cost': {
            'basis': 'window_quote', 'minimum': None, 'maximum': 2,
            'quote_profile_id': 'repeat.cost.accepted_hand'}})
        self.assertEqual(repeat_match_public_from_dict(public['match']), modifier.spec.match)
        serialized = json.dumps(public)
        for private in ('hidden.source', 'source_id', 'contributions', 'submitted_cost', 'cost_facts'):
            self.assertNotIn(private, serialized)
        forged = deepcopy(public['match'])
        forged['recipient_cost']['cost_facts'] = asdict(self.facts())
        with self.assertRaises(ValueError):
            repeat_match_public_from_dict(forged)

    def test_legacy_cost_input_import_is_the_same_registered_frozen_type(self):
        from hs_sim.engine.costs import CostQuoteInput as legacy
        self.assertIs(legacy, CostQuoteInput)


if __name__ == '__main__':
    unittest.main()
