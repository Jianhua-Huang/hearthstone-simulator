"""Read-only diagnostics against a frozen engine; writes local evidence only."""
from pathlib import Path
import argparse, cProfile, hashlib, json, os, pstats, statistics, sys, time, traceback

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--compare', type=Path)
args = parser.parse_args()
previous = json.loads(args.compare.read_text(encoding='utf-8')) if args.compare else None
root = args.source.resolve()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(root))
os.chdir(root)
report = {'success': False, 'notes': [
    'Native engine and player DTO timings; no HTTP, browser, animation or AI search.',
    'Standard-candidate card sources; experimental deck policy, not official format certification.',
    'Small fixed workloads and deterministic policy, not ranked deck or percentile estimates.',
    'Setup/clone/action construction/assertions excluded from individual action timings.']}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()

def save():
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

def timed(fn):
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    result = fn()
    return result, {'wall_ms': (time.perf_counter_ns()-wall)/1e6,
                    'cpu_ms': (time.process_time_ns()-cpu)/1e6}

def profile(name, fn):
    pr = cProfile.Profile()
    value = pr.runcall(fn)
    pr.dump_stats(str(out/(name+'.pstats')))
    with (out/(name+'-profile.txt')).open('w', encoding='utf-8') as stream:
        ps = pstats.Stats(pr, stream=stream)
        ps.sort_stats('cumulative').print_stats(40)
        ps.sort_stats('tottime').print_stats(25)
    report.setdefault('profiles', {})[name] = [
        {'file': f, 'line': n, 'function': name2, 'calls': calls,
         'self_ms': own*1000, 'inclusive_ms': total*1000}
        for (f,n,name2),(primitive,calls,own,total,callers) in
        sorted(ps.stats.items(), key=lambda item:-item[1][3])[:70]]
    return value

