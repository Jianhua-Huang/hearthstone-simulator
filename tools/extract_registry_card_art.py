"""Extract exact registered-card portraits from the installed client's asset manifest.

Only serialized asset data is read. Bundles are processed once per phase, with
one live Unity environment at a time; no client code is run or decompiled.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import re
import sys
import warnings

import UnityPy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hs_sim.engine.representative import build_registry

PRIORITY = {'CORE_REV_990', 'SC_403'}


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path, value):
    staging = path.with_name(path.name + '.extracting')
    staging.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    staging.replace(path)


def extract(client):
    warnings.simplefilter('ignore')
    UnityPy.config.FALLBACK_UNITY_VERSION = '6000.3.11f1'
    source = client / 'Data' / 'Win'
    destination = ROOT / 'web_ui' / 'static' / 'assets'
    destination.mkdir(parents=True, exist_ok=True)
    registry = build_registry()
    requested = sorted(registry.cards)
    mapping_path = destination / 'cards.json'
    original_mapping = json.loads(mapping_path.read_text(encoding='utf8')) if mapping_path.exists() else {}
    mapping = dict(original_mapping)
    manifest_path = source / 'asset_manifest.unity3d'
    manifest = UnityPy.load(str(manifest_path))
    cards_map = None
    catalog = None
    for obj in manifest.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        data = obj.read_typetree()
        if data.get('m_Name') == 'cards_map':
            cards_map = dict(zip(data['map']['keys'], data['map']['values']))
        elif data.get('m_Name') == 'base_assets_catalog':
            catalog = data
    if cards_map is None or catalog is None:
        raise ValueError('The client manifest has no card map or base asset catalog')
    by_guid = {row['guid']: catalog['m_bundleNames'][row['bundleId']] for row in catalog['m_assets']}
    del manifest, catalog, obj
    gc.collect()
    sources = {}
    missing = []
    definitions = defaultdict(list)
    portraits = defaultdict(list)
    receipts = []
    bundles_read = []

    def source_hash(bundle):
        if bundle not in sources:
            sources[bundle] = digest(source / bundle)
        return sources[bundle]

    def absent(cid, reason, **extra):
        missing.append({'card_id': cid, 'name': registry.card(cid).name, 'reason': reason, **extra})

    for cid in requested:
        entry = cards_map.get(cid)
        if not entry:
            absent(cid, 'no_exact_card_id_in_client_manifest')
            continue
        asset, guid = entry.rsplit(':', 1)
        bundle = by_guid.get(guid)
        if bundle is None or not (source / bundle).is_file():
            absent(cid, 'definition_bundle_unavailable', asset=entry, bundle=bundle)
            continue
        definitions[bundle].append((cid, Path(asset).stem, entry))

    def priority(item):
        return (not any(row[0] in PRIORITY for row in item[1]), item[0])

    for bundle, rows in sorted(definitions.items(), key=priority):
        env = UnityPy.load(str(source / bundle))
        bundles_read.append(bundle)
        names = {obj.path_id: obj.read().m_Name for obj in env.objects if obj.type.name == 'GameObject'}
        wanted = {name for _, name, _ in rows}
        references = {}
        for obj in env.objects:
            if obj.type.name != 'MonoBehaviour':
                continue
            data = obj.read_typetree()
            name = names.get(data.get('m_GameObject', {}).get('m_PathID'))
            if name in wanted and data.get('m_PortraitTexturePath'):
                references[name] = data['m_PortraitTexturePath']
        for cid, name, entry in rows:
            reference = references.get(name)
            if not reference:
                absent(cid, 'exact_card_definition_has_no_portrait', definition=entry, bundle=bundle)
                continue
            asset, guid = reference.rsplit(':', 1)
            texture_bundle = by_guid.get(guid)
            if texture_bundle is None or not (source / texture_bundle).is_file():
                absent(cid, 'portrait_bundle_unavailable', portrait=reference, bundle=texture_bundle)
                continue
            portraits[texture_bundle].append((cid, Path(asset).stem, {
                'definition': entry, 'definition_bundle': bundle,
                'definition_sha256': source_hash(bundle), 'portrait': reference,
            }))
        del env, names, references, obj
        gc.collect()
    print(json.dumps({'phase': 'resolved_portraits', 'requested': len(requested),
                      'definition_bundles': len(definitions), 'texture_bundles': len(portraits),
                      'missing': missing}, ensure_ascii=False), flush=True)

    for bundle, rows in sorted(portraits.items(), key=priority):
        env = UnityPy.load(str(source / bundle))
        bundles_read.append(bundle)
        wanted = defaultdict(list)
        for cid, name, provenance in rows:
            wanted[name].append((cid, provenance))
        found = set()
        obj = texture = None
        for obj in env.objects:
            if obj.type.name != 'Texture2D':
                continue
            texture = obj.read()
            if texture.m_Name not in wanted:
                continue
            image = None
            for cid, provenance in wanted[texture.m_Name]:
                filename = mapping.get(cid, cid + '.webp')
                if not re.fullmatch(r'[A-Za-z0-9_]+\.webp', filename):
                    absent(cid, 'filename_not_static_asset_safe', file=filename)
                    continue
                output = destination / filename
                retained = cid in original_mapping and output.is_file()
                if image is None:
                    image = texture.image
                    original_size = list(image.size)
                    image.thumbnail((640, 640))
                if not retained:
                    image.save(output, 'WEBP', quality=88, method=6)
                mapping[cid] = filename
                found.add(cid)
                receipts.append({'card_id': cid, 'name': registry.card(cid).name,
                    'file': filename, 'texture': texture.m_Name, 'texture_path_id': obj.path_id,
                    'bundle': bundle, 'source_sha256': source_hash(bundle),
                    'output_sha256': digest(output), 'original_size': original_size,
                    'export_size': list(image.size), 'retained_existing_output': retained,
                    **provenance})
            if image is not None:
                image.close()
        for cid, name, provenance in rows:
            if cid not in found and not any(row['card_id'] == cid for row in missing):
                absent(cid, 'exact_portrait_texture_not_found', texture=name, bundle=bundle)
        del env, obj, texture
        gc.collect()
        # A bounded checkpoint also makes the two requested portraits available first.
        write_json(mapping_path, dict(sorted(mapping.items())))
        if any(cid in PRIORITY for cid, _, _ in rows):
            print(json.dumps({'phase': 'priority_portraits_saved', 'cards': sorted(found & PRIORITY)}, ensure_ascii=False), flush=True)

    report = {
        'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'client': str(client), 'read_only_client': True,
        'purpose': 'Exact local card portraits for the experimental web UI; artwork is not rules support evidence.',
        'registry_version': registry.version, 'registry_fingerprint': registry.fingerprint(),
        'requested_card_ids': requested, 'requested_count': len(requested),
        'resolved_count': len(receipts), 'mapping_count': len(mapping),
        'previous_mapping_entries_preserved': all(mapping.get(k) == v for k, v in original_mapping.items()),
        'source_manifest_sha256': digest(manifest_path),
        'extraction': {'unity_fallback_version': '6000.3.11f1', 'max_dimension': 640,
                       'webp_quality': 88, 'existing_outputs_preserved': True,
                       'bundles_read': len(bundles_read), 'max_live_bundle_environments': 1},
        'assets': sorted(receipts, key=lambda item: item['card_id']),
        'missing': sorted(missing, key=lambda item: item['card_id']),
    }
    write_json(destination / 'registry-card-art-manifest.json', report)
    print(json.dumps({key: report[key] for key in ('requested_count', 'resolved_count', 'mapping_count', 'previous_mapping_entries_preserved', 'missing')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', type=Path, default=Path(r'D:\游戏\Hearthstone'))
    extract(parser.parse_args().client)
