"""Only the complete native Treant may omit its runtime carved spell name."""
from copy import deepcopy
from pathlib import Path
import unittest

from tools.card_batch import read,canonical,check_face

SUPPORT=read(Path(__file__).resolve().parents[1]/'data/support/card-source-carved-treant-display-v1.json')


class CarvedTreantDisplayTests(unittest.TestCase):
    def check(self,row,face,locale,decl={'{0}':''}):return check_face(row,face,locale,decl)

    def test_complete_raw_and_primary_responses_accept_only_explicit_native_name_omission(self):
        self.assertEqual(canonical(SUPPORT),'ce852ce71c4cb0f6d2cfcf76ab61ade03a4f26d02569675347e8c919e637fdcb')
        self.assertEqual(canonical(SUPPORT['record']),SUPPORT['record_sha256'])
        for locale,o in SUPPORT['faces'].items():
            self.assertIn(o['face'],o['response']['cards']);self.check(SUPPORT['record'],o['face'],locale)
            with self.assertRaises(ValueError):self.check(SUPPORT['record'],o['face'],locale,None)

    def test_changed_source_body_identity_or_stats_cannot_borrow_native_exception(self):
        for key,value in (('id','other'),('text','<b>战吼：</b>施放{0}并抽牌。'),('health',3)):
            raw=deepcopy(SUPPORT['record']);raw[key]=value
            for locale,o in SUPPORT['faces'].items():
                with self.subTest(key=key,locale=locale),self.assertRaises(ValueError):self.check(raw,o['face'],locale)

    def test_primary_additional_rules_wrong_body_and_numbers_are_still_strict(self):
        for locale,o in SUPPORT['faces'].items():
            for key,value in (('text',o['face']['text']+' Draw a card.'),('manaCost',2),('attack',3),('health',3),('cardTypeId',5)):
                face=deepcopy(o['face']);face[key]=value
                with self.subTest(key=key,locale=locale),self.assertRaises(ValueError):self.check(SUPPORT['record'],face,locale)

    def test_other_markers_replacements_and_unreviewed_declarations_reject(self):
        for locale,o in SUPPORT['faces'].items():
            for declaration in ({'{0}':'0'},{'{1}':''},{'{0}':'','@':''}):
                with self.subTest(declaration=declaration,locale=locale),self.assertRaises(ValueError):
                    self.check(SUPPORT['record'],o['face'],locale,declaration)


if __name__=='__main__':unittest.main()
