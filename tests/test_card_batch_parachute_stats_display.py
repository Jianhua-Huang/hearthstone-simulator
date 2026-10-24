"""Only the exact original Parachute SPELL has hidden 1/1 summon script fields."""
from copy import deepcopy
import unittest
from hs_sim.cards.past_parachute_draws_cards import PARACHUTE, load_batch
from tools.card_batch import canonical, check_face, sha


class ParachuteScriptStatsDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = load_batch()
        cls.raw = next(x['record'] for x in cls.batch['dependencies'] if x['record']['id'] == PARACHUTE)
        cls.faces = [o for o in cls.batch['official_observations'] if o['card_id'] == PARACHUTE]

    def test_both_full_primary_responses_preserve_raw_summon_stats(self):
        self.assertEqual(canonical(self.raw), '41987aa7e975512f1fb7c3cac7876394d3cdd6658acca7e45678c29fa5b7efe1')
        self.assertEqual((self.raw['attack'], self.raw['health']), (1, 1))
        for o in self.faces:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            self.assertIsNone(o['face'].get('attack')); self.assertIsNone(o['face'].get('health'))
            check_face(self.raw, o['face'], o['locale'])

    def test_complete_raw_changes_cannot_borrow_the_exception(self):
        for key, value in (('attack', None), ('health', None), ('cost', 2), ('type', 'MINION')):
            with self.subTest(field=key):
                raw = deepcopy(self.raw); raw[key] = value
                with self.assertRaises(ValueError): check_face(raw, self.faces[0]['face'], self.faces[0]['locale'])

    def test_nonempty_primary_stats_or_other_parent_are_rejected(self):
        for key, value in (('attack', 1), ('health', 1), ('attack', False), ('parentId', 1), ('cardTypeId', 4)):
            with self.subTest(field=key, value=value):
                face = deepcopy(self.faces[0]['face']); face[key] = value
                with self.assertRaises(ValueError): check_face(self.raw, face, self.faces[0]['locale'])

    def test_cost_name_and_rule_checks_remain_strict(self):
        for key, value in (('manaCost', 0), ('name', 'Different'), ('text', 'Summon a 2/2 Pirate.')):
            with self.subTest(field=key):
                face = deepcopy(self.faces[0]['face']); face[key] = value
                with self.assertRaises(ValueError): check_face(self.raw, face, self.faces[0]['locale'])

    def test_other_nonminion_source_does_not_receive_the_stat_policy(self):
        raw = deepcopy(self.raw); raw['id'] = 'UNREVIEWED_PARACHUTE'
        with self.assertRaises(ValueError): check_face(raw, self.faces[0]['face'], self.faces[0]['locale'])
