"""A clean checkout contains all runtime and historical regression inputs."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.reference_inputs import reference_path
from fixture_inputs import fixture_input_map,fixture_manifest

ROOT=Path(__file__).resolve().parents[1]


class RepositoryInputTests(unittest.TestCase):
    def test_every_packaged_input_retains_its_recorded_complete_digest(self):
        manifest=json.loads((ROOT/'tests/fixtures/input-manifest.json').read_text(encoding='utf8'))
        self.assertGreater(len(manifest),100)
        for old,row in manifest.items():
            with self.subTest(original=old):
                path=ROOT/row['path'];raw=path.read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])
                self.assertEqual(len(raw),row['bytes'])
                self.assertFalse(path.resolve().is_relative_to(ROOT/'outputs'))
    def test_runtime_references_reject_absolute_parent_and_escaping_paths(self):
        for bad in ('../outside.json',str(ROOT/'outputs/outside.json')):
            with self.subTest(path=bad),self.assertRaises(ValueError):reference_path(bad,root=ROOT)
        self.assertEqual(reference_path('outputs/card-integration-20261014/cards-37.0.0.255026.json',root=ROOT),
            ROOT/'data/reference/card-integration-20261014/cards-37.0.0.255026.json')
    def test_complete_standard_registry_builds_with_outputs_and_network_forbidden(self):
        from hs_sim.local_pool_format import build_cn37_local_pool_format
        original_text,original_bytes=Path.read_text,Path.read_bytes
        def guard(path,reader,*args,**kwargs):
            logical=Path(path).absolute()
            self.assertFalse(logical.is_relative_to(ROOT/'outputs'),str(path))
            self.assertFalse(logical.is_relative_to(ROOT/'data/extracted'),str(path))
            return reader(path,*args,**kwargs)
        with patch.object(Path,'read_text',lambda p,*a,**k:guard(p,original_text,*a,**k)), \
                patch.object(Path,'read_bytes',lambda p,*a,**k:guard(p,original_bytes,*a,**k)), \
                patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected network')):
            fmt=build_cn37_local_pool_format()
        self.assertEqual(fmt.target_id,'cn37-local-special-pools-v20-911ab243e0c080c4')
        self.assertFalse(fmt.formal_pool_complete)
    def test_manifest_rebinding_preserves_pins_and_original_metadata(self):
        old='outputs/card-integration-20261014/cards-37.0.0.255026.json'
        original={'source':old,'source_sha256':'unchanged','nested':[{'response_file':old}]}
        new=fixture_manifest(original)
        self.assertEqual(original['source'],old)
        self.assertEqual(new['source'],fixture_input_map()[old])
        self.assertEqual(new['source_sha256'],'unchanged')
        self.assertEqual(new['nested'][0]['response_file'],new['source'])
