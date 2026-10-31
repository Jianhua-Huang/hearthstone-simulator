"""Compare unchanged engine semantics and a closed, fixed timing harness."""
from pathlib import Path
import argparse
import hashlib
import json
import statistics
import traceback


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def metric(before, after):
    return {'before_ms': before, 'after_ms': after,
            'change_percent': (after / before - 1) * 100,
            'speedup': before / after}


def compare(before_path, after_path, allowed, full):
    before, after = load(before_path), load(after_path)
    for role, report in (('before', before), ('after', after)):
        require(report['success'] and report['benchmark_checks_passed'] and
                report['frozen_source_unchanged'], role + ' benchmark did not complete cleanly')
    require(before['identity'] == after['identity'], 'Changed fixture, schema, registry or mechanics identity')
    require(before['python'] == after['python'] and before['platform'] == after['platform'],
            'Different Python/platform')
    require(before['harness_sha256'] == after['harness_sha256'], 'Changed parent timing harness')
    bm = load(before_path.parent / 'source-manifest.json')['frozen']
    am = load(after_path.parent / 'source-manifest.json')['frozen']
    for tool in ('tools/engine_performance_baseline.py', 'tools/engine_performance_standard.py'):
        require(bm[tool] == am[tool], 'Changed timed tool: ' + tool)
    immutable = {p for p in set(bm) | set(am) if p.startswith(('hs_sim/', 'data/'))}
    changes = sorted(p for p in immutable if bm.get(p) != am.get(p))
    require(all(p.startswith('hs_sim/engine/') for p in allowed), 'Allow only reviewed engine paths')
    require(set(changes) <= set(allowed), 'Changed unreviewed runtime/card/data input: ' + str(changes))
    result = {'full': full, 'changed_runtime_paths': changes, 'timed_tools_identical': True,
              'card_sources_and_data_identical': True, 'cases': {}}
    if full:
        require(set(before['cases']) == set(after['cases']), 'Missing complete benchmark cases')
    for name, row in after['cases'].items():
        old = before['cases'][name]
        for field in ('state_sha256', 'result_sha256'):
            require(old[field] == row[field], 'Semantic difference in ' + name + '/' + field)
        result['cases'][name] = metric(old['median_ms'], row['median_ms'])
    if full or after['history']:
        require([r['state_sha256'] for r in before['history']] ==
                [r['state_sha256'] for r in after['history']], 'Changed repeated-cast history')
        result['history_equal'] = True
    if full:
        bs, ns = before['standard_result'], after['standard_result']
        require(bs['success'] and ns['success'], 'Incomplete standard host workload')
        for key in ('identity', 'deck', 'initial_state_sha256', 'match_final'):
            require(bs[key] == ns[key], 'Changed standard workload/' + key)
        result['standard_cases'] = {}
        for cid, row in ns['cases'].items():
            old = bs['cases'][cid]
            require(old['after_state_sha256'] == row['after_state_sha256'], 'Changed pending cast/' + cid)
            require([s['completed_snapshot_sha256'] for s in old['samples']] ==
                    [s['completed_snapshot_sha256'] for s in row['samples']], 'Changed completed cast/' + cid)
            total = lambda case: statistics.median(
                s['apply']['wall_ms'] + sum(t['wall_ms'] for t in s['selections']) for s in case['samples'])
            result['standard_cases'][cid] = {'apply': metric(old['median_apply_ms'], row['median_apply_ms']),
                                             'including_selections': metric(total(old), total(row))}
        semantic = lambda rows: [{k: v for k, v in row.items() if k not in ('query', 'submit')}
                                 for row in rows]
        require(semantic(bs['match_trace']) == semantic(ns['match_trace']),
                'Changed per-action snapshot/RNG/events/commands/legal actions/player results/views')
        require(bs['final_restore_replay_equal'] and ns['final_restore_replay_equal'],
                'Restore/replay checks did not pass')
        result['match_steps'] = len(ns['match_trace'])
        result['all_step_semantics_equal'] = True
        elapsed = lambda report: sum(row[k]['wall_ms'] for row in report['match_trace']
                                     for k in ('query', 'submit'))
        result['match_query_submit'] = metric(elapsed(bs), elapsed(ns))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--allow-engine-change', action='append', default=[])
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'success': False, 'comparer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        report.update(compare(args.before.resolve(), args.after.resolve(), args.allow_engine_change, args.full))
        report['success'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    (args.output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'success': report['success'], 'output': str(args.output)}, ensure_ascii=False))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
