"""Audit pinned root faces and declarations, without claiming effect support."""
from collections import Counter
from dataclasses import asdict, fields, is_dataclass
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import card_batch as batch
from hs_sim.engine.model import CardDefinition
from hs_sim.cards.metadata import metadata_from_record

# Printed values and input selection alone do not implement the printed body.
NON_BODY_FIELDS = frozenset(('id','name','kind','cost','attack','health','durability',
    'metadata','spell_school','requires_target','targeting','target_rule'))
EXTERNAL_MAPS = ('hand_parity_profiles', 'turn_draw_profiles', 'live_hand_spell_profiles',
                 'held_battlecry_forms_profiles')
META_FIELDS = ('collectible','classes','rarity','runes','tribes','factions','subtypes')
PRIMARY_TYPES = {'MINION': 4, 'SPELL': 5, 'WEAPON': 7, 'HERO': 3, 'LOCATION': 39}
PRIMARY_NUMBERS = {'cost': 'manaCost', 'attack': 'attack', 'health': 'health', 'durability': 'health'}


def load_primary_catalog(path, source_sha256, inventory_sha256, *, root=ROOT):
    """Load whole pinned official responses; the receipt is local byte evidence."""
    raw = Path(path).read_bytes()
    manifest = json.loads(raw.decode('utf-8-sig'))
    if (type(manifest) is not dict or set(manifest) != {
            'schema', 'source_sha256', 'inventory_sha256', 'catalog_sources', 'files'} or
            type(manifest['schema']) is not int or manifest['schema'] != 1 or
            manifest['source_sha256'] != source_sha256 or manifest['inventory_sha256'] != inventory_sha256):
        raise ValueError('Primary catalog manifest differs from its full source/inventory binding')
    batch.validate_catalog_sources(manifest['catalog_sources'])
    paths = {s[key] for s in manifest['catalog_sources'] for key in ('response_file', 'receipt_file')}
    if type(manifest['files']) is not dict or set(manifest['files']) != paths:
        raise ValueError('Every full catalog body and receipt requires its exact file pin')
    root = Path(root).resolve()
    for name, digest in manifest['files'].items():
        file = (root / batch.relative_file(name)).resolve()
        if not file.is_relative_to(root) or batch.sha(file) != digest:
            raise ValueError('Primary catalog full file pin changed or escaped its root')
    index = batch.catalog_index(manifest['catalog_sources'], root)
    if (Path(path).read_bytes() != raw or
            any(batch.sha(root / name) != digest for name, digest in manifest['files'].items())):
        raise RuntimeError('Primary catalog changed during observation')
    return index, dict(path=str(Path(path).resolve()), sha256=hashlib.sha256(raw).hexdigest(),
                      files=manifest['files'], evidence_scope='Printed numeric scalar only; no rule or CN deployment certification')


def primary_numeric_evidence(raw, field, index):
    """Require matching numeric values in both primary locales; never infer zero."""
    if index is None:
        return None
    observations, values = [], []
    for locale in ('zh_CN', 'en_US'):
        observation = index.get((locale, raw['dbf_id']))
        if observation is None:
            observations.append(dict(locale=locale, status='primary_face_missing'))
            continue
        face = observation['face']
        name = raw['name'] if locale == 'zh_CN' else raw['name_en']
        if (face.get('id') != raw['dbf_id'] or face.get('name') != name or
                face.get('cardTypeId') != PRIMARY_TYPES[raw['type']] or
                type(face.get('collectible')) not in (int, bool) or face['collectible'] not in (0, 1) or
                bool(face['collectible']) != raw['collectible']):
            raise ValueError('Primary numeric evidence selected a different physical face: ' + raw['id'])
        value = face.get(PRIMARY_NUMBERS[field])
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('Primary numeric evidence requires an explicit nonnegative integer')
        if value is not None:
            values.append(value)
        observations.append(dict(locale=locale, url=observation['url'],
            response_file=observation['response_file'], response_sha256=observation['response_sha256'],
            full_face_sha256=batch.canonical(face), value=value,
            status='explicit_primary_number' if value is not None else 'primary_value_absent'))
    if len(set(values)) > 1:
        raise ValueError('Primary locales disagree on the printed number: ' + raw['id'] + '.' + field)
    confirmed = len(values) == 2
    return dict(field=field, confirmed=confirmed, value=values[0] if confirmed else None,
                observations=observations, scope='Numeric scalar; complete rule text is not compared')


