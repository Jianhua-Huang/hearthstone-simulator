"""Read-only worker checks and exclusive evidence archive; never accept behavior.

No Game.apply, merge, central registration, permission request or source edits.
The caller still reviews complete card semantics and runs main-tree scope tests.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import card_batch as b


def baseline_python(worker, baseline, guard, additions):
    """Verify all old protected code against the actual Git parent, including mixed EOLs."""
    body = subprocess.check_output(['git', '-C', str(worker), 'archive', '--format=tar', baseline,
                                    '--', 'hs_sim', 'tests', 'tools'])
    with tarfile.open(fileobj=io.BytesIO(body)) as archive:
        original = {x.name:archive.extractfile(x).read() for x in archive.getmembers()
                    if x.isfile() and x.name.endswith('.py')}
    b.require(set(guard)-set(original) == set(additions), 'Unexpected untracked protected worker code')
    b.require(set(original) <= set(guard), 'Worker lost original protected source files')
    for name in set(guard)&set(original):
        b.require((worker/name).read_bytes().replace(b'\r\n', b'\n') == original[name].replace(b'\r\n', b'\n'),
                  'Worker changed baseline code: '+name)
    return dict(old_protected_python=len(original), actual_guard_count=len(guard),
                baseline_code_exact_after_line_ending_normalization=True)


def archive_files(worker, output, expected):
    """Never overwrite earlier artifacts or follow an input outside the worker tree."""
    worker, output = Path(worker).resolve(), Path(output).resolve()
    b.require(not output.exists(), 'Use a fresh evidence archive')
    checked = {}
    for name, pin in expected.items():
        rel = b.relative_file(name)
        source = worker/rel
        b.require(source.resolve().is_relative_to(worker) and source.is_file(), 'Evidence escaped worker: '+name)
        b.require(b.sha(source) == pin, 'Evidence changed before archive: '+name)
        checked[name] = source
    output.mkdir(parents=True)
    for name, source in checked.items():
        target = output/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        b.require(b.sha(target) == expected[name], 'Archived evidence differs: '+name)
    return dict(files=expected, file_count=len(expected), archive=str(output),
                all_original_bytes_rechecked=True)


def source_records(data, catalog):
    raw = {x['id']:x for x in catalog}
    rows = [row for section in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only')
            for row in data.get(section, [])]
    seen = set()
    for row in rows:
        cid = row['record']['id']
        b.require(cid not in seen and cid in raw, 'Duplicated/unknown original source identity')
        seen.add(cid)
        b.require(row['record'] == raw[cid] and b.canonical(row['record']) == row['record_sha256'],
                  'Incomplete/changed original source: '+cid)
    return raw, len(rows)


def audit(worker, delivery_path, data_path, output):
    worker, output = Path(worker).resolve(), Path(output).resolve()
    b.require(output.is_relative_to(ROOT/'outputs') and not output.exists(), 'Use a fresh workspace output directory')
    delivery_file = worker/b.relative_file(delivery_path)
    data_file = worker/b.relative_file(data_path)
    d, data = b.read(delivery_file), b.read(data_file)
    commit, baseline = d['commit'], d['baseline']
    b.require(subprocess.check_output(['git', '-C', str(worker), 'rev-parse', 'HEAD'], text=True).strip() == commit,
              'Worker HEAD differs from the delivered commit')
    b.require(not subprocess.check_output(['git', '-C', str(worker), 'status', '--porcelain'], text=True).strip(),
              'Worker tree is not clean')
    b.require(subprocess.check_output(['git', '-C', str(worker), 'rev-parse', commit+'^'], text=True).strip() == baseline,
              'Worker commit has another parent')
    task = b.load_manifest(worker/d['source_manifest'])
    scope = b.check_commit(worker, commit, task)
    allowed = set(task['allowed_files'])
    b.require(set(d['scope_files']) == allowed and data_path in allowed, 'Delivered source escaped assigned files')
    guard = b.source_guard(worker)
    code = baseline_python(worker, baseline, guard, {x for x in allowed if x.endswith('.py')})
    for name in allowed:
        blob = subprocess.check_output(['git', '-C', str(worker), 'show', commit+':'+name])
        b.require((worker/name).read_bytes().replace(b'\r\n', b'\n') == blob.replace(b'\r\n', b'\n'),
                  'Worker file differs from its committed blob')
    catalog_path = worker/b.relative_file(data['source']['path'])
    b.require(b.sha(catalog_path) == data['source']['sha256'] == task['source_sha256'], 'Source catalog changed')
    raw, record_count = source_records(data, b.read(catalog_path))
    faces, originals = {}, {}
    for obs in data['official_observations']:
        source = Path(obs['response_file']).resolve()
        b.require(source.is_relative_to(worker/'outputs'), 'Primary response escaped worker output cache')
        b.require(b.sha(source) == obs['response_sha256'] and obs['face'] in b.read(source)['cards'],
                  'Primary cache body changed')
        b.require(b.read(source.with_suffix('.receipt.json')) == obs['observation'], 'Primary observation receipt changed')
        b.check_face(raw[obs['card_id']], obs['face'], obs['locale'],
                     data.get('display_normalizations', {}).get(obs['card_id']),
                     numeric_normalizations=data.get('numeric_normalizations', {}).get(obs['card_id']))
        key = (obs['card_id'], obs['locale'])
        b.require(key not in faces, 'Duplicated strict primary face')
        faces[key] = obs['face']
    for row in data.get('cards', []) + data.get('dependencies', []):
        for locale in ('zh_CN', 'en_US'):
            b.require((row['record']['id'], locale) in faces, 'Executable definition lacks a strict primary face')
    for edge in data.get('exact_parent_child_links', []):
        b.require(edge['dbf_id'] == raw[edge['child']]['dbf_id'] and edge['dbf_id'] in
                  faces[(edge['parent'], edge['locale'])].get('childIds', []), 'Claimed API relation is absent')
    for edge in data.get('source_tag_links', []):
        b.require(raw[edge['parent']]['tags'][edge['tag']] == edge['dbf_id'] == raw[edge['child']]['dbf_id'],
                  'Claimed original source tag differs')
    runs = []
    for receipt in b.read(worker/d['final_test_receipts']):
        run = worker/receipt['run']; selected = b.read(run/'inputs.json')['selected']
        result = b.verify_run(worker, run, sorted({x.split('.')[0] for x in selected}), guard, selected)
        b.require(result['methods'] == receipt['methods'] and result['seconds'] == receipt['seconds'],
                  'Worker test receipt changed')
        runs.append(result)
    b.require(not d['active_worker_test_sessions'] and all(x.get('consumed') and type(x['exit_code']) is int
              for x in d['terminals']), 'Worker has unconsumed or live test sessions')
    for field in ('public_engine_changed', 'central_assembly_changed', 'version_identity_changed', 'ledgers_changed'):
        b.require(d[field] is False, 'Worker declared an out-of-scope change')
    for folder in (delivery_file.parent, (worker/d['source_manifest']).parent):
        b.require(folder.resolve().is_relative_to(worker/'outputs'), 'Worker artifact folder escaped outputs')
        for source in folder.rglob('*'):
            if source.is_file():
                b.require(source.resolve().is_relative_to(worker), 'Artifact symlink escaped worker')
                originals[source.relative_to(worker).as_posix()] = b.sha(source)
    for path, pin in d['evidence_files_sha256'].items():
        source = Path(path); source = source if source.is_absolute() else worker/source
        b.require(source.resolve().is_relative_to(worker), 'Declared evidence escaped worker')
        b.require(b.sha(source) == pin, 'Declared evidence changed')
        originals[source.relative_to(worker).as_posix()] = pin
    for name in allowed: originals[name] = b.sha(worker/name)
    index = archive_files(worker, output/'worker-archive', originals)
    report = dict(batch=d['batch'], worker_commit=commit, worker_baseline=baseline, scope=scope,
        baseline_python=code, complete_raw_records=record_count, strict_primary_faces=len(faces),
        exact_api_links=len(data.get('exact_parent_child_links', [])),
        original_source_tag_links=len(data.get('source_tag_links', [])),
        named_links_are_separate=data.get('named_dependency_links', []),
        candidate_pool_qualifications_require_manual_review=data.get('pool_predicate_qualifications', []),
        rejected_primary_observations=data.get('rejected_complete_primary_observations', []),
        final_runs=runs, original_terminal_receipts=d['terminals'], archive=index,
        mechanical_audit_passed=True, behavior_review_required=True, main_tests_required=True,
        main_behavior_acceptance=False, formal_pool_certified=False, cn_calibration_certified=False,
        game_actions=0, source_mutations=0, git_merges=0)
    b.save_new(output/'audit.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    parser.add_argument('--delivery', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    r = audit(args.worker, args.delivery, args.data, args.output)
    print(json.dumps(dict(batch=r['batch'], mechanical_audit_passed=True, raw_records=r['complete_raw_records'],
        strict_faces=r['strict_primary_faces'], archived_files=r['archive']['file_count'],
        final_worker_methods=sum(x['methods'] for x in r['final_runs']), behavior_review_required=True), ensure_ascii=False))


if __name__ == '__main__': main()
