"""Prepare pinned card batches and verify scoped delivery/test evidence.

This tool prepares evidence, not card behavior or official support claims.
It never changes the engine, merges Git commits, or infers effects from text.
"""
from __future__ import annotations

import argparse
import ast
import builtins
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
import symtable
import unittest
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def registration_prefix(builder, target, registration, *, after=False):
    """Capture one actual registration boundary without running later dependents.

    Incremental source tests need the same real builder immediately before and
    after their batch. Skipping registration but completing the modern builder
    is invalid once later batches legitimately depend on those original cards.
    """
    from unittest.mock import patch
    require(callable(builder) and callable(registration) and type(target) is str and
            bool(target) and type(after) is bool, 'Invalid registration boundary request')

    class PrefixReady(Exception):
        def __init__(self, registry):
            self.registry = registry

    def capture(registry):
        if after:
            registration(registry)
        raise PrefixReady(registry)

    with patch(target, capture):
        try:
            builder()
        except PrefixReady as found:
            return found.registry
    raise ValueError('Requested original registration boundary was not reached')


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


def python_name_candidates(paths, *, root=ROOT):
    """Read-only missing-global hints; never import or execute candidate files.

    This catches missing imports and misspelled module names before managed
    tests. It is a conservative diagnostic, not a proof of runtime correctness.
    """
    special = {'__name__', '__file__', '__package__', '__doc__', '__builtins__',
               '__loader__', '__spec__', '__cached__', '__annotations__'}
    result = []
    for value in paths:
        relative = relative_file(value)
        require(relative.suffix == '.py', 'Name preflight requires Python sources')
        table = symtable.symtable((Path(root)/relative).read_text(encoding='utf-8-sig'), value, 'exec')
        declared = {s.get_name() for s in table.get_symbols()
                    if s.is_assigned() or s.is_imported() or s.is_namespace()}
        known = declared | set(dir(builtins)) | special
        pending = [(table, table.get_name())]
        while pending:
            scope, name = pending.pop()
            for symbol in scope.get_symbols():
                if symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in known:
                    result.append(dict(path=value, scope=name, line=max(1, scope.get_lineno()),
                                       symbol=symbol.get_name()))
            pending.extend((child, name+'.'+child.get_name()) for child in scope.get_children())
    return sorted(result, key=lambda row: (row['path'], row['scope'], row['symbol']))


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
    if 'official_catalogs' in task:
        validate_catalog_sources(task['official_catalogs'])
    card_caches = task.get('official_card_caches', {})
    require(type(card_caches) is dict and set(card_caches) <= set(ids),
            'Explicit primary caches must name assigned source identities')
    require(not card_caches or 'official_catalogs' in task,
            'Explicit primary caches supplement an explicit catalog source')
    for value in card_caches.values():
        relative_file(value)
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
    # This exact client row has empty Chinese localization. The primary Chinese
    # face falls back to its complete English name/body; retain both originals.
    trial_english_fallback = (chinese and row.get('id') == 'CAP_405t1' and
        canonical(row) == 'aaf172d1f75aa377a2990f808114a28a4d807c2bca3288002f6a2afc1f6c3dcb' and
        row['name'] == row['text'] == '')
    require(face['name'] == row['name_en' if trial_english_fallback or not chinese else 'name'], 'Official card name drift')
    raw_text = row['text_en' if trial_english_fallback or not chinese else 'text']
    states = raw_text.split('@')
    # This exact source repeats one rule in initial/ready/plain UI forms.
    # The gallery shows the initial form with its explicit printed threshold.
    # Check all complete bodies; never discard a different alternate effect.
    yshaarj_display = (row.get('id') == 'BE_784' and
        canonical(row) == '18595e76a8234afb0f93bd153a6d4e61b5055532e889bd06e9d819da441867b9' and
        display_normalizations == {'{0}': '30'})
    if yshaarj_display:
        forms = [re.fullmatch(r'(.+?)\s*<i>([^<>]*)</i>\s*', s, flags=re.S) for s in states[:2]]
        labels = ('（还剩{0}点！）', '（已经就绪！）') if chinese else ('({0}left!)', '(Ready!)')
        def same_rule(text):
            value = display(text)
            return value if chinese else value.replace('Mana', 'mana')
        require(len(states) == 3 and all(forms) and row['tags'].get('TAG_SCRIPT_DATA_NUM_1') == 30 and
                tuple(display(form[2]) for form in forms) == labels and '{0}' not in states[2] and
                all(same_rule(form[1]) == same_rule(states[2]) for form in forms),
                'Yshaarj lost its complete original thirty-Mana progress forms')
        raw_text = states[0]
    # This complete pinned source repeats the same rule body in initial/ready/
    # plain display forms. The gallery shows only the initial printed count5.
    # Preserve the full original row; this is not a general progress shortcut.
    broodqueen_display = (row.get('id') == 'BE_565' and
        canonical(row) == '0a6c00e59f610d2663d7e5b59d0cbdd6d0ff877b062c2bc18a82cf83987aa6aa' and
        display_normalizations == {'{0}': '5'})
    if broodqueen_display:
        require(len(states) == 3 and row['tags'].get('TAG_SCRIPT_DATA_NUM_1') == 5,
                'Broodqueen lost her complete original progress forms')
        raw_text = states[0]
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
    # The complete Dreadlynx API body omits its two live reversed-stat slots.
    # Preserve the rule, Rush, opposite-stats explanation and printed numbers.
    dreadlynx_display = (display_normalizations == {'{0}': '', '{1}': ''} and row['id'] == 'BE_850t' and
        canonical(row) == '57a1e5f98f8362375f6979f2891fd0d484ffd8322a98bca457cb893ce4ad6190')
    # The actual Zombeast template has two runtime ingredient text slots. Both
    # complete primary faces omit them; no printed effect body is discarded.
    zombeast_display = (display_normalizations == {'{0}': '', '{1}': ''} and row['id'] == 'ICC_828t' and
                        canonical(row) == 'afa504c878895524959d208f1afb003bbfcc9aa2a71717362c1a61793c950bb7')
    upgraded_recruit_display = (display_normalizations == {'{0}': ''} and row['id'] == 'HERO_04bp2' and
        canonical(row) == 'e591407799b3a77a6013ede32fccc293544df11bcdf4b8c3b1371edcb4ede54d')
    upgraded_hunter_display = (display_normalizations == {'@': ''} and row['id'] == 'HERO_05bp2' and
        canonical(row) == '405a2877e62fd20fd01e5ec1c38c7eb4a1bcb84b4a263a8750bdaf6e2a4f925a')
    # The gallery keeps both complete Lookout texts but omits the branch
    # delimiter and live card-name slot. No rule body or number is removed.
    lookout_display = (display_normalizations == {'@': '', '{5}': ''} and row['id'] == 'EDR_950' and
        canonical(row) == 'a9b334b37835480b161475c3b16412aa08f5ca52b3d66e42d2c9483ca2e8ce1e')
    # Horrible Egg names its captured Dragon at runtime. Both complete gallery
    # faces omit only that name; the native Deathrattle body and all metadata
    # stay strict. This exact original row is not a general {0} exception.
    egg_name_display = (display_normalizations == {'{0}': ''} and row['id'] == 'EDR_454t' and
        canonical(row) == 'cd319168db51490cfc038bcdaba343e7178c57fe6b3b00745df0ef326fa536cb')
    # A spell carrier's actual spell name is native runtime material. Only
    # these complete pinned sources may omit that live name, never rule text.
    carved_spell_display = (display_normalizations == {'{0}': ''} and canonical(row) == {
        'MEND_046t': '270e5645ef9e6516bbe8b66af518eda5b2c8a4822ba05f27df830b46678c8b6a',
        'TIME_704t': 'b76ce848596c774d48234e85471174592985a622dd052ed49aaea172ff60daeb',
        'BE_055t': '5ea2e77de346612e33729c27b62b124e4fb1fe286a292ce5eeab26e6c0553317',
    }.get(row['id']))
    # The actual Rajh child receives its whole chosen passive text at runtime.
    # Its complete gallery faces are empty and explicitly show manaCost zero.
    # This exact template is not permission to omit any static rule sentence.
    assembled_power_display = (row.get('id') == 'BE_004p' and
        canonical(row) == '60682d8b56e484eec1cc77cfa313b8ddb61bddfa54576184387b8b9a1796f3f0' and
        row.get('type') == 'HERO_POWER' and row['tags'].get('HIDE_COST') == 1 and
        display(raw_text) == '{0}' and face.get('text') == '' and face.get('parentId') == 132353 and
        display_normalizations == {'{0}': ''})
    # Specimen Jar's gallery retains both complete empty/filled bodies; only
    # their delimiter and the runtime captive name are absent.
    jar_name_display = (display_normalizations == {'@': '', '{5}': ''} and row['id'] == 'TLC_841t' and
        canonical(row) == '9c9987a3461b47265c8d6d16c2a42727f1d00242c4cfb2add856f03534ec9ecd')
    informant_class_display = (display_normalizations == {'@': '', '{0}': ''} and row['id'] == 'CATA_614' and
        canonical(row) == 'd9e8ce7e0a805d07395cc94993f8d67f0e8cc4e5307efb628167e30bcf3e290b')
    # Both complete Magmaw bodies and its finite99counter label stay intact.
    # The primary gallery omits only the delimiter and live remaining scalar.
    colossal_reserve_display = (display_normalizations == {'@': '', '{0}': ''} and row['id'] == 'CATA_550' and
        canonical(row) == '440c61376f11ca2a2ed2a7fa598ea8e096f5cd20eefc374cf467c2767ac24fe1')
    potion_display = (row.get('id') == 'JAIL_504t3p' and row.get('dbf_id') == 131327 and
                     row.get('type') == 'SPELL' and row.get('cost') == 1 and
                     display(raw_text) == '{0}{1}' and face.get('text') == '' and
                     face.get('parentId') == 125989 and
                     display_normalizations == {'{0}': '', '{1}': ''})
    location_template_display = (canonical(row) == {
        'TLC_100t1': 'bcb87ea6206c4d7d5adaa32bef080418e274a5154984317e3ad731d9db66de3c',
        'TLC_100t2': 'fae77f3af6d08a68e15fbf59d322f1e53d96003d08d41249d420dac6f7fc748d',
        'TLC_100t3': 'd3f9182d2f8606798061a76439d5018118d55346692687f7f235ce7af3788cc6',
    }.get(row.get('id')) and row.get('type') == 'LOCATION' and
        display(raw_text) == '{0}{1}' and face.get('text') == '' and face.get('parentId') == 117762 and
        display_normalizations == {'{0}': '', '{1}': ''})
    trial_template_display = (canonical(row) == {
        'CAP_405tb1': '789ca3514fc23dd818d209b0f8cf0a23cf5e71f1cfc11265f8c2c1d84307231a',
        'CAP_405tb2': '41fe854200ef39b3d366b388b202681b8f35da5956a082790ceba1fa745951dd',
        'CAP_405tb3': '0ccd88a0e6893c709d8314ee826d2b39ffa4fb2de055bbab363511b6c92394e5',
    }.get(row.get('id')) and row.get('type') == 'SPELL' and
        face.get('parentId') == 127067 and display_normalizations ==
        ({'@': '', '{0}': '', '{1}': ''} if row.get('id') == 'CAP_405tb3' else {'{0}': '', '{1}': ''}))
    jade_coin_display = (row.get('id') == 'JAIL_504t' and
                        canonical(row) == 'cc68b154cb60375019f76676875ed9f66a95b66e67c44919cfd6730d8b6c3af9' and
                        display_normalizations == ({'@': '', '{0}': ''} if chinese else {'@': '', '{0}': '', '{1}': ''}))
    for marker, replacement in (display_normalizations or {}).items():
        require(type(marker) is str and type(replacement) is str,
                'Display markers and replacements must be strings')
        require(marker in raw_text, 'Reviewed display marker is absent from the complete source')
        if marker == '@':
            printed = row['tags'].get('TAG_SCRIPT_DATA_NUM_1')
            require(type(replacement) is str and ((jade_coin_display or progress_display or counter_display or leyline_display or smoldering_display or upgraded_hunter_display or lookout_display or jar_name_display or informant_class_display or colossal_reserve_display) and replacement == '' or
                    type(printed) is int and
                    (replacement == '' or replacement.isdigit() and printed == int(replacement))),
                    'Dynamic display must be omitted or equal its explicit printed script value')
        elif marker == '{0}':
            require(broodqueen_display and replacement == '5' or yshaarj_display and replacement == '30' or
                    (jade_coin_display or potion_display or location_template_display or trial_template_display or assembled_power_display or progress_display or mana_forms_display or recruit_display or leyline_display or smoldering_display or bones_display or dreadlynx_display or zombeast_display or upgraded_recruit_display or egg_name_display or carved_spell_display or informant_class_display or colossal_reserve_display) and replacement == '',
                    'Only explicitly reviewed complete display forms may omit their live value')
        elif marker == '{1}':
            require((jade_coin_display or potion_display or location_template_display or trial_template_display or leyline_display or smoldering_display or bones_display or dreadlynx_display or zombeast_display) and replacement == '', 'Only complete pinned bodies may omit their dynamic value display')
        elif marker == '{5}':
            require((lookout_display or jar_name_display) and replacement == '', 'Only a pinned complete name display may be omitted')
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
    allowed_urls = (url, legacy_url)
    if row.get('collectible') is False:
        allowed_urls += (url + '&collectible=0', legacy_url + '&collectible=0')
        url += '&collectible=0'
    if path.exists() or receipt.exists():
        require(path.exists() and receipt.exists(), 'Incomplete official cache pair; preserve it and use another cache')
        pin = read(receipt)
        require(pin['url'] in allowed_urls and pin['sha256'] == sha(path), 'Official cache body/receipt mismatch')
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
        # Retain a complete JSON response even if it has zero/multiple matching
        # faces. The common semantic check below still rejects that observation;
        # a byte receipt is never evidence that the required card was verified.
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


