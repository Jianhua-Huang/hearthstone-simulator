"""Reproducible local tag census and dependency backlog, never a legal-card pool."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_plan(plan):
    if set(plan)!={'schema_version','target_id','inventory_complete','source_sha256','contracts','families'} or plan['schema_version']!=1:
        raise ValueError('Unknown mechanism plan schema')
    if plan['inventory_complete'] is not False:
        raise ValueError('A tag census cannot declare inventory complete')
    contracts=plan['contracts'];families=plan['families']
    ids=[f['id'] for f in families]
    if len(ids)!=len(set(ids)) or set(ids)&set(contracts):raise ValueError('Duplicate dependency identity')
    tags=set()
    for f in families:
        if set(f)!={'id','name','tags','depends_on','status','next_work','mode_scope'}:raise ValueError('Unknown family fields')
        if f['status'] not in ('partial','planned','needs_version_check') or f['mode_scope']!='unverified':raise ValueError('Invalid scope/status')
        if set(f['depends_on'])-set(ids)-set(contracts):raise ValueError('Unknown dependency')
        if type(f['tags']) is not list or any(type(t) is not str or not t for t in f['tags']):raise ValueError('Invalid tag declaration')
        if len(set(f['tags']))!=len(f['tags']) or tags&set(f['tags']):raise ValueError('Ambiguous tag assignment')
        tags.update(f['tags'])
    graph={f['id']:f['depends_on'] for f in families};visiting=set();done=set()
    def visit(key):
        if key in done or key in contracts:return
        if key in visiting:raise ValueError('Cyclic mechanism dependencies')
        visiting.add(key)
        for dep in graph[key]:visit(dep)
        visiting.remove(key);done.add(key)
    for key in ids:visit(key)


def inventory(cards,plan,source_sha256):
    validate_plan(plan)
    if source_sha256!=plan['source_sha256']:raise ValueError('Source fingerprint differs from the frozen plan')
    if type(cards) is not list or any(type(c) is not dict or type(c.get('id')) is not str or type(c.get('tags')) is not dict for c in cards):
        raise ValueError('Expected extracted card records')
    if len({c['id'] for c in cards})!=len(cards):raise ValueError('Duplicate source card identity')
    collectible=[c for c in cards if c.get('collectible') is True]
    known={t for f in plan['families'] for t in f['tags']}
    counts=Counter(t for c in collectible for t,v in c['tags'].items() if v and not t.isdigit())
    rows=[]
    for f in plan['families']:
        hits=sorted((c for c in cards if any(c['tags'].get(t) for t in f['tags'])),key=lambda c:c['id'])
        roots=[c for c in hits if c.get('collectible') is True]
        rows.append({**f,'all_record_matches':len(hits),'collectible_record_matches':len(roots),
            'example_records':[{'id':c['id'],'data_sha256':digest(c)} for c in (roots or hits)[:5]]})
    return {'schema_version':1,'target_id':plan['target_id'],'source_sha256':source_sha256,'plan_sha256':digest(plan),
        'inventory_complete':False,'mode_legality_verified':False,'full_pool_count':None,
        'source_records':len(cards),'collectible_flag_records':len(collectible),
        'scope_note':'All source modes, aliases, cosmetics and preloads may be present. Tags identify review candidates, not executable behavior or current CN legality. Untagged text and reachable noncollectibles need separate review.',
        'families':rows,'unassigned_named_tags':dict(sorted((t,n) for t,n in counts.items() if t not in known))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--plan',type=Path,default=Path('data/support/m5-mechanism-plan.json'))
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();raw=args.source.read_bytes()
    result=inventory(json.loads(raw),json.loads(args.plan.read_text(encoding='utf-8')),hashlib.sha256(raw).hexdigest())
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('source_records','collectible_flag_records','inventory_complete','full_pool_count')}))


if __name__=='__main__':main()
