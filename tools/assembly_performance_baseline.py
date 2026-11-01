"""Fixed-pool assembly/choice benchmarks and bounded training-style steps.

Reuse the canonical source freeze, source guards, timing and comparison runner.
No browser/server access. Timed steps include native apply and player DTO query;
policy inference, resets, cloning and evidence serialization are excluded.
"""
from pathlib import Path
import cProfile, ctypes, hashlib, json, pstats, statistics, sys
import engine_performance_baseline as baseline


def execute(args, report, out, source):
    sys.path.insert(0, str(source))
    import os
    os.chdir(source)
    from hs_sim.local_pool_format import build_cn37_local_pool_format
    from hs_sim.engine import Game, Scenario, PlayerSetup, PlayCard, SelectChoice, IllegalAction
    from hs_sim.engine.actions import action_to_dict
    from hs_sim.engine.replay import build_replay, replay
    fmt = build_cn37_local_pool_format(); registry = fmt.registry
    deck = ('CORE_CS2_029', 'CORE_BAR_541', 'TIME_857') * 10
    def fixture(hand, seed=31):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=hand, deck=deck,
                        board=('Core_CS2_200',) * 2, mana=10, max_mana=10),
            PlayerSetup('HERO_01', hero_power_card_id='HERO_01bp', deck=deck,
                        board=('Core_CS2_200',) * 2, mana=10, max_mana=10)),
            seed=seed, name='assembly-performance-v1', generation_context=fmt.context), registry)
    def play(g, cid):
        source_id = next(i for i in g._state.players[1].hand if g._state.entities[i].card_id == cid)
        target = g._state.players[2].board[0] if cid == 'CORE_BAR_541' else None
        return PlayCard(1, source_id, target)
    def choose(g):
        ch = g._state.pending_choice
        return SelectChoice(ch.player_id, ch.id, tuple(o.id for o in ch.options[:ch.min_count]))
    def apply(g, command):
        g.apply(command)
        return None
    def check(g):
        snap = g.snapshot()
        independent = build_cn37_local_pool_format().registry
        restored = Game.from_snapshot(json.loads(json.dumps(snap)), independent)
        clone = g.clone(); replayed = replay(build_replay(g), independent)
        assert restored.snapshot() == clone.snapshot() == replayed.snapshot() == snap
        assert [restored.observe(p) for p in (1, 2)] == [g.observe(p) for p in (1, 2)]
        if g._state.pending_choice:
            ch = g._state.pending_choice
            try: g.apply(SelectChoice(ch.player_id, ch.id, ('invalid-assembly-perf',)))
            except IllegalAction: pass
            else: raise AssertionError('Invalid choice accepted')
            assert g.snapshot() == snap
            command = choose(g)
            for copy in (restored, clone, replayed): copy.apply(command)
            assert restored.snapshot() == clone.snapshot() == replayed.snapshot()
            assert g.snapshot() == snap
        return {'snapshot_sha256': baseline.digest(snap),
                'views_sha256': baseline.digest([g.observe(p) for p in (1, 2)])}

    cases = {}
    for cid in ('BE_114', 'BE_004', 'CORE_BAR_541', 'TIME_857'):
        base = fixture((cid,)); command = play(base, cid)
        cases['play_' + cid] = (base, lambda g, a=command: apply(g, a))
        waiting = base.clone(); waiting.apply(command)
        assert waiting._state.pending_choice is not None
        command = choose(waiting)
        cases['choose_' + cid] = (waiting, lambda g, a=command: apply(g, a))
    if args.cases:
        assert set(args.cases) <= cases.keys()
        cases = {k:v for k,v in cases.items() if k in args.cases}
    report['identity'] = {'fixture': 'assembly-performance-v1', 'registry': registry.version,
                          'fingerprint': registry.fingerprint(), 'context': repr(fmt.context),
                          'inputs': {name: baseline.digest(g.snapshot()) for name,(g,_) in cases.items()}}
    report['cases'] = {}; report['history'] = []
    for name,(base,fn) in cases.items(): fn(base.clone())
    for iteration in range(args.samples):
        for name,(base,fn) in cases.items():
            g = base.clone(); result,timing = baseline.measure(lambda: fn(g))
            state_hash = baseline.digest(g.snapshot()); result_hash = baseline.digest(result)
            row = report['cases'].setdefault(name, {'samples':[], 'state_sha256':state_hash, 'result_sha256':result_hash})
            assert row['state_sha256'] == state_hash and row['result_sha256'] == result_hash
            row['samples'].append(timing)
            if iteration == 0: row['correctness'] = check(g)
        baseline.save(out/'report.json', report)
        print('assembly samples',iteration+1,'/',args.samples,flush=True)
    for row in report['cases'].values():
        walls=[r['wall_ms'] for r in row['samples']]
        row.update(median_ms=statistics.median(walls),min_ms=min(walls),max_ms=max(walls),
                   median_cpu_ms=statistics.median(r['cpu_ms'] for r in row['samples']))

    # A bounded three-assembly trajectory from one state, including player DTO
    # creation after every action. This is not a complete RL trainer benchmark.
    base = fixture(('BE_114',) * 3)
    trajectories = []
    for repeat in range(3):
        g=base.clone(); rows=[]
        for n in range(3):
            command=play(g,'BE_114')
            for phase in ('play','choose'):
                if phase=='choose': command=choose(g)
                def step():
                    g.apply(command)
                    return g.for_player(1).legal_actions()
                result,timing=baseline.measure(step)
                assert result['error'] is None
                rows.append({**timing,'command':action_to_dict(command),'state_sha256':baseline.digest(g.snapshot()),
                             'view_sha256':baseline.digest(result)})
        trajectories.append(rows)
        print('trajectory',repeat+1,'/',3,flush=True)
    report['trajectories']=trajectories
    signature=lambda rows:[(x['command'],x['state_sha256'],x['view_sha256'])for x in rows]
    assert all(signature(rows)==signature(trajectories[0])for rows in trajectories)
    report['trajectory_identity']=signature(trajectories[0])
    totals=[sum(x['wall_ms']for x in rows)for rows in trajectories]
    report['trajectory_summary']={'actions':6,'total_ms':totals,'median_ms':statistics.median(totals),
                                  'steps_per_second':6e3/statistics.median(totals)}
    report['profiles']={}
    for name in ('play_BE_114','play_BE_004'):
        if name not in cases:continue
        base,fn=cases[name];g=base.clone();profiler=cProfile.Profile()
        profiler.runcall(fn,g);profiler.dump_stats(str(out/(name+'.pstats')))
        with (out/(name+'-profile.txt')).open('w',encoding='utf-8')as stream:
            pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(45)
    report['benchmark_checks_passed']=True
    report['notes'].append('Training-style throughput is six native actions plus player DTO queries; excludes policy inference, reset, cloning and evidence serialization. GC remains enabled.')


if __name__ == '__main__':
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    assert kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),1)
    baseline.execute=execute
    baseline.__file__=__file__
    baseline.main()
