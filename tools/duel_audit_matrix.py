"""Serial paired fixed-scene matrix; retains every ordinary and HTTP sample."""
from pathlib import Path
import argparse
import json
import statistics
import subprocess
import sys
from duel_audit import read, write, file_hash


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', type=Path, required=True); p.add_argument('--after', type=Path, required=True)
    p.add_argument('--fixtures', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cpu-mask', type=int, default=1); p.add_argument('--samples', type=int, default=3)
    p.add_argument('--reference-results', type=Path, help='Validate only the new source against saved complete reference signatures; no paired timing claim')
    a = p.parse_args(); output = a.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    sources = {k: read(path / 'identity.json')['source'] for k, path in (('before', a.before), ('after', a.after))}
    result = {'success': False, 'cpu_mask': a.cpu_mask, 'samples_per_mode_source': a.samples,
              'fixtures': str(a.fixtures.resolve()), 'matrix_sha256': file_hash(__file__), 'cases': [],
              'reference_results': str(a.reference_results.resolve()) if a.reference_results else None,
              'paired_timing_comparison': a.reference_results is None,
              'limits': ['All original samples retained; small fixed scenes do not establish P95.',
                         'Registry/code loaded; caches independently reset before cold query and submit; GC enabled.',
                         'No profiler. Snapshot/assertion/clone outside native submit; actual HTTP includes production listing.']}
    for i, (name, fixture) in enumerate(read(a.fixtures).items()):
        order = ('before', 'after') if i % 2 == 0 else ('after', 'before')
        for side in order:
            if side == 'before' and a.reference_results: continue
            folder = output / name / side; folder.parent.mkdir(parents=True, exist_ok=True)
            write(output / 'progress.json', {**result, 'current': {'case': name, 'side': side, 'order': order}})
            command = [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).with_name('duel_audit_bench.py')),
                       '--source', sources[side], '--fixture', fixture, '--output', str(folder),
                       '--samples', str(a.samples), '--cpu-mask', str(a.cpu_mask), '--http']
            with folder.with_suffix('.log').open('w', encoding='utf8') as stream:
                code = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT).returncode
            assert code == 0, 'Benchmark failed; retain log: ' + str(folder.with_suffix('.log'))
        old = read((a.reference_results / name / 'after' if a.reference_results else output / name / 'before') / 'result.json')
        new = read(output / name / 'after/result.json')
        for side in (old, new): assert side['success'] and side['source_guard'] and side['gc_enabled']
        assert old['harness_sha256'] == new['harness_sha256'] and old['host_adapter_sha256'] == new['host_adapter_sha256']
        assert old['signature'] == new['signature'], 'Complete native query/reply/players/state/RNG differ: ' + name
        for key in ('normalized_reply_sha256', 'normalized_query_sha256'):
            if a.reference_results:
                assert all(r[key] in {v[key] for v in old['http_samples'] if v['mode'] == r['mode']} for r in new['http_samples'])
            else: assert [r[key] for r in old['http_samples']] == [r[key] for r in new['http_samples']]
        row = {'name': name, 'fixture': fixture, 'order': order, 'complete_native_semantics_equal': True,
               'complete_http_body_equal_except_random_host_ticket': True, 'modes': {}}
        for mode in ('cold', 'warm'):
            if a.reference_results:
                samples = [r['submit'] for r in new['http_samples'] if r['mode'] == mode]
                row['modes'][mode] = {'validation_only_native': new['native'][mode],
                                     'validation_only_http_ms': statistics.median(r['http_ms'] for r in samples)}
                continue
            entry = {'before': old['native'][mode], 'after': new['native'][mode],
                     'submit_change_percent': (new['native'][mode]['submit'] / old['native'][mode]['submit'] - 1) * 100}
            for side, data in (('before_http', old), ('after_http', new)):
                samples = [r['submit'] for r in data['http_samples'] if r['mode'] == mode]
                entry[side] = {'median_http_ms': statistics.median(r['http_ms'] for r in samples),
                               'median_submit_ms': statistics.median(r['server']['command_submit_ms'] for r in samples)}
            row['modes'][mode] = entry
        result['cases'].append(row); write(output / 'progress.json', result)
        print(json.dumps({'case': name, 'complete_semantics_equal': True, 'modes': row['modes']}), flush=True)
    source_count = 1 if a.reference_results else 2
    result.update(success=True, native_samples=len(result['cases']) * a.samples * 2 * source_count,
                  actual_http_action_pairs=len(result['cases']) * a.samples * 2 * source_count,
                  actual_http_requests=len(result['cases']) * a.samples * 4 * source_count)
    write(output / 'result.json', result)


if __name__ == '__main__': main()
