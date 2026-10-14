from pathlib import Path
import collections
import json

root=Path(__file__).resolve().parent
out=root/'results'
inventory=json.loads((out/'inventory.json').read_text(encoding='utf-8'))
presets=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(out.glob('*.seed0.json'))]
games=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(out.glob('game.*.json'))]
case_index={(c['module'],c['case']):c for c in inventory['preset_cases']}
groups={}
for result in presets:
    family='Arthas' if '.t_arthas_' in result['module'] else 'LichKing' if '.t_lich_' in result['module'] else 'Nathria'
    counter=groups.setdefault(family,collections.Counter())
    counter['total']+=1
    counter[result['status']]+=1
    if result['status']=='completed':
        if result['assertion_calls']>0 or case_index[(result['module'],result['case'])]['static_assertions']>0:
            counter['completed_with_assertion_evidence']+=1
        else:
            counter['completed_without_assertion_evidence']+=1
summary=dict(preset_count=len(presets),preset_status=dict(collections.Counter(p['status'] for p in presets)),groups=groups,
             game_count=len(games),game_status=dict(collections.Counter(g['status'] for g in games)),
             failure_types=dict(collections.Counter(p.get('error_type') for p in presets if p['status']=='failed')),
             failures=[p for p in presets if p['status']=='failed'],game_results=games)
if (out/'batch.json').exists():
    summary['batch_timeouts']=[r for r in json.loads((out/'batch.json').read_text(encoding='utf-8')) if r.get('status')=='timeout']
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in ('failures','game_results')},ensure_ascii=False,indent=2))
