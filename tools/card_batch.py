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
    numeric = task.get('numeric_normalizations', {})
    require(type(numeric) is dict and set(numeric) <= set(ids),
            'Printed zero declarations must name assigned source identities')
    for values in numeric.values():
        validate_numeric_normalizations(values)
        require(bool(values), 'Printed zero declarations must be explicit nonempty fields')
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
    # The client plural prefix is omitted by the primary API. Keep BOTH branch
    # texts (and every rule number); only its literal formatting prefix is gone.
    text = re.sub(r'\|4(?=\([^()\r\n]*,[^()\r\n]*\))', '', text)
    # Other macros and all actual rules/numbers remain strictly comparable.
    text = html.unescape(re.sub(r'<[^>]+>', '', text)).replace('[x]', '')
    return re.sub(r'\s+', '', text.translate(str.maketrans('', '', '$#&_')))


def validate_numeric_normalizations(values):
    require(type(values) is dict and set(values) <= {'cost', 'attack'} and
            all(type(v) is int and v == 0 for v in values.values()),
            'Only explicit printed cost/attack zero declarations are supported')


def repeated_mana_forms(row, states, locale):
    """Three complete, equal rule bodies with only left/ready UI suffixes.

    The gallery concatenates all three original forms and omits the dynamic
    value. Keep every body; this never selects or drops an alternate effect.
    """
    threshold = row['tags'].get('TAG_SCRIPT_DATA_NUM_1')
    if (len(states) != 3 or row.get('type') != 'MINION' or row['tags'].get('BATTLECRY') != 1 or
            type(threshold) is not int or threshold <= 0):
        return False
    forms = [re.fullmatch(r'(.+?)\s*<i>([^<>]*)</i>\s*', s, flags=re.S) for s in states[:2]]
    if not all(forms): return False
    labels = ('（还剩{0}点！）', '（已经就绪！）') if locale == 'zh_CN' else ('({0}left!)', '(Ready!)')
    body = display(states[2])
    held = f'消耗过{threshold}点法力值' if locale == 'zh_CN' else f'spent{threshold}Mana'
    return (held in body and '{0}' not in body and
            tuple(display(form[2]) for form in forms) == labels and
            all(display(form[1]) == body for form in forms))


