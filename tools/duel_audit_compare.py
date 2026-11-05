"""Compare two immutable audit batches without inventing missing observations."""
from itertools import zip_longest
from pathlib import Path
import argparse
import gzip
import json
from duel_audit import read, write, file_hash, stats


def difference(a, b, path='$'):
    if type(a) is not type(b): return path + ': type'
    if isinstance(a, dict):
        if a.keys() != b.keys(): return path + ': keys'
        for key in a:
            found = difference(a[key], b[key], path + '.' + str(key))
            if found: return found
    elif isinstance(a, list):
        if len(a) != len(b): return path + ': length'
        for i, (x, y) in enumerate(zip(a, b)):
            found = difference(x, y, path + '[' + str(i) + ']')
            if found: return found
    elif a != b: return path + ': value'
    return None


def snapshot(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def rows(path):
    with path.open(encoding='utf8') as stream:
        for line in stream:
            if line.strip():
                assert line.endswith('\n'), 'Incomplete trajectory line'
                yield json.loads(line)


def normalized_checks(value):
    """Host facts emit set-backed keyword evidence; no engine wire is changed."""
    result = json.loads(json.dumps(value))
    for check in result:
        evidence = check.get('evidence', {})
        keywords = evidence.get('keywords')
        if type(keywords) is list and all(type(k) is str for k in keywords):
            evidence['keywords'] = sorted(keywords)  # Retain multiplicity.
    return result


def compare(before, after, output):
    before, after, output = map(lambda p: Path(p).resolve(), (before, after, output))
    output.mkdir(parents=True, exist_ok=False)
    result = {'success': False, 'before': str(before), 'after': str(after),
              'steps': 0, 'snapshots': 0, 'full_replies': 0, 'differences': [],
              'not_recorded_in_baseline': ['complete initial legal query DTO at every step',
                                           'independent both-player outputs at every step'],
              'comparer_sha256': file_hash(__file__), 'normalized_keyword_order_receipts': [],
              'normalization_scope': 'Only host checks[*].evidence.keywords sorted as multiset; complete API/snapshot/RNG arrays remain exact.'}
    timing = {side: {key: [] for key in ('query_ms', 'submit_ms')} for side in ('before', 'after')}
    errors = []
    def equal(a, b, label):
        found = difference(a, b)
        if found: errors.append({'where': label, 'difference': found})
        return found is None
    try:
        identities = [read(p / 'identity.json') for p in (before, after)]
        manifests = [read(p / 'source-manifest.json') for p in (before, after)]
        for k in ('core', 'schema', 'target'): equal(identities[0][k], identities[1][k], 'identity/' + k)
        for field in ('decks', 'pairs', 'checks'):
            equal(read(before / 'plan.json')[field], read(after / 'plan.json')[field], 'plan/' + field)
        for field in ('seed', 'seeds', 'max_steps', 'max_turns', 'cpu_mask'):
            equal(read(before / 'config.json')[field], read(after / 'config.json')[field], 'config/' + field)
        equal(read(before / 'run-status.json')['games'], read(after / 'run-status.json')['games'], 'game_outcomes')
        for p in (before, after):
            assert read(p / 'run-status.json')['status'] == 'finished'
        immutable = ('data/', 'hs_sim/cards/', 'web_ui/')
        for key in set(manifests[0]['files']) | set(manifests[1]['files']):
            if key.startswith(immutable) or key == 'tools/duel_audit_runtime.py':
                equal(manifests[0]['files'].get(key), manifests[1]['files'].get(key), 'immutable/' + key)
        game_folders = sorted(p.name for p in (before / 'private').iterdir() if p.is_dir())
        equal(game_folders, sorted(p.name for p in (after / 'private').iterdir() if p.is_dir()), 'game_folders')
        for folder in game_folders:
            left, right = before / 'private' / folder, after / 'private' / folder
            equal(snapshot(left / 'initial.json.gz'), snapshot(right / 'initial.json.gz'), folder + '/initial')
            result['snapshots'] += 1
            for old, new in zip_longest(rows(left / 'steps.jsonl'), rows(right / 'steps.jsonl')):
                if old is None or new is None:
                    errors.append({'where': folder, 'difference': 'step count'}); continue
                label = old['id']
                for field in ('id', 'actor', 'turn', 'action', 'command', 'accepted', 'error',
                              'card_id', 'card_name', 'policy_rng_before', 'policy_rng_after',
                              'events', 'failure'):
                    equal(old.get(field), new.get(field), label + '/' + field)
                old_checks, new_checks = old.get('checks', []), new.get('checks', [])
                if old_checks != new_checks and normalized_checks(old_checks) == normalized_checks(new_checks):
                    result['normalized_keyword_order_receipts'].append({'id': label, 'before': old_checks, 'after': new_checks,
                                                                        'same_types_members_and_multiplicity': True})
                equal(normalized_checks(old_checks), normalized_checks(new_checks), label + '/checks')
                assert 'reply' in old and 'reply' in new, 'Full reply was not recorded'
                equal(old['reply'], new['reply'], label + '/complete_reply'); result['full_replies'] += 1
                equal(snapshot(old['after_snapshot']['path']), snapshot(new['after_snapshot']['path']), label + '/complete_snapshot')
                result['snapshots'] += 1; result['steps'] += 1
                if old['accepted'] and new['accepted']:
                    for side, row in (('before', old), ('after', new)):
                        for key in timing[side]: timing[side][key].append(row['timings'][key])
                with (output / 'steps.jsonl').open('a', encoding='utf8') as stream:
                    stream.write(json.dumps({'id': label, 'before': old['timings'], 'after': new['timings'],
                                             'semantic_difference_count_so_far': len(errors)}, ensure_ascii=False) + '\n')
            write(output / 'progress.json', {**result, 'differences': errors[:20]})
        for identity, manifest in zip(identities, manifests):
            assert all(file_hash(Path(identity['source']) / p) == sha for p, sha in manifest['files'].items()), 'Frozen source changed'
        result.update(success=not errors, difference_count=len(errors), differences=errors[:30],
                      frozen_sources_unchanged=True, identities=identities,
                      timing={side: {key: stats(values) for key, values in data.items()} for side, data in timing.items()},
                      totals={side: {key: sum(values) for key, values in data.items()} for side, data in timing.items()},
                      above_500_ms={side: sum(v > 500 for v in data['submit_ms']) for side, data in timing.items()})
    except Exception:
        import traceback
        result['exception'] = traceback.format_exc(); result['differences'] = errors[:30]
    write(output / 'result.json', result)
    print(json.dumps({k: result[k] for k in ('success', 'steps', 'snapshots', 'full_replies')}, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True); parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if compare(args.before, args.after, args.output)['success'] else 2)
