"""Isolated, versioned engine benchmarks. Never edits simulator or live matches.

Run with -B -X utf8. Each output must be new; a guarded source/data/test copy is
loaded before any hs_sim import. Timings exclude setup, clone, and assertions.
"""
from pathlib import Path
import argparse
import cProfile
import hashlib
import json
import os
import platform
import pstats
import shutil
import statistics
import subprocess
import sys
import time
import traceback


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inventory(root):
    paths = [p for name in ('hs_sim', 'tests', 'tools') for p in (root / name).rglob('*.py')]
    paths += [p for p in (root / 'data').rglob('*') if p.is_file()]
    paths += [root / 'tools/run_tests.py', root / 'outputs/card-integration-20261014/cards-37.0.0.255026.json']
    linked = set()
    def visit(value):
        if isinstance(value, dict):
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, str) and value.startswith('outputs/'):
            candidate = (root / value).resolve()
            if candidate.is_relative_to(root) and candidate.is_file(): linked.add(candidate)
    for document in (root / 'data').rglob('*.json'):
        try: visit(json.loads(document.read_text(encoding='utf-8-sig')))
        except (UnicodeError, json.JSONDecodeError): pass
    paths += list(linked)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths))}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def measure(fn):
    cpu = time.process_time_ns()
    wall = time.perf_counter_ns()
    result = fn()
    elapsed = (time.perf_counter_ns() - wall) / 1e6
    cpu_elapsed = (time.process_time_ns() - cpu) / 1e6
    return result, {'wall_ms': elapsed, 'cpu_ms': cpu_elapsed}


