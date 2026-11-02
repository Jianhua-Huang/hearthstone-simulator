"""Replay an autoplayer finding using its original frozen engine, offline only."""
from pathlib import Path
import argparse
import cProfile
import json
import statistics
import sys
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--finding',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=3);p.add_argument('--profile',action='store_true');a=p.parse_args()
    source=a.source.resolve();sys.path.insert(0,str(source))
    from hs_sim.local_pool_format import build_cn37_local_pool_format
    from hs_sim.engine import Game
    from hs_sim.engine.replay import replay
    from dataclasses import replace
    fmt=build_cn37_local_pool_format();original=fmt.registry.pool('constructed.minions',fmt.context)
    for name in ('representative.attack-cost-minions','representative.legendary-dragons'):
        fmt.registry.register_pool(replace(original,id=name,version='ui-standard-match-full-minions-v1:'+original.version))
    finding=json.loads(a.finding.read_text(encoding='utf-8'));root=a.finding.parent
    payload=json.loads((root/finding['replay']).read_text(encoding='utf-8'))
    length=finding.get('replay_prefix_length')
    if length is not None:payload={**payload,'actions':payload['actions'][:length]}
    elif finding['accepted']:payload={**payload,'actions':payload['actions'][:-1]}
    game=replay(payload,fmt.registry);snapshot=game.snapshot();actor=finding['actor'];rows=[]
    for index in range(a.samples+int(a.profile)):
        g=Game.from_snapshot(snapshot,fmt.registry);port=g.for_player(actor)
        prof=cProfile.Profile() if a.profile and index==a.samples else None
        t=time.perf_counter();view=port.legal_actions();query=(time.perf_counter()-t)*1000
        t=time.perf_counter();cpu=time.process_time()
        if prof:prof.enable()
        result=port.legal_actions() if finding['action_type']=='legal_actions' else port.submit({'revision':view['revision'],'action':finding['action']})
        if prof:prof.disable()
        row={'sample_index':index,'query_ms':query,'operation_ms':(time.perf_counter()-t)*1000,'cpu_ms':(time.process_time()-cpu)*1000,
             'accepted':result.get('accepted'),'error':result.get('error'),'profiled':prof is not None,'after_hash':g.state_hash()}
        rows.append(row);print(json.dumps(row),flush=True)
        if prof:
            a.output.mkdir(parents=True,exist_ok=True);prof.dump_stats(str(a.output/'finding.pstats'))
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'result.json').write_text(json.dumps({'finding':finding['id'],'source':str(source),'samples':rows,
        'first_operation_ms':rows[0]['operation_ms'],
        'cache_policy':'Natural caches: first sample and repeated same snapshot may differ. Do not treat cache-hit median as first-use performance.',
        'median_operation_ms':statistics.median(r['operation_ms']for r in rows if not r['profiled'])},indent=2),encoding='utf-8')


if __name__=='__main__':main()
