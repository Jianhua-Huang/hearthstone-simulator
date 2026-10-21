"""Official host migration preserves strict complete-response cache proofs."""
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.card_batch import official, read, save_new, sha

PACKAGE = Path(__file__).resolve().parents[1] / 'data/cards/opponent-hand-entry-theft-v1.json'
OLD = 'https://hearthstone.blizzard.com/en-us/api/cards?card=131316&locale=en_US'
NEW = 'https://playhearthstone.com/en-us/api/cards?card=131316&locale=en_US'


class OfficialCacheTests(unittest.TestCase):
    def material(self):
        package=read(PACKAGE);row=package['cards'][0]['record']
        face=next(x['face']for x in package['official_observations']if x['locale']=='en_US')
        data=dict(cards=[face,{'id':999999,'fixture_only':'retain the complete response'}],
            cardCount=2,pageCount=1,page=1,fixture_only={'whole_response':True})
        return row,json.dumps(data,ensure_ascii=False).encode('utf-8')
    def cached(self,root,body,url):
        file=Path(root)/'131316-en_US.json';file.write_bytes(body)
        save_new(file.with_suffix('.receipt.json'),dict(url=url,sha256=sha(file),bytes=len(body),observed_at='fixture'))
        return file
    def test_both_official_hosts_keep_original_url_and_complete_pinned_body_offline(self):
        row,body=self.material()
        for url in (OLD,NEW):
            with self.subTest(url=url),TemporaryDirectory()as root:
                file=self.cached(root,body,url)
                with patch('tools.card_batch.urlopen')as network:
                    result=official(row,'en_US',root,offline=True)
                network.assert_not_called();self.assertEqual(result['url'],url)
                self.assertEqual(file.read_bytes(),body)
                self.assertEqual(read(file)['fixture_only'],{'whole_response':True})
    def test_arbitrary_host_query_locale_and_byte_mismatch_are_rejected_without_network(self):
        row,body=self.material()
        for url,corrupt in ((NEW.replace('playhearthstone.com','playhearthstone.com.attacker.invalid'),False),
                (NEW+'&extra=1',False),(NEW.replace('en_US','zh_CN'),False),(NEW,True)):
            with self.subTest(url=url,corrupt=corrupt),TemporaryDirectory()as root:
                file=self.cached(root,body,url)
                if corrupt:file.write_bytes(body+b' ')
                with patch('tools.card_batch.urlopen')as network,self.assertRaises(ValueError):
                    official(row,'en_US',root,offline=True)
                network.assert_not_called()
    def test_fresh_fetch_uses_canonical_host_and_preserves_the_whole_response(self):
        row,body=self.material()
        with TemporaryDirectory()as root:
            with patch('tools.card_batch.urlopen',return_value=BytesIO(body))as network:
                result=official(row,'en_US',root)
            self.assertEqual(network.call_args.args[0].full_url,NEW)
            file=Path(result['response_file']);self.assertEqual(file.read_bytes(),body)
            self.assertEqual(result['observation']['url'],NEW)
            self.assertEqual(result['response_sha256'],sha(file))
    def test_torn_pair_or_missing_primary_face_never_becomes_a_fresh_accepted_cache(self):
        row,body=self.material()
        with TemporaryDirectory()as root:
            file=Path(root)/'131316-en_US.json';file.write_bytes(body)
            with patch('tools.card_batch.urlopen')as network,self.assertRaises(ValueError):
                official(row,'en_US',root)
            network.assert_not_called();self.assertEqual(file.read_bytes(),body)
        with TemporaryDirectory()as root:
            invalid=json.dumps({'cards':[]}).encode()
            with patch('tools.card_batch.urlopen',return_value=BytesIO(invalid)),self.assertRaises(ValueError):
                official(row,'en_US',root)
            file=Path(root)/'131316-en_US.json'
            self.assertEqual(file.read_bytes(),invalid)
            receipt=read(file.with_suffix('.receipt.json'))
            self.assertEqual((receipt['sha256'],receipt['bytes']),(sha(file),len(invalid)))
            with patch('tools.card_batch.urlopen')as network,self.assertRaises(ValueError):
                official(row,'en_US',root,offline=True)
            network.assert_not_called()
    def test_ambiguous_full_response_is_preserved_but_never_accepted_or_retried(self):
        row,body=self.material();data=json.loads(body)
        data['cards'].append(data['cards'][0]);body=json.dumps(data).encode()
        with TemporaryDirectory()as root:
            with patch('tools.card_batch.urlopen',return_value=BytesIO(body)),self.assertRaises(ValueError):
                official(row,'en_US',root)
            file=Path(root)/'131316-en_US.json';self.assertEqual(file.read_bytes(),body)
            self.assertEqual(read(file.with_suffix('.receipt.json'))['sha256'],sha(file))
            with patch('tools.card_batch.urlopen')as network,self.assertRaises(ValueError):
                official(row,'en_US',root)
            network.assert_not_called();self.assertEqual(file.read_bytes(),body)


if __name__=='__main__':unittest.main()
