"""Reusable audit workflow: evidence, novelty, thresholds, handoff and native DTOs."""
from pathlib import Path
import json
import gzip
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import duel_audit as audit
import duel_audit_runtime as runtime


class Evidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.batch = self.root / 'batch'
        self.batch.mkdir()
        self.history = self.root / 'history.json'
        audit.write(self.history, {'schema': 1, 'files': {}, 'seen': [], 'runs': [], 'deliveries': {}})
        audit.write(self.batch / 'config.json', {
            'history': str(self.history), 'slow_ms': 500, 'query_slow_ms': 500,
            'function_thread': audit.FUNCTION_THREAD, 'performance_thread': audit.PERFORMANCE_THREAD})
        audit.write(self.batch / 'identity.json', {
            'source': str(self.batch), 'core': 1, 'head': 'test', 'target': 'test', 'engine_sha256': 'engine'})
        audit.write(self.batch / 'source-manifest.json', {'files': {}})
        audit.write(self.batch / 'plan.json', {'decks': {'a': {'rows': [
            {'id': 'A', 'name': 'draw'}, {'id': 'UNPLAYED', 'name': 'not exercised'}]}}})
        audit.write(self.batch / 'run-status.json', {'status': 'finished', 'games': [{'id': 'g', 'status': 'completed'}]})

    def tearDown(self):
        self.temp.cleanup()

    def rows(self, rows, tail=''):
        folder = self.batch / 'private/g'
        folder.mkdir(parents=True, exist_ok=True)
        base = {'pair': 'pair-1', 'game_id': 'A-1', 'step': 0, 'actor': 1,
                'card_id': 'A', 'card_name': 'draw', 'action': {'type': 'play_card'},
                'accepted': True, 'checks': [], 'before_snapshot': {'path': 'full-before.json.gz'},
                'after_snapshot': {'path': 'full-after.json.gz'}}
        (folder / 'steps.jsonl').write_text(''.join(json.dumps({**base, **r}) + '\n' for r in rows) + tail, encoding='utf8')

    def test_strict_threshold_failed_commands_and_unplayed_coverage(self):
        self.rows([
            {'id': 'boundary', 'timings': {'submit_ms': 500}},
            {'id': 'slow', 'timings': {'submit_ms': 500.01}},
            {'id': 'query', 'timings': {'query_ms': 600, 'submit_ms': 1}},
            {'id': 'reject', 'timings': {'submit_ms': 900}, 'accepted': False, 'failure': 'rejected_enumerated_action'},
        ], tail='{"id":"incomplete')
        result = audit.analyze(self.batch)
        self.assertEqual((result['actions'], result['accepted'], result['slow_actions'], result['failures']), (4, 3, 2, 1))
        self.assertEqual(result['coverage'][1]['verdict'], 'not_exercised')
        fixture = audit.read(self.batch / 'fixtures/slow.json')
        self.assertEqual(fixture['before'], 'full-before.json.gz')
        self.assertEqual(result['timing']['submit_ms']['max_ms'], 500.01)

    def test_queue_needs_real_destination_receipt_then_deduplicates(self):
        self.rows([{'id': 'slow', 'timings': {'submit_ms': 501}}])
        audit.analyze(self.batch)
        packet = self.batch / 'handoff/performance.json'
        self.assertFalse(audit.read(packet)['delivery_confirmed'])
        receipt = self.root / 'receipt.json'
        audit.write(receipt, {'confirmed': True, 'thread_id': 'wrong thread'})
        argv = ['audit', 'ack', '--batch', str(self.batch), '--kind', 'performance', '--receipt', str(receipt)]
        with patch.object(sys, 'argv', argv), self.assertRaises(AssertionError):
            audit.main()
        self.assertFalse(audit.read(self.history)['deliveries'])
        audit.write(receipt, {'confirmed': True, 'thread_id': audit.PERFORMANCE_THREAD})
        with patch.object(sys, 'argv', argv):
            self.assertEqual(audit.main(), 0)
        audit.analyze(self.batch)
        self.assertEqual(audit.read(packet)['pending'], [])
        self.assertTrue(audit.read(packet)['delivery_confirmed'])

    def test_partial_analysis_cannot_claim_completion_or_update_history(self):
        self.rows([{'id': 'slow', 'timings': {'submit_ms': 700}}])
        audit.write(self.batch / 'run-status.json', {'status': 'running', 'games': [{'status': 'running'}]})
        result = audit.analyze(self.batch, partial=True)
        self.assertFalse(result['pipeline_complete'])
        self.assertFalse(audit.read(self.history)['seen'])
        with self.assertRaises(AssertionError):
            audit.analyze(self.batch)

    def test_frozen_source_change_rejected(self):
        self.rows([])
        file = self.batch / 'engine.py'
        file.write_text('old', encoding='utf8')
        audit.write(self.batch / 'source-manifest.json', {'files': {'engine.py': audit.file_hash(file)}})
        file.write_text('new', encoding='utf8')
        with self.assertRaises(AssertionError):
            audit.analyze(self.batch)

    def test_history_import_streams_complete_rows_and_excludes_nested_sources(self):
        root = self.root / 'legacy'
        folder = root / 'outputs/environment-old/pair/run/private'
        folder.mkdir(parents=True)
        log = folder / 'A-steps.jsonl'
        log.write_text('{"card_id":"OLD"}\n{"card_id":', encoding='utf8')
        nested = root / 'outputs/environment-old/frozen-source/outputs/x/decks/cards.json'
        audit.write(nested, {'cards': ['NESTED']})
        target = self.root / 'import.json'
        result = audit.import_history(root, target)
        self.assertEqual(result['seen'], ['OLD'])
        self.assertEqual(audit.import_history(root, target), result)
        log.write_text('{"card_id":"OLD"}\n{"card_id":"LATER"}\n', encoding='utf8')
        self.assertEqual(audit.import_history(root, target)['seen'], ['LATER', 'OLD'])

    def test_timeout_preserves_inflight_without_success_timing(self):
        self.rows([])
        folder = self.batch / 'private/g'
        audit.write(folder / 'inflight-command.json', {'id': 'inflight', 'timings': {'query_ms': 10}, 'action': {'type': 'play_card'}})
        audit.write(self.batch / 'run-status.json', {'status': 'running', 'games': [], 'phase': {'game': 'g', 'stage': 'submit'}})
        with patch.object(audit.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 1)):
            self.assertEqual(audit.worker(self.batch, 'run'), 124)
        row = json.loads((folder / 'steps.jsonl').read_text())
        self.assertIsNone(row['accepted'])
        self.assertEqual(row['failure'], 'worker_timeout')
        self.assertNotIn('submit_ms', row['timings'])


