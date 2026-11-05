"""The comparer must detect private/RNG/reply changes, not only visible stats."""
from pathlib import Path
import gzip
import json
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from duel_audit import write
from duel_audit_compare import compare


class CompareEvidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.old, self.new = self.root / 'old', self.root / 'new'
        for batch in (self.old, self.new):
            write(batch / 'identity.json', {'core': 'same', 'schema': 1, 'target': 'same', 'source': str(batch)})
            write(batch / 'source-manifest.json', {'files': {}})
            write(batch / 'plan.json', {'decks': {'a': {'cards': ['A']}}, 'pairs': [['a', 'b']], 'checks': {}})
            write(batch / 'config.json', {'seed': 1, 'seeds': [1], 'max_steps': 10, 'max_turns': 10, 'cpu_mask': 1})
            write(batch / 'run-status.json', {'status': 'finished', 'games': [{'status': 'completed'}]})
            folder = batch / 'private/g'; folder.mkdir(parents=True)
            for name in ('initial', 'after'):
                (folder / (name + '.json.gz')).write_bytes(gzip.compress(json.dumps({'visible': 5, 'private_deck': ['A', 'B'], 'rng_state': [1, 2]}).encode()))
            row = {'id': 'g-step0', 'command': {'revision': 'same', 'action': {'type': 'end_turn'}},
                   'reply': {'accepted': True, 'observation': {'hero': 30}}, 'accepted': True,
                   'timings': {'query_ms': 4, 'submit_ms': 600 if batch == self.old else 100},
                   'after_snapshot': {'path': str(folder / 'after.json.gz')}}
            (folder / 'steps.jsonl').write_text(json.dumps(row) + '\n', encoding='utf8')

    def tearDown(self): self.temp.cleanup()

    def test_equal_complete_data_allows_timing_change_and_records_missing_query_scope(self):
        result = compare(self.old, self.new, self.root / 'equal')
        self.assertTrue(result['success'])
        self.assertEqual((result['steps'], result['snapshots'], result['full_replies']), (1, 2, 1))
        self.assertEqual(result['above_500_ms'], {'before': 1, 'after': 0})
        self.assertIn('complete initial legal query DTO at every step', result['not_recorded_in_baseline'])

    def test_hidden_deck_or_rng_change_is_not_hidden_by_same_visible_reply(self):
        for field, value in (('private_deck', ['B', 'A']), ('rng_state', [1, 3])):
            path = self.new / 'private/g/after.json.gz'
            state = {'visible': 5, 'private_deck': ['A', 'B'], 'rng_state': [1, 2]}; state[field] = value
            path.write_bytes(gzip.compress(json.dumps(state).encode()))
            result = compare(self.old, self.new, self.root / field)
            self.assertFalse(result['success'])
            self.assertTrue(any(field in r['difference'] for r in result['differences']))

    def test_complete_reply_change_is_rejected_even_if_snapshot_equal(self):
        path = self.new / 'private/g/steps.jsonl'; row = json.loads(path.read_text())
        row['reply']['observation']['hero'] = 29; path.write_text(json.dumps(row) + '\n', encoding='utf8')
        result = compare(self.old, self.new, self.root / 'reply')
        self.assertFalse(result['success'])
        self.assertTrue(any('complete_reply' in r['where'] for r in result['differences']))

    def test_only_auditor_keyword_order_is_normalized_with_raw_receipt(self):
        for batch, keywords in ((self.old, ['taunt', 'rush']), (self.new, ['rush', 'taunt'])):
            path = batch / 'private/g/steps.jsonl'; row = json.loads(path.read_text())
            row['checks'] = [{'status': 'pass', 'evidence': {'keywords': keywords}}]
            path.write_text(json.dumps(row) + '\n', encoding='utf8')
        result = compare(self.old, self.new, self.root / 'keyword_order')
        self.assertTrue(result['success'])
        self.assertEqual(len(result['normalized_keyword_order_receipts']), 1)
        path = self.new / 'private/g/steps.jsonl'; row = json.loads(path.read_text())
        row['checks'][0]['evidence']['keywords'] = ['rush', 'rush']
        path.write_text(json.dumps(row) + '\n', encoding='utf8')
        self.assertFalse(compare(self.old, self.new, self.root / 'keyword_members')['success'])


if __name__ == '__main__': unittest.main()
