"""Both complete Jar texts remain strict; only its pinned live name is omitted."""
from copy import deepcopy
from pathlib import Path
import unittest
from tools.card_batch import read, canonical, check_face

SUPPORT=read(Path(__file__).resolve().parents[1]/'data/support/card-source-jar-name-display-v1.json')


class JarNameDisplayTests(unittest.TestCase):
    def check(self,row,face,locale,declaration=None,numeric=None):
        return check_face(row,face,locale,SUPPORT['normalizations'] if declaration is None else declaration,
            numeric_normalizations={'attack':0} if numeric is None else numeric)

    def test_both_complete_faces_and_explicit_zero_preserve_empty_and_filled_text(self):
        self.assertEqual(canonical(SUPPORT),'76918d0fd6f79945619c06ac6a09ee888d954771bc3c9555a6aa6139c03dbb9a')
        self.assertEqual(canonical(SUPPORT['record']),SUPPORT['record_sha256'])
        for locale,o in SUPPORT['faces'].items():
            self.assertEqual(o['response']['cards'][0],o['face']);self.check(SUPPORT['record'],o['face'],locale)

    def test_changed_complete_raw_identity_body_or_numbers_cannot_borrow_exception(self):
        for key,value in (('id','other'),('cost',2),('text','<b>亡语：</b>放出{5}！')):
            row=deepcopy(SUPPORT['record']);row[key]=value
            for locale,o in SUPPORT['faces'].items():
                with self.assertRaises(ValueError):self.check(row,o['face'],locale)

    def test_primary_missing_empty_body_extra_rules_or_numeric_drift_reject(self):
        for locale,o in SUPPORT['faces'].items():
            for key,value in (('text','<b>Deathrattle:</b> Release !'),('text',o['face']['text']+' Draw a card.'),
                    ('attack',1),('health',2),('manaCost',2)):
                face=dict(o['face']);face[key]=value
                with self.assertRaises(ValueError):self.check(SUPPORT['record'],face,locale)

    def test_incomplete_nonempty_and_unreviewed_markers_or_implicit_zero_reject(self):
        for locale,o in SUPPORT['faces'].items():
            for declaration in ({'@':''},{'{5}':''},{'@':'','{5}':'0'},{'@':'','{0}':''}):
                with self.assertRaises(ValueError):self.check(SUPPORT['record'],o['face'],locale,declaration)
            with self.assertRaises(ValueError):self.check(SUPPORT['record'],o['face'],locale,numeric={})


if __name__=='__main__':unittest.main()
