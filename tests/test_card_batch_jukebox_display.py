"""Only the complete pinned Totem may omit its live Recruit size/article slots."""
from copy import deepcopy
from pathlib import Path
import unittest

from tools.card_batch import canonical, check_face, read

REFERENCE = read(Path(__file__).resolve().parents[1]/'data/cards/past-paladin-mech-local-reference-v1.json')
RAW = next(v['record'] for v in REFERENCE['candidate_records'] if v['record']['id']=='JAM_010')
FACES = {v['locale']:v['face'] for v in REFERENCE['official_observations'] if v['card_id']=='JAM_010'}
DECLARATIONS = REFERENCE['display_normalizations']['JAM_010']


class JukeboxDisplayTests(unittest.TestCase):
    def check(self,raw,face,locale,declaration=None):
        return check_face(raw,face,locale,DECLARATIONS[locale] if declaration is None else declaration,
            numeric_normalizations={'attack':0})

    def test_both_complete_faces_omit_only_live_recruit_slots_and_require_explicit_zero_attack(self):
        self.assertEqual(canonical(RAW),'657a67966983d7bd55b23173e96b4915e2d5150ffc0d841c71b9cb2d41523f40')
        for locale,face in FACES.items():
            self.check(RAW,face,locale)
            with self.assertRaises(ValueError): check_face(RAW,face,locale,numeric_normalizations={'attack':0})
            with self.assertRaises(ValueError): check_face(RAW,face,locale,DECLARATIONS[locale])

    def test_other_identity_source_rule_or_printed_stats_cannot_borrow_the_display_exception(self):
        for key,value in (('id','other'),('text',RAW['text']+'抽一张牌。'),('health',5),('cost',1)):
            row=deepcopy(RAW); row[key]=value
            for locale,face in FACES.items():
                with self.assertRaises(ValueError): self.check(row,face,locale)

    def test_full_primary_rule_and_numeric_metadata_remain_strict(self):
        for locale,source in FACES.items():
            for key,value in (('text',source['text']+' Draw a card.'),('text','Summon a Recruit.'),
                    ('manaCost',3),('attack',1),('health',5),('cardTypeId',5)):
                face=dict(source); face[key]=value
                with self.assertRaises(ValueError): self.check(RAW,face,locale)

    def test_unreviewed_markers_and_numeric_substitution_are_rejected(self):
        for locale,face in FACES.items():
            for declaration in ({'{0}':'1/1'},{'{0}':'','@':''},{'{1}':''},{'{0}':'','{1}':'1'}):
                with self.assertRaises(ValueError): self.check(RAW,face,locale,declaration)


if __name__=='__main__':unittest.main()