def external_declarations(registry, card_id):
    result = []
    for name in EXTERNAL_MAPS:
        mapping = getattr(registry, name, {})
        if card_id in mapping:
            value = mapping[card_id]
            if (not is_dataclass(value) or isinstance(value, type) or
                    getattr(value, 'card_id', None) != card_id):
                raise ValueError('External source proof requires its full root-bound typed declaration')
            result.append(dict(registry_property=name, declaration=asdict(value)))
    if card_id in getattr(registry, 'random_target_cards', ()):
        result.append(dict(registry_property='random_target_cards', card_id=card_id))
    return result


def audit_surface(source_rows, root_ids, registry, *, primary_index=None):
    if (type(root_ids) is not list or not root_ids or
            any(type(cid) is not str or not cid or cid.strip() != cid for cid in root_ids) or
            len(root_ids) != len(set(root_ids))):
        raise ValueError('Surface audit requires unique explicit nonempty root identities')
    if type(source_rows) is not list or any(
            type(row) is not dict or type(row.get('id')) is not str or
            not row['id'] or row['id'].strip() != row['id'] for row in source_rows):
        raise ValueError('Surface audit requires the complete source row list')
    by_id = {row['id']:row for row in source_rows}
    if len(by_id) != len(source_rows):
        raise ValueError('Duplicate physical source identity')
    missing_source = sorted(set(root_ids)-set(by_id))
    if missing_source:
        raise ValueError('Pinned root is absent from the full source: '+','.join(missing_source))
    observations, mismatches, absences, unresolved, missing = [], [], [], [], []
    unresolved_absences, confirmed_absent_fields = [], 0
    for cid in sorted(root_ids):
        raw = by_id[cid]
        if raw.get('collectible') is not True or raw.get('type') not in ('MINION','SPELL','WEAPON','HERO','LOCATION'):
            raise ValueError('Explicit root is not a collectible card: '+cid)
        if cid not in registry.cards:
            missing.append(cid)
            observations.append(dict(card_id=cid, registered=False, source_record_sha256=batch.canonical(raw)))
            continue
        card = registry.card(cid)
        differences, unknown = [], []

        def compare(field, expected, actual):
            if expected is None:
                item = dict(field=field, actual=actual, reason='source_value_absent')
                proof = primary_numeric_evidence(raw, field, primary_index) if field in PRIMARY_NUMBERS else None
                if proof is not None:
                    item['primary_evidence'] = proof
                    if proof['confirmed'] and batch.canonical(proof['value']) != batch.canonical(actual):
                        differences.append(dict(field=field, expected=proof['value'], actual=actual,
                                                basis='two_locale_primary_numeric_evidence'))
                unknown.append(item)
            elif batch.canonical(expected) != batch.canonical(actual):
                differences.append(dict(field=field, expected=expected, actual=actual))

        compare('name',raw.get('name'),card.name)
        compare('kind',raw['type'],card.kind.name)
        compare('cost',raw.get('cost'),card.cost)
        if raw['type'] in ('MINION','WEAPON'):
            compare('attack',raw.get('attack'),card.attack)
        if raw['type'] in ('MINION','HERO'):
            compare('health',raw.get('health'),card.health)
        if raw['type'] in ('WEAPON','LOCATION'):
            compare('durability',raw.get('health'),card.durability)
        if card.metadata is None:
            differences.append(dict(field='metadata',expected='complete printed metadata',actual=None))
        else:
            expected, actual = asdict(metadata_from_record(raw)), asdict(card.metadata)
            for key in META_FIELDS:
                compare('metadata.'+key,expected[key],actual[key])
        empty = CardDefinition(card.id,card.name,card.kind)
        semantic = [field.name for field in fields(CardDefinition) if field.name not in NON_BODY_FIELDS
            and getattr(card,field.name) != getattr(empty,field.name)]
        external = external_declarations(registry,cid)
        text = bool(batch.display(raw.get('text','')))
        if text and not semantic and not external:
            unresolved.append(cid)
        if differences:
            mismatches.append(dict(card_id=cid,differences=differences))
        if unknown:
            absences.append(dict(card_id=cid,fields=unknown))
            still_unknown = [item for item in unknown if not item.get('primary_evidence', {}).get('confirmed', False)]
            confirmed_absent_fields += len(unknown) - len(still_unknown)
            if still_unknown:
                unresolved_absences.append(dict(card_id=cid, fields=still_unknown))
        observations.append(dict(card_id=cid,registered=True,source_record_sha256=batch.canonical(raw),
            definition_sha256=batch.canonical(asdict(card)), semantic_fields=semantic,
            external_declarations=external,printed_differences=differences,source_absences=unknown,
            text_without_body_declaration=text and not semantic and not external))
    return dict(schema=1,candidate_root_count=len(root_ids),registered_root_count=len(root_ids)-len(missing),
        unregistered_root_ids=missing,printed_mismatches=mismatches,source_absences=absences,
        unresolved_source_absences=unresolved_absences,
        primary_confirmed_absent_field_count=confirmed_absent_fields,
        unresolved_text_surfaces=unresolved,observations=observations,
        registered_kind_counts=dict(Counter(registry.card(cid).kind.value for cid in root_ids if cid in registry.cards)),
        all_roots_registered=not missing,
        known_printed_values_match=not mismatches,
        registered_texts_have_declarations=not unresolved,
        all_registered_surfaces_accounted=not mismatches and not unresolved and not unresolved_absences,
        behavior_complete=False,formal_pool_certified=False,cn_calibration_complete=False,
        limits=['Declarations and printed material are not execution evidence.',
            'One declaration does not prove all printed clauses or their dependencies are implemented.',
            'Absent printed source values remain unverified; no zero value is guessed.',
            'Deck/generation identities, legality, pools, effects and timing require separate evidence.',
            'External proof maps are explicit; unknown external mechanisms remain unresolved.'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--primary-catalog',type=Path,
                        help='Optional manifest pinning complete bilingual primary catalog bodies and receipts')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.output.exists():parser.error('Use a new output file; old evidence is preserved')
    source=args.source.read_bytes();inventory=args.inventory.read_bytes()
    policy=json.loads(inventory.decode('utf-8-sig'))
    if hashlib.sha256(source).hexdigest()!=policy['source_sha256']:
        parser.error('The full source differs from the explicit root inventory pin')
    guard=batch.source_guard(ROOT)
    primary_index, primary_binding = None, None
    if args.primary_catalog:
        primary_index, primary_binding = load_primary_catalog(args.primary_catalog,
            hashlib.sha256(source).hexdigest(), hashlib.sha256(inventory).hexdigest(), root=ROOT)
    from hs_sim.cards import build_registry
    registry=build_registry()
    result=audit_surface(json.loads(source.decode('utf-8-sig')),policy['candidate_root_ids'],registry,
                         primary_index=primary_index)
    if args.source.read_bytes()!=source or args.inventory.read_bytes()!=inventory:
        raise RuntimeError('Source or root inventory changed during the audit')
    if batch.source_guard(ROOT)!=guard:
        raise RuntimeError('Registry sources changed during the audit')
    if primary_binding and (batch.sha(args.primary_catalog) != primary_binding['sha256'] or
            any(batch.sha(ROOT / name) != digest for name, digest in primary_binding['files'].items())):
        raise RuntimeError('Primary catalog changed during the audit')
    result.update(source=dict(path=str(args.source.resolve()),sha256=hashlib.sha256(source).hexdigest()),
        inventory=dict(path=str(args.inventory.resolve()),sha256=hashlib.sha256(inventory).hexdigest()),
        content_version=registry.version,source_guard=guard,primary_catalog=primary_binding,game_actions=0)
    batch.save_new(args.output,result)
    print(json.dumps(dict(candidate_root_count=result['candidate_root_count'],
        registered_root_count=result['registered_root_count'],
        unregistered_root_count=len(result['unregistered_root_ids']),
        printed_mismatch_count=len(result['printed_mismatches']),
        unresolved_text_count=len(result['unresolved_text_surfaces']),
        absent_source_card_count=len(result['source_absences']),
        unresolved_source_card_count=len(result['unresolved_source_absences']),
        primary_confirmed_absent_field_count=result['primary_confirmed_absent_field_count'],
        behavior_complete=False, formal_pool_certified=False, cn_calibration_complete=False,
        output=str(args.output)),ensure_ascii=False))
    return int(bool(result['unregistered_root_ids'] or result['printed_mismatches'] or
                    result['unresolved_text_surfaces']))


if __name__=='__main__':raise SystemExit(main())
