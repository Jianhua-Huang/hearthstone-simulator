"""Candidate membership must preserve unimplemented, future and cross-set records."""

import unittest

from hs_sim.catalog import CardCatalog
from hs_sim.standard_inventory import build_standard_inventory


def record(cid, dbf, card_set, **kwargs):
    row = dict(id=cid, dbf_id=dbf, name=cid, collectible=True, type='MINION',
               card_set_id=card_set, tags={})
    row.update(kwargs)
    return row


class StandardInventoryTests(unittest.TestCase):
    def policy(self):
        return dict(mode='STANDARD', formal_pool_complete=False,
                    candidate_set_ids=[1637, 1941], early_available_ids=['BE_036'])

    def test_actual_set_not_core_prefix_controls_candidates_and_future_records_remain(self):
        rows = [record('CORE_retired', 1, 1810), record('new_core', 2, 1637),
                record('BE_036', 3, 1994), record('BE_future', 4, 1994),
                record('event_pending', 5, 1941)]
        data = build_standard_inventory(CardCatalog(rows), self.policy(), ('CORE_retired',))
        self.assertEqual(data['candidate_root_ids'], ['BE_036', 'event_pending', 'new_core'])
        self.assertEqual(len(data['records']), 5)
        self.assertEqual(data['registered_candidate_root_count'], 0)
        self.assertFalse(data['formal_pool_complete'])
        self.assertTrue(all(r['membership_review_required'] for r in data['records']))

    def test_cross_set_static_hints_keep_cycles_and_unresolved_references_without_claiming_complete(self):
        rows = [record('BE_036', 1, 1994, related_dbf_ids=[2, 999]),
                record('cross_token', 2, 12, collectible=False,
                    xml_card_references=[dict(tag='next', dbf_id=3)]),
                record('other_token', 3, 12, collectible=False, related_dbf_ids=[2])]
        data = build_standard_inventory(CardCatalog(rows), self.policy())
        self.assertEqual(data['static_dependency_hint_ids'], ['cross_token', 'other_token'])
        self.assertEqual(data['unresolved_static_hints'][0]['dbf_id'], 999)
        self.assertFalse(data['reachability_complete'])
        self.assertEqual(len(data['records']), 3)

    def test_definition_presence_never_becomes_legality_or_effect_verification(self):
        rows = [record('BE_036', 1, 1994), record('unimplemented', 2, 1637)]
        data = build_standard_inventory(CardCatalog(rows), self.policy(), ('BE_036',))
        self.assertEqual(data['candidate_root_ids'], ['BE_036', 'unimplemented'])
        self.assertEqual(data['registered_candidate_root_count'], 1)
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['reachability_complete'])
        self.assertNotIn('supported', data['records'][0])

    def test_unknown_early_exception_and_false_formal_claim_are_rejected(self):
        catalog = CardCatalog([record('BE_036', 1, 1994)])
        for field, value in [('early_available_ids', ['missing']), ('candidate_set_ids', [True]),
                             ('formal_pool_complete', True), ('mode', 'WILD')]:
            with self.subTest(field=field):
                policy = self.policy(); policy[field] = value
                with self.assertRaises(ValueError):
                    build_standard_inventory(catalog, policy)

    def test_explicit_exclusion_keeps_full_source_and_reachable_hint_even_if_registered(self):
        rows = [record('BE_036', 1, 1994, related_dbf_ids=[2]),
                record('event_future', 2, 1941), record('event_available', 3, 1941)]
        policy = self.policy(); policy['excluded_ids'] = ['event_future']
        data = build_standard_inventory(CardCatalog(rows), policy, ('event_future', 'event_available'))
        self.assertEqual(data['candidate_root_ids'], ['BE_036', 'event_available'])
        self.assertEqual(data['registered_candidate_root_count'], 1)
        self.assertEqual(data['candidate_counts_by_set'], {'1941': 1, '1994': 1})
        self.assertEqual(data['static_dependency_hint_ids'], ['event_future'])
        self.assertEqual(len(data['records']), 3)
        excluded = next(r for r in data['records'] if r['id'] == 'event_future')
        self.assertEqual(excluded['candidate_reason'], 'explicitly_excluded_root')
        self.assertFalse(excluded['standard_candidate'])
        self.assertTrue(excluded['registered_definition_present'])
        self.assertTrue(excluded['membership_review_required'])
        self.assertFalse(data['formal_pool_complete'])
        self.assertFalse(data['reachability_complete'])

    def test_exclusions_reject_unknown_nonroot_conflicting_and_malformed_id_declarations(self):
        catalog = CardCatalog([record('BE_036', 1, 1994), record('event_future', 2, 1941),
                               record('token', 3, 1941, collectible=False)])
        for excluded in (None, 'event_future', [True], [[]], [''], [' event_future'],
                         ['missing'], ['token'], ['BE_036'], ['event_future', 'event_future']):
            with self.subTest(excluded=excluded):
                policy = self.policy(); policy['excluded_ids'] = excluded
                with self.assertRaises(ValueError):
                    build_standard_inventory(catalog, policy)
