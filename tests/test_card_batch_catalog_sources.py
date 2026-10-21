"""Whole official catalog responses retain strict per-card primary checks."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import card_batch as batch

PACKAGE = Path(__file__).resolve().parents[1] / 'data/cards/past-one-cost-leaves-v1.json'


class CatalogSourceTests(unittest.TestCase):
    def seed(self, root):
        root = Path(root); data = batch.read(PACKAGE); row = data['dependencies'][0]['record']
        faces = {o['locale']: o['face'] for o in data['official_observations'] if o['card_id'] == row['id']}
        sources = []
        for locale in ('zh_CN', 'en_US'):
            sources.append(self.page(root, locale, 1, faces[locale]))
        batch.save_new(root/'source.json', [row])
        manifest = dict(schema=1, batch='explicit-catalog-fixture', source='source.json',
            source_sha256=batch.sha(root/'source.json'), roots=[row['id']], dependencies=[],
            existing_dependencies=[], evidence_only=[], effect_groups=[dict(cards=[row['id']])],
            allowed_files=['data/cards/fixture.json', 'hs_sim/cards/fixture.py', 'tests/test_fixture.py'],
            official_catalogs=sources)
        batch.save_new(root/'manifest.json', manifest)
        return row, faces, sources

    def page(self, root, locale, page, face):
        response = f'pages/{locale}-{page}.json'; receipt = f'pages/{locale}-{page}.receipt.json'
        body = dict(cards=[deepcopy(face), {'id': 999999, 'fixture_only': 'Retain the whole body'}],
            cardCount=2, pageCount=1, page=page, fixture_only={'not_a_pool_certificate': True})
        batch.save_new(root/response, body)
        batch.save_new(root/receipt, dict(
            url=f'https://hearthstone.blizzard.com/en-us/api/cards?set=standard&pageSize=500&page={page}&locale={locale}',
            sha256=batch.sha(root/response), bytes=(root/response).stat().st_size, observed_at='fixture'))
        return dict(locale=locale, response_file=response, receipt_file=receipt)

    def rewrite(self, root, source, body):
        path = root/source['response_file']; path.write_text(json.dumps(body), encoding='utf-8')
        pin = batch.read(root/source['receipt_file'])
        pin.update(sha256=batch.sha(path), bytes=path.stat().st_size)
        (root/source['receipt_file']).write_text(json.dumps(pin), encoding='utf-8')

    def test_each_locale_has_one_exact_primary_and_whole_response_is_preserved(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); row, _, sources = self.seed(root)
            original = {s['response_file']: (root/s['response_file']).read_bytes() for s in sources}
            index = batch.catalog_index(sources, root)
            self.assertEqual(len(index), 4)
            for locale in ('zh_CN', 'en_US'):
                observation = batch.catalog_official(row, locale, index)
                self.assertEqual(observation['face']['id'], row['dbf_id'])
                self.assertIn('set=standard', observation['url'])
                self.assertEqual(observation['response_sha256'], batch.sha(observation['response_file']))
            for path, body in original.items(): self.assertEqual((root/path).read_bytes(), body)

    def test_prepare_uses_pinned_catalogs_offline_without_per_card_network_or_cache(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); self.seed(root)
            with patch('tools.card_batch.urlopen') as network:
                result = batch.prepare(root/'manifest.json', root/'prepared', root=root,
                    cache=root/'unused-card-cache', offline=True)
            network.assert_not_called()
            self.assertEqual(result['full_primary_faces'], 2)
            self.assertFalse(result['behavior_verified'])
            self.assertFalse((root/'unused-card-cache').exists())
            review = batch.read(root/'prepared/source-review.json')
            self.assertTrue(review['source_verified']); self.assertFalse(review['formal_pool_complete'])
            self.assertEqual(len(review['official_observations']), 2)

    def test_changed_body_or_byte_count_rejects_before_acceptance(self):
        for kind in ('body', 'count'):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                root = Path(tmp); _, _, sources = self.seed(root); source = sources[0]
                if kind == 'body':
                    path = root/source['response_file']; path.write_bytes(path.read_bytes()+b' ')
                else:
                    path = root/source['receipt_file']; pin = batch.read(path); pin['bytes'] += 1
                    path.write_text(json.dumps(pin), encoding='utf-8')
                with self.assertRaises(ValueError): batch.catalog_index(sources, root)

    def test_arbitrary_host_locale_path_and_query_do_not_become_catalog_proofs(self):
        for change in ('host', 'locale', 'path', 'query'):
            with self.subTest(change=change), TemporaryDirectory() as tmp:
                root = Path(tmp); _, _, sources = self.seed(root)
                path = root/sources[0]['receipt_file']; pin = batch.read(path)
                if change == 'host': pin['url'] = pin['url'].replace('hearthstone.blizzard.com', 'hearthstone.blizzard.com.invalid')
                elif change == 'locale': pin['url'] = pin['url'].replace('locale=zh_CN', 'locale=en_US')
                elif change == 'path': pin['url'] = pin['url'].replace('/api/cards', '/news')
                else: pin['url'] += '&unexpected=fixture'
                path.write_text(json.dumps(pin), encoding='utf-8')
                with self.assertRaises(ValueError): batch.catalog_index(sources, root)

    def test_duplicate_primary_across_pages_is_not_deduplicated(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); _, faces, sources = self.seed(root)
            sources.append(self.page(root, 'en_US', 2, faces['en_US']))
            with self.assertRaises(ValueError): batch.catalog_index(sources, root)

    def test_missing_assigned_primary_never_falls_back_to_network_or_other_locale(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); row, _, sources = self.seed(root)
            source = sources[0]; body = batch.read(root/source['response_file'])
            body['cards'] = [face for face in body['cards'] if face['id'] != row['dbf_id']]
            self.rewrite(root, source, body)
            with patch('tools.card_batch.urlopen') as network, self.assertRaises(ValueError):
                batch.prepare(root/'manifest.json', root/'prepared', root=root, offline=True)
            network.assert_not_called(); self.assertFalse((root/'prepared/source-review.json').exists())

    def test_matching_receipt_does_not_hide_changed_rules_or_numeric_face(self):
        for field, value in (('manaCost', 99), ('text', 'Explicitly wrong rules')):
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                root = Path(tmp); row, _, sources = self.seed(root); source = sources[0]
                body = batch.read(root/source['response_file']); body['cards'][0][field] = value
                self.rewrite(root, source, body)
                index = batch.catalog_index(sources, root)
                with self.assertRaises(ValueError): batch.catalog_official(row, source['locale'], index)

    def test_catalog_descriptors_reject_empty_duplicate_and_escaping_paths(self):
        source = dict(locale='en_US', response_file='pages/one.json', receipt_file='pages/one.receipt.json')
        for sources in ([], [source, source], [dict(source, response_file='../outside.json')]):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                batch.validate_catalog_sources(sources)

    def test_existing_per_card_cache_contract_remains_available(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); row, faces, _ = self.seed(root); path = root/f"{row['dbf_id']}-en_US.json"
            batch.save_new(path, dict(cards=[faces['en_US']]))
            batch.save_new(path.with_suffix('.receipt.json'), dict(
                url=f"https://playhearthstone.com/en-us/api/cards?card={row['dbf_id']}&locale=en_US", sha256=batch.sha(path)))
            with patch('tools.card_batch.urlopen') as network:
                observation = batch.official(row, 'en_US', root, offline=True)
            network.assert_not_called(); self.assertEqual(observation['face']['id'], row['dbf_id'])

    def seed_explicit_dependency(self, root):
        row, faces, sources = self.seed(root)
        token = deepcopy(row); token['id'] += '_CACHE_TOKEN'; token['dbf_id'] += 1
        token['collectible'] = False; token['tags']['COLLECTIBLE'] = 0
        (root/'source.json').write_text(json.dumps([row, token]), encoding='utf-8')
        manifest = batch.read(root/'manifest.json')
        manifest.update(source_sha256=batch.sha(root/'source.json'), dependencies=[token['id']],
            official_ids=[row['id'], token['id']], official_card_caches={token['id']: 'token-cache'})
        (root/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        for locale, face in faces.items():
            copy = deepcopy(face); copy.update(id=token['dbf_id'], collectible=False)
            path = root/'token-cache'/f"{token['dbf_id']}-{locale}.json"
            batch.save_new(path, dict(cards=[copy], fixture_only='Keep complete response'))
            batch.save_new(path.with_suffix('.receipt.json'), dict(
                url=f"https://playhearthstone.com/en-us/api/cards?card={token['dbf_id']}&locale={locale}&collectible=0",
                sha256=batch.sha(path), bytes=path.stat().st_size, observed_at='fixture'))
        return token, sources

    def test_explicit_noncollectible_dependency_joins_catalog_offline(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); token, _ = self.seed_explicit_dependency(root)
            with patch('tools.card_batch.urlopen') as network:
                result = batch.prepare(root/'manifest.json', root/'prepared', root=root, offline=True)
            network.assert_not_called()
            self.assertEqual((result['complete_rows'], result['full_primary_faces']), (2, 4))
            review = batch.read(root/'prepared/source-review.json')
            observations = [x for x in review['official_observations'] if x['card_id'] == token['id']]
            self.assertEqual(len(observations), 2)
            self.assertTrue(all('collectible=0' in x['url'] for x in observations))

    def test_explicit_dependency_missing_pair_or_wrong_bytes_never_fetches(self):
        for defect in ('language', 'receipt', 'bytes'):
            with self.subTest(defect=defect), TemporaryDirectory() as tmp:
                root = Path(tmp); token, _ = self.seed_explicit_dependency(root)
                path = root/'token-cache'/f"{token['dbf_id']}-zh_CN.json"
                if defect == 'language': path.unlink()
                elif defect == 'receipt': path.with_suffix('.receipt.json').unlink()
                else:
                    receipt = path.with_suffix('.receipt.json'); pin = batch.read(receipt); pin['bytes'] += 1
                    receipt.write_text(json.dumps(pin), encoding='utf-8')
                with patch('tools.card_batch.urlopen') as network, self.assertRaises(ValueError):
                    batch.prepare(root/'manifest.json', root/'prepared', root=root, offline=False)
                network.assert_not_called(); self.assertFalse((root/'prepared/source-review.json').exists())

    def test_same_face_in_catalog_and_explicit_cache_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); token, sources = self.seed_explicit_dependency(root)
            token_face = batch.read(root/'token-cache'/f"{token['dbf_id']}-en_US.json")['cards'][0]
            body = batch.read(root/sources[1]['response_file']); body['cards'].append(token_face)
            self.rewrite(root, sources[1], body)
            with patch('tools.card_batch.urlopen') as network, self.assertRaises(ValueError):
                batch.prepare(root/'manifest.json', root/'prepared', root=root, offline=True)
            network.assert_not_called()


if __name__ == '__main__': unittest.main()
