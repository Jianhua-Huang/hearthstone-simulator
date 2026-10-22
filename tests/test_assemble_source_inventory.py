"""Pinned source extraction must not become an implementation-filtered pool."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hs_sim.assemble_inventory import (audit_registered_support, build_source_inventory,
    text_observation)
from hs_sim.catalog import CardCatalog
from hs_sim.targets import canonical_digest
from tools.inventory_assemble_sources import main


def record(cid='A', text='<b>战吼：</b>&抽一张牌。', english='<b>Battlecry:</b>& Draw a card.', kind='MINION', tags=None):
    return dict(id=cid, dbf_id=100+sum(map(ord,cid)), name='源牌'+cid, name_en='Source '+cid,
        text=text, text_en=english, type=kind, collectible=True, cost=None, attack=None,
        health=None, tags={} if tags is None else tags, unknown_future_field={'retained':[None,2]})


class AssembleSourceInventoryTests(unittest.TestCase):
    def test_complete_original_rows_and_unknown_fields_remain_unchanged_and_independent(self):
        raw=record();original=deepcopy(raw);catalog=CardCatalog([raw]);result=build_source_inventory(catalog)
        row,=result['records'];self.assertEqual(row['source_record'],original)
        self.assertEqual(row['source_record_sha256'],canonical_digest(original))
        raw['unknown_future_field']['retained'].append('later')
        self.assertEqual(row['source_record'],original)
        self.assertIsNone(row['source_record']['cost']);self.assertIsNone(row['source_record']['health'])

    def test_raw_bilingual_halves_roundtrip_without_closing_markup_or_changing_numbers(self):
        raw=record(text='[x]<b>复生\n亡语：</b>&\n造成$3点伤害。',english='[x]<b>Reborn\nDeathrattle:</b>&\nDeal $3 damage.')
        result=build_source_inventory(CardCatalog([raw]));row=result['records'][0]
        for locale,field in (('zh_CN','text'),('en_US','text_en')):
            body=row['languages'][locale]
            self.assertEqual(body['prefix']+'&'+body['suffix'],raw[field])
            self.assertEqual(body['status'],'single')
        self.assertTrue(row['both_locales_single_nonempty_split'])

    def test_html_entities_are_preserved_and_do_not_create_fake_split_markers(self):
        value=text_observation('x &amp; y &#38; z &#x26; &lt;tag&gt; &nbsp;')
        self.assertEqual(value['marker_offsets'],[]);self.assertEqual(len(value['html_entities']),6)
        self.assertEqual(value['status'],'absent');self.assertIsNone(value['prefix'])

    def test_backslash_ampersands_are_observed_without_becoming_halves(self):
        for text in ('Attack \\& Armor','Attack \\\\& Armor'):
            with self.subTest(text=text):
                value=text_observation(text)
                self.assertEqual(value['marker_offsets'],[]);self.assertEqual(len(value['backslash_ampersand_offsets']),1)
        raw=record(text='攻击力与护甲值',english='Attack \\\\& Armor')
        row=build_source_inventory(CardCatalog([raw]))['records'][0]
        self.assertFalse(row['source_split_observed']);self.assertEqual(row['languages']['en_US']['status'],'absent')

    def test_unknown_entity_like_text_is_not_silently_treated_as_known_markup(self):
        value=text_observation('prefix &not_a_real_entity_123; suffix')
        self.assertEqual(value['status'],'single');self.assertEqual(value['html_entities'],[])
        self.assertIn('not_a_real_entity_123',value['suffix'])

    def test_empty_or_multiple_halves_are_retained_for_review_without_invented_parts(self):
        for text,status in (('&body','empty_half'),('prefix&','empty_half'),('a&b&c','ambiguous')):
            value=text_observation(text);self.assertEqual(value['status'],status)
            if status=='ambiguous':self.assertIsNone(value['prefix']);self.assertIsNone(value['suffix'])
        raw=record(text='没有分界',english='prefix&body')
        row=build_source_inventory(CardCatalog([raw]))['records'][0]
        self.assertTrue(row['source_split_observed']);self.assertFalse(row['both_locales_single_nonempty_split'])

    def test_named_craft_tags_remain_evidence_even_when_no_text_split_exists(self):
        raw=record(text='未知正文',english='Unknown body',tags={'CRAFTABLE_OUTPUT_POWER':1,'CRAFTABLE_FUTURE_RULE':2})
        result=build_source_inventory(CardCatalog([raw]));row=result['records'][0]
        self.assertEqual(row['named_craft_tags'],raw['tags']);self.assertTrue(row['craftable_output_tag_enabled'])
        self.assertFalse(row['source_split_observed']);self.assertEqual(row['executable_role'],'unverified')
        self.assertEqual(result['counts']['source_output_tag_enabled'],1)

    def test_unknown_flag_values_are_not_coerced_to_enabled_or_dropped(self):
        for value in (0,2,True,'1',None):
            raw=record(text='',english='',tags={'CRAFTABLE_OUTPUT_POWER':value})
            row=build_source_inventory(CardCatalog([raw]))['records'][0]
            self.assertFalse(row['craftable_output_tag_enabled']);self.assertEqual(row['named_craft_tags'],raw['tags'])

    def test_weapons_spells_and_heroes_keep_their_actual_kind_and_missing_stats(self):
        rows=[record(kind=kind,cid=kind)for kind in ('WEAPON','SPELL','HERO')]
        result=build_source_inventory(CardCatalog(rows))
        self.assertEqual(result['counts']['split_by_type'],{'HERO':1,'SPELL':1,'WEAPON':1})
        for item in result['records']:
            self.assertEqual(item['source_record']['type'],item['source_type'])
            self.assertIsNone(item['source_record']['attack']);self.assertIsNone(item['source_record']['health'])
            self.assertEqual(item['ordinary_live_membership'],'unverified')

    def test_proposed_standard_roots_do_not_remove_cross_series_sources(self):
        result=build_source_inventory(CardCatalog([record('A'),record('WILD')]),['A'])
        self.assertEqual({x['id']for x in result['records']},{'A','WILD'})
        self.assertEqual(result['counts']['proposed_standard_split_records'],1)
        self.assertFalse(next(x for x in result['records']if x['id']=='WILD')['proposed_standard_root'])
        self.assertFalse(result['formal_pool_complete']);self.assertFalse(result['runtime_pool_installed'])

    def test_numeric_tags_have_no_guessed_semantic_names(self):
        raw=record(tags={'4546':1,'4932':1,'CRAFTABLE_OUTPUT_POWER':1})
        row=build_source_inventory(CardCatalog([raw]))['records'][0]
        self.assertEqual(row['unresolved_numeric_tags'],{'4546':1,'4932':1})
        self.assertNotIn('allowed_source_roles',row)

    def test_proxy_references_preserve_full_directive_without_creating_minion_stats(self):
        raw=record('SPELL',kind='SPELL',text='时点&效果~GAMEPLAY_ASPROXY_SPELL',
            english='timing&effect~GAMEPLAY_ASPROXY_MISSING')
        row=build_source_inventory(CardCatalog([raw]))['records'][0]
        refs={x['card_id']:x for x in row['literal_proxy_references']}
        self.assertTrue(refs['SPELL']['self_reference']);self.assertTrue(refs['SPELL']['raw_record_present'])
        self.assertFalse(refs['MISSING']['raw_record_present'])
        self.assertTrue(row['languages']['en_US']['suffix'].endswith('~GAMEPLAY_ASPROXY_MISSING'))
        self.assertIsNone(row['source_record']['health'])

    def test_order_is_deterministic_and_prefix_groups_do_not_mean_behavior_compatibility(self):
        a,b=record('A'),record('B');b['text_en']=b['text_en'].replace('Draw a card.','Gain 3 Armor.')
        first=build_source_inventory(CardCatalog([b,a]));second=build_source_inventory(CardCatalog([a,b]))
        self.assertEqual(first,second);self.assertEqual(first['counts']['exact_bilingual_prefix_groups'],1)
        self.assertEqual(first['exact_bilingual_prefix_groups'][0]['source_ids'],['A','B'])
        self.assertTrue(all(x['compatibility']=='unverified'for x in first['records']))

    def test_missing_or_duplicate_root_ids_and_malformed_sources_are_explicit_errors(self):
        catalog=CardCatalog([record()])
        for roots in (['MISSING'],['A','A'],'A',[True]):
            with self.subTest(roots=roots),self.assertRaises(ValueError):build_source_inventory(catalog,roots)
        with self.assertRaises(ValueError):CardCatalog([record('A'),record('a')])
        with self.assertRaises(ValueError):text_observation(None)
        with self.assertRaises(ValueError):build_source_inventory(CardCatalog([record(tags={4546:1})]))

    def test_support_snapshot_never_filters_unimplemented_or_nonminion_sources(self):
        catalog=CardCatalog([record('A'),record('W',kind='WEAPON')]);inventory=build_source_inventory(catalog)
        saved=deepcopy(inventory);audit=audit_registered_support(inventory,catalog,['A'],['A'])
        self.assertEqual(inventory,saved);self.assertEqual({x['id']for x in audit['observed_source_rows']},{'A','W'})
        self.assertEqual(audit['source_split_rows_without_registered_definition'],['W'])
        self.assertEqual(audit['source_split_rows_without_reviewed_template'],['W'])
        self.assertTrue(audit['registration_is_not_effect_or_membership_verification'])

    def test_similar_names_core_prefixes_and_generation_exclusion_families_are_not_alias_proof(self):
        original=record('A');core=record('CORE_A',text='',english='');core['name_en']=original['name_en']
        catalog=CardCatalog([core,original]);inventory=build_source_inventory(catalog)
        audit=audit_registered_support(inventory,catalog,['CORE_A'],['CORE_A'],{'declared':['CORE_A','A']})
        row,=audit['reviewed_templates_without_source_split']
        self.assertEqual(row['marked_same_english_name_ids'],['A'])
        self.assertEqual(row['declared_generation_exclusion_families'][0]['source_ids'],['CORE_A','A'])
        self.assertFalse(row['live_membership_verified']);self.assertFalse(audit['formal_pool_complete'])
        self.assertEqual({x['id']for x in inventory['records']},{'A'})

    def test_missing_reviewed_source_is_reported_and_catalog_drift_or_duplicate_observations_fail(self):
        catalog=CardCatalog([record()]);inventory=build_source_inventory(catalog)
        audit=audit_registered_support(inventory,catalog,[],['MISSING'])
        self.assertTrue(audit['reviewed_templates_without_source_split'][0]['source_record_missing'])
        bad=deepcopy(inventory);bad['records'].append(deepcopy(bad['records'][0]))
        with self.assertRaises(ValueError):audit_registered_support(bad,catalog)
        altered=deepcopy(catalog.cards);altered[0]['text']='new source'
        with self.assertRaises(ValueError):audit_registered_support(inventory,CardCatalog(altered))
        bad=deepcopy(inventory);bad['formal_pool_complete']=True
        with self.assertRaises(ValueError):audit_registered_support(bad,catalog)


class AssembleInventoryCliTests(unittest.TestCase):
    def inputs(self, folder):
        source=folder/'cards.json';basis=folder/'roots.json';rows=[record()]
        raw=json.dumps(rows,ensure_ascii=False).encode();source.write_bytes(raw)
        basis.write_text(json.dumps(dict(source_sha256=hashlib.sha256(raw).hexdigest(),
            proposed_candidate_root_ids=['A'])),encoding='utf-8')
        return source,basis

    def argv(self,source,basis,out):
        return ['--data',str(source),'--root-manifest',str(basis),'--output',str(out)]

    def test_source_only_cli_does_not_build_a_registry_and_repeated_new_output_is_identical(self):
        with TemporaryDirectory()as directory:
            folder=Path(directory);source,basis=self.inputs(folder)
            with patch('hs_sim.cards.build_registry',side_effect=AssertionError('Source-only inventory must not build runtime')):
                with redirect_stdout(StringIO()):
                    main(self.argv(source,basis,folder/'one.json'));main(self.argv(source,basis,folder/'two.json'))
            self.assertEqual((folder/'one.json').read_bytes(),(folder/'two.json').read_bytes())
            value=json.loads((folder/'one.json').read_text(encoding='utf-8'))
            self.assertEqual(value['source']['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertFalse(value['proposed_standard_basis']['membership_certified'])

    def test_cli_refuses_old_outputs_same_paths_and_other_catalog_basis(self):
        with TemporaryDirectory()as directory:
            folder=Path(directory);source,basis=self.inputs(folder);out=folder/'old.json';out.write_bytes(b'preserve')
            with redirect_stdout(StringIO()),patch('sys.stderr',new=StringIO()):
                with self.assertRaises(SystemExit):main(self.argv(source,basis,out))
                with self.assertRaises(SystemExit):main(self.argv(source,basis,folder/'new.json')+['--support-audit',str(folder/'new.json')])
                data=json.loads(basis.read_text());data['source_sha256']='0'*64;basis.write_text(json.dumps(data))
                with self.assertRaises(SystemExit):main(self.argv(source,basis,folder/'other.json'))
            self.assertEqual(out.read_bytes(),b'preserve');self.assertFalse((folder/'new.json').exists())
            self.assertFalse((folder/'other.json').exists())

    def test_cli_detects_input_drift_before_writing_any_output(self):
        with TemporaryDirectory()as directory:
            folder=Path(directory);source,basis=self.inputs(folder);out=folder/'output.json'
            def mutate(*args,**kwargs):
                result=build_source_inventory(*args,**kwargs);source.write_bytes(source.read_bytes()+b' ');return result
            with patch('tools.inventory_assemble_sources.build_source_inventory',side_effect=mutate):
                with self.assertRaises(RuntimeError):main(self.argv(source,basis,out))
            self.assertFalse(out.exists())

    def test_optional_support_audit_is_separate_and_bound_to_exact_source_inventory_bytes(self):
        with TemporaryDirectory()as directory:
            folder=Path(directory);source,basis=self.inputs(folder);out=folder/'inventory.json';audit=folder/'audit.json'
            registry=SimpleNamespace(cards={'A':None},assemble_templates={'A':None},generation_families={},
                version='explicit-fixture',fingerprint=lambda:'fixture-fingerprint')
            with patch('hs_sim.cards.build_registry',return_value=registry),redirect_stdout(StringIO()):
                main(self.argv(source,basis,out)+['--support-audit',str(audit)])
            value=json.loads(audit.read_text(encoding='utf-8'))
            self.assertEqual(value['inventory_sha256'],hashlib.sha256(out.read_bytes()).hexdigest())
            self.assertEqual(value['reviewed_template_count'],1)
            self.assertNotIn('registered_definition_present',json.loads(out.read_text(encoding='utf-8'))['records'][0])


if __name__=='__main__':unittest.main()