def validate_catalog_sources(sources):
    require(type(sources) is list and bool(sources), 'Explicit full official catalog sources are required')
    seen = set()
    for source in sources:
        require(type(source) is dict and set(source) == {'locale', 'response_file', 'receipt_file'},
                'Catalog sources require locale, full response and receipt paths')
        require(source['locale'] in ('zh_CN', 'en_US'), 'Unsupported catalog locale')
        for key in ('response_file', 'receipt_file'):
            require(relative_file(source[key]).suffix == '.json', 'Catalog source must be a saved JSON file')
        identity = source['locale'], source['response_file']
        require(identity not in seen, 'Repeated catalog source')
        seen.add(identity)


def catalog_index(sources, root=ROOT):
    """Read each whole pinned body once; never fetch or infer pool membership."""
    from hs_sim.targets import _load_json
    validate_catalog_sources(sources)
    root = Path(root).resolve(); result = {}
    for source in sources:
        paths = {key: (root / relative_file(source[key])).resolve()
                 for key in ('response_file', 'receipt_file')}
        require(all(path.is_relative_to(root) for path in paths.values()), 'Catalog source escaped its root')
        body = paths['response_file']; pin = _load_json(paths['receipt_file'])
        require(type(pin) is dict and type(pin.get('url')) is str, 'Catalog receipt lost its actual source URL')
        url = urlsplit(pin['url']); query = parse_qs(url.query)
        require(url.scheme == 'https' and url.hostname in ('hearthstone.blizzard.com', 'playhearthstone.com') and
                url.port in (None, 443) and url.username is None and url.password is None and not url.fragment and
                url.path.rstrip('/') == '/en-us/api/cards' and query.get('locale') == [source['locale']] and
                set(query) <= {'locale', 'set', 'page', 'pageSize'} and all(len(v) == 1 for v in query.values()),
                'Catalog receipt has an unsupported official URL or different locale')
        digest = sha(body)
        require(pin.get('sha256') == digest and type(pin.get('bytes')) is int and pin['bytes'] == body.stat().st_size,
                'Complete catalog body/receipt byte identity changed')
        data = _load_json(body)
        require(type(data) is dict and type(data.get('cards')) is list, 'Catalog lost its full cards response')
        for face in data['cards']:
            require(type(face) is dict and type(face.get('id')) is int and face['id'] > 0,
                    'Catalog has an unknown primary face identity')
            identity = source['locale'], face['id']
            require(identity not in result, 'Ambiguous primary face across catalog pages')
            result[identity] = dict(response_file=str(body), response_sha256=digest,
                                    url=pin['url'], face=face, observation=pin)
    return result


