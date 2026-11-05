"""Host imports must preserve actual deck identity and reject partial data."""
import base64
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from firestone_decks import decode_deckstring
from duel_audit import validate_pairs


class FirestoneImport(unittest.TestCase):
    def test_real_metadata_deck_preserves_card_counts(self):
        code = 'AAECAf0GAA+xnwSCoASDoATnoATEngbRggePhAepiAfGkgeEmQfQsgfgvgfPvwfb1weO3AcAAA=='
        value = decode_deckstring(code)
        self.assertEqual(value['format'], 2)
        self.assertEqual(value['heroes'], [893])
        self.assertEqual(len(value['cards']), 15)
        self.assertTrue(all(count == 2 for _, count in value['cards']))
        self.assertEqual(sum(count for _, count in value['cards']), 30)

    def test_sideboard_owner_and_duplicate_quantities_are_preserved(self):
        # header, version, standard, hero, main singleton/two/n sections,
        # sideboard flag and corresponding singleton/two/n sections.
        raw = bytes([0,1,2,1,7,1,10,0,0,1,1,11,10,1,12,10,1,13,3,10])
        value = decode_deckstring(base64.b64encode(raw).decode())
        self.assertEqual(value['cards'], [(10,1)])
        self.assertEqual(value['sideboards'], [(11,1,10),(12,2,10),(13,3,10)])

    def test_truncation_and_unknown_suffix_are_not_silently_ignored(self):
        for raw in (b'\0\1\2\1\x80',bytes([0,1,2,1,7,0,0,0,0,8]),
                    bytes([0,1,2,1,7,1,10,1,10,0,0])):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_deckstring(base64.b64encode(raw).decode())

    def test_actual_shared_cards_require_explicit_import_opt_in(self):
        decks={'a':{'cards':['A','B']},'b':{'cards':['B','C']}}
        original = repr(decks)
        with self.assertRaises(ValueError):validate_pairs(decks,[['a','b']])
        validate_pairs(decks,[['a','b']],True)
        self.assertEqual(repr(decks),original)
        for invalid in (1,'true',None):
            with self.assertRaises(ValueError):validate_pairs(decks,[['a','b']],invalid)
        with self.assertRaises(ValueError):validate_pairs(decks,[['a','a']],True)


if __name__ == '__main__':unittest.main()
