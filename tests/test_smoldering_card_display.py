"""Pinned complete Smoldering display forms, without dropping either rule body."""
from copy import deepcopy
from pathlib import Path
import unittest

from tools import card_batch as batch


class SmolderingCardDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=batch.read(Path(__file__).resolve().parents[1]/'data/support/card-source-smoldering-display-v1.json')
        if batch.canonical(cls.data)!='3ba41812d719d4b0ee1caf5c1158e24c86e4190ca3a5b0ff99f32731052bbdda':
            raise ValueError('Complete original display fixture changed')
        cls.rows={r['record']['id']:r['record']for r in cls.data['records']}
        cls.markers={'@':'','{0}':'','{1}':''}

    def test_four_primary_faces_keep_both_complete_original_bodies(self):
        before=deepcopy(self.data)
        for o in self.data['observations']:
            raw=self.rows[o['card_id']]
            self.assertEqual(len(raw['text'if o['locale']=='zh_CN'else'text_en'].split('@')),2)
            batch.check_face(raw,o['face'],o['locale'],self.markers)
            with self.assertRaises(ValueError):batch.check_face(raw,o['face'],o['locale'])
        self.assertEqual(self.data,before)

    def test_omitted_branch_and_changed_primary_rules_are_rejected(self):
        for o in self.data['observations']:
            raw=self.rows[o['card_id']];text=o['face']['text']
            changed=text.replace('friendly','opposing').replace('enemy','friendly').replace('友方','敌方').replace('所有敌方','所有友方')
            for value in (text[:len(text)//2],changed):
                with self.assertRaises(ValueError):
                    batch.check_face(raw,dict(o['face'],text=value),o['locale'],self.markers)

    def test_unpinned_source_rule_or_initial_counter_change_is_rejected(self):
        for o in self.data['observations']:
            for key in ('TAG_SCRIPT_DATA_NUM_1','TAG_SCRIPT_DATA_NUM_2'):
                raw=deepcopy(self.rows[o['card_id']]);raw['tags'][key]+=1
                with self.assertRaises(ValueError):batch.check_face(raw,o['face'],o['locale'],self.markers)

    def test_undeclared_and_partial_macro_shapes_are_rejected(self):
        o=self.data['observations'][0];raw=self.rows[o['card_id']]
        for markers in ({'@':'','{0}':''},{'@':'','{0}':'1','{1}':''},{'@':'','{0}':'','{2}':''}):
            with self.assertRaises(ValueError):batch.check_face(raw,o['face'],o['locale'],markers)

    def test_primary_metadata_and_identity_remain_strict(self):
        o=self.data['observations'][0];raw=self.rows[o['card_id']]
        for key,value in (('manaCost',99),('cardTypeId',4),('classId',9),('id',1)):
            with self.assertRaises(ValueError):
                batch.check_face(raw,dict(o['face'],**{key:value}),o['locale'],self.markers)
