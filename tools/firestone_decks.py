"""Import an already cached Firestone metadata export. No network requests.

Deckstring v1 wire layout: HearthSim/python-hearthstone, deckstrings.py.
Keep DBF identities, quantities and sideboards; reject unknown extensions.
Native legality is tested against the local pinned pool, not the source patch.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
import argparse
import base64
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))


def decode_deckstring(code):
    raw = base64.b64decode(code, validate=True)
    pos = 0

    def integer():
        nonlocal pos
        value = 0
        for shift in range(0, 35, 7):
            if pos >= len(raw):
                raise ValueError('Truncated deckstring')
            byte = raw[pos]
            pos += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('Deckstring integer too large')

    if not raw or raw[0] != 0:
        raise ValueError('Invalid deckstring header')
    pos = 1
    if integer() != 1:
        raise ValueError('Unsupported deckstring version')
    fmt = integer()
    heroes = [integer() for _ in range(integer())]
    if len(heroes) != 1:
        raise ValueError('Exactly one hero required')

    def entries(sideboard=False):
        result = []
        for copies in (1, 2, None):
            size = integer()
            if size > 1000:
                raise ValueError('Deckstring section too large')
            for _ in range(size):
                dbf = integer()
                count = integer() if copies is None else copies
                owner = integer() if sideboard else None
                if dbf < 1 or count < 1 or count > 100:
                    raise ValueError('Invalid card identity or count')
                result.append((dbf, count, owner) if sideboard else (dbf, count))
        identities = [(r[0], r[2]) if sideboard else r[0] for r in result]
        if len(identities) != len(set(identities)):
            raise ValueError('Repeated identity across deckstring sections')
        return result

    cards = entries()
    sideboards = []
    if pos < len(raw):
        flag = integer()
        if flag not in (0, 1):
            raise ValueError('Unknown sideboard flag')
        if flag:
            sideboards = entries(True)
    if pos != len(raw):
        raise ValueError('Unrecognized deckstring extension; original preserved')
    return dict(format=fmt, heroes=heroes, cards=cards, sideboards=sideboards)


def import_metadata(metadata, output):
    from duel_audit import file_hash, write
    from duel_audit_runtime import catalog, spec, profiles, CORE_EFFECTS_VERSION
    from hs_sim.engine.construction import validate_deck
    from hs_sim.engine.tourists import requires_runes

    output.mkdir(parents=True, exist_ok=False)
    document = json.loads(metadata.read_text('utf8'))
    games = document['games']
    c = catalog(output, 'import')
    raw_path = ROOT / 'data/extracted/cards.json'
    rows = json.loads(raw_path.read_text('utf8'))
    by_dbf = {r['dbf_id']: r for r in rows}
    if len(by_dbf) != len(rows):
        raise ValueError('Ambiguous local DBF identities')
    grouped = defaultdict(list)
    for game in games:
        grouped[game['deckCode']].append(game)
    result = []
    class_names = {'demonhunter': 'demon_hunter', 'deathknight': 'death_knight'}
    for code, sources in grouped.items():
        row = {'id': 'fs-' + hashlib.sha256(json.dumps(code).encode()).hexdigest()[:12],
               'code': code, 'sample_count': len(sources),
               'sources': [{k: g[k] for k in ('gameId', 'date', 'playerClass', 'opponentClass', 'buildNumber', 'region')} for g in sources]}
        if not isinstance(code, str) or not code.strip():
            row['status'] = 'source_missing_deck_code'
            result.append(row)
            continue
        try:
            decoded = decode_deckstring(code)
            row['decoded'] = decoded
            dbfs = set(decoded['heroes']) | {r[0] for r in decoded['cards']}
            dbfs |= {x for r in decoded['sideboards'] for x in (r[0], r[2])}
            missing = sorted(dbfs - by_dbf.keys())
            if missing:
                row.update(status='unknown_dbf', missing_dbf_ids=missing)
                result.append(row)
                continue
            classes = {class_names.get(g['playerClass'], g['playerClass']) for g in sources}
            if len(classes) != 1 or decoded['format'] != 2:
                raise ValueError('Source class disagreement or non-standard deck code')
            klass = classes.pop()
            hero = by_dbf[decoded['heroes'][0]]
            power = by_dbf.get(hero['tags'].get('HERO_POWER'))
            if power is None:
                raise ValueError('Starting hero power absent from local DBF catalog')
            bands = defaultdict(list)
            for dbf, count, owner in decoded['sideboards']:
                bands[by_dbf[owner]['id']].extend([by_dbf[dbf]['id']] * count)
            deck = {'label': 'Firestone · ' + klass + ' · ' + row['id'][3:9], 'card_class': klass,
                    'hero_card_id': hero['id'], 'hero_power_card_id': power['id'],
                    'cards': [by_dbf[dbf]['id'] for dbf, count in decoded['cards'] for _ in range(count)],
                    'runes': None, 'sideboards': [{'source_card_id': owner, 'cards': cards} for owner, cards in bands.items()]}
            row['deck'] = deck
            row['cards'] = [{k: by_dbf[dbf].get(k) for k in ('id', 'dbf_id', 'name', 'name_en')} | {'count': count} for dbf, count in decoded['cards']]
            all_ids = set(deck['cards']) | {hero['id'], power['id']} | set(bands)
            all_ids |= {cid for cards in bands.values() for cid in cards}
            row['missing_definitions'] = sorted(all_ids - c.registry.cards.keys())
            # Deckstrings do not encode rune allocation. Only a uniquely forced
            # allocation is eligible; do not invent spare runes for actual data.
            native = spec(deck)
            if requires_runes(native.card_class, native.cards, c.registry, c.fmt.policy):
                candidates = []
                for blood in range(4):
                    for frost in range(4 - blood):
                        runes = dict(blood=blood, frost=frost, unholy=3-blood-frost)
                        trial = {**deck, 'runes': runes}
                        report = validate_deck(spec(trial), c.registry, c.fmt.policy)
                        if not any(i.code in ('rune_loadout', 'rune_requirements', 'unknown_runes') for i in report.issues):
                            candidates.append(runes)
                row['possible_rune_allocations'] = candidates
                if len(candidates) == 1:
                    deck['runes'] = candidates[0]
                    row['runes_origin'] = 'Uniquely required by imported card requirements; not encoded in source.'
            report = validate_deck(spec(deck), c.registry, c.fmt.policy)
            row['native_issues'] = [asdict(i) for i in report.issues]
            row['status'] = 'native_valid' if not report.issues else 'native_rejected'
            if len(row.get('possible_rune_allocations', [])) > 1:
                row['status'] = 'rune_allocation_not_in_source'
        except Exception as exc:
            row.update(status='import_error', error=f'{type(exc).__name__}: {exc}')
        result.append(row)

    summary = dict(source=str(metadata.resolve()), source_sha256=file_hash(metadata),
                   metadata_games=len(games), unique_deck_codes=sum(isinstance(code,str) and bool(code.strip()) for code in grouped),
                   games_without_deck_code=sum(len(v) for code,v in grouped.items() if not isinstance(code,str) or not code.strip()),
                   classes=dict(Counter(g['playerClass'] for g in games)),
                   source_builds=dict(Counter(str(g['buildNumber']) for g in games)),
                   core=CORE_EFFECTS_VERSION, target=c.fmt.target_id,
                   local_dbf_catalog_sha256=file_hash(raw_path),
                   statuses=dict(Counter(r['status'] for r in result)),
                   missing_definitions=dict(Counter(cid for r in result for cid in r.get('missing_definitions', []))),
                   native_issue_codes=dict(Counter(i['code'] for r in result for i in r.get('native_issues', []))),
                   limits=['Source build is preserved, not certified equivalent to the local CN target.',
                           'Only recording-player decks are supplied by metadata; original opposing deck and RNG are unknown.',
                           'Native legality and executable definitions do not certify complete effect correctness.'])
    write(output / 'compatibility.json', {'summary': summary, 'decks': result})
    # Six distinct classes with the most represented original, valid deck each.
    # Two-bot tests are new matches; never present them as original XML replay.
    chosen = []
    for klass in ('shaman', 'priest', 'druid', 'warlock', 'mage', 'warrior'):
        eligible = [r for r in result if r['status'] == 'native_valid' and r['deck']['card_class'] == klass]
        if eligible:
            chosen.append(max(eligible, key=lambda r: (r['sample_count'], r['id'])))
    if len(chosen) % 2:
        chosen.pop()
    checks = {}
    for row in chosen:
        for cid in set(row['deck']['cards']):
            card = c.registry.card(cid)
            from web_ui.server import plain_card_text
            checks[cid] = profiles({'kind': card.kind.value, 'text': plain_card_text(c.records.get(cid, ({}, ''))[0].get('text', ''))})
    write(output / 'selected-decks.json', {'decks': {r['id']: r['deck'] for r in chosen},
           'pairs': [[chosen[i]['id'], chosen[i+1]['id']] for i in range(0, len(chosen), 2)],
           'allow_shared_cards': True, 'checks': checks,
           'provenance': {'metadata_sha256': summary['source_sha256'],
                          'codes': {r['id']: r['code'] for r in chosen},
                          'scope': 'Original recording-player decks paired into new games; no source match reconstruction.'}})
    write(output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def verify_batch(batch, compatibility, output):
    """Roundtrip original imports and full initial/final states using frozen code.

    This deliberately checks endpoints and native replay, not every saved
    intermediate snapshot. It is not an original Firestone action translator.
    """
    from duel_audit import read, write, file_hash, set_affinity
    set_affinity(16)
    output.mkdir(parents=True, exist_ok=False)
    batch = batch.resolve()
    identity = read(batch / 'identity.json')
    source = Path(identity['source'])
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / 'tools'))
    import duel_audit_runtime as runtime
    from duel_audit_compare import snapshot
    from hs_sim.engine.replay import load_replay
    assert runtime.ROOT == source
    c = runtime.catalog(output, 'verify', batch / 'plans/pair-1.json')
    manifest = read(batch / 'source-manifest.json')['files']
    imported = read(compatibility)
    assert file_hash(source / 'data/extracted/cards.json') == imported['summary']['local_dbf_catalog_sha256']
    dbf = {r['dbf_id']: r['id'] for r in read(source / 'data/extracted/cards.json')}
    original = {r['id']: r for r in imported['decks']}
    plan = read(batch / 'plan.json')
    result = {'success': False, 'batch': str(batch), 'identity': identity,
              'decks': [], 'games': [], 'scope': 'All selected original deck imports; all initial/final snapshots and saved native replays. No intermediate-boundary restore or original XML replay.'}
    for key, deck in plan['decks'].items():
        item = original[key]
        decoded = decode_deckstring(item['code'])
        assert deck['cards'] == [dbf[cid] for cid, count in decoded['cards'] for _ in range(count)]
        for name, value in item['deck'].items():
            assert deck[name] == value, f'Imported deck field changed: {key}/{name}'
        result['decks'].append({'id': key, 'main_deck_entries': len(deck['cards']),
                                'original_code_dbf_counts_and_sideboards_preserved': True})
    for entry in read(batch / 'run-status.json')['games']:
        assert entry['status'] == 'completed'
        folder = batch / 'private' / entry['id']
        commands = [json.loads(line) for line in (folder / 'steps.jsonl').read_text('utf8').splitlines() if line]
        assert all(row['accepted'] for row in commands)
        initial = snapshot(folder / 'initial.json.gz')
        final = snapshot(commands[-1]['after_snapshot']['path'])
        for expected in (initial, final):
            assert runtime.Game.from_snapshot(expected, c.registry, mode='release').snapshot() == expected
        game = load_replay(folder / 'final-replay.json', c.registry, mode='release')
        assert game.snapshot() == final
        row = {'game': entry['id'], 'accepted_actions': len(commands),
               'full_initial_and_final_restore_equal_including_rng': True,
               'native_saved_replay_full_final_equal_including_rng': True}
        result['games'].append(row)
        write(output / 'progress.json', result)
        print(json.dumps(row), flush=True)
    assert all(file_hash(source / name) == sha for name, sha in manifest.items())
    modules = {name: module.__file__ for name, module in sys.modules.items()
               if name.startswith(('hs_sim', 'web_ui')) and getattr(module, '__file__', None)}
    assert all(Path(path).resolve().is_relative_to(source) for path in modules.values())
    result.update(success=True, frozen_source_guard=True, engine_modules_from_frozen_source=True,
                  checker_sha256=file_hash(__file__),
                  compatibility_sha256=file_hash(compatibility))
    write(output / 'result.json', result)
    print(json.dumps({'success': True, 'decks': len(result['decks']), 'games': len(result['games'])}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--metadata', type=Path)
    group.add_argument('--verify-batch', type=Path)
    parser.add_argument('--compatibility', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.verify_batch:
        if not args.compatibility:parser.error('--verify-batch requires --compatibility')
        verify_batch(args.verify_batch, args.compatibility, args.output)
    else:
        import_metadata(args.metadata, args.output)
