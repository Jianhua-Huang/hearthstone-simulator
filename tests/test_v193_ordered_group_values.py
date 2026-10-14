"""Unexecuted ordered-group component tests; full engine integration remains open."""
from copy import deepcopy
from dataclasses import asdict, replace
from random import Random
import json
import unittest

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SummonStats, Zone
from hs_sim.engine.registry import Registry
from hs_sim.engine.summon_quantities import SummonCause, SummonEntryMaterial
from hs_sim.engine.ordered_summon_groups import (GroupSummonEntryLink, OrderedGroupMember,
    OrderedGroupSelection, OrderedSummonGroupSpec, SelectedGroupOccurrence, from_dict,
    select, validate_selection)


def registry():
    result = Registry('ordered-group-component-only')
    result.register_card(CardDefinition('cause', 'Cause', CardType.SPELL))
    result.register_card(CardDefinition('a', 'First body', CardType.MINION, attack=1, health=2))
    result.register_card(CardDefinition('b', 'Second body', CardType.MINION, attack=3, health=4))
    result.register_card(CardDefinition('spell', 'Unsupported body', CardType.SPELL))
    result.register_card(CardDefinition('magnetic', 'Unsupported composite', CardType.MINION,
                                        attack=1, health=1, keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',)))
    result.register_behavior('dr', lambda c: [])
    return result


def request(members=None, **kwargs):
    cause = SummonCause(SourceAllocationFact(1, 'cause', CardType.SPELL, 1, 1,
                                            Zone.GRAVEYARD, 0, 1, 2, 2), 1, 1, 0)
    if members is None:
        members = (OrderedGroupMember('left-a', SummonEntryMaterial('a'), 0),
                   OrderedGroupMember('middle-b', SummonEntryMaterial('b'), 1),
                   OrderedGroupMember('right-a', SummonEntryMaterial('a'), 2))
    return OrderedSummonGroupSpec(1, cause, members, **kwargs)


class OrderedGroupValueTests(unittest.TestCase):
    def test_original_equal_faces_preserve_distinct_occurrences_and_positions_without_rng(self):
        rng = Random(193); before = rng.getstate()
        value = select(registry(), request(), 0, rng)
        self.assertEqual([(m.index, m.member_key, m.material.card_id, m.position, m.extra_ordinal)
                          for m in value.occurrences],
                         [(0, 'left-a', 'a', 0, None), (1, 'middle-b', 'b', 1, None),
                          (2, 'right-a', 'a', 2, None)])
        self.assertEqual(rng.getstate(), before)
        self.assertEqual(value.rng_before, value.rng_after)

    def test_one_additional_member_is_one_extra_for_the_whole_group(self):
        rng = Random(194)
        spec = request(extra_policy='weighted_occurrence_with_replacement')
        value = select(registry(), spec, 1, rng)
        self.assertEqual(len(value.occurrences), 4)
        self.assertEqual([m.extra_ordinal for m in value.occurrences], [None, None, None, 0])
        self.assertEqual(value.spec, spec)
        self.assertEqual(len(value.spec.members), 3)

    def test_each_extra_is_an_independent_weighted_physical_occurrence_draw(self):
        members = (OrderedGroupMember('a-plain', SummonEntryMaterial('a'), extra_weight=1),
                   OrderedGroupMember('a-taunt', SummonEntryMaterial('a', keywords=(Keyword.TAUNT,)), extra_weight=2),
                   OrderedGroupMember('b-body', SummonEntryMaterial('b'), extra_weight=4))
        spec = request(members, extra_policy='weighted_occurrence_with_replacement', extra_position=0)
        local = Random(195)
        tickets = [local.randrange(7) for _ in range(12)]
        expected = ['a-plain' if t == 0 else 'a-taunt' if t < 3 else 'b-body' for t in tickets]
        value = select(registry(), spec, 12, Random(195))
        self.assertEqual([m.member_key for m in value.occurrences[3:]], expected)
        self.assertEqual([m.extra_ordinal for m in value.occurrences[3:]], list(range(12)))
        self.assertEqual([m.position for m in value.occurrences[3:]], [0] * 12)
        self.assertEqual(value.rng_after, local.getstate())
        recipes = {m.occurrence_key: m.material for m in members}
        self.assertTrue(all(m.material == recipes[m.member_key] for m in value.occurrences))

    def test_zero_extra_weight_does_not_remove_an_original_body(self):
        members = (OrderedGroupMember('zero', SummonEntryMaterial('a'), extra_weight=0),
                   OrderedGroupMember('one', SummonEntryMaterial('b'), extra_weight=1))
        value = select(registry(), request(members, extra_policy='weighted_occurrence_with_replacement'), 4, Random(196))
        self.assertEqual([m.member_key for m in value.occurrences], ['zero', 'one', 'one', 'one', 'one', 'one'])

    def test_original_recipes_include_stats_keywords_and_deathrattles(self):
        recipe = SummonEntryMaterial('a', SummonStats(5, 6), ('dr',), (Keyword.TAUNT,))
        spec = request((OrderedGroupMember('recipe', recipe),), extra_policy='weighted_occurrence_with_replacement')
        value = select(registry(), spec, 2, Random(197))
        self.assertEqual(tuple(m.material for m in value.occurrences), (recipe, recipe, recipe))
        validate_selection(registry(), value)

    def test_empty_original_group_with_no_extras_keeps_empty_and_no_rng(self):
        rng = Random(198); before = rng.getstate()
        value = select(registry(), request(()), 0, rng)
        self.assertEqual(value.occurrences, ())
        self.assertEqual(rng.getstate(), before)

    def test_unavailable_extra_domain_and_unknown_policy_fail_before_rng(self):
        for spec in (request(), request((), extra_policy='weighted_occurrence_with_replacement'),
                     request((OrderedGroupMember('zero', SummonEntryMaterial('a'), extra_weight=0),),
                             extra_policy='weighted_occurrence_with_replacement')):
            rng = Random(199); before = rng.getstate()
            with self.assertRaises(ValueError): select(registry(), spec, 1, rng)
            self.assertEqual(rng.getstate(), before)
        with self.assertRaises(ValueError): request(extra_policy='guess')

    def test_unknown_body_including_zero_weight_is_rejected_before_random_draw(self):
        spec = request((OrderedGroupMember('unknown', SummonEntryMaterial('missing'), extra_weight=0),
                        OrderedGroupMember('known', SummonEntryMaterial('a'))),
                       extra_policy='weighted_occurrence_with_replacement')
        rng = Random(200); before = rng.getstate()
        with self.assertRaises(ValueError): select(registry(), spec, 1, rng)
        self.assertEqual(rng.getstate(), before)

    def test_nonminion_and_unsupported_composite_recipe_are_explicitly_rejected(self):
        for card_id in ('spell', 'magnetic'):
            spec = request((OrderedGroupMember('body', SummonEntryMaterial(card_id)),))
            with self.assertRaises(ValueError): select(registry(), spec, 0, Random(201))

    def test_duplicate_occurrence_keys_and_invalid_numeric_values_are_rejected(self):
        with self.assertRaises(ValueError):
            request((OrderedGroupMember('same', SummonEntryMaterial('a')),
                     OrderedGroupMember('same', SummonEntryMaterial('b'))))
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError): OrderedGroupMember('slot', SummonEntryMaterial('a'), extra_weight=value)
            with self.assertRaises(ValueError): select(registry(), request(), value, Random(202))
            with self.assertRaises(ValueError): GroupSummonEntryLink(1, value)

    def test_full_selection_value_roundtrips_with_all_occurrences_and_rng(self):
        value = select(registry(), request(extra_policy='weighted_occurrence_with_replacement'), 3, Random(203))
        payload = json.loads(json.dumps(asdict(value)))
        restored = from_dict(OrderedGroupSelection, payload)
        self.assertEqual(restored, value)
        validate_selection(registry(), restored)

    def test_selection_rejects_truncation_reordering_material_or_extra_count_tamper(self):
        value = select(registry(), request(extra_policy='weighted_occurrence_with_replacement'), 2, Random(204))
        changes = ({'occurrences': value.occurrences[:-1]},
                   {'occurrences': (value.occurrences[1], value.occurrences[0], *value.occurrences[2:])},
                   {'occurrences': (replace(value.occurrences[0], material=SummonEntryMaterial('b')), *value.occurrences[1:])},
                   {'additional': 1})
        for change in changes:
            with self.assertRaises(ValueError): replace(value, **change)

    def test_rng_and_position_tamper_cannot_match_the_same_selection_value(self):
        value = select(registry(), request(extra_policy='weighted_occurrence_with_replacement'), 1, Random(205))
        with self.assertRaises(ValueError): replace(value, rng_after=Random(999).getstate())
        altered = replace(value.occurrences[-1], position=3)
        with self.assertRaises(ValueError): replace(value, occurrences=(*value.occurrences[:-1], altered))
        payload = json.loads(json.dumps(asdict(value)))
        payload['spec']['unexpected'] = True
        with self.assertRaises(ValueError): from_dict(OrderedGroupSelection, payload)

    def test_group_links_have_a_distinct_wire_namespace_and_cannot_decode_pool_shapes(self):
        group = GroupSummonEntryLink(7, 2)
        self.assertEqual(asdict(group), {'group_id': 7, 'index': 2})
        self.assertEqual(from_dict(GroupSummonEntryLink, asdict(group)), group)
        with self.assertRaises(ValueError): from_dict(GroupSummonEntryLink, {'batch_id': 7, 'index': 2})
        with self.assertRaises(ValueError): from_dict(object, {})


if __name__ == '__main__':
    unittest.main()
