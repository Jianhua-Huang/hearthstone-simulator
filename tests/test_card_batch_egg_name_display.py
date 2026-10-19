"""A single complete Egg source may omit only its runtime Dragon name."""
from copy import deepcopy
from pathlib import Path
import unittest

from tools.card_batch import read, canonical, check_face

SUPPORT = read(Path(__file__).resolve().parents[1] / 'data/support/card-source-egg-name-display-v1.json')


class EggNameDisplayTests(unittest.TestCase):
    def check(self, row, face, locale, declaration={'{0}': ''}):
        return check_face(row, face, locale, declaration, numeric_normalizations={'attack': 0})
    def test_complete_support_and_explicit_name_only_omission_in_both_full_faces(self):
        self.assertEqual(canonical(SUPPORT), '84da371cdfad9a165bd1b23382d01507bef0e8142112d2823b7a7416f555de11')
        self.assertEqual(canonical(SUPPORT['record']), SUPPORT['record_sha256'])
        for locale, observation in SUPPORT['faces'].items():
            self.assertEqual(observation['response']['cards'][0], observation['face'])
            self.check(SUPPORT['record'], observation['face'], locale)
            with self.assertRaises(ValueError): self.check(SUPPORT['record'], observation['face'], locale, None)
    def test_changed_source_identity_rules_or_metadata_cannot_borrow_name_exception(self):
        for key, value in (('id', 'other'), ('text', '<b>亡语：</b>召唤{0}并抽牌。'), ('health', 3)):
            raw = deepcopy(SUPPORT['record']); raw[key] = value
            for locale, o in SUPPORT['faces'].items():
                with self.assertRaises(ValueError): self.check(raw, o['face'], locale)
    def test_primary_additional_rule_numeric_replacement_or_wrong_body_rejects(self):
        for locale, o in SUPPORT['faces'].items():
            for key, value in (('text', o['face']['text'] + ' Draw a card.'), ('text', 'Deathrattle: Summon 0.'),
                    ('manaCost', 2), ('attack', 1), ('health', 3), ('cardTypeId', 5)):
                face = dict(o['face']); face[key] = value
                with self.assertRaises(ValueError): self.check(SUPPORT['record'], face, locale)
    def test_other_markers_nonempty_substitution_and_missing_zero_declaration_reject(self):
        for locale, o in SUPPORT['faces'].items():
            for declaration in ({'{0}': '0'}, {'{1}': ''}, {'{0}': '', '@': ''}):
                with self.assertRaises(ValueError): self.check(SUPPORT['record'], o['face'], locale, declaration)
            with self.assertRaises(ValueError): check_face(SUPPORT['record'], o['face'], locale, {'{0}': ''})


if __name__ == '__main__': unittest.main()
