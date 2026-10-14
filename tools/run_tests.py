"""Run an unchanged unittest suite with per-test timings and saved diagnostics."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event


def run_groups(source, output, selected, workers, keep_going):
    """Keep each module's class fixtures together in an independent process."""
    groups = {}
    for name in selected:
        groups.setdefault(name.rsplit('.', 2)[0], []).append(name)
    stopped = Event()
    runner = str(Path(__file__).resolve())
    # Larger modules start first so a long group is less likely to finish alone.
    ordered = sorted(groups.items(), key=lambda item: -len(item[1]))

    def execute(index, module, names):
        if stopped.is_set():
            return {'module': module, 'not_started': True, 'tests': names}
        child_output = output / 'groups' / f'{index:03d}-{module}'
        child_output.parent.mkdir(parents=True, exist_ok=True)
        test_list = child_output.with_suffix('.tests.json')
        test_list.write_text(json.dumps(names, ensure_ascii=False), encoding='utf-8')
        argv = [sys.executable, '-B', '-X', 'utf8', runner, '--source', str(source),
                '--output', str(child_output), '--test-list', str(test_list)]
        if keep_going:
            argv.append('--keep-going')
        child = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8')
        child_output.mkdir(parents=True, exist_ok=True)
        (child_output / 'stdout.txt').write_text(child.stdout, encoding='utf-8')
        (child_output / 'stderr.txt').write_text(child.stderr, encoding='utf-8')
        path = child_output / 'result.json'
        report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        passed = (child.returncode == 0 and report is not None and report['success']
                  and report['source_guard'] and report['executed'] == len(names))
        if not passed and not keep_going:
            stopped.set()
        return {'module': module, 'output': str(child_output), 'exit_code': child.returncode,
                'passed': passed, 'report': report, 'tests': names}

    results = []
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, index, module, names)
                   for index, (module, names) in enumerate(ordered)]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if not result.get('not_started'):
                print(json.dumps({'group': result['module'], 'passed': result['passed'],
                                  'finished_groups': sum(not row.get('not_started') for row in results),
                                  'total_groups': len(groups)}), flush=True)
    timings = []
    reports = []
    for result in results:
        if result.get('not_started'):
            continue
        if result['report'] is not None:
            reports.append(result['report'])
        path = Path(result['output']) / 'test-times.jsonl'
        if path.exists():
            timings.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
    completed = [row['test'] for row in timings]
    coverage = len(completed) == len(set(completed)) == len(selected) and set(completed) == set(selected)
    (output / 'test-times.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n'
                                                  for row in timings), encoding='utf-8')
    (output / 'groups.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'selected': len(selected), 'executed': sum(row['executed'] for row in reports),
            'success': coverage and all(row.get('passed', False) for row in results),
            'seconds': time.perf_counter() - start, 'workers': workers,
            'exactly_once_coverage': coverage,
            'failures': [item for row in reports for item in row['failures']],
            'errors': [item for row in reports for item in row['errors']],
            'skipped': [item for row in reports for item in row['skipped']],
            'slowest': sorted(timings, key=lambda row: row['seconds'], reverse=True)[:20]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--keep-going', action='store_true')
    parser.add_argument('--test-list', type=Path,
                        help='JSON method list, avoiding Windows command-line size limits')
    parser.add_argument('--workers', type=int, default=1,
                        help='Independent module processes within this one suite (default: 1)')
    parser.add_argument('tests', nargs='*', help='Module/test names; omitted means full discovery')
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error('--workers must be between 1 and 16')
    if args.test_list and args.tests:
        parser.error('Use either positional test names or --test-list')
    names = args.tests
    if args.test_list:
        names = json.loads(args.test_list.read_text(encoding='utf-8'))
        if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
            parser.error('--test-list must contain a nonempty JSON list of test names')
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path[:0] = [str(source), str(source / 'tests')]
    os.chdir(source)

    def inventory():
        return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in ('hs_sim', 'tests', 'tools')
                for p in sorted((source / folder).rglob('*.py'))}

    before = inventory()
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromNames(names) if names
             else loader.discover(str(source / 'tests')))

    def ids(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                yield from ids(item)
            else:
                yield item.id()

    selected = list(ids(suite))
    if loader.errors or not selected or len(selected) != len(set(selected)):
        diagnostics = {'loader_errors': loader.errors,
                       'duplicate_methods': sorted({name for name in selected if selected.count(name) > 1})}
        (output / 'discovery-errors.json').write_text(json.dumps(diagnostics, ensure_ascii=False,
            indent=2), encoding='utf-8')
        raise RuntimeError(f'Test discovery failed; see {output / "discovery-errors.json"}')
    (output / 'inputs.json').write_text(json.dumps({'source': str(source),
        'python': sys.version, 'selected': selected, 'source_sha256': before,
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'full_discovery': not names}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'selected': len(selected), 'full': not names,
                      'output': str(output)}, ensure_ascii=False), flush=True)
    if args.workers > 1:
        report = run_groups(source, output, selected, args.workers, args.keep_going)
        report.update(source=str(source), source_guard=before == inventory())
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: report[key] for key in ('selected', 'executed', 'success', 'seconds',
                                                      'source_guard', 'exactly_once_coverage')}), flush=True)
        return 0 if report['success'] and report['source_guard'] else 1
    timings = []
    with (output / 'test-times.jsonl').open('x', encoding='utf-8', buffering=1) as timer_stream:
        class TimedResult(unittest.TextTestResult):
            def startTest(self, test):
                super().startTest(test)
                self.started = time.perf_counter()
                self.cpu_started = time.process_time()
                self.red_before = len(self.errors) + len(self.failures)
                self.skipped_before = len(self.skipped)
                self.expected_before = len(self.expectedFailures)
                self.unexpected_before = len(self.unexpectedSuccesses)

            def stopTest(self, test):
                row = {'test': test.id(), 'seconds': time.perf_counter() - self.started,
                       'cpu_seconds': time.process_time() - self.cpu_started,
                       'status': ('failed' if len(self.errors) + len(self.failures) > self.red_before
                                  else 'unexpected_success' if len(self.unexpectedSuccesses) > self.unexpected_before
                                  else 'expected_failure' if len(self.expectedFailures) > self.expected_before
                                  else 'skipped' if len(self.skipped) > self.skipped_before else 'passed')}
                timings.append(row)
                timer_stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                super().stopTest(test)

        start = time.perf_counter()
        with (output / 'validation.txt').open('x', encoding='utf-8', buffering=1) as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2,
                failfast=not args.keep_going, resultclass=TimedResult).run(suite)
        elapsed = time.perf_counter() - start
    completed = [row['test'] for row in timings]
    coverage = len(completed) == len(set(completed)) == len(selected) and set(completed) == set(selected)
    report = {'source': str(source), 'selected': len(selected), 'executed': result.testsRun,
              'success': result.wasSuccessful() and coverage, 'seconds': elapsed,
              'exactly_once_coverage': coverage,
              'source_guard': before == inventory(),
              'failures': [(t.id(), message) for t, message in result.failures],
              'errors': [(t.id(), message) for t, message in result.errors],
              'expected_failures': [t.id() for t, _ in result.expectedFailures],
              'unexpected_successes': [t.id() for t in result.unexpectedSuccesses],
              'skipped': [(t.id(), reason) for t, reason in result.skipped],
              'slowest': sorted(timings, key=lambda row: row['seconds'], reverse=True)[:20]}
    (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('selected', 'executed', 'success', 'seconds',
                                                  'source_guard')}, ensure_ascii=False), flush=True)
    return 0 if report['success'] and report['source_guard'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