def check_face(row, face, locale, display_normalizations=None, *, numeric_normalizations=None):
    chinese = locale == 'zh_CN'
    require(locale in ('zh_CN', 'en_US'), 'Unreviewed face locale')
    if display_normalizations is not None:
        require(type(display_normalizations) is dict, 'Display declarations must be mappings')
        locales = {'zh_CN', 'en_US'}
        if set(display_normalizations) & locales:
            require(set(display_normalizations) <= locales and
                    all(type(v) is dict for v in display_normalizations.values()),
                    'Locale display declarations cannot mix marker and locale keys')
            display_normalizations = display_normalizations.get(locale)
    require(face['id'] == row['dbf_id'], 'Official response selected another DBF identity')
    require(face['name'] == row['name' if chinese else 'name_en'], 'Official card name drift')
    raw_text = row['text' if chinese else 'text_en']
    states = raw_text.split('@')
    progress_labels = ('（还剩{0}个！）', '（已经就绪！）') if chinese else ('({0}left!)', '(Ready!)')
    progress_display = (display_normalizations == {'@': '', '{0}': ''} and len(states) == 3 and
                        '{0}' not in states[0] and
                        all(re.fullmatch(r'\s*<i>.*</i>\s*', s, flags=re.S) for s in states[1:]) and
                        tuple(display(s) for s in states[1:]) == progress_labels)
    mana_forms_display = (display_normalizations == {'@': '', '{0}': ''} and
                          repeated_mana_forms(row, states, locale))
    # A primary face may leave the counter label intact but omit its live value.
    # Require a reviewed, single trailing label and preserve the entire rule body,
    # label text and denominator. Never treat a rule-body @ as a display counter.
    counter = re.fullmatch(r'([^@]*)@\s*<i>([^<>@]*@[^<>@]*)</i>\s*', raw_text, flags=re.S)
    counter_labels = (('（已使用@张）', '（已死亡@个）', '（减少@点）', '（@/4）') if chinese
                      else ('(@)', '(@/4)'))
    counter_display = (display_normalizations == {'@': ''} and counter is not None and
                       bool(display(counter[1])) and display(counter[2]) in counter_labels)
    recruit_bodies = {
        ('MEND_802', 'zh_CN'): '召唤两个{0}并具有圣盾的白银之手新兵。',
        ('MEND_802', 'en_US'): 'Summon two {0} Silver Hand Recruits with Divine Shield.',
        ('MEND_900', 'zh_CN'): '召唤并获取四个{0}的白银之手新兵。',
        ('MEND_900', 'en_US'): 'Summon and get four {0} Silver Hand Recruits.',
    }
    # The API omits only the live stat pair. Counts, shield and acquisition
    # remain in these exact original bodies; this is not a general macro rule.
    recruit_display = (display_normalizations == {'{0}': ''} and row.get('type') == 'SPELL' and
                       display(raw_text) == display(recruit_bodies.get((row['id'], locale), '')))
    leyline_pins = {
        'MEND_500': '132924d54e920a9e232451d78270dce82997ea4dcf4e04139caca9fbe6bb8b2d',
        'MEND_502': 'cdf80ae32e59da20337167be95e99eac9802b8b842e6b968de993a1ec33f0371',
        'MEND_504': '8828c777196157e5bfcdc08fbe76e55ece23b3d8acfb91c8b6e0db7d860894ae',
    }
    # Both full bodies remain. Only these pinned records may omit their live
    # scalar/count slots and the delimiter exactly as the primary API does.
    leyline_display = (display_normalizations == {'@': '', '{0}': '', '{1}': ''} and
                       row['id'] in leyline_pins and canonical(row) == leyline_pins[row['id']])
    smoldering_pins = {
        'FIR_914': 'af33d9fe2a7e86d958c7cbc07e15fe1be3aac4d1127d8502708f0c15a536b656',
        'FIR_916': 'f5f9dcfdcbab32723e5d9a568b3e91d5c6d5191ffdba699d4304be6b447a23b9',
    }
    # The gallery retains both full live/final-turn bodies but omits their
    # scalar and remaining-turn slots. These exact original rows alone qualify.
    smoldering_display = (display_normalizations == {'@': '', '{0}': '', '{1}': ''} and
                         row['id'] in smoldering_pins and canonical(row) == smoldering_pins[row['id']])
    # Bones preserves both complete rule bodies; the primary gallery omits
    # exactly its two native parameter slots, not an executable 0/0 default.
    bones_display = (display_normalizations == {'{0}': '', '{1}': ''} and row['id'] == 'TLC_829t' and
                     canonical(row) == '082069689d67c8d86b654a0fe74baabff66ebcf2830b01a7e2835714aa02a558')
    upgraded_recruit_display = (display_normalizations == {'{0}': ''} and row['id'] == 'HERO_04bp2' and
        canonical(row) == 'e591407799b3a77a6013ede32fccc293544df11bcdf4b8c3b1371edcb4ede54d')
    upgraded_hunter_display = (display_normalizations == {'@': ''} and row['id'] == 'HERO_05bp2' and
        canonical(row) == '405a2877e62fd20fd01e5ec1c38c7eb4a1bcb84b4a263a8750bdaf6e2a4f925a')
    # The gallery keeps both complete Lookout texts but omits the branch
    # delimiter and live card-name slot. No rule body or number is removed.
    lookout_display = (display_normalizations == {'@': '', '{5}': ''} and row['id'] == 'EDR_950' and
        canonical(row) == 'a9b334b37835480b161475c3b16412aa08f5ca52b3d66e42d2c9483ca2e8ce1e')
    for marker, replacement in (display_normalizations or {}).items():
        require(type(marker) is str and type(replacement) is str,
                'Display markers and replacements must be strings')
        require(marker in raw_text, 'Reviewed display marker is absent from the complete source')
        if marker == '@':
            printed = row['tags'].get('TAG_SCRIPT_DATA_NUM_1')
            require(type(replacement) is str and ((progress_display or counter_display or leyline_display or smoldering_display or upgraded_hunter_display or lookout_display) and replacement == '' or
                    type(printed) is int and
                    (replacement == '' or replacement.isdigit() and printed == int(replacement))),
                    'Dynamic display must be omitted or equal its explicit printed script value')
        elif marker == '{0}':
            require((progress_display or mana_forms_display or recruit_display or leyline_display or smoldering_display or bones_display or upgraded_recruit_display) and replacement == '',
                    'Only explicitly reviewed complete display forms may omit their live value')
        elif marker == '{1}':
            require((leyline_display or smoldering_display or bones_display) and replacement == '', 'Only complete pinned bodies may omit their dynamic value display')
        elif marker == '{5}':
            require(lookout_display and replacement == '', 'Only the pinned Lookout name display may be omitted')
        elif re.fullmatch(r'<b>巨型\+[1-9][0-9]*</b>。', marker):
            require(chinese and row.get('type') == 'MINION' and
                    type(row['tags'].get('COLOSSAL')) is int and row['tags']['COLOSSAL'] == 1 and
                    raw_text.startswith(marker) and raw_text.count(marker) == 1 and
                    replacement == marker[:-1],
                    'Only an explicit leading Chinese Colossal separator may be omitted')
        else:
            require(marker == '~GAMEPLAY_ASPROXY_' + row['id'] and replacement == '',
                    'Unreviewed display normalization')
        raw_text = raw_text.replace(marker, replacement)
    require(display(face['text']) == display(raw_text),
            'Official card rules drift: ' + row['id'])
    pairs = [('manaCost', 'cost'), ('attack', 'attack'), ('health', 'health')]
    numeric = {} if numeric_normalizations is None else numeric_normalizations
    validate_numeric_normalizations(numeric)
    for primary, raw in pairs:
        expected = row.get(raw)
        if raw in numeric:
            tag = 'COST' if raw == 'cost' else 'ATK'
            require(expected is None and tag not in row['tags'],
                    'Printed zero cannot replace an explicit source value/tag')
            require(row.get('type') in ('MINION', 'SPELL', 'WEAPON', 'LOCATION', 'HERO', 'HERO_POWER') and
                    (raw != 'attack' or row['type'] == 'MINION'),
                    'Printed attack zero requires an actual minion source')
            require(type(face.get(primary)) is int and face[primary] == 0,
                    'Printed zero requires its exact full primary zero face')
            expected = 0
        require(face.get(primary) == expected, 'Official numeric face drift: ' + primary)
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