class PrintedFragments(unittest.TestCase):
    def test_unknown_checks_fail_before_a_match_instead_of_becoming_false_passes(self):
        registry = SimpleNamespace(cards={'A': object()})
        for checks in ({'A': [{'type': 'invented'}]}, {'MISSING': []}, {'A': [{'type': 'draw_min', 'amount': True}]}):
            with self.assertRaises(ValueError):
                runtime.validate_checks(checks, registry)
        runtime.validate_checks({'A': [{'type': 'draw_min', 'amount': 2}]}, registry)

    def test_explicit_deck_keeps_runes_and_sideboard_configuration(self):
        d = {'hero_card_id': 'HERO_11', 'hero_power_card_id': 'HERO_11bp',
             'card_class': 'death_knight', 'cards': ['EXAMPLE'],
             'runes': {'blood': 1, 'frost': 1, 'unholy': 1},
             'sideboards': [{'source_card_id': 'EXAMPLE', 'cards': ['OTHER']}]}
        spec = runtime.spec(d)
        self.assertEqual(spec.runes.total, 3)
        self.assertEqual(spec.sideboards[0].cards, ('OTHER',))

    def check(self, clause, *, deck=(1, 2), events=(), pending=None, entity=None):
        before = {'players': {'1': {'deck': deck}}}
        after = {'pending': pending, 'entities': {} if entity is None else {'9': entity}}
        return runtime.check_components([clause], 9, 1, before, after, events)[0]

    def test_draw_accounts_for_burns_and_does_not_certify_empty_deck(self):
        clause = {'type': 'draw_min', 'amount': 2}
        events = [{'kind': 'card_drawn', 'player_id': 1}, {'kind': 'card_burned', 'player_id': 1}]
        self.assertEqual(self.check(clause, events=events)['status'], 'pass')
        self.assertEqual(self.check(clause, events=events[:1])['status'], 'needs_review')
        self.assertEqual(self.check(clause, deck=())['status'], 'not_exercised')

    def test_removed_shield_or_pending_is_not_false_failure(self):
        clause = {'type': 'intrinsic_keyword', 'keyword': 'divine_shield'}
        entity = {'zone': 'board', 'silenced': False, 'dormant': False, 'keywords': []}
        self.assertEqual(self.check(clause, entity=entity)['status'], 'needs_review')
        event = {'kind': 'shield_lost', 'source_id': 9, 'target_id': None}
        self.assertEqual(self.check(clause, entity=entity, events=[event])['status'], 'not_exercised')
        self.assertEqual(self.check(clause, entity=entity, pending={'purpose': 'discover'})['status'], 'not_exercised')

    def test_profiles_do_not_turn_conditional_or_complex_text_into_oracles(self):
        row = {'text': '战吼：抽两张牌。', 'kind': 'minion'}
        self.assertEqual(runtime.profiles(row), [{'type': 'draw_min', 'amount': 2}])
        row['text'] = '如果你控制一个野兽，抽两张牌。'
        self.assertEqual(runtime.profiles(row), [])


class NativeWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.batch = Path(cls.temp.name) / 'native'
        doc = audit.read(ROOT / 'web_ui/autoplay_decks.json')
        audit.write(cls.batch / 'plans/pair-1.json', doc)
        c = cls.controller = runtime.catalog(cls.batch, 'test', cls.batch / 'plans/pair-1.json')
        audit.write(cls.batch / 'identity.json', {'source': str(ROOT), 'core': runtime.CORE_EFFECTS_VERSION, 'target': c.fmt.target_id})
        audit.write(cls.batch / 'source-manifest.json', {'files': {}})
        audit.write(cls.batch / 'config.json', {'cpu_mask': 1, 'seeds': [19], 'max_steps': 8, 'max_turns': 1})
        audit.write(cls.batch / 'plan.json', {'decks': doc['decks'], 'pairs': [list(doc['decks'])], 'checks': {}})
        cls.views = []
        original = runtime.choose_action
        def policy(view, rng, **kwargs):
            cls.views.append(view)
            return original(view, rng, **kwargs)
        with patch.object(runtime, 'choose_action', policy):
            runtime.run(cls.batch)
        cls.rows = [json.loads(line) for file in (cls.batch / 'private').glob('*/steps.jsonl') for line in file.read_text(encoding='utf8').splitlines()]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_two_native_orders_and_hidden_information_boundary(self):
        status = audit.read(self.batch / 'run-status.json')
        self.assertEqual(len(status['games']), 2)
        self.assertEqual({r['actor'] for r in self.rows}, {1, 2})
        self.assertTrue(all(r['accepted'] and not r.get('failure') for r in self.rows))
        for view in self.views:
            self.assertNotIn('state', view)
            self.assertNotIn('rng_state', view)
            observation = view['observation']
            opponent = next(p for p in observation['players'] if p['id'] != observation['viewer'])
            self.assertTrue(all(not c.get('card_id') or c['card_id'] == 'GAME_005' for c in opponent['hand']))

    def test_logged_snapshot_reproduces_exact_native_after(self):
        row = self.rows[0]
        fixture = self.batch / 'fixture.json'
        audit.write(fixture, {'decks': str(self.batch / 'plans/pair-1.json'), 'actor': row['actor'],
                             'action': row['action'], 'before': row['before_snapshot']['path'], 'after': row['after_snapshot']['path']})
        output = self.batch / 'reproduced'
        self.assertEqual(runtime.reproduce(fixture, output), 0)
        result = audit.read(output / 'result.json')
        self.assertTrue(result['accepted'])
        self.assertTrue(result['full_after_match'])

    def test_every_saved_boundary_is_restored_and_bad_boundary_is_retained(self):
        expected = len(list((self.batch / 'private').glob('*/*.json.gz')))
        output = self.batch / 'restore-all'
        with patch.object(runtime, 'catalog', return_value=self.controller):
            self.assertEqual(audit.restore_worker(self.batch, output), 0)
        result = audit.read(output / 'summary.json')
        self.assertTrue(result['all_passed'])
        self.assertEqual(result['checked'], expected)
        bad = self.batch / 'private/corrupt/bad.json.gz'
        bad.parent.mkdir()
        bad.write_bytes(gzip.compress(b'{}'))
        try:
            failed = self.batch / 'restore-with-invalid'
            with patch.object(runtime, 'catalog', return_value=self.controller):
                self.assertEqual(audit.restore_worker(self.batch, failed), 2)
            result = audit.read(failed / 'summary.json')
            self.assertEqual((result['checked'], len(result['failures'])), (expected + 1, 1))
            self.assertEqual(result['failures'][0]['snapshot'], str(bad))
            self.assertTrue(Path(result['failures'][0]['exception']).exists())
            self.assertTrue(bad.exists())
        finally:
            bad.unlink()


if __name__ == '__main__':
    unittest.main()
