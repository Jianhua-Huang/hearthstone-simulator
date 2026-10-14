"""The candidate census is deterministic and cannot certify a legal pool."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tools.inventory_mechanisms import inventory,validate_plan


class MechanismInventoryTests(unittest.TestCase):
    def setUp(self):
        self.plan=json.loads((Path(__file__).resolve().parents[1]/'data/support/m5-mechanism-plan.json').read_text(encoding='utf-8'))
        self.cards=[{'id':'a','collectible':True,'tags':{'COMBO':1,'NEW_TAG':1}},
                    {'id':'b','collectible':False,'tags':{'OUTCAST':1}},
                    {'id':'c','collectible':True,'tags':{'COMBO':0}}]

    def run_inventory(self):return inventory(self.cards,self.plan,self.plan['source_sha256'])

    def test_count_records_once_across_multiple_family_tags(self):
        self.cards[0]['tags']['OUTCAST']=1
        result=self.run_inventory();row=next(f for f in result['families'] if f['id']=='play_history')
        self.assertEqual((row['all_record_matches'],row['collectible_record_matches']),(2,1))
        self.assertEqual(row['example_records'][0]['id'],'a');self.assertEqual(len(row['example_records'][0]['data_sha256']),64)

    def test_candidate_counts_are_not_formal_pool(self):
        result=self.run_inventory();self.assertIsNone(result['full_pool_count']);self.assertFalse(result['inventory_complete'])
        self.assertFalse(result['mode_legality_verified']);self.assertEqual(result['collectible_flag_records'],2)

    def test_unassigned_tags_remain_explicit(self):
        self.assertEqual(self.run_inventory()['unassigned_named_tags'],{'NEW_TAG':1})

    def test_order_independent_and_input_is_unchanged(self):
        before=deepcopy(self.cards);result=self.run_inventory();self.cards.reverse()
        self.assertEqual(self.run_inventory(),result);self.assertEqual(list(reversed(self.cards)),before)

    def test_source_fingerprint_mismatch_rejected(self):
        with self.assertRaises(ValueError):inventory(self.cards,self.plan,'wrong')

    def test_duplicate_card_identity_rejected(self):
        self.cards.append(deepcopy(self.cards[0]))
        with self.assertRaises(ValueError):self.run_inventory()

    def test_dependency_cycle_rejected(self):
        self.plan['families'][0]['depends_on']=['play_history']
        with self.assertRaises(ValueError):validate_plan(self.plan)

    def test_unknown_dependency_rejected(self):
        self.plan['families'][0]['depends_on']=['unknown']
        with self.assertRaises(ValueError):validate_plan(self.plan)

    def test_duplicate_tag_assignment_rejected(self):
        self.plan['families'][1]['tags'].append('COMBO')
        with self.assertRaises(ValueError):validate_plan(self.plan)

    def test_complete_claim_rejected(self):
        self.plan['inventory_complete']=True
        with self.assertRaises(ValueError):validate_plan(self.plan)

    def test_declared_contract_paths_exist(self):
        root=Path(__file__).resolve().parents[1]
        for paths in self.plan['contracts'].values():
            for path in paths:self.assertTrue((root/path).is_file(),path)


if __name__=='__main__':unittest.main()