def catalog_official(row, locale, index, *, display_normalizations=None, numeric_normalizations=None):
    require((locale, row['dbf_id']) in index, 'Assigned primary face missing from its explicit catalog sources')
    observation = index[locale, row['dbf_id']]
    check_face(row, observation['face'], locale, display_normalizations,
               numeric_normalizations=numeric_normalizations)
    return dict(card_id=row['id'], locale=locale, **observation)


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
    if 'official_catalogs' in task:
        index = catalog_index(task['official_catalogs'], root)
        explicit = task.get('official_card_caches', {})
        require(set(explicit) <= set(faces), 'Explicit primary caches must be in the official face scope')
        require(all((locale, rows[cid]['dbf_id']) not in index
                    for cid in explicit for locale in ('zh_CN', 'en_US')),
                'Ambiguous primary face across catalog and explicit card cache')
        observations = []
        for cid in faces:
            for locale in ('zh_CN', 'en_US'):
                display = task.get('display_normalizations', {}).get(cid)
                numeric = task.get('numeric_normalizations', {}).get(cid)
                if cid in explicit:
                    folder = (Path(root) / relative_file(explicit[cid])).resolve()
                    require(folder.is_relative_to(Path(root).resolve()), 'Primary cache escaped its root')
                    body = folder / f"{rows[cid]['dbf_id']}-{locale}.json"
                    receipt = body.with_suffix('.receipt.json')
                    require(body.is_file() and receipt.is_file(), 'Incomplete explicit primary cache pair')
                    pin = read(receipt)
                    require(type(pin.get('bytes')) is int and pin['bytes'] == body.stat().st_size,
                            'Explicit primary cache byte identity changed')
                    observations.append(official(rows[cid], locale, folder, offline=True,
                        display_normalizations=display, numeric_normalizations=numeric))
                else:
                    observations.append(catalog_official(rows[cid], locale, index,
                        display_normalizations=display, numeric_normalizations=numeric))
    else:
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


