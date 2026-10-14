from copy import deepcopy
import unittest

from tools.extract_client import LOCALES, localized, normalize_cards, validate_tables


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.enums = {'GAME_TAG': {'ATK': 47, 'HEALTH': 45, 'COST': 48, 'CARDTYPE': 202,
                                   'CHARGE': 197, 'SCRIPT_DATA': 2},
                      'TAG_CARDTYPE': {'MINION': 4}}
        self.card = {'m_ID': 1, 'm_noteMiniGuid': 'TEST', 'm_name': {'m_locValues': ['Example']}}

    def normalize(self, tags):
        return normalize_cards({'CARD': [self.card], 'CARD_TAG': tags}, self.enums, 'zhCN')[0]

    def tag(self, tag_id, value, reference=0, keyword=0):
        return {'m_cardId': 1, 'm_tagId': tag_id, 'm_tagValue': value,
                'm_isReferenceTag': reference, 'm_isPowerKeywordTag': keyword}

    def test_reference_power_keyword_is_also_gameplay_tag(self):
        card = self.normalize([self.tag(197, 1, reference=1, keyword=1),
                               self.tag(2, 7, reference=1)])
        self.assertEqual(card['tags'], {'CHARGE': 1})
        self.assertEqual(len(card['reference_tags']), 2)
        self.assertEqual(card['power_keyword_tags'], [{'tag': 'CHARGE', 'value': 1}])

    def test_non_reference_keyword_and_unknown_tag_preserved(self):
        card = self.normalize([self.tag(197, 1, keyword=1), self.tag(999999, 42)])
        self.assertEqual(card['tags'], {'CHARGE': 1, '999999': 42})

    def test_reference_value_does_not_override_regular_stat(self):
        card = self.normalize([self.tag(48, 2), self.tag(48, 99, reference=1),
                               self.tag(999999, 7, reference=1)])
        self.assertEqual(card['cost'], 2)
        self.assertEqual(card['tags'], {'COST': 2})
        self.assertEqual(card['reference_tags'], [
            {'tag': 'COST', 'value': 99}, {'tag': '999999', 'value': 7},
        ])

    def test_unknown_type_relationships_and_event_controls_preserved(self):
        self.card['m_battlegroundsActiveEvent'] = 123
        self.card['m_changeVersion'] = 456
        card = normalize_cards({
            'CARD': [self.card], 'CARD_TAG': [self.tag(202, 999)],
            'RELATED_CARDS': [{'m_cardId': 1, 'm_relatedCardDatabaseId': 1}],
        }, self.enums, 'enUS')[0]
        self.assertEqual(card['type'], '999')
        self.assertEqual(card['related_dbf_ids'], [1])
        self.assertEqual(card['source_events'], {'battlegroundsActiveEvent': 123})
        self.assertEqual(card['name'], 'Example')

    def test_zero_is_not_missing_and_absent_stats_not_inferred(self):
        card = self.normalize([self.tag(47, 0), self.tag(48, 0), self.tag(202, 4)])
        self.assertEqual(card['attack'], 0)
        self.assertEqual(card['cost'], 0)
        self.assertIsNone(card['health'])
        self.assertEqual(card['type'], 'MINION')

    def test_locale_index_and_missing_translation(self):
        values = [''] * len(LOCALES)
        values[12] = '中文'
        self.assertEqual(localized({'m_name': {'m_locValues': values}}, 'm_name', 'zhCN'), '中文')
        self.assertEqual(localized(self.card, 'm_name', 'zhCN'), '')

    def test_conflicts_and_duplicate_id_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting tag'):
            self.normalize([self.tag(47, 1), self.tag(47, 2)])
        with self.assertRaisesRegex(ValueError, 'Duplicate card'):
            normalize_cards({'CARD': [self.card, self.card], 'CARD_TAG': []}, self.enums, 'enUS')


class SchemaValidationTests(unittest.TestCase):
    def setUp(self):
        self.tables = {
            'CARD': [{
                'm_ID': 1, 'm_noteMiniGuid': 'TEST_SCHEMA',
                'm_name': {'m_locValues': ['Example'] * 14},
                'm_textInHand': {'m_locValues': [''] * 14},
            }],
            'CARD_TAG': [{
                'm_cardId': 1, 'm_tagId': 48, 'm_tagValue': 0,
                'm_isReferenceTag': 0, 'm_isPowerKeywordTag': 1,
            }],
        }

    def test_valid_table_schema_accepts_empty_text_and_zero_tag(self):
        validate_tables(self.tables)

    def test_schema_mismatch_and_orphan_tags_are_rejected(self):
        corruptions = [
            (('CARD',), []),
            (('CARD_TAG',), []),
            (('CARD',), {}),
            (('CARD_TAG',), {}),
            (('CARD', 0, 'm_ID'), '1'),
            (('CARD', 0, 'm_noteMiniGuid'), ''),
            (('CARD', 0, 'm_name'), None),
            (('CARD', 0, 'm_name', 'm_locValues'), ['Example'] * 13),
            (('CARD', 0, 'm_name', 'm_locValues'), ['Example'] * 15),
            (('CARD', 0, 'm_name', 'm_locValues'), [7] * 14),
            (('CARD', 0, 'm_textInHand'), {}),
            (('CARD', 0, 'm_textInHand', 'm_locValues'), 'not a list'),
            (('CARD_TAG', 0, 'm_cardId'), 999),
            (('CARD_TAG', 0, 'm_cardId'), '1'),
            (('CARD_TAG', 0, 'm_tagId'), '48'),
            (('CARD_TAG', 0, 'm_tagValue'), '0'),
            (('CARD_TAG', 0, 'm_isReferenceTag'), 2),
            (('CARD_TAG', 0, 'm_isPowerKeywordTag'), None),
        ]
        for path, value in corruptions:
            tables = deepcopy(self.tables)
            target = tables
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path, value=value), self.assertRaises(ValueError):
                validate_tables(tables)
        for field in ('m_isReferenceTag', 'm_isPowerKeywordTag'):
            tables = deepcopy(self.tables)
            del tables['CARD_TAG'][0][field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                validate_tables(tables)


if __name__ == '__main__':
    unittest.main()