def official(row, locale, cache, *, offline=False, display_normalizations=None, numeric_normalizations=None):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{row['dbf_id']}-{locale}.json"
    receipt = path.with_suffix('.receipt.json')
    url = f"https://playhearthstone.com/en-us/api/cards?card={row['dbf_id']}&locale={locale}"
    legacy_url = f"https://hearthstone.blizzard.com/en-us/api/cards?card={row['dbf_id']}&locale={locale}"
    if path.exists() or receipt.exists():
        require(path.exists() and receipt.exists(), 'Incomplete official cache pair; preserve it and use another cache')
        pin = read(receipt)
        require(pin['url'] in (url, legacy_url) and pin['sha256'] == sha(path), 'Official cache body/receipt mismatch')
        url = pin['url']
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
    check_face(row, faces[0], locale, display_normalizations, numeric_normalizations=numeric_normalizations)
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
    require(set(task.get('numeric_normalizations', {})) <= set(faces),
            'Every printed zero declaration requires full primary observations')
    cache = Path(cache) if cache else Path(root) / 'outputs/card-source-cache-cn37/official'
    with ThreadPoolExecutor(max_workers=4) as executor:
        observations = list(executor.map(lambda pair: official(rows[pair[0]], pair[1], cache, offline=offline,
                            display_normalizations=task.get('display_normalizations', {}).get(pair[0]),
                            numeric_normalizations=task.get('numeric_normalizations', {}).get(pair[0])),
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
