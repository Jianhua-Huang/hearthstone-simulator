"""Compact runtime observations must not weaken body or byte integrity."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools import card_batch as batch


class RuntimeReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.value = dict(schema=1, head='a'*40, source_guard={},
            definitions={'A': {'full_body': 'old declaration '*300}},
            pool_cards={'A': {'id': 'A', 'cost': 1}}, families={}, pools=[],
            default_fingerprint='old', default_snapshot={'state': {'turn': 1}, 'schema_version': 1})
        self.base = self.root/'base.json'
        batch.save_new(self.base, self.value)

    def changed(self):
        value = deepcopy(self.value)
        value['head'] = 'b'*40
        value['definitions']['B'] = {'full_body': 'new exact declaration'}
        value['pool_cards']['B'] = {'id': 'B', 'cost': 0}
        value['default_snapshot']['schema_version'] = 2
        return value

    def save(self, path='ref.json', value=None, baseline=None):
        path = self.root/path
        batch.save_registry_reference(path, value or self.changed(), baseline or self.base,
                                      root=self.root, native_parts=('A', 'B'))
        return path

    def test_full_observation_and_compact_additions_roundtrip_without_recopying_old_body(self):
        self.assertEqual(batch.read_registry_observation(self.base, root=self.root), self.value)
        ref = self.save(); record = batch.read(ref)
        self.assertNotIn('old declaration', ref.read_text(encoding='utf-8'))
        self.assertEqual(record['additions']['definitions'], {'B': self.changed()['definitions']['B']})
        self.assertEqual(batch.read_registry_observation(ref, root=self.root), self.changed())

    def test_chained_reference_retains_both_old_and_new_additions(self):
        one = self.save(); value = self.changed()
        value['definitions']['C'] = {'full_body': 'third'}
        value['pool_cards']['C'] = {'id': 'C', 'cost': 4}
        two = self.save('two.json', value, one)
        self.assertEqual(set(batch.read(two)['additions']['definitions']), {'C'})
        self.assertEqual(batch.read_registry_observation(two, root=self.root), value)

    def test_existing_identical_reference_format_remains_readable(self):
        record = dict(schema=1, kind='verified-identical-runtime-body-reference',
            baseline='base.json', baseline_sha256=batch.sha(self.base),
            identical_sections=list(batch._RUNTIME_BODY), head=self.value['head'], source_guard={},
            actual_full_observation_sha256=batch.canonical(self.value), native_parts=['A'],
            runtime_content_sha256=batch.canonical({k: self.value[k] for k in batch._RUNTIME_BODY}),
            actual_full_observation_compared=True)
        path = self.root/'old-ref.json'; batch.save_new(path, record)
        self.assertEqual(batch.read_registry_observation(path, root=self.root), self.value)

    def test_baseline_byte_change_rejects_even_when_json_meaning_is_unchanged(self):
        ref = self.save(); self.base.write_text(self.base.read_text(encoding='utf-8')+'\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'byte identity'):
            batch.read_registry_observation(ref, root=self.root)

    def test_reference_rejects_changed_digest_overlap_or_false_unchanged_claim(self):
        original = batch.read(self.save())
        for name in ('digest', 'overlap', 'unchanged', 'replace-map', 'unknown', 'unverified'):
            row = deepcopy(original)
            if name == 'digest': row['actual_full_observation_sha256'] = '0'*64
            elif name == 'overlap': row['additions']['definitions']['A'] = {'full_body': 'replacement'}
            elif name == 'unchanged': row['identical_sections'].append('definitions')
            elif name == 'replace-map': row['overrides']['definitions'] = {}
            elif name == 'unknown': row['acceptance_passed'] = True
            else: row['actual_full_observation_compared'] = False
            path = self.root/(name+'.json'); batch.save_new(path, row)
            with self.subTest(name=name), self.assertRaises(ValueError):
                batch.read_registry_observation(path, root=self.root)

    def test_existing_card_mutation_or_removal_requires_full_capture(self):
        for key in ('definitions', 'pool_cards'):
            for operation in ('change', 'remove'):
                value = self.changed()
                if operation == 'change': value[key]['A'] = {'other': 'body'}
                else: value[key].pop('A')
                with self.subTest(key=key, operation=operation), self.assertRaisesRegex(ValueError, 'full capture'):
                    self.save(key+'-'+operation+'.json', value)

    def test_current_source_change_and_existing_output_cannot_be_overwritten(self):
        ref = self.save(); original = ref.read_bytes()
        with self.assertRaises(FileExistsError):
            self.save()
        self.assertEqual(ref.read_bytes(), original)
        source = self.root/'hs_sim/x.py'; source.parent.mkdir(); source.write_text('changed = True\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.save('stale.json')
        self.assertFalse((self.root/'stale.json').exists())

    def test_reference_paths_cycles_and_excessive_chains_are_rejected(self):
        original = batch.read(self.save())
        for name, target in (('parent', '../outside.json'), ('absolute', str(self.base)), ('cycle', 'cycle.json')):
            value = deepcopy(original); value['baseline'] = target
            path = self.root/(name+'.json'); batch.save_new(path, value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                batch.read_registry_observation(path, root=self.root)
        last = self.base
        for n in range(16):
            value = dict(schema=1, kind='verified-identical-runtime-body-reference',
                baseline=last.name, baseline_sha256=batch.sha(last),
                identical_sections=list(batch._RUNTIME_BODY), head=self.value['head'], source_guard={},
                actual_full_observation_sha256=batch.canonical(self.value), actual_full_observation_compared=True)
            last = self.root/('chain'+str(n)+'.json'); batch.save_new(last, value)
        with self.assertRaisesRegex(ValueError, 'excessive'):
            batch.read_registry_observation(last, root=self.root)
