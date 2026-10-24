"""A surface inventory must expose missing evidence without certifying behavior."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict, replace
from io import StringIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine.hand_parity import HandParityTransformProfile
from hs_sim.engine.held_battlecry_forms import HeldBattlecryFormsProfile
from hs_sim.engine.live_hand_spells import LiveHandSpellProfile
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SpellSchool, TargetSpec
from hs_sim.engine.turn_start_draws import TurnDrawSuppressionProfile
from tools import audit_standard_surface as audit


ROOT = Path(__file__).resolve().parents[1]


def row(cid='audit.root', kind='MINION', **overrides):
    result = dict(id=cid, name=cid, type=kind, collectible=True, cost=3,
                  attack=2, health=4, text='', tags={'CLASS': 12, 'RARITY': 1})
    result.update(overrides)
    return result


def definition(raw, **overrides):
    kind = CardType[raw['type']]
    values = dict(cost=raw.get('cost', 0), metadata=metadata_from_record(raw))
    if kind in (CardType.MINION, CardType.WEAPON):
        values['attack'] = raw.get('attack', 0)
    if kind in (CardType.MINION, CardType.HERO):
        values['health'] = raw.get('health', 0)
    if kind in (CardType.WEAPON, CardType.LOCATION):
        values['durability'] = raw.get('health', 0)
    values.update(overrides)
    return CardDefinition(raw['id'], raw['name'], kind, **values)


def registry(*cards, **profiles):
    cards = {card.id: card for card in cards}
    return SimpleNamespace(cards=cards, card=cards.__getitem__, version='audit.fixture', **profiles)


class StandardSurfaceAuditTests(unittest.TestCase):
    def test_weapon_and_location_health_is_durability_and_source_is_preserved(self):
        rows = [row('weapon', 'WEAPON'), row('location', 'LOCATION'), row('minion'), row('hero', 'HERO')]
        before = deepcopy(rows)
        result = audit.audit_surface(rows, [r['id'] for r in rows], registry(*(definition(r) for r in rows)))
        self.assertEqual(result['printed_mismatches'], [])
        self.assertEqual(result['source_absences'], [])
        self.assertEqual(result['registered_kind_counts'], dict(weapon=1, location=1, minion=1, hero=1))
        self.assertEqual(rows, before)

    def test_wrong_printed_values_and_complete_metadata_are_reported(self):
        raw = row()
        card = definition(raw)
        changed = replace(card, name='wrong', cost=9, health=1,
                          metadata=replace(card.metadata, tribes=('mech',)))
        result = audit.audit_surface([raw], [raw['id']], registry(changed))
        differences = result['printed_mismatches'][0]['differences']
        self.assertEqual({d['field'] for d in differences}, {'name', 'cost', 'health', 'metadata.tribes'})
        self.assertFalse(result['known_printed_values_match'])
        self.assertFalse(result['all_registered_surfaces_accounted'])

    def test_missing_zero_fields_remain_unknown_while_explicit_zero_is_compared(self):
        absent, explicit = row('absent'), row('explicit', cost=0, attack=0)
        absent.pop('cost'); absent.pop('attack')
        result = audit.audit_surface([absent, explicit], ['absent', 'explicit'],
                                     registry(definition(absent), definition(explicit)))
        self.assertEqual(result['printed_mismatches'], [])
        self.assertEqual([r['card_id'] for r in result['source_absences']], ['absent'])
        self.assertEqual({f['field'] for f in result['source_absences'][0]['fields']}, {'cost', 'attack'})
        self.assertTrue(all(f['reason'] == 'source_value_absent' for f in result['source_absences'][0]['fields']))
        self.assertFalse(result['all_registered_surfaces_accounted'])

    def test_unregistered_roots_are_retained_and_nonroots_do_not_expand_scope(self):
        rows = [row('known'), row('missing'), row('other')]
        result = audit.audit_surface(rows, ['known', 'missing'], registry(definition(rows[0])))
        self.assertEqual((result['candidate_root_count'], result['registered_root_count']), (2, 1))
        self.assertEqual(result['unregistered_root_ids'], ['missing'])
        self.assertEqual([r['card_id'] for r in result['observations']], ['known', 'missing'])
        self.assertFalse(result['observations'][1]['registered'])
        self.assertFalse(result['all_roots_registered'])

    def test_input_selection_and_school_alone_do_not_implement_a_body(self):
        raw = row('spell', 'SPELL', text='Deal 3 damage.')
        card = definition(raw, requires_target=True, targeting=TargetSpec(), spell_school=SpellSchool.FIRE)
        result = audit.audit_surface([raw], ['spell'], registry(card))
        self.assertEqual(result['unresolved_text_surfaces'], ['spell'])
        self.assertEqual(result['observations'][0]['semantic_fields'], [])
        self.assertFalse(result['registered_texts_have_declarations'])

    def test_callback_or_keyword_presence_never_certifies_all_clauses_or_execution(self):
        raw = row(text='Taunt. Battlecry: draw a card.')
        for overrides, field in [({'keywords': (Keyword.TAUNT,)}, 'keywords'),
                                 ({'battlecry': 'not.executed.by.this.audit'}, 'battlecry')]:
            with self.subTest(field=field):
                result = audit.audit_surface([raw], [raw['id']], registry(definition(raw, **overrides)))
                self.assertIn(field, result['observations'][0]['semantic_fields'])
                self.assertTrue(result['registered_texts_have_declarations'])
                for key in ('behavior_complete', 'formal_pool_certified', 'cn_calibration_complete'):
                    self.assertIs(result[key], False)

    def test_external_mechanisms_keep_full_typed_proof_including_osks_real_forms(self):
        profiles = [('hand_parity_profiles', HandParityTransformProfile('parity', 'other')),
                    ('turn_draw_profiles', TurnDrawSuppressionProfile('draw')),
                    ('live_hand_spell_profiles', LiveHandSpellProfile('hand', 'spell')),
                    ('held_battlecry_forms_profiles', HeldBattlecryFormsProfile('osk', ('form1', 'form2')))]
        rows = [row(p.card_id, text='External native effect.') for _, p in profiles]
        rows.append(row('mayor', text='All targets are chosen randomly.'))
        maps = {name: {p.card_id: p} for name, p in profiles}
        maps['random_target_cards'] = frozenset(('mayor',))
        result = audit.audit_surface(rows, [r['id'] for r in rows], registry(*(definition(r) for r in rows), **maps))
        observed = {r['card_id']: r for r in result['observations']}
        self.assertEqual(result['unresolved_text_surfaces'], [])
        for name, profile in profiles:
            self.assertEqual(observed[profile.card_id]['external_declarations'],
                             [dict(registry_property=name, declaration=asdict(profile))])
        self.assertEqual(observed['mayor']['external_declarations'],
                         [dict(registry_property='random_target_cards', card_id='mayor')])

    def test_unknown_maps_do_not_hide_bodies_and_malformed_or_wrong_root_proof_is_rejected(self):
        raw = row(text='Unreviewed external effect.')
        r = registry(definition(raw), arbitrary_profiles={raw['id']: 'claim'})
        self.assertEqual(audit.audit_surface([raw], [raw['id']], r)['unresolved_text_surfaces'], [raw['id']])
        for value in ({'card_id': raw['id']}, TurnDrawSuppressionProfile('other'), TurnDrawSuppressionProfile):
            with self.subTest(value=value):
                r = registry(definition(raw), turn_draw_profiles={raw['id']: value})
                with self.assertRaisesRegex(ValueError, 'root-bound typed'):
                    audit.audit_surface([raw], [raw['id']], r)

    def test_invalid_roots_and_source_identities_are_rejected_instead_of_normalized(self):
        raw = row()
        for ids in (None, [], ('audit.root',), [['audit.root']], [True], [''], [' audit.root'], [raw['id']] * 2, ['missing']):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    audit.audit_surface([raw], ids, registry())
        for rows in ([raw, raw], [{'id': []}], [dict(raw, collectible=False)], [dict(raw, type='HERO_POWER')]):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    audit.audit_surface(rows, [raw['id']], registry())

    def cli_fixture(self, folder):
        source, inventory, output = (folder / name for name in ('source.json', 'inventory.json', 'audit.json'))
        raw = row(text='Battlecry: do something.')
        source.write_text(json.dumps([raw]), encoding='utf-8')
        inventory.write_text(json.dumps(dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                             candidate_root_ids=[raw['id']])), encoding='utf-8')
        args = ['--source', str(source), '--inventory', str(inventory), '--output', str(output)]
        return source, inventory, output, args, registry(definition(raw))

    def test_cli_binds_full_inputs_emits_bounded_counts_and_never_overwrites(self):
        with TemporaryDirectory() as folder:
            source, inventory, output, args, r = self.cli_fixture(Path(folder))
            stdout = StringIO()
            with patch('hs_sim.cards.build_registry', return_value=r), redirect_stdout(stdout):
                self.assertEqual(audit.main(args), 1)  # A body declaration is genuinely missing.
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['source']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(saved['inventory']['sha256'], hashlib.sha256(inventory.read_bytes()).hexdigest())
            self.assertEqual(saved['game_actions'], 0)
            self.assertEqual(json.loads(stdout.getvalue())['unresolved_text_count'], 1)
            self.assertLess(len(stdout.getvalue()), 650)
            before = output.read_bytes()
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit), patch('hs_sim.cards.build_registry') as build:
                audit.main(args)
            build.assert_not_called()
            self.assertEqual(output.read_bytes(), before)

    def test_cli_rejects_wrong_full_source_pin_before_building_registry(self):
        with TemporaryDirectory() as folder:
            source, _, output, args, _ = self.cli_fixture(Path(folder))
            source.write_bytes(source.read_bytes() + b'\n')
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit), patch('hs_sim.cards.build_registry') as build:
                audit.main(args)
            build.assert_not_called()
            self.assertFalse(output.exists())

    def test_cli_detects_source_or_inventory_change_during_observation(self):
        for which in (0, 1):
            with self.subTest(input=which), TemporaryDirectory() as folder:
                source, inventory, output, args, r = self.cli_fixture(Path(folder))
                def mutate():
                    p = (source, inventory)[which]
                    p.write_bytes(p.read_bytes() + b'\n')
                    return r
                with patch('hs_sim.cards.build_registry', side_effect=mutate), self.assertRaisesRegex(RuntimeError, 'changed during'):
                    audit.main(args)
                self.assertFalse(output.exists())

    def test_cli_rejects_registry_source_changes_instead_of_signing_mixed_state(self):
        with TemporaryDirectory() as folder:
            _, _, output, args, r = self.cli_fixture(Path(folder))
            with patch('hs_sim.cards.build_registry', return_value=r), patch.object(
                    audit.batch, 'source_guard', side_effect=[{'source.py': 'before'}, {'source.py': 'after'}]):
                with self.assertRaisesRegex(RuntimeError, 'Registry sources changed'):
                    audit.main(args)
            self.assertFalse(output.exists())

    def test_fixed_cn37_inventory_checks_every_root_and_keeps_external_proofs(self):
        from hs_sim.cards import build_registry
        manifest = json.loads((ROOT / 'data/cards/launch-candidate-cn37-v1.json').read_text(encoding='utf-8'))
        source = (ROOT / 'outputs/card-integration-20261014/cards-37.0.0.255026.json').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), manifest['source_sha256'])
        result = audit.audit_surface(json.loads(source), manifest['candidate_root_ids'], build_registry())
        self.assertEqual(result['candidate_root_count'], 1322)
        self.assertEqual({r['card_id'] for r in result['observations']}, set(manifest['candidate_root_ids']))
        self.assertLessEqual(set(result['unregistered_root_ids']), {'BE_588'})
        self.assertEqual(result['printed_mismatches'], [])
        self.assertEqual(result['unresolved_text_surfaces'], [])
        observed = {r['card_id']: r for r in result['observations']}
        for cid in ('CATA_615', 'CORE_CFM_670', 'TIME_617', 'TLC_241', 'TLC_452'):
            self.assertTrue(observed[cid]['external_declarations'])
        osk = observed['TLC_452']['external_declarations'][0]
        self.assertEqual(osk['registry_property'], 'held_battlecry_forms_profiles')
        self.assertEqual(len(osk['declaration']['forms']), 31)
        self.assertFalse(result['behavior_complete'])
        self.assertFalse(result['formal_pool_certified'])
        self.assertFalse(result['cn_calibration_complete'])


if __name__ == '__main__':
    unittest.main()
