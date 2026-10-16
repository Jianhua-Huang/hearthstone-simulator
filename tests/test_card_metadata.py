"""Printed secondary race flags are explicit data, never guessed from names."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from hs_sim.cards.metadata import metadata_from_record,validate_race_pin
from hs_sim.targets import TargetValidationError


class CardMetadataTests(unittest.TestCase):
    def record(self,**tags):
        return dict(id='reviewed',type='MINION',collectible=True,tags={'CLASS':12,**tags})

    def test_secondary_flag_adds_a_second_tribe_and_duplicate_primary_is_not_repeated(self):
        meta=metadata_from_record(self.record(CARDRACE=11,**{'2542':1}))
        self.assertEqual(meta.tribes,('undead','beast'))
        self.assertEqual(metadata_from_record(self.record(CARDRACE=17,**{'2539':1})).tribes,('mech',))
        self.assertEqual(metadata_from_record(self.record(CARDRACE=43)).tribes,('quilboar',))

    def test_unknown_primary_race_and_boolean_or_nonbinary_flags_raise(self):
        for tags in ({'CARDRACE':999},{'CARDRACE':True},{'2542':True},{'2542':2}):
            with self.subTest(tags=tags),self.assertRaises(TargetValidationError):
                metadata_from_record(self.record(**tags))

    def test_all_race_primary_is_the_pinned_enum_and_not_unknown_or_empty(self):
        from hs_sim.cards.metadata import PIN_PATH
        data=json.loads(PIN_PATH.read_text(encoding='utf-8'))
        self.assertEqual(data['race_enum']['ALL'],26)
        self.assertEqual(metadata_from_record(self.record(CARDRACE=26)).tribes,('all',))

    def test_mapping_pin_changes_cannot_silently_relabel_card_tribes(self):
        validate_race_pin()
        from hs_sim.cards.metadata import PIN_PATH
        data=json.loads(PIN_PATH.read_text(encoding='utf-8'))
        data['race_rows'][0]['m_ID']=999
        with TemporaryDirectory() as folder:
            path=Path(folder)/'changed.json'; path.write_text(json.dumps(data),encoding='utf-8')
            with patch('hs_sim.cards.metadata.PIN_PATH',path),self.assertRaises(TargetValidationError):
                validate_race_pin()
