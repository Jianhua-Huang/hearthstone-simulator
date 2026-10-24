"""One complete Boar /10 progress label can omit its runtime value only."""
from copy import deepcopy
from pathlib import Path
import unittest

from tools.card_batch import read,canonical,check_face

SUPPORT=read(Path(__file__).resolve().parents[1]/'data/support/card-source-boar-counter-display-v1.json')
PIN='148c2e16dbbbf6667e163c8f24660956ae8fef7574707fb538b8ab7bfd37fb73'


class BoarCounterDisplayTests(unittest.TestCase):
    def test_full_source_and_both_complete_responses_preserve_the_ten_death_rule(self):
        self.assertEqual(canonical(SUPPORT),PIN)
        self.assertEqual(canonical(SUPPORT['record']),SUPPORT['record_sha256'])
        original=deepcopy(SUPPORT)
        for locale,o in SUPPORT['faces'].items():
            self.assertEqual(o['response']['cards'][0],o['face'])
            check_face(SUPPORT['record'],o['face'],locale,{'@':''})
            with self.assertRaises(ValueError):check_face(SUPPORT['record'],o['face'],locale)
        self.assertEqual(SUPPORT,original)

    def test_changed_full_source_cannot_borrow_the_counter_display(self):
        for key,value in (('id','other'),('health',2),('name','Other')):
            raw=deepcopy(SUPPORT['record']);raw[key]=value
            for locale,o in SUPPORT['faces'].items():
                with self.subTest(key=key,locale=locale),self.assertRaises(ValueError):check_face(raw,o['face'],locale,{'@':''})
        for key in ('text','text_en'):
            raw=deepcopy(SUPPORT['record']);raw[key]=raw[key].replace('10','11')
            for locale,o in SUPPORT['faces'].items():
                with self.assertRaises(ValueError):check_face(raw,o['face'],locale,{'@':''})

    def test_changed_primary_threshold_weapon_denominator_or_extra_rule_rejects(self):
        for locale,o in SUPPORT['faces'].items():
            text=o['face']['text']
            for body in (text.replace('10','7'),text.replace('15/3','15/2'),
                    text.replace('/10','/11'),text+' Draw a card.',text.split('<i>')[0]):
                with self.subTest(locale=locale,body=body),self.assertRaises(ValueError):
                    check_face(SUPPORT['record'],dict(o['face'],text=body),locale,{'@':''})

    def test_nonempty_live_value_extra_marker_and_changed_primary_metadata_reject(self):
        for locale,o in SUPPORT['faces'].items():
            for declaration in ({'@':'10'},{'@':'0'},{'@':'','{0}':''},{}):
                with self.assertRaises(ValueError):check_face(SUPPORT['record'],o['face'],locale,declaration)
            for key,value in (('manaCost',2),('attack',2),('health',2),('cardTypeId',5),('collectible',False)):
                with self.assertRaises(ValueError):check_face(SUPPORT['record'],dict(o['face'],**{key:value}),locale,{'@':''})
