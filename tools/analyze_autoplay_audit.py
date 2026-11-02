"""Summarize a finished host audit without claiming a complete card oracle."""
from pathlib import Path
from collections import Counter, defaultdict
import argparse
import hashlib
import json
import re
import statistics


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def stats(values):
    values=sorted(values)
    return {'count':len(values),'median_ms':statistics.median(values)if values else None,
            'p95_ms':values[int((len(values)-1)*.95)]if values else None,'max_ms':max(values,default=None)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--focused',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();batch=args.batch.resolve();run=batch/'run';out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    report=read(run/'report.json');assert report['status']=='finished','Batch not finished'
    rows=[json.loads(line)for p in sorted((run/'private').glob('*-steps.jsonl'))for line in p.read_text(encoding='utf-8').splitlines()]
    assert len(rows)==report['action_count']
    source=read(batch/'source-manifest.json')['frozen']
    changed=[name for name,digest in source.items()if hashlib.sha256((batch/'frozen-source'/name).read_bytes()).hexdigest()!=digest]
    assert not changed,changed
    focused=read(args.focused)
    focused_cards=defaultdict(list)
    for case in focused['cases']:focused_cards[case['case'].split()[0]].append(case)
    stage_stats={key:stats([r['timings'][key]for r in rows if key in r['timings']])for key in
                 ('query_ms','policy_ms','adapter_ms','submit_ms','audit_ms','projection_ms')}
    orders={g['id']:g['order']for g in report['games']}
    by_deck={deck:{'actions':sum(orders[r['game_id']][r['actor']-1]==deck for r in rows),
        'submit':stats([r['timings']['submit_ms']for r in rows if orders[r['game_id']][r['actor']-1]==deck])}for deck in('shaman','priest')}
    by_environment={env:stats([r['timings']['submit_ms']for r in rows if r['game_id'].startswith(env+'-')])for env in('A','B')}
    groups=defaultdict(list)
    for row in rows:groups[(row['card_id'],row['card_name'],row['action']['type'])].append(row['timings']['submit_ms'])
    slow_groups=[{'card_id':cid,'card_name':name,'action_type':kind,**stats(values)}for(cid,name,kind),values in groups.items()]
    slow_groups.sort(key=lambda g:g['max_ms'],reverse=True)
    slow=[{k:r[k]for k in ('game_id','step','actor','card_id','card_name','action','timings','accepted','error')}
          for r in rows if r['timings']['submit_ms']>=1000 or r['timings']['query_ms']>=500]
    failed=[{k:r[k]for k in ('game_id','step','actor','card_id','card_name','action','error')}for r in rows if not r['accepted']]
    cases=[]
    for deck in report['decks'].values():
        for card in deck['rows']:
            cid=card['id'];played=[r for r in rows if r['card_id']==cid and r['action']['type']=='play_card'and r['accepted']]
            components=[c for r in rows for c in r.get('effect_checks',[])if c.get('card_id')==cid]
            case={'card_id':cid,'name':card['name'],'deck_copies':card['count'],
                'description':re.sub('<[^>]*>','',card['text']),'normal_match_plays':len(played),
                'observed_components':list({c['clause']for c in components}),'component_verdicts':dict(Counter(c['status']for c in components)),
                'focused_clauses':focused_cards[cid],
                'verdict':'partial_no_mismatch_in_checked_clauses'if components or focused_cards[cid]else'smoke_only_needs_review',
                'scope':'未认证整卡全部条件、数值组合或国服正式规则。'}
            if any(r['card_id']==cid for r in failed):case['verdict']='observed_operational_failure'
            if any(not x['passed']for x in focused_cards[cid]):case['verdict']='focused_clause_failure_needs_review'
            if cid=='BE_114':case['generated_content_failure']='某拼装结果的结束效果未获constructed.past.cards来源范围认可，导致回合结束回滚。'
            cases.append(case)
    # Read only selected receipt fields; never serialize the nested proof/state
    # strings into this public summary or a browser response.
    family=[];family_checks=[];sizes=[]
    for path in sorted((run/'private').glob('*-final-snapshot.json')):
        snap=read(path);accepted={};completed_by_player=defaultdict(set)
        for event in snap['events']:
            data=dict(event.get('data',{}))
            if event['kind']=='family_ability_accepted':
                proof=json.loads(data['proof'])['fields']['record']['fields'];req=proof['request']['fields'];src=req['source']['fields'];pid=event['player_id']
                row={'game_id':path.name.split('-final')[0],'source_card_id':src['card_id'],'source_id':event['source_id'],
                    'epoch':src['zone_epoch'],'ability':req['ability_card_id'],'multiplier':proof['multiplier'],
                    'prior_completed':sorted(completed_by_player[pid]),'completed':False}
                expected=3 if src['card_id']=='BE_013'and {'BE_013t1','BE_013t2','BE_013t3','BE_013t4'}<=completed_by_player[pid]else 1
                row['multiplier_matches_description_gate']=proof['multiplier']==expected
                accepted[proof['id']]=row;family.append(row);sizes.append(len(data['proof'].encode('utf-8')))
            elif event['kind']=='family_ability_completed':
                item=accepted.get(data['trigger_id'])
                if item:item['completed']=True;completed_by_player[event['player_id']].add(item['ability'])
    family_groups=defaultdict(list)
    for row in family:family_groups[(row['game_id'],row['source_card_id'],row['source_id'],row['epoch'])].append(row)
    for (gid,cid,sid,epoch),items in family_groups.items():
        if cid in('BE_778','BE_014'):
            count=2 if cid=='BE_778'else 1;abilities=[i['ability']for i in items]
            family_checks.append({'game_id':gid,'card_id':cid,'clause':'选择不同技能并触发完成','passed':len(items)==count and len(set(abilities))==count and all(i['completed']for i in items),'abilities':abilities})
    for row in family:
        if row['source_card_id']=='BE_013':family_checks.append({'game_id':row['game_id'],'card_id':'BE_013','clause':'四技能先前完成与三倍接受倍率相符','passed':row['multiplier_matches_description_gate']and row['completed'],'multiplier':row['multiplier'],'prior_completed':row['prior_completed']})
    for case in cases:
        case['family_receipt_clauses']=[x for x in family_checks if x['card_id']==case['card_id']]
        if case['family_receipt_clauses']:case['verdict']='partial_no_mismatch_in_checked_clauses'if all(x['passed']for x in case['family_receipt_clauses'])else'family_receipt_mismatch_needs_review'
    summary={'status':'analysis_complete','batch':str(batch),'target':report['target'],'games':report['games'],
        'actions':len(rows),'accepted':sum(r['accepted']for r in rows),'rejected':len(failed),
        'source_guard':{'files':len(source),'unchanged':True},'timing_stages':stage_stats,
        'by_actor_deck':by_deck,'by_environment':by_environment,'slow_count':len(slow),
        'slow_actions':slow,'slow_groups':slow_groups[:20],'failures':failed,'cards':cases,
        'coverage':{'unique_deck_cards':len(cases),'played_in_normal_matches':sum(c['normal_match_plays']>0 for c in cases),
                    'normal_or_focused':sum(bool(c['normal_match_plays']or c['focused_clauses'])for c in cases),
                    'live_component_counts':report['effect_components'],'focused_passed':focused['passed'],'focused_total':focused['total'],
                    'family_receipt_passed':sum(x['passed']for x in family_checks),'family_receipt_total':len(family_checks)},
        'family_receipts':family,'proof_size':{'largest_family_proof_bytes':max(sizes,default=0)},
        'limits':['随机合法动作策略不用于评估套牌强弱。','定向效果夹具使用30费及基础辅助牌，不混入正常对局性能样本。',
                  '片段断言、技能接受/完成证明不等于全部技能数值已独立复算。','生成牌及跨职业机制发生的失败不被忽略或当作白板。',
                  '背景负载未受控，只有约毫秒级差异不能据此宣称优化收益。']}
    save(out/'analysis.json',summary)
    lines=['萨满/牧师：双方自动对战分析',f"目标宿主 {report['target']}",f"{len(report['games'])}局：正常结束 {sum(g['status']=='completed'for g in report['games'])}，异常 {sum(g['status']=='error'for g in report['games'])}；动作 {len(rows)}，拒绝 {len(failed)}。",'']
    for key,value in stage_stats.items():lines.append(f"{key}: 中位数 {value['median_ms']}ms，P95 {value['p95_ms']}ms，最大 {value['max_ms']}ms")
    lines+=['',f"超过1秒命令/500ms查询共{len(slow)}次，详见analysis.json。",'功能覆盖问题：拼装结果未审核生成范围；牧师复制能量仪式后缺少本职业兆示士兵。',
        f"正常对局打出{summary['coverage']['played_in_normal_matches']}/36种卡，定向补测后36种均实际执行。",f"定向描述片段{focused['passed']}/{focused['total']}通过；技能选择/倍率记录{sum(x['passed']for x in family_checks)}/{len(family_checks)}通过。",'',
        '逐卡结论（全部为限定片段/待复核，不冒充完整正确）：']
    for case in cases:lines.append(f"{case['card_id']} {case['name']}: 正常出牌{case['normal_match_plays']}次；{case['verdict']}；观察片段：{'、'.join(case['observed_components']) or '见定向/技能证明或仍待复核'}")
    lines+=['',*summary['limits']]
    (out/'report.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'actions':len(rows),'slow':len(slow),'coverage':summary['coverage'],'family_all_pass':all(x['passed']for x in family_checks)},ensure_ascii=False))


if __name__=='__main__':main()
