"""Only the three complete native location templates omit their live slots."""
from copy import deepcopy
from pathlib import Path
import unittest
from tools.card_batch import check_face, read

PACKET = read(Path(__file__).resolve().parents[1] / 'data/cards/elise-crafted-locations-v1.json')
ROWS = {x['record']['id']: x['record'] for x in PACKET['dependencies']}
TEMPLATES = ('TLC_100t1', 'TLC_100t2', 'TLC_100t3')
DECLARATION = {'{0}': '', '{1}': ''}


class LocationTemplateDisplayTests(unittest.TestCase):
    def test_three_complete_bilingual_native_templates_keep_all_printed_numbers(self):
        for obs in PACKET['official_observations']:
            if obs['card_id'] in TEMPLATES:
                check_face(ROWS[obs['card_id']], obs['face'], obs['locale'], DECLARATION)
    def test_changed_source_body_identity_parent_or_face_numbers_cannot_borrow_exception(self):
        for obs in PACKET['official_observations']:
            if obs['card_id'] not in TEMPLATES:
                continue
            row = ROWS[obs['card_id']]
            for key, value in (('id', 'other'), ('health', 3), ('text', '{0}{1} Draw a card.')):
                bad = deepcopy(row)
                bad[key] = value
                with self.assertRaises(ValueError):
                    check_face(bad, obs['face'], obs['locale'], DECLARATION)
            for key, value in (('parentId', 1), ('health', 3), ('manaCost', 7), ('text', 'Draw a card.')):
                bad = dict(obs['face'], **{key: value})
                with self.assertRaises(ValueError):
                    check_face(row, bad, obs['locale'], DECLARATION)
            with self.assertRaises(ValueError):
                check_face(row, obs['face'], obs['locale'])


if __name__ == '__main__':
    unittest.main()