try:
    started = time.perf_counter()
    from hs_sim.local_pool_format import build_cn37_local_pool_format
    from hs_sim.engine import (Game, Scenario, PlayerSetup, GenerationContext,
        PlayCard, SelectChoice, Attack, EndTurn, Concede, UseHeroPower)
    from hs_sim.engine.construction import DeckPolicy, DeckSpec, MatchSetup
    from hs_sim.engine.model import CardClass
    from hs_sim.engine.player_api import PlayerPort
    from hs_sim.engine.replay import build_replay, replay
    report['import_ms'] = (time.perf_counter()-started)*1000
    fmt, report['registry_build'] = timed(build_cn37_local_pool_format)
    registry = fmt.registry
    report['identity'] = {'registry': registry.version, 'definitions': len(registry.cards),
                          'python': sys.version,'target':fmt.target_id,'pools':len(registry.pools)}
    save()
    print('registry loaded',report['identity'],report['registry_build'],flush=True)

    original = json.loads((root/'data/reference/card-integration-20261014/cards-37.0.0.255026.json').read_text(encoding='utf-8-sig'))
    original = original if isinstance(original,list) else original['cards']
    rows = {r['id']:r for r in original}
    policy = json.loads((root/'data/cards/standard-candidate-policy-cn37-20261015.json').read_text(encoding='utf-8'))
    def candidate(cid):
        r = rows[cid]
        assert r['collectible'] and (r['card_set_id'] in policy['candidate_set_ids'] or cid in policy['early_available_ids'])
        assert cid in registry.cards
        return cid
    minion = candidate('Core_CS2_200')
    cards = tuple(candidate(c) for c in ('CORE_CS2_029','CORE_CS2_024','CORE_BAR_541',
        'CORE_CS2_179','CORE_EX1_010','CORE_EX1_096','CORE_EX1_162','CORE_EX1_506',
        'CORE_EX1_509','CORE_GVG_085','CORE_LOOT_413','CORE_NEW1_023',
        'CORE_ULD_723','CORE_UNG_205','CS3_038'))
    deck = tuple(c for c in cards for _ in range(2))
    report['deck'] = list(deck)
    def scenario(hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=hand,deck=deck,
                        board=(minion,minion),mana=10,max_mana=10),
            PlayerSetup('HERO_01',hero_power_card_id='HERO_01bp',deck=deck,
                        board=(minion,minion),mana=10,max_mana=10)),seed=31,
            name='standard candidate performance workload',
            generation_context=fmt.context),registry)
    base, report['scenario_create'] = timed(lambda:scenario(('CORE_CS2_029',)))
    report['same_registry_fingerprint'] = timed(registry.fingerprint)[1]
    report['cases'] = {}
    report['initial_state_sha256'] = digest(base.snapshot())
    for cid in ('CORE_CS2_029','CORE_BAR_541','TIME_857'):
        candidate(cid)
        g = base if cid=='CORE_CS2_029' else scenario((cid,))
        source = g._state.players[1].hand[0]
        target = g._state.players[2].hero_id if cid=='CORE_CS2_029' else (
            g._state.players[2].board[0] if cid=='CORE_BAR_541' else None)
        action = PlayCard(1,source,target)
        values = []
        after_digest = None
        for i in range(4):
            run = g.clone()
            _, action_time = timed(lambda:run.apply(action))
            if cid=='CORE_CS2_029':
                assert run._state.entities[target].health==24
            elif cid=='CORE_BAR_541':
                assert run._state.entities[target].health==5 and run._state.pending_choice is not None
            else:
                assert run._state.pending_choice is not None
            after_hash = run.state_hash()
            assert after_digest is None or after_digest==after_hash
            after_digest = after_hash
            _, public_time = timed(lambda:PlayerPort(run,1).legal_actions())
            selected = []
            while run._state.pending_choice is not None:
                ch = run._state.pending_choice
                a = SelectChoice(ch.player_id,ch.id,tuple(o.id for o in ch.options[:ch.min_count]))
                _, selection_time = timed(lambda:run.apply(a))
                selected.append(selection_time)
                assert len(selected)<=8
            if cid=='CORE_BAR_541': assert len(run._state.players[1].hand)==1
            if cid=='TIME_857': assert len(run._state.players[1].hand)==2
            if i:
                values.append({'apply':action_time,'public_query':public_time,'selections':selected,
                    'completed_snapshot_sha256':digest(run.snapshot())})
        case = {'samples':values,'after_state_sha256':after_digest,
                'median_apply_ms':statistics.median(r['apply']['wall_ms'] for r in values),
                'median_public_query_ms':statistics.median(r['public_query']['wall_ms'] for r in values)}
        report['cases'][cid] = case
        profiled = g.clone()
        profile(cid,lambda:profiled.apply(action))
        save()
        print('case',cid,case['median_apply_ms'],flush=True)

    specs = tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,deck) for _ in range(2))
    setup = fmt.match_setup(specs,seed=20261031,first_player=1)
    match, report['match_create'] = timed(lambda:Game.from_decks(setup,registry))
    trace = []
    late = None
    for step in range(180):
        state = match._state
        if state.status!='playing': break
        actor = state.pending_choice.player_id if state.pending_choice else state.active_player
        result, query_time = timed(lambda:PlayerPort(match,actor).legal_actions())
        assert result['error'] is None, result['error']
        obs = result['observation']
        enemy = next(p for p in obs['players'] if p['id']!=actor)
        hero_ref = enemy['hero']['ref']
        actions = [a for a in result['actions'] if a['type']!='concede']
        assert actions
        def score(a):
            return {'select_choice':100,'attack':60,'play_card':50,'use_hero_power':20,
                    'end_turn':-100}.get(a['type'],40) + (5 if a.get('target',a.get('defender'))==hero_ref else 0)
        selected = max(actions,key=score)
        if step==65: late=match.clone()
        accepted, submit_time = timed(lambda:PlayerPort(match,actor).submit(
            {'revision':result['revision'],'action':selected}))
        assert accepted['accepted'],accepted['error']
        trace.append({'step':step,'turn':state.turn,'action':selected['type'],
            'query':query_time,'submit':submit_time,'entities':len(state.entities),
            'events':len(match._events),'plays':len(state.play_history),
            'visible_actions':len(actions), 'command':selected,
            'snapshot_sha256':digest(match.snapshot()),
            'query_sha256':digest(result),'submit_sha256':digest(accepted),
            'other_player_view_sha256':digest(match.observe(3-actor))})
        if step%15==0:
            report['match_trace']=trace;save()
            print('match step',step,'turn',match._state.turn,flush=True)
    report['match_trace']=trace
    report['match_final']={'status':match._state.status,'winner':match._state.winner,
        'turn':match._state.turn,'actions':len(trace),'snapshot_bytes':len(json.dumps(match.snapshot()))}
    final = match.snapshot()
    restored, report['final_restore'] = timed(lambda:Game.from_snapshot(final,registry))
    assert restored.snapshot()==final
    replayed, report['final_replay'] = timed(lambda:replay(build_replay(match),registry))
    assert replayed.snapshot()==final
    report['final_restore_replay_equal']=True
    profile('registry_fingerprint',registry.fingerprint)
    if late is not None:
        actor=late._state.pending_choice.player_id if late._state.pending_choice else late._state.active_player
        query=profile('late_player_query',lambda:PlayerPort(late,actor).legal_actions())
        legal=[a for a in query['actions'] if a['type']!='concede']
        profile('late_submit',lambda:PlayerPort(late,actor).submit(
            {'revision':query['revision'],'action':max(legal,key=score)}))
    if previous is not None:
        assert previous['success']
        assert previous['identity']==report['identity'] and previous['deck']==report['deck']
        assert previous['initial_state_sha256']==report['initial_state_sha256']
        comparisons={}
        for cid,row in report['cases'].items():
            before=previous['cases'][cid]
            assert before['after_state_sha256']==row['after_state_sha256']
            assert [s['completed_snapshot_sha256']for s in before['samples']]==[s['completed_snapshot_sha256']for s in row['samples']]
            comparisons[cid]={'median_ratio_new_over_old':row['median_apply_ms']/before['median_apply_ms']}
        keys=('step','turn','action','command','entities','events','plays','visible_actions',
              'snapshot_sha256','query_sha256','submit_sha256','other_player_view_sha256')
        assert [{k:r[k]for k in keys}for r in previous['match_trace']]==[{k:r[k]for k in keys}for r in trace]
        assert previous['match_final']==report['match_final']
        report['comparison']={'all_semantic_checks_equal':True,'cases':comparisons}
    report['success']=True
except Exception:
    report['error']=traceback.format_exc()
    print(report['error'],flush=True)
finally:
    save()
print(json.dumps({'success':report['success'],'output':str(out)},ensure_ascii=False),flush=True)
raise SystemExit(0 if report['success'] else 1)
