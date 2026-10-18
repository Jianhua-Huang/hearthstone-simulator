"""Only the complete pinned Bones faces may omit their two native display slots."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tools.card_batch import check_face
from hs_sim.targets import canonical_digest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = json.loads((ROOT/'data/support/card-source-bones-display-v1.json').read_text(encoding='utf-8'))


class BonesDisplayTests(unittest.TestCase):
    def faces(self):
        for locale, observation in SUPPORT['faces'].items():
            yield locale, observation['face']
    def test_complete_support_and_both_primary_faces(self):
        self.assertEqual(canonical_digest(SUPPORT), 'a1765294d0f4d81c409318fde39bd40cceb9fec8a50fc03158d6e6c127e78da2')
        for locale, face in self.faces(): check_face(SUPPORT['record'], face, locale, SUPPORT['normalizations'])
    def test_both_slots_must_be_explicitly_declared(self):
        for declaration in (None, {}, {'{0}': ''}, {'{1}': ''}):
            for locale, face in self.faces():
                with self.assertRaises(ValueError): check_face(SUPPORT['record'], face, locale, declaration)
    def test_modified_complete_original_record_cannot_borrow_exception(self):
        for field, value in (('id', 'different'), ('cost', 3), ('text', '使一个随从获得+{0}/+{1}。额外规则。')):
            row = deepcopy(SUPPORT['record']); row[field] = value
            for locale, face in self.faces():
                with self.assertRaises(ValueError): check_face(row, face, locale, SUPPORT['normalizations'])
    def test_primary_numbers_or_extra_rules_are_not_dynamic_display_omission(self):
        for locale, original in self.faces():
            for text in ('Give a minion +0/+0.', 'Give a minion +1/+1.', 'Give a minion + /+ . Draw a card.'):
                face = deepcopy(original); face['text'] = text
                with self.assertRaises(ValueError): check_face(SUPPORT['record'], face, locale, SUPPORT['normalizations'])
    def test_other_substitutions_and_unreviewed_macros_reject(self):
        for declaration in ({'{0}': '0', '{1}': '0'}, {'{0}': '', '{1}': '', '@': ''}, {'{0}': '', '{2}': ''}):
            for locale, face in self.faces():
                with self.assertRaises(ValueError): check_face(SUPPORT['record'], face, locale, declaration)
    def test_primary_identity_and_cost_stay_strict(self):
        for locale, original in self.faces():
            for field, value in (('id', 1), ('manaCost', 9)):
                face = deepcopy(original); face[field] = value
                with self.assertRaises(ValueError): check_face(SUPPORT['record'], face, locale, SUPPORT['normalizations'])


if __name__ == '__main__': unittest.main()