def check_preservation(before, after, allowed_files, added_ids, *, reviewed_tooling_python=()):
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
    # Worker/CLI defaults remain the original three-file rule. The mainline may
    # name independently reviewed tooling changes without masking their hashes
    # or weakening the engine/default/card-content preservation checks.
    require(type(reviewed_tooling_python) is tuple and
            len(reviewed_tooling_python) == len(set(reviewed_tooling_python)) and
            all(type(p) is str and p.startswith(('tools/', 'tests/')) and p.endswith('.py') and
                p in before['source_guard'] for p in reviewed_tooling_python), 'Invalid reviewed tooling scope')
    permitted = {'hs_sim/cards/constructed.py', *reviewed_tooling_python}
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


def local_import_closure(root, module, current_guard, *, cache=None):
    """Conservative local static imports; unresolved dynamic imports forbid reuse."""
    root = Path(root).resolve(); keys = set(current_guard)
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', module), 'Invalid test module identity')
    entry = 'tests/' + module.replace('.', '/') + '.py'
    require(entry in keys, 'Selected test module is outside the current source guard')
    memo = {} if cache is None else cache
    identity = str(root), canonical(current_guard)
    def resolve(name):
        parts = name.split('.'); found = set()
        for prefix in ('', 'tests/'):
            paths = [prefix+'/'.join(parts)+'.py', prefix+'/'.join(parts)+'/__init__.py']
            paths += [prefix+'/'.join(parts[:i])+'/__init__.py' for i in range(1, len(parts))]
            found.update(p for p in paths if p in keys)
        return found
    seen = set(); pending = [entry]; dynamic = []
    while pending:
        path = pending.pop()
        if path in seen: continue
        seen.add(path); key = identity, path
        if key not in memo:
            require(sha(root/path) == current_guard[path], 'Current import source changed while proving reuse')
            package = path[:-3].split('/')[:-1]
            if package and package[0] == 'tests': package = package[1:]
            imports = set(); unknown = []
            for node in ast.walk(ast.parse((root/path).read_text(encoding='utf-8-sig'))):
                names = []
                if isinstance(node, ast.Import): names = [x.name for x in node.names]
                elif isinstance(node, ast.ImportFrom):
                    prefix = package[:len(package)-node.level+1] if node.level else []
                    base = '.'.join(prefix+([node.module] if node.module else []))
                    names = ([base] if base else []) + [(base+'.' if base else '')+x.name for x in node.names if x.name != '*']
                elif isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else None
                    if name in ('import_module', '__import__'):
                        if node.args and isinstance(node.args[0], ast.Constant) and type(node.args[0].value) is str and not node.args[0].value.startswith('.'):
                            names = [node.args[0].value]
                        else: unknown.append(dict(path=path, line=node.lineno))
                    elif name in ('exec', 'eval', 'exec_module', 'module_from_spec'):
                        unknown.append(dict(path=path, line=node.lineno))
                for name in names: imports.update(resolve(name))
            memo[key] = imports, unknown
        imports, unknown = memo[key]
        dynamic.extend(unknown); pending.extend(imports-seen)
    return dict(dependencies=sorted(seen), dynamic_import_sites=dynamic)


