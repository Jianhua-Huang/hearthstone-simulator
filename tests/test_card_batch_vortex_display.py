"""Finite primary counter display keeps the full pinned rule and token evidence."""
from copy import deepcopy
import unittest
from hs_sim.cards.visage_vortex_cards import INSPIRATION,load_batch
from tools import card_batch as b


class VortexDisplayTests(unittest.TestCase):
    def faces(self):
        d=load_batch();row=next(x['record'] for x in d['dependencies'] if x['record']['id']==INSPIRATION)
        return [(row,o['face'],o['locale']) for o in d['official_observations'] if o['card_id']==INSPIRATION]
    def test_both_complete_faces_require_explicit_counter_and_preserve_originals(self):
        self.assertEqual(len(self.faces()),2)
        for row,face,locale in self.faces():
            old=deepcopy((row,face))
            with self.assertRaises(ValueError):b.check_face(row,face,locale)
            b.check_face(row,face,locale,{'@':''});self.assertEqual((row,face),old)
    def test_complete_rules_numbers_and_bonus_wording_cannot_drift(self):
        for row,face,locale in self.faces():
            for text in (face['text'].replace('4/5','5/5'),face['text'].replace('随机','指定') if locale=='zh_CN' else face['text'].replace('random','chosen')):
                with self.subTest(locale=locale,text=text),self.assertRaises(ValueError):
                    b.check_face(row,dict(face,text=text),locale,{'@':''})
    def test_chinese_allowance_requires_exact_full_original_row_and_counter_label(self):
        row,face,locale=next(x for x in self.faces() if x[2]=='zh_CN')
        for changed in (dict(row,name=row['name']+'x'),dict(row,text=row['text'].replace('召唤@个','获得@点')),dict(row,dbf_id=row['dbf_id']+1)):
            with self.subTest(row=changed['id']),self.assertRaises(ValueError):b.check_face(changed,face,locale,{'@':''})


if __name__=='__main__':unittest.main()