def execute(args, report, out, source):
    # Imports deliberately occur only after creating the immutable input copy.
    sys.path.insert(0, str(source))
    os.chdir(source)
    from hs_sim.engine import (Game, Scenario, PlayerSetup, GenerationContext,
                               PlayCard, SelectChoice, Attack, EndTurn, IllegalAction)
    from hs_sim.engine.actions import action_to_dict
    from hs_sim.engine.player_api import PlayerPort
    from hs_sim.engine.replay import build_replay, replay
    from hs_sim.engine.continuations import FrameCodec
    from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
    if args.registry == 'constructed':
        from hs_sim.cards.constructed import build_registry
    else:
        from hs_sim.engine.representative import build_registry

    registry = build_registry()
    def game(hand=(), deck=('CS2_029',) * 12, board=(), enemy=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, deck=deck, board=board, mana=10, max_mana=10),
            PlayerSetup('HERO_01', deck=('CS2_182',) * 12, board=enemy)),
            seed=3, name='performance-baseline-v1',
            generation_context=GenerationContext('local-2026-09-23', 'experimental')), registry)

    def card(g, cid):
        return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)

    def select(g):
        ch = g.state.pending_choice
        return SelectChoice(ch.player_id, ch.id, (ch.options[0].id,))

    def checkpoint(g):
        snap = g.snapshot()
        restored = Game.from_snapshot(json.loads(json.dumps(snap)), build_registry())
        cloned = g.clone()
        replayed = replay(build_replay(g), build_registry())
        assert restored.snapshot() == cloned.snapshot() == replayed.snapshot() == snap
        for viewer in (1, 2):
            assert restored.observe(viewer) == cloned.observe(viewer) == replayed.observe(viewer) == g.observe(viewer)
        if g.state.pending_choice:
            ch = g.state.pending_choice
            before = g.snapshot()
            try:
                g.apply(SelectChoice(ch.player_id, ch.id, ('invalid-perf-option',)))
            except IllegalAction:
                pass
            else:
                raise AssertionError('Invalid selection unexpectedly accepted')
            assert g.snapshot() == before
            # Both branches start at the same saved boundary; resuming a clone
            # must not mutate the original or double-pay after restore.
            action = select(g)
            mana = g.state.players[ch.player_id].mana
            cloned.apply(action)
            assert g.snapshot() == before
            restored.apply(action)
            replayed.apply(action)
            assert restored.snapshot() == cloned.snapshot() == replayed.snapshot()
            assert restored.state.players[ch.player_id].mana == mana
        return {'snapshot_sha256': digest(snap), 'views_sha256': digest([g.observe(1), g.observe(2)]),
                'entities': len(g.state.entities), 'plays': len(g.state.play_history),
                'events': len(g.events), 'pending': g.state.pending_choice is not None}

    shadow = game(('UNG_029',))
    shadow3 = game(('UNG_029',), ('CS2_029', 'CS2_024', 'UNG_029') * 4)
    pending = shadow3.clone()
    pending.apply(PlayCard(1, card(pending, 'UNG_029')))
    assert len(pending.state.pending_choice.options) == 3
    fire = game(('CS2_029',))
    combat = game(board=('CS2_182',), enemy=('CS2_182',))
    dense = game(('CS2_029',) * 10, board=('CS2_182',) * 7, enemy=('CS2_182',) * 7)
    pending_snapshot = pending.snapshot()
    report['identity'] = {'schema': SNAPSHOT_SCHEMA_VERSION, 'registry': args.registry,
                          'fixture_initial_sha256': digest(shadow.snapshot()),
                          'snapshot_versions': {k: v for k, v in shadow.snapshot().items()
                                                if 'version' in k or 'fingerprint' in k}}
    def apply(g, action):
        g.apply(action)
        return None
    # Resolve native commands before timing: public Game.state itself deep-copies
    # state, which otherwise contaminates the measured Game.apply duration.
    fire_action = PlayCard(1, card(fire, 'CS2_029'), fire.state.players[2].hero_id)
    shadow_action = PlayCard(1, card(shadow, 'UNG_029'))
    shadow3_action = PlayCard(1, card(shadow3, 'UNG_029'))
    selection_action = select(pending)
    combat_state = combat.state
    attack_action = Attack(1, combat_state.players[1].board[0], combat_state.players[2].board[0])
    cases = {
        'fireball': (fire, lambda g: apply(g, fire_action)),
        'shadow_one_option': (shadow, lambda g: apply(g, shadow_action)),
        'shadow_three_options': (shadow3, lambda g: apply(g, shadow3_action)),
        'select_choice': (pending, lambda g: apply(g, selection_action)),
        'attack': (combat, lambda g: apply(g, attack_action)),
        'end_turn': (fire, lambda g: apply(g, EndTurn(1))),
        'legal_actions_dense': (dense, lambda g: [action_to_dict(a) for a in g.legal_actions()]),
        'player_actions_dense': (dense, lambda g: PlayerPort(g, 1).legal_actions()),
        'observe_pending': (pending, lambda g: g.observe(1)),
        'snapshot_pending': (pending, lambda g: g.snapshot()),
        'restore_pending': (pending, lambda g: Game.from_snapshot(pending_snapshot, registry)),
    }
    if args.cases:
        unknown = set(args.cases) - set(cases)
        if unknown: raise ValueError('Unknown benchmark cases: ' + str(sorted(unknown)))
        cases = {k: v for k, v in cases.items() if k in args.cases}
    report['cases'] = {}
    # A warm-up per case, then interleaved samples reduce order/load bias.
    for base, fn in cases.values():
        fn(base.clone())
    for iteration in range(args.samples):
        for name, (base, fn) in cases.items():
            candidate = base.clone()
            result, timing = measure(lambda: fn(candidate))
            if isinstance(result, Game):
                result = result.snapshot()  # outside timed restore
            state_digest = digest(candidate.snapshot())
            result_digest = digest(result)
            row = report['cases'].setdefault(name, {'samples': [], 'state_sha256': state_digest,
                                                      'result_sha256': result_digest})
            assert row['state_sha256'] == state_digest and row['result_sha256'] == result_digest
            row['samples'].append(timing)
            if iteration == 0:
                row['correctness'] = checkpoint(candidate)
                if name.endswith('dense'):
                    row['action_count'] = len(result['actions'] if isinstance(result, dict) else result)
        print(f'baseline samples {iteration + 1}/{args.samples}', flush=True)
        save(out / 'report.json', report)
    for row in report['cases'].values():
        walls = [s['wall_ms'] for s in row['samples']]
        row.update(median_ms=statistics.median(walls), min_ms=min(walls), max_ms=max(walls),
                   median_cpu_ms=statistics.median(s['cpu_ms'] for s in row['samples']))

    report['history'] = []
    for repeat in range(0 if args.cases else 2):
        g = game(('UNG_029',) * 5)
        for nth in range(1, 6):
            cast_action = PlayCard(1, card(g, 'UNG_029'))
            _, timing = measure(lambda: g.apply(cast_action))
            ch = g.state.pending_choice
            row = dict(timing, repeat=repeat + 1, nth=nth, entities=len(g.state.entities),
                       plays=len(g.state.play_history), options=len(ch.options))
            choice_action = select(g)
            _, selection = measure(lambda: g.apply(choice_action))
            row['selection'] = selection
            row['state_sha256'] = digest(g.snapshot())
            report['history'].append(row)
        checkpoint(g)
        print(f'history run {repeat + 1}/2 complete', flush=True)

    # Profile only AFTER ordinary timings. No wrappers or validation bypasses.
    report['profiles'] = {}
    for name in ('shadow_three_options', 'select_choice', 'legal_actions_dense', 'attack'):
        if name not in cases: continue
        base, fn = cases[name]
        candidate = base.clone()
        profiler = cProfile.Profile()
        profiler.runcall(fn, candidate)
        profiler.dump_stats(str(out / (name + '.pstats')))
        with (out / (name + '-profile.txt')).open('w', encoding='utf-8') as stream:
            stats = pstats.Stats(profiler, stream=stream)
            stats.sort_stats('cumulative').print_stats(45)
            stats.sort_stats('tottime').print_stats(25)
        rows = []
        for (file, line, name2), (primitive, calls, own, cumulative, _) in stats.stats.items():
            if 'hs_sim' in file or name2 in ('deepcopy', 'get_type_hints'):
                rows.append({'file': file, 'line': line, 'function': name2, 'calls': calls,
                             'primitive_calls': primitive, 'self_ms': own * 1000,
                             'inclusive_ms': cumulative * 1000})
        report['profiles'][name] = sorted(rows, key=lambda r: -r['inclusive_ms'])
    tree = FrameCodec(pending.mechanics, pending.registry).encode(pending._frame)
    nodes = []
    def walk(value):
        if isinstance(value, dict):
            if set(value) == {'state'}:
                nodes.append({'sha256': digest(value), 'bytes': len(json.dumps(value, separators=(',', ':')).encode())})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(tree)
    report['pending_frame'] = {'json_bytes': len(json.dumps(tree, separators=(',', ':')).encode()),
                               'state_nodes': nodes, 'unique_state_contents': len({n['sha256'] for n in nodes})}
    report['benchmark_checks_passed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--registry', choices=('representative', 'constructed'), default='representative')
    parser.add_argument('--regressions', action='store_true')
    parser.add_argument('--case', action='append', dest='cases', help='Only selected cases; omit history stress.')
    parser.add_argument('--standard', action='store_true', help='Also run the fixed CN37 host and full match.')
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    if args.compare: args.compare = args.compare.resolve()
    if args.samples < 3:
        parser.error('Use at least 3 samples; small samples are not latency percentiles.')
    original = args.source.resolve()
    out = args.output.resolve()
    previous = json.loads(args.compare.read_text(encoding='utf-8')) if args.compare else None
    out.mkdir(parents=True, exist_ok=False)
    report = {'format': 1, 'success': False, 'python': sys.version, 'platform': platform.platform(),
              'processor': platform.processor(), 'samples': args.samples,
              'notes': ['Artificial real-card fixtures, no frontend or live match access.',
                        'Setup, native command construction, public state lookup, and correctness assertions excluded from action timings; GC stays enabled.',
                        'Profile cumulative times overlap and must not be summed.',
                        'Small sample medians/ranges; no p95 or official rules certification.']}
    try:
        before = inventory(original)
        frozen = out / 'frozen-source'
        for relative in before:
            dest = frozen / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original / relative, dest)
        after = inventory(original)
        frozen_before = inventory(frozen)
        capture = {'source': str(original), 'before': before, 'after': after,
                   'frozen': frozen_before, 'stable': before == after == frozen_before}
        save(out / 'source-manifest.json', capture)
        if not capture['stable']:
            raise RuntimeError('Source changed during capture; retry in a new output directory.')
        report['source_manifest_sha256'] = digest(frozen_before)
        report['harness_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        shutil.copyfile(Path(__file__), out / 'harness.py')
        execute(args, report, out, frozen)
        if args.regressions:
            # Existing negative tests include forged proofs with rehashed outer
            # snapshots, post-selection exceptions, RNG, payment and privacy.
            modules = ['test_m3_choices', 'test_h2_choice_boundary',
                       'test_h2_paid_hand_acceptance', 'test_m3_information']
            save(out / 'regression-modules.json', modules)
            command = [sys.executable, '-B', '-X', 'utf8', str(frozen / 'tools/run_tests.py'),
                       *modules, '--source', str(frozen), '--workers', '2',
                       '--output', str(out / 'regressions')]
            with (out / 'regression-console.txt').open('w', encoding='utf-8') as log:
                child = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            report['regression_exit_code'] = child.returncode
            report['regression_result'] = json.loads((out / 'regressions/result.json').read_text(encoding='utf-8'))
            assert child.returncode == 0 and report['regression_result']['success']
        if args.standard:
            command = [sys.executable, '-B', '-X', 'utf8', str(frozen / 'tools/engine_performance_standard.py'),
                       '--source', str(frozen), '--output', str(out / 'standard')]
            if args.compare:
                command += ['--compare', str(args.compare.resolve().parent / 'standard/report.json')]
            with (out / 'standard-console.txt').open('w', encoding='utf-8') as log:
                child = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            report['standard_exit_code'] = child.returncode
            report['standard_result'] = json.loads((out / 'standard/report.json').read_text(encoding='utf-8'))
            assert child.returncode == 0 and report['standard_result']['success']
        report['frozen_source_unchanged'] = inventory(frozen) == frozen_before
        assert report['frozen_source_unchanged']
        if previous:
            compatible = (previous.get('success') is True and previous.get('identity') == report['identity']
                          and previous.get('harness_sha256') == report['harness_sha256']
                          and previous.get('python') == report['python']
                          and previous.get('platform') == report['platform'])
            comparisons = {}
            for name, row in report['cases'].items():
                old = previous.get('cases', {}).get(name)
                if old:
                    comparisons[name] = {'median_ratio_new_over_old': row['median_ms'] / old['median_ms'],
                                         'same_state_and_result': all(row[k] == old[k] for k in ('state_sha256', 'result_sha256'))}
            report['comparison'] = {'compatible_inputs_and_environment': compatible, 'cases': comparisons,
                                     'same_history_states': [r['state_sha256'] for r in previous.get('history', [])] == [r['state_sha256'] for r in report['history']],
                                     'note': 'If incompatible, rebaseline; ratios alone are not a speedup claim. Background CPU contention is uncontrolled.'}
            if not compatible: raise AssertionError('Incompatible benchmark inputs/environment; establish a matching baseline.')
            if compatible:
                assert all(r['same_state_and_result'] for r in comparisons.values())
                if not args.cases: assert report['comparison']['same_history_states']
        report['success'] = True
    except Exception:
        report['error'] = traceback.format_exc()
        print(report['error'], flush=True)
    finally:
        save(out / 'report.json', report)
    print(json.dumps({'success': report['success'], 'output': str(out)}, ensure_ascii=False), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
