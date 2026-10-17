"""Prepare pinned card batches and verify scoped delivery/test evidence.

This tool prepares evidence, not card behavior or official support claims.
It never changes the engine, merges Git commits, or infers effects from text.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    from hs_sim.targets import canonical_digest
    return canonical_digest(value)


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never replace historical evidence, including after an interrupted run.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def relative_file(value):
    require(isinstance(value, str) and '\\' not in value, 'Use repository-relative POSIX paths')
    p = Path(value)
    require(not p.is_absolute() and p.parts and '..' not in p.parts and ':' not in value,
            'A batch path must remain inside the repository')
    return p


def load_manifest(path):
    task = read(path)
    require(task.get('schema') == 1, 'Unknown card-batch manifest schema')
    roots = task['roots']
    require(isinstance(roots, list) and roots and all(isinstance(x, str) and x for x in roots),
            'Explicit root identities are required')
    sections = [roots] + [task.get(key, []) for key in
                          ('dependencies', 'existing_dependencies', 'evidence_only')]
    ids = [cid for section in sections for cid in section]
    require(len(ids) == len(set(ids)), 'Root/dependency/evidence identities must be unique')
    grouped = [cid for group in task['effect_groups'] for cid in group['cards']]
    require(len(grouped) == len(set(grouped)) and set(grouped) == set(roots),
            'Effect groups must partition the assigned roots exactly once')
    allowed = task['allowed_files']
    require(len(allowed) == 3 and len(set(allowed)) == 3, 'Simple batches have three independent new files')
    for value, prefix, suffix in zip(sorted(allowed),
            ('data/cards/', 'hs_sim/cards/', 'tests/'), ('.json', '.py', '.py')):
        relative_file(value)
        require(value.startswith(prefix) and value.endswith(suffix), 'Unexpected simple-batch file scope')
    require(task.get('source_sha256') and len(task['source_sha256']) == 64, 'Pin the complete source SHA256')
    return task


def pinned_rows(task, root=ROOT):
    path = Path(root) / relative_file(task['source'])
    require(sha(path) == task['source_sha256'], 'Complete source catalog hash changed')
    values = read(path)
    require(isinstance(values, list), 'Expected complete source rows')
    rows = {row['id']: row for row in values}
    require(len(rows) == len(values), 'Duplicate source identity')
    for key in ('roots', 'dependencies', 'existing_dependencies', 'evidence_only'):
        for cid in task.get(key, []):
            require(cid in rows, 'Unknown assigned source identity: ' + cid)
    return rows


def display(text):
    # Only presentation syntax is normalized. Rules, numbers and macros remain.
    text = html.unescape(re.sub(r'<[^>]+>', '', text)).replace('[x]', '')
    return re.sub(r'\s+', '', text.translate(str.maketrans('', '', '$#&_')))


def check_face(row, face, locale, display_normalizations=None):
    chinese = locale == 'zh_CN'
    require(locale in ('zh_CN', 'en_US'), 'Unreviewed face locale')
    require(face['id'] == row['dbf_id'], 'Official response selected another DBF identity')
    require(face['name'] == row['name' if chinese else 'name_en'], 'Official card name drift')
    raw_text = row['text' if chinese else 'text_en']
    for marker, replacement in (display_normalizations or {}).items():
        require(marker in raw_text, 'Reviewed display marker is absent from the complete source')
        if marker == '@':
            printed = row['tags'].get('TAG_SCRIPT_DATA_NUM_1')
            require(type(printed) is int and type(replacement) is str and
                    (replacement == '' or replacement.isdigit() and printed == int(replacement)),
                    'Dynamic display must be omitted or equal its explicit printed script value')
        else:
            require(marker == '~GAMEPLAY_ASPROXY_' + row['id'] and replacement == '',
                    'Only explicit numeric displays and the original proxy suffix may be normalized')
        raw_text = raw_text.replace(marker, replacement)
    require(display(face['text']) == display(raw_text),
            'Official card rules drift: ' + row['id'])
    pairs = [('manaCost', 'cost'), ('attack', 'attack'), ('health', 'health')]
    for primary, raw in pairs:
        require(face.get(primary) == row.get(raw), 'Official numeric face drift: ' + primary)
    for primary, raw in [('cardTypeId', 'CARDTYPE'), ('cardSetId', 'CARD_SET'), ('rarityId', 'RARITY')]:
        if raw in row['tags']:
            require(face.get(primary) == row['tags'][raw], 'Official typed face drift: ' + primary)
    require(type(face['collectible']) in (int, bool) and face['collectible'] in (0, 1) and
            bool(face['collectible']) == row['collectible'], 'Official collectibility drift')
    if 'CLASS' in row['tags']:
        require(face['classId'] == row['tags']['CLASS'], 'Official class drift')
    if 'MULTIPLE_CLASSES' in row['tags']:
        mask = row['tags']['MULTIPLE_CLASSES']
        classes = {cid for cid in range(1, mask.bit_length() + 1) if mask & (1 << (cid - 1))}
        require(set(face.get('multiClassIds') or [face['classId']]) == classes,
                'Official multiple classes drift')
    if 'CARDRACE' in row['tags']:
        races = set(face.get('multiTypeIds', [])) | {face.get('minionTypeId')}
        require(row['tags']['CARDRACE'] in races, 'Official primary minion type drift')


def official(row, locale, cache, *, offline=False, display_normalizations=None):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{row['dbf_id']}-{locale}.json"
    receipt = path.with_suffix('.receipt.json')
    url = f"https://hearthstone.blizzard.com/en-us/api/cards?card={row['dbf_id']}&locale={locale}"
    if path.exists() or receipt.exists():
        require(path.exists() and receipt.exists(), 'Incomplete official cache pair; preserve it and use another cache')
        pin = read(receipt)
        require(pin['url'] == url and pin['sha256'] == sha(path), 'Official cache body/receipt mismatch')
    else:
        require(not offline, 'No pinned official cache: ' + path.name)
        request = Request(url, headers={'User-Agent': 'Hearthstone-simulator-source-audit/1.0'})
        with urlopen(request, timeout=25) as response:
            body = response.read()
        data = json.loads(body.decode('utf-8-sig'))
        require(isinstance(data.get('cards'), list), 'Official API did not return full cards')
        # Preserve full observations even when semantic comparison rejects them.
        # A receipt authenticates cached bytes, not correctness or applicability.
        faces = [f for f in data['cards'] if f.get('id') == row['dbf_id']]
        require(len(faces) == 1, 'Missing or ambiguous primary face')
        with path.open('xb') as stream:
            stream.write(body)
        save_new(receipt, dict(url=url, sha256=sha(path), bytes=len(body),
                              observed_at=datetime.now(timezone.utc).isoformat()))
    data = read(path)
    faces = [f for f in data['cards'] if f.get('id') == row['dbf_id']]
    require(len(faces) == 1, 'Missing or ambiguous cached primary face')
    check_face(row, faces[0], locale, display_normalizations)
    return dict(card_id=row['id'], locale=locale, response_file=str(path.resolve()),
                response_sha256=sha(path), url=url, face=faces[0], observation=read(receipt))


def prepare(manifest, output, *, root=ROOT, cache=None, offline=False):
    from hs_sim.cards.metadata import metadata_from_record
    from hs_sim.cards.health_cards import SCHOOLS
    task = load_manifest(manifest)
    rows = pinned_rows(task, root)
    if 'candidate_inventory' in task:
        inventory_path = Path(root) / relative_file(task['candidate_inventory'])
        require(sha(inventory_path) == task['candidate_inventory_sha256'], 'Candidate inventory pin changed')
        inventory = read(inventory_path)
        inventory_rows = {row['id']: row for row in inventory['records']}
        require(all(inventory_rows[cid]['standard_candidate'] and not
                    inventory_rows[cid]['registered_definition_present'] for cid in task['roots']),
                'Assigned roots must be missing Standard candidates')
    output = Path(output)
    require(not output.exists(), 'Use a fresh batch preparation directory')
    output.mkdir(parents=True)
    ids = [cid for key in ('roots', 'dependencies', 'existing_dependencies', 'evidence_only')
           for cid in task.get(key, [])]
    require(all('SPELL_SCHOOL' not in rows[cid]['tags'] or
                rows[cid]['tags']['SPELL_SCHOOL'] in SCHOOLS for cid in ids), 'Unknown printed spell school')
    cards = {cid: dict(record=rows[cid], record_sha256=canonical(rows[cid]),
                      metadata=asdict(metadata_from_record(rows[cid])),
                      spell_school=SCHOOLS.get(rows[cid]['tags'].get('SPELL_SCHOOL')))
             for cid in ids}
    faces = task.get('official_ids', task['roots'] + task.get('dependencies', []))
    require(len(faces) == len(set(faces)) and set(faces) <= set(ids), 'Official scope must use explicit unique source identities')
    cache = Path(cache) if cache else Path(root) / 'outputs/card-source-cache-cn37/official'
    with ThreadPoolExecutor(max_workers=4) as executor:
        observations = list(executor.map(lambda pair: official(rows[pair[0]], pair[1], cache, offline=offline,
                            display_normalizations=task.get('display_normalizations', {}).get(pair[0])),
                            [(cid, locale) for cid in faces for locale in ('zh_CN', 'en_US')]))
    result = dict(schema=1, batch=task['batch'], task=task, cards=cards,
                  official_observations=observations, source_verified=True,
                  official_faces_verified=len(observations), behavior_verified=False,
                  formal_pool_complete=False, cn_calibrated=False)
    require(sha(Path(root) / task['source']) == task['source_sha256'], 'Source catalog changed during preparation')
    save_new(output / 'source-review.json', result)
    save_new(output / 'manifest.json', task)
    return dict(batch=task['batch'], complete_rows=len(cards), full_primary_faces=len(observations),
                behavior_verified=False, output=str(output))


def source_guard(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha(p) for folder in ('hs_sim', 'tests', 'tools')
            for p in (root / folder).rglob('*.py')}


def capture(output, root=ROOT):
    from hs_sim.cards import build_registry
    from hs_sim.engine import Game, PlayerSetup, Scenario
    from hs_sim.engine.representative import build_registry as defaults
    r = build_registry()
    d = defaults()
    data = dict(schema=1, head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                source_guard=source_guard(root), definitions={cid: asdict(c) for cid, c in r.cards.items()},
                pool_cards={cid: asdict(c) for cid, c in r.pool_cards.items()},
                families=dict(r.generation_families), pools=[asdict(p) for p in r.pools.values()],
                default_fingerprint=d.fingerprint(), default_snapshot=Game.from_scenario(
                    Scenario((PlayerSetup('HERO_08'), PlayerSetup('HERO_08'))), d).snapshot())
    save_new(output, data)
    return dict(definitions=len(r.cards), protected_python=len(data['source_guard']), output=str(output))


def check_commit(root, commit, task):
    lines = subprocess.check_output(['git', 'diff-tree', '--root', '--no-commit-id', '--name-status', '-r', commit],
                                    cwd=root, text=True).splitlines()
    actual = [line.split('\t') for line in lines]
    require(all(len(row) == 2 and row[0] == 'A' for row in actual), 'Worker may only add independent new files')
    require(sorted(row[1] for row in actual) == sorted(task['allowed_files']), 'Worker commit escaped assigned scope')
    return dict(commit=commit, added_files=[row[1] for row in actual])


def check_preservation(before, after, allowed_files, added_ids):
    # Serialize enums/tuples exactly as the on-disk baseline does.
    after = json.loads(json.dumps(after, ensure_ascii=False))
    for cid, value in before['definitions'].items():
        require(after['definitions'].get(cid) == value, 'Existing complete definition changed: ' + cid)
    require(set(after['definitions']) - set(before['definitions']) == set(added_ids), 'Unexpected executable card inventory')
    for cid, value in before['pool_cards'].items():
        require(after['pool_cards'].get(cid) == value, 'Existing complete pool metadata changed: ' + cid)
    require(set(after['pool_cards']) - set(before['pool_cards']) <= set(added_ids), 'Unassigned pool metadata additions')
    for key in ('families', 'pools', 'default_fingerprint', 'default_snapshot'):
        require(before[key] == after[key], 'Existing registry/default identity changed: ' + key)
    permitted = {'hs_sim/cards/constructed.py'}
    changed = [p for p, pin in before['source_guard'].items() if after['source_guard'].get(p) != pin]
    require(set(changed) <= permitted, 'Unexpected previously existing Python change: ' + ', '.join(changed))
    new = set(after['source_guard']) - set(before['source_guard'])
    require(new <= {p for p in allowed_files if p.endswith('.py')}, 'Unassigned new Python source')
    return dict(old_definitions=len(before['definitions']), old_pool_cards=len(before['pool_cards']),
                unchanged_public_python=sum(p.startswith('hs_sim/engine/') for p in before['source_guard']),
                changed_previous_python=changed, added_definition_ids=sorted(added_ids))


def verify_preservation(before_path, task, implemented, output, root=ROOT):
    from hs_sim.cards import build_registry
    from hs_sim.engine import Game, PlayerSetup, Scenario
    from hs_sim.engine.representative import build_registry as defaults
    r, d = build_registry(), defaults()
    after = dict(source_guard=source_guard(root), definitions={cid: asdict(c) for cid, c in r.cards.items()},
                 pool_cards={cid: asdict(c) for cid, c in r.pool_cards.items()}, families=dict(r.generation_families),
                 pools=[asdict(p) for p in r.pools.values()], default_fingerprint=d.fingerprint(),
                 default_snapshot=Game.from_scenario(Scenario((PlayerSetup('HERO_08'), PlayerSetup('HERO_08'))), d).snapshot())
    result = check_preservation(read(before_path), after, task['allowed_files'], implemented)
    save_new(output, dict(result, source_guard=after['source_guard'], content_version=r.version))
    return result


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test.id()


def verify_run(root, run, names, current_guard, expected_ids):
    """Accept one complete green scoped run only, bound to actual current source."""
    root, run = Path(root).resolve(), Path(run).resolve()
    result, inputs = read(run / 'result.json'), read(run / 'inputs.json')
    require(not inputs['full_discovery'], 'Incremental card acceptance must be scoped')
    guard = {Path(k).as_posix(): v for k, v in inputs['source_sha256'].items()}
    require(guard == current_guard, 'Test evidence belongs to different source dependencies')
    ids = inputs['selected']
    require(ids and len(ids) == len(set(ids)) and set(ids) == set(expected_ids), 'Selected methods missing, repeated or unrequested')
    require(result['success'] and result['source_guard'] and result['exactly_once_coverage'], 'Run did not complete successfully')
    require(result['selected'] == result['executed'] == len(ids), 'Run omitted selected methods')
    require(not any(result[k] for k in ('failures', 'errors', 'skipped')), 'Run contains failed or skipped methods')
    seen = []
    modules = set()
    for group in read(run / 'groups.json'):
        module = group['module']
        require(module not in modules and group['passed'] and group['exit_code'] == 0, 'Duplicate or incomplete test group')
        modules.add(module)
        path = Path(group['output'])
        if not path.is_absolute():
            path = root / path
        require(path.resolve().is_relative_to(run), 'Test group escaped its run directory')
        g, pin = read(path / 'result.json'), read(path / 'inputs.json')
        subset = [x for x in ids if x.startswith(module + '.')]
        require({Path(k).as_posix(): v for k, v in pin['source_sha256'].items()} == current_guard,
                'Test group belongs to different source dependencies')
        require(set(pin['selected']) == set(subset) and len(pin['selected']) == len(subset), 'Group selected-method mismatch')
        require(g['success'] and g['source_guard'] and g['exactly_once_coverage'] and
                g['selected'] == g['executed'] == len(subset) and
                not any(g[k] for k in ('failures', 'errors', 'skipped')), 'Incomplete green test group')
        times = [json.loads(line) for line in (path / 'test-times.jsonl').read_text(encoding='utf-8').splitlines() if line]
        require(len(times) == len(subset) and {x['test'] for x in times} == set(subset) and
                all(x['status'] == 'passed' for x in times), 'Missing or failed per-method evidence')
        seen.extend(subset)
    require(len(seen) == len(set(seen)) == len(ids) and set(seen) == set(ids), 'Run group coverage is incomplete')
    return dict(run=str(run.relative_to(root)), methods=len(ids), seconds=result['seconds'], names=names,
                result_sha256=sha(run / 'result.json'), full_regression_runs=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cache', type=Path)
    p.add_argument('--offline', action='store_true')
    p = sub.add_parser('capture')
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('scope')
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--repository', type=Path, default=ROOT)
    p.add_argument('--commit', required=True)
    p = sub.add_parser('preserve')
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--implemented', nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('receipt')
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--selection', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        result = prepare(args.manifest, args.output, cache=args.cache, offline=args.offline)
    elif args.action == 'capture':
        result = capture(args.output)
    elif args.action == 'scope':
        result = check_commit(args.repository, args.commit, load_manifest(args.manifest))
    elif args.action == 'preserve':
        task = load_manifest(args.manifest)
        require(set(args.implemented) <= set(task['roots'] + task.get('dependencies', [])), 'Unassigned implemented identity')
        result = verify_preservation(args.before, task, args.implemented, args.output)
    else:
        sys.path.insert(0, str(ROOT / 'tests'))
        names = read(args.selection)
        ids = list(flatten(unittest.defaultTestLoader.loadTestsFromNames(names)))
        require(not any('_FailedTest' in cid for cid in ids) and len(ids) == len(set(ids)), 'Invalid or overlapping test selection')
        result = verify_run(ROOT, args.run, names, source_guard(ROOT), ids)
        save_new(args.output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