def verify_group_reuse(root, group, module, current_guard, expected_ids, *, import_cache=None):
    """Reuse a complete green child group only when its actual local inputs agree."""
    root, group = Path(root).resolve(), Path(group).resolve()
    require(group.is_relative_to(root), 'Test group escaped its workspace')
    result, inputs = read(group/'result.json'), read(group/'inputs.json')
    require(not inputs.get('full_discovery', False), 'Group reuse must be scoped')
    ids = inputs['selected']
    require(ids and len(ids) == len(set(ids)) and set(ids) == set(expected_ids) and
            all(x.startswith(module+'.') for x in ids), 'Group reuse selected methods are missing or repeated')
    require(result['success'] and result['source_guard'] and result['exactly_once_coverage'] and
            result['selected'] == result['executed'] == len(ids) and
            not any(result[k] for k in ('failures', 'errors', 'skipped')), 'Group is not complete green evidence')
    times = [json.loads(x) for x in (group/'test-times.jsonl').read_text(encoding='utf-8').splitlines() if x]
    require(len(times) == len(ids) and {x['test'] for x in times} == set(ids) and
            all(x['status'] == 'passed' for x in times), 'Group reuse lacks complete per-method evidence')
    closure = local_import_closure(root, module, current_guard, cache=import_cache)
    require(not closure['dynamic_import_sites'], 'Unresolved dynamic imports prevent group reuse')
    original = {Path(k).as_posix(): v for k, v in inputs['source_sha256'].items()}
    require(all(original.get(k) == current_guard.get(k) for k in closure['dependencies']),
            'Group dependencies changed; previous green cannot be inherited')
    return dict(module=module, output=group.relative_to(root).as_posix(), methods=ids,
        seconds=result['seconds'], local_import_closure=closure['dependencies'], dynamic_import_sites=[],
        complete_green_group=True, result_sha256=sha(group/'result.json'),
        inputs_sha256=sha(group/'inputs.json'), test_times_sha256=sha(group/'test-times.jsonl'))


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
