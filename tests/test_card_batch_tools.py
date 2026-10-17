"""Reject stale, incomplete, out-of-scope or drifting batch evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import card_batch as batch


class CardBatchToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'outputs/related-01'
        self.group = self.run / 'groups/000-test_sample'
        self.group.mkdir(parents=True)
        self.guard = {'hs_sim/engine/game.py': 'original'}
        self.ids = ['test_sample.Case.test_effect', 'test_sample.Case.test_privacy']
        inputs = dict(full_discovery=False, source_sha256=self.guard, selected=self.ids)
        result = dict(success=True, source_guard=True, exactly_once_coverage=True,
                      selected=2, executed=2, failures=[], errors=[], skipped=[], seconds=0.1)
        for path in (self.run, self.group):
            self.write(path / 'inputs.json', inputs)
            self.write(path / 'result.json', result)
        self.write(self.run / 'groups.json', [dict(module='test_sample', output=str(self.group), passed=True, exit_code=0)])
        (self.group / 'test-times.jsonl').write_text(''.join(json.dumps(dict(test=x, status='passed')) + '\n'
                                                          for x in self.ids), encoding='utf-8')

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def check(self, guard=None):
        return batch.verify_run(self.root, self.run, ['test_sample'], self.guard if guard is None else guard, self.ids)

    def test_complete_scoped_run_accepts_exact_current_source(self):
        receipt = self.check()
        self.assertEqual((receipt['methods'], receipt['full_regression_runs']), (2, 0))
        self.assertEqual(receipt['result_sha256'], batch.sha(self.run / 'result.json'))

    def test_green_run_from_changed_engine_cannot_be_inherited(self):
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.check({'hs_sim/engine/game.py': 'modified'})

    def test_missing_or_repeated_method_is_not_complete_coverage(self):
        path = self.group / 'test-times.jsonl'
        path.write_text(json.dumps(dict(test=self.ids[0], status='passed')) + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'per-method'):
            self.check()
        path.write_text((json.dumps(dict(test=self.ids[0], status='passed')) + '\n') * 2, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'per-method'):
            self.check()

    def test_failed_skipped_or_full_discovery_run_cannot_claim_acceptance(self):
        original = batch.read(self.run / 'result.json')
        for key, value in [('success', False), ('errors', ['error']), ('skipped', ['skip'])]:
            self.write(self.run / 'result.json', dict(original, **{key: value}))
            with self.assertRaises(ValueError):
                self.check()
        self.write(self.run / 'result.json', original)
        data = batch.read(self.run / 'inputs.json')
        self.write(self.run / 'inputs.json', dict(data, full_discovery=True))
        with self.assertRaisesRegex(ValueError, 'scoped'):
            self.check()

    def test_group_guard_cannot_differ_from_successful_parent(self):
        data = batch.read(self.group / 'inputs.json')
        self.write(self.group / 'inputs.json', dict(data, source_sha256={'hs_sim/engine/game.py': 'different'}))
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.check()

    def test_group_path_must_belong_to_original_run(self):
        self.write(self.run / 'groups.json', [dict(module='test_sample', output=str(self.root), passed=True, exit_code=0)])
        with self.assertRaisesRegex(ValueError, 'escaped'):
            self.check()

    def test_empty_or_overlapping_selection_is_rejected(self):
        data = batch.read(self.run / 'inputs.json')
        for ids in ([], self.ids + self.ids[:1]):
            self.write(self.run / 'inputs.json', dict(data, selected=ids))
            with self.assertRaisesRegex(ValueError, 'Selected methods'):
                self.check()

    def test_manifest_partition_and_three_file_scope_cannot_be_forged(self):
        manifest = dict(schema=1, roots=['A', 'B'], effect_groups=[dict(cards=['A', 'B'])],
                        source_sha256='0' * 64, allowed_files=['data/cards/new.json', 'hs_sim/cards/new.py', 'tests/test_new.py'])
        path = self.root / 'task.json'
        self.write(path, manifest)
        self.assertEqual(batch.load_manifest(path)['roots'], ['A', 'B'])
        for changes in (dict(dependencies=['A']), dict(effect_groups=[dict(cards=['A', 'A'])]),
                        dict(allowed_files=['data/cards/new.json', 'hs_sim/engine/game.py', 'tests/test_new.py'])):
            self.write(path, dict(manifest, **changes))
            with self.assertRaises(ValueError):
                batch.load_manifest(path)

    def test_commit_must_add_only_the_three_assigned_files(self):
        task = dict(allowed_files=['data/cards/new.json', 'hs_sim/cards/new.py', 'tests/test_new.py'])
        valid = '\n'.join('A\t' + x for x in task['allowed_files'])
        with patch.object(batch.subprocess, 'check_output', return_value=valid):
            self.assertEqual(len(batch.check_commit(self.root, 'commit', task)['added_files']), 3)
        for invalid in (valid.replace('A\t', 'M\t', 1), valid + '\nA\ths_sim/engine/game.py'):
            with patch.object(batch.subprocess, 'check_output', return_value=invalid), self.assertRaises(ValueError):
                batch.check_commit(self.root, 'commit', task)

    def face(self):
        raw = dict(id='A', dbf_id=101, name='卡牌', name_en='Card', text='<b>造成</b>$3点伤害。',
                   text_en='Deal $3 damage.', cost=2, attack=None, health=None, collectible=True,
                   tags=dict(CLASS=4, CARDTYPE=5, CARD_SET=1, RARITY=3))
        face = dict(id=101, name='卡牌', text='<b>造成</b>3点伤害。', manaCost=2, classId=4,
                    cardTypeId=5, cardSetId=1, rarityId=3, collectible=1)
        return raw, face

    def test_full_official_face_rejects_numeric_rules_and_identity_drift(self):
        raw, face = self.face()
        batch.check_face(raw, face, 'zh_CN')
        for changes in (dict(id=102), dict(text='造成4点伤害。'), dict(manaCost=3), dict(classId=7), dict(collectible=0)):
            with self.assertRaises(ValueError):
                batch.check_face(raw, dict(face, **changes), 'zh_CN')
        self.assertNotEqual(batch.display('Deal @ damage'), batch.display('Deal 3 damage'))

    def test_reviewed_dynamic_display_is_bound_to_complete_printed_script_value(self):
        raw, face = self.face()
        raw['text'] = '造成$@点伤害。'
        raw['tags']['TAG_SCRIPT_DATA_NUM_1'] = 3
        batch.check_face(raw, face, 'zh_CN', {'@': '3'})
        batch.check_face(raw, dict(face, text='造成点伤害。'), 'zh_CN', {'@': ''})
        for mapping in ({'@': '4'}, {'伤害': '治疗'}, {'@': 'unreviewed'}):
            with self.assertRaises(ValueError):
                batch.check_face(raw, face, 'zh_CN', mapping)

    def test_multiple_classes_are_checked_without_guessing_a_single_class(self):
        raw, face = self.face()
        raw['tags'].pop('CLASS')
        raw['tags']['MULTIPLE_CLASSES'] = 8193
        face['multiClassIds'] = [1, 14]
        batch.check_face(raw, face, 'zh_CN')
        with self.assertRaisesRegex(ValueError, 'multiple classes'):
            batch.check_face(raw, dict(face, multiClassIds=[1, 7]), 'zh_CN')

    def counter_faces(self):
        data = batch.read(Path(__file__).resolve().parents[1]/'data/cards/simple-followup-p74-v1.json')
        rows = {x['record']['id']:x['record'] for x in data['evidence_only']}
        return [(rows[o['card_id']], o['face'], o['locale'])
                for o in data['rejected_complete_primary_observations']]

    def test_eight_original_counter_faces_need_explicit_declaration_and_preserve_originals(self):
        observations = self.counter_faces()
        self.assertEqual(len(observations), 8)
        self.assertEqual({row['id'] for row, _, _ in observations},
                         {'JAIL_909', 'END_009', 'JAIL_974', 'JAIL_474'})
        for row, face, locale in observations:
            with self.subTest(card=row['id'], locale=locale):
                original = deepcopy((row, face))
                with self.assertRaises(ValueError):batch.check_face(row, face, locale)
                batch.check_face(row, face, locale, {'@': ''})
                self.assertEqual((row, face), original)

    def test_counter_display_keeps_the_complete_rule_body_and_denominator(self):
        row, face, locale = next(x for x in self.counter_faces()
                                if x[0]['id']=='JAIL_974' and x[2]=='en_US')
        for text in (face['text'].replace('4 other', '5 other'),
                     face['text'].replace('/4', '/5'),
                     face['text'].replace('enemy', 'friendly character'),
                     face['text'].replace("cast 'Fireball'", 'deal 6 damage'),
                     face['text'].replace('Deathrattle:', 'Battlecry:')):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'rules drift'):
                batch.check_face(row, dict(face, text=text), locale, {'@': ''})
        for text in (row['text_en'].replace('/4', '/5'),
                     row['text_en'].replace('4 other', '5 other')):
            with self.subTest(source=text), self.assertRaises(ValueError):
                batch.check_face(dict(row, text_en=text), face, locale, {'@': ''})

    def test_counter_display_cannot_remove_rule_values_arbitrary_labels_or_multiple_states(self):
        raw, face = self.face()
        for text in ('造成@点伤害。@<i>（已使用@张）</i>',
                     '造成3点伤害。@<i>（获得@护甲）</i>',
                     '造成3点伤害。@<i>（已使用@张）</i>额外规则',
                     '造成3点伤害。@<i>（已使用@张）</i>@<i>（已经就绪！）</i>',
                     '造成3点伤害。@<i>（已使用<b>@</b>张）</i>',
                     '造成3点伤害。@<i>（已使用{0}张）</i>',
                     '造成3点伤害。@<i>（@/5）</i>'):
            candidate = dict(raw, text=text)
            displayed = dict(face, text=text.replace('@', ''))
            with self.subTest(text=text), self.assertRaises(ValueError):
                batch.check_face(candidate, displayed, 'zh_CN', {'@': ''})
        raw['text']='造成3点伤害。@<i>(@)</i>'
        with self.assertRaises(ValueError):
            batch.check_face(raw, dict(face, text=raw['text'].replace('@','')), 'zh_CN', {'@':''})

    def test_client_plural_prefix_keeps_both_branches_and_all_actual_numbers(self):
        self.assertEqual(batch.display('Cast 3 |4(spell, spells) to deal 6 damage.'),
            batch.display('Cast 3 (spell, spells) to deal 6 damage.'))
        for text in ('4', '|40(spell, spells)', '|4(spell)', '|4(spell, spells', '|4((a,b),c)'):
            self.assertIn('|4' if text.startswith('|4') else '4', batch.display(text))
        self.assertNotEqual(batch.display('Deal @ damage'), batch.display('Deal 3 damage'))

    def test_plural_display_cannot_hide_changed_numbers_rules_or_removed_branches(self):
        raw, face = self.face()
        raw['text_en'] = 'Cast 3 |4(spell, spells) to deal 6 damage.'
        face.update(name=raw['name_en'], text='Cast 3 (spell, spells) to deal 6 damage.')
        batch.check_face(raw, face, 'en_US')
        for text in ('Cast 4 (spell, spells) to deal 6 damage.',
                'Cast 3 (spell, spells) to heal 6 Health.',
                'Cast 3 spells to deal 6 damage.', 'Cast 3 (spell, spells) to deal 7 damage.'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'rules drift'):
                batch.check_face(raw, dict(face, text=text), 'en_US')

    def colossal_face(self):
        raw, face = self.face()
        raw.update(type='MINION', attack=4, health=6,
            text='<b>巨型+3</b>。恢复3点生命值。', text_en='<b>Colossal +3.</b> Restore 3 Health.')
        raw['tags'].update(CARDTYPE=4, COLOSSAL=1)
        face.update(attack=4, health=6, cardTypeId=4, text='<b>巨型+3</b> 恢复3点生命值。')
        return raw, face, {'zh_CN': {'<b>巨型+3</b>。': '<b>巨型+3</b>'}}

    def test_explicit_colossal_separator_is_locale_scoped_and_keeps_all_rule_numbers(self):
        raw, face, mapping = self.colossal_face()
        batch.check_face(raw, face, 'zh_CN', mapping)
        english = dict(face, name=raw['name_en'], text=raw['text_en'])
        batch.check_face(raw, english, 'en_US', mapping)
        for text in ('<b>巨型+2</b> 恢复3点生命值。', '<b>巨型+3</b> 恢复4点生命值。',
                     '<b>巨型+3</b> 造成3点伤害。', '<b>巨型+3</b> 恢复3点生命值'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'rules drift'):
                batch.check_face(raw, dict(face, text=text), 'zh_CN', mapping)

    def test_colossal_separator_cannot_normalize_untyped_nonleading_or_repeated_rules(self):
        raw, face, mapping = self.colossal_face()
        candidates = [dict(raw, type='SPELL'), dict(raw, text='先' + raw['text']),
            dict(raw, text=raw['text'] * 2)]
        for tag in (None, True, 0, 2):
            candidate = deepcopy(raw)
            candidate['tags']['COLOSSAL'] = tag
            candidates.append(candidate)
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                batch.check_face(candidate, face, 'zh_CN', mapping)
        for declaration in ([], {'zh_CN': []}, dict(mapping, **{'@': ''}),
                {'zh_CN': {'<b>巨型+3</b>。': '<b>巨型+2</b>'}},
                {'zh_CN': {'<b>巨型+3</b>。': ''}}):
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                batch.check_face(raw, face, 'zh_CN', declaration)
        with self.assertRaises(ValueError):
            batch.check_face(raw, dict(face, name=raw['name_en']), 'en_US', mapping['zh_CN'])

    def test_real_black_blood_bilingual_faces_require_explicit_separator_and_preserve_originals(self):
        root = Path(__file__).resolve().parents[1]
        evidence = batch.read(root / 'outputs/card-parallel-p62-20261017/worker-230af709/preaudit-source-rejections-01.json')
        mapping = {'zh_CN': {'<b>巨型+3</b>。': '<b>巨型+3</b>'}}
        cache = root / 'outputs/card-integration-20261014/tool-plural-primary-original'
        checks = [c for c in evidence['checks'] if c['card_id'] == 'CATA_300']
        self.assertEqual({c['locale'] for c in checks}, {'zh_CN', 'en_US'})
        for check in checks:
            row, locale = check['record'], check['locale']
            original = deepcopy(row)
            body = cache / f"{row['dbf_id']}-{locale}.json"
            original_body = body.read_bytes()
            self.assertEqual(batch.canonical(row), check['record_sha256'])
            if locale == 'zh_CN':
                with self.assertRaisesRegex(ValueError, 'rules drift'):
                    batch.official(row, locale, cache, offline=True)
            observed = batch.official(row, locale, cache, offline=True, display_normalizations=mapping)
            self.assertEqual(observed['face'], check['face'])
            self.assertEqual((row, body.read_bytes()), (original, original_body))

    def test_two_complete_real_new_moon_faces_keep_explicit_counter_review_and_originals(self):
        data = batch.read(Path(__file__).resolve().parents[1]/'data/cards/simple-followup-p62-v1.json')
        rows = {r['record']['id']:r['record'] for r in data['evidence_only']}
        for cid in ('EDR_460', 'EDR_461'):
            for locale in ('zh_CN', 'en_US'):
                with self.subTest(cid=cid, locale=locale):
                    raw = rows[cid]
                    face = next(o['face'] for o in data['parent_observations']
                        if (o['card_id'],o['locale'])==(cid,locale))
                    original = deepcopy((raw,face))
                    with self.assertRaisesRegex(ValueError, 'rules drift'):
                        batch.check_face(raw,face,locale)
                    batch.check_face(raw,face,locale,{'@':''})
                    self.assertEqual((raw,face),original)

    def zero_minion(self):
        raw, face = self.face()
        raw.update(type='MINION', health=2)
        raw['tags']['CARDTYPE'] = 4
        face.update(cardTypeId=4, health=2, attack=0)
        return raw, face

    def test_missing_attack_is_still_strict_without_a_card_specific_zero_declaration(self):
        raw, face = self.zero_minion()
        with self.assertRaisesRegex(ValueError, 'numeric face drift'):
            batch.check_face(raw, face, 'zh_CN')

    def test_explicit_zero_minion_is_bound_to_both_primary_faces_without_mutating_source(self):
        raw, face = self.zero_minion()
        before = deepcopy(raw)
        batch.check_face(raw, face, 'zh_CN', numeric_normalizations={'attack': 0})
        english = dict(face, name=raw['name_en'], text=raw['text_en'])
        batch.check_face(raw, english, 'en_US', numeric_normalizations={'attack': 0})
        self.assertEqual(raw, before)
        self.assertIsNone(raw['attack'])

    def test_missing_cost_can_only_be_declared_as_exact_primary_zero(self):
        raw, face = self.face()
        raw.update(type='SPELL', cost=None)
        for value in (1, False, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                batch.check_face(raw, dict(face, manaCost=value), 'zh_CN', numeric_normalizations={'cost': 0})
        batch.check_face(raw, dict(face, manaCost=0), 'zh_CN', numeric_normalizations={'cost': 0})

    def test_zero_declaration_cannot_hide_a_present_raw_value_or_tag(self):
        raw, face = self.zero_minion()
        for changes, tags in (({'attack': 1}, {}), ({'attack': 0}, {}), ({}, {'ATK': 0})):
            candidate = deepcopy(raw)
            candidate.update(changes)
            candidate['tags'].update(tags)
            with self.subTest(changes=changes, tags=tags), self.assertRaises(ValueError):
                batch.check_face(candidate, face, 'zh_CN', numeric_normalizations={'attack': 0})

    def test_zero_policy_rejects_boolean_positive_health_and_nonminion_attack_overrides(self):
        raw, face = self.zero_minion()
        for mapping in ({'attack': False}, {'attack': 1}, {'health': 0}, {'manaCost': 0}, []):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                batch.check_face(raw, face, 'zh_CN', numeric_normalizations=mapping)
        raw['type'] = 'SPELL'
        with self.assertRaisesRegex(ValueError, 'actual minion'):
            batch.check_face(raw, face, 'zh_CN', numeric_normalizations={'attack': 0})

    def test_manifest_zero_policy_cannot_change_unassigned_cards_or_undeclared_fields(self):
        manifest = dict(schema=1, roots=['A'], effect_groups=[dict(cards=['A'])], source_sha256='0' * 64,
            allowed_files=['data/cards/new.json', 'hs_sim/cards/new.py', 'tests/test_new.py'],
            numeric_normalizations={'A': {'attack': 0}})
        path = self.root / 'zeros.json'
        self.write(path, manifest)
        self.assertEqual(batch.load_manifest(path)['numeric_normalizations'], {'A': {'attack': 0}})
        for value in ({'B': {'attack': 0}}, {'A': {}}, {'A': {'health': 0}}, {'A': {'cost': False}}, []):
            self.write(path, dict(manifest, numeric_normalizations=value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                batch.load_manifest(path)

    def test_cached_zero_observation_still_requires_explicit_semantic_validation(self):
        raw, face = self.zero_minion()
        cache = self.root / 'zeros'
        cache.mkdir()
        body = cache / '101-zh_CN.json'
        self.write(body, dict(cards=[face]))
        self.write(body.with_suffix('.receipt.json'), dict(
            url='https://hearthstone.blizzard.com/en-us/api/cards?card=101&locale=zh_CN', sha256=batch.sha(body)))
        original = body.read_bytes()
        with self.assertRaises(ValueError):
            batch.official(raw, 'zh_CN', cache, offline=True)
        checked = batch.official(raw, 'zh_CN', cache, offline=True, numeric_normalizations={'attack': 0})
        self.assertEqual(checked['face'], face)
        self.assertEqual(body.read_bytes(), original)

    def test_offline_cache_requires_full_body_receipt_and_checks_hash(self):
        raw, face = self.face()
        cache = self.root / 'cache'
        cache.mkdir()
        body = cache / '101-zh_CN.json'
        self.write(body, dict(cards=[face]))
        receipt = body.with_suffix('.receipt.json')
        self.write(receipt, dict(url='https://hearthstone.blizzard.com/en-us/api/cards?card=101&locale=zh_CN', sha256=batch.sha(body)))
        self.assertEqual(batch.official(raw, 'zh_CN', cache, offline=True)['face'], face)
        self.write(body, dict(cards=[dict(face, manaCost=3)]))
        with self.assertRaisesRegex(ValueError, 'cache body/receipt'):
            batch.official(raw, 'zh_CN', cache, offline=True)

    def test_preservation_rejects_old_pool_change_and_engine_edit(self):
        before = dict(definitions={'A': {'cost': 1}}, pool_cards={'A': {'cost': 1}}, families={}, pools=[],
                      default_fingerprint='stable', default_snapshot={'turn': 1},
                      source_guard={'hs_sim/engine/game.py': 'same', 'hs_sim/cards/constructed.py': 'before'})
        after = deepcopy(before)
        after['definitions']['B'] = {'cost': 2}
        after['pool_cards']['B'] = {'cost': 2}
        after['source_guard']['hs_sim/cards/constructed.py'] = 'after'
        self.assertEqual(batch.check_preservation(before, after, [], ['B'])['old_pool_cards'], 1)
        altered = deepcopy(after)
        altered['pool_cards']['A']['cost'] = 9
        with self.assertRaisesRegex(ValueError, 'pool metadata'):
            batch.check_preservation(before, altered, [], ['B'])
        altered = deepcopy(after)
        altered['source_guard']['hs_sim/engine/game.py'] = 'different'
        with self.assertRaisesRegex(ValueError, 'existing Python'):
            batch.check_preservation(before, altered, [], ['B'])

    def progress_fixture(self):
        from hs_sim.targets import canonical_digest
        data = batch.read(Path(__file__).resolve().parents[1]/'data/support/card-source-progress-labels-v1.json')
        self.assertEqual(canonical_digest(data), '8078f410dca34a1bfd9b8acaac003d2b4caa441e3482c412147a8f093ee84a43')
        self.assertEqual(canonical_digest(data['record']), data['record_sha256'])
        return data

    def test_explicit_trailing_progress_elision_matches_both_complete_primary_faces_without_mutation(self):
        data = self.progress_fixture(); original = deepcopy(data)
        for o in data['observations']:
            batch.check_face(data['record'], o['face'], o['locale'], {'@': '', '{0}': ''})
        self.assertEqual(data, original)

    def test_progress_elision_is_not_implicit_or_available_through_partial_declarations(self):
        data = self.progress_fixture()
        for o in data['observations']:
            for declaration in (None, {'@': ''}, {'{0}': ''}, {'@': '', '{0}': '3'}):
                with self.subTest(locale=o['locale'], declaration=declaration), self.assertRaises(ValueError):
                    batch.check_face(data['record'], o['face'], o['locale'], declaration)

    def test_progress_profile_cannot_remove_rule_counters_or_arbitrary_trailing_effects(self):
        data = self.progress_fixture(); o = next(o for o in data['observations'] if o['locale'] == 'en_US')
        original = data['record']['text_en']
        for text in ('{0} '+original, original.replace('(Ready!)', '(Gain 5 Armor!)'),
                original.replace('@', '', 1), original.replace('<i>({0} left!)</i>', '{0}')):
            raw = dict(data['record'], text_en=text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                batch.check_face(raw, o['face'], 'en_US', {'@': '', '{0}': ''})

    def test_progress_profile_keeps_main_rules_numbers_and_every_typed_field_strict(self):
        data = self.progress_fixture(); o = next(o for o in data['observations'] if o['locale'] == 'en_US')
        face = o['face']
        changes = [('text', face['text'].replace('8-Cost', '9-Cost')),
                   ('text', face['text'].replace('3 other spells', '4 other spells')),
                   ('manaCost', 8), ('id', face['id']+1), ('classId', face['classId']+1),
                   ('collectible', 0), ('attack', 0)]
        for key, value in changes:
            self.assertNotEqual(face.get(key), value)
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                batch.check_face(data['record'], dict(face, **{key:value}), 'en_US', {'@': '', '{0}': ''})


if __name__ == '__main__':
    unittest.main()
