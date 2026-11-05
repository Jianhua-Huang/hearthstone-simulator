"""Reusable local deck -> two bots -> evidence -> analysis/handoff workflow.

No simulator changes. CLI does not send Codex messages: `handoff` emits exact
connector arguments; `ack` records a confirmed delivery by the calling agent.
"""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,gzip,hashlib,json,math,os,shutil,subprocess,sys,time,traceback

ROOT=Path(__file__).resolve().parents[1]
FUNCTION_THREAD='01a0ce20-8605-74d1-a6df-5e9bb259108b'
PERFORMANCE_THREAD='01a19572-6358-7031-80de-83d70dc1b134'
def read(path):return json.loads(Path(path).read_text('utf8'))
def write(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp')
 temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
 for attempt in range(20):
  try:temp.replace(path);return
  except PermissionError:
   if attempt==19:raise
   time.sleep(.01*(attempt+1))
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate_pairs(decks,pairs,allow_shared_cards=False):
 """Original imported lists may overlap; never edit real cards to avoid it."""
 if type(allow_shared_cards)is not bool:raise ValueError('allow_shared_cards must be boolean')
 for pair in pairs:
  if type(pair)is not list or len(pair)!=2 or pair[0]==pair[1]or any(k not in decks for k in pair):raise ValueError('Each pair requires two distinct known deck keys')
  if not allow_shared_cards and not set(decks[pair[0]]['cards']).isdisjoint(decks[pair[1]]['cards']):raise ValueError('Opposing decks share card IDs; original imported lists require explicit allow_shared_cards=true')
def stats(values):
 values=sorted(values)
 return{'count':len(values),'median_ms':values[len(values)//2]if len(values)%2 else sum(values[len(values)//2-1:len(values)//2+1])/2,'p95_ms':values[math.ceil(.95*len(values))-1],'max_ms':values[-1]}if values else None

def set_affinity(mask):
 if sys.platform=='win32':
  import ctypes
  kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=ctypes.c_void_p;kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
  if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),mask):raise OSError('Cannot apply audit CPU affinity')

def restore_worker(batch,output):
 """Strictly restore every captured boundary using its own frozen engine.

 This verifier can be newer than the frozen runner; both identities are recorded.
 No header migration, proof removal, state repair, action replay or bot input.
 """
 config=read(batch/'config.json');identity=read(batch/'identity.json');source=Path(identity['source']);set_affinity(config['cpu_mask'])
 assert read(batch/'run-status.json')['status']=='finished','Finish trajectory capture before restoration checks'
 manifest=read(batch/'source-manifest.json')
 assert all(file_hash(source/p)==sha for p,sha in manifest['files'].items()),'Frozen input changed'
 sys.path.insert(0,str(source));sys.path.insert(0,str(source/'tools'))
 import duel_audit_runtime as runtime
 assert runtime.ROOT==source,'Restoration imported a different engine source'
 output.mkdir(parents=True,exist_ok=False);c=runtime.catalog(output,'restore',batch/'plans/pair-1.json')
 assert runtime.CORE_EFFECTS_VERSION==identity['core']and c.fmt.target_id==identity['target']
 files=sorted((batch/'private').glob('*/*.json.gz'));failures=[];completed=0
 summary={'source':str(source),'identity':identity,'verifier':str(Path(__file__).resolve()),'verifier_sha256':file_hash(__file__),'cpu_mask':config['cpu_mask'],'total':len(files),'checked':0,'failures':[],'status':'running','scope':'Every saved initial/after boundary; full snapshot equality including RNG; not action timing or full card certification.'}
 write(output/'summary.json',summary)
 for path in files:
  row={'snapshot':str(path),'boundary':str(path.relative_to(batch/'private')),'passed':False};start=time.perf_counter()
  try:
   raw=gzip.decompress(path.read_bytes());row['snapshot_sha256']=hashlib.sha256(raw).hexdigest();before=json.loads(raw)
   restored=runtime.Game.from_snapshot(before,c.registry,mode='release');actual=restored.snapshot()
   if actual!=before:raise AssertionError('Full restored snapshot differs')
   row['passed']=True;del restored,actual,before,raw
  except Exception:
   trace=traceback.format_exc();error=output/(path.parent.name+'-'+path.stem+'.exception.txt');error.write_text(trace,encoding='utf8');row.update(exception=str(error),exception_tail=trace.splitlines()[-1]);failures.append(dict(row))
  row['verification_ms']=round((time.perf_counter()-start)*1000,3)
  with(output/'boundaries.jsonl').open('a',encoding='utf8')as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
  completed+=1
  if completed%50==0 or not row['passed']:
   summary.update(checked=completed,failures=failures);write(output/'summary.json',summary);print(json.dumps({'event':'restore_progress','checked':completed,'total':len(files),'failures':len(failures)}),flush=True)
 assert all(file_hash(source/p)==sha for p,sha in manifest['files'].items()),'Frozen input changed during verification'
 summary.update(status='finished',checked=completed,failures=failures,source_guard=True,all_passed=bool(files)and not failures);write(output/'summary.json',summary)
 print(json.dumps({'event':'restore_complete','checked':completed,'failures':len(failures),'all_passed':summary['all_passed']}),flush=True)
 return 0 if summary['all_passed']else 2
def history_sources(root):
 """Only prior match evidence, not card unit tests or nested frozen copies."""
 outputs=Path(root)/'outputs';files=set(outputs.glob('*/decks/*.json'))
 files.add(Path(root)/'web_ui/autoplay_decks.json')
 for directory in outputs.iterdir()if outputs.exists()else():
  if directory.is_dir()and directory.name.startswith(('environment-','mixed-deck-','long-tail-')):
   files.update(directory.glob('*/run/private/*-steps.jsonl'))
   files.update(directory.glob('optimized/*/run/private/*-steps.jsonl'))
 return sorted(p for p in files if p.is_file())
def seen_cards(value):
 result=set()
 def walk(v):
  if isinstance(v,dict):
   if isinstance(v.get('card_id'),str):result.add(v['card_id'])
   if isinstance(v.get('cards'),list):result.update(c for c in v['cards']if isinstance(c,str))
   for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 walk(value);return result
def import_history(root,path):
 path=Path(path);history=read(path)if path.exists()else{'schema':1,'files':{},'seen':[],'runs':[],'deliveries':{}}
 for file in history_sources(root):
  stat=file.stat();key=str(file.resolve());stamp=[stat.st_size,stat.st_mtime_ns]
  if history['files'].get(key,{}).get('stamp')==stamp:continue
  cards=set()
  if file.suffix=='.jsonl':
   with file.open(encoding='utf8')as stream:
    for line in stream:
     if line.strip()and line.endswith('\n'):cards.update(seen_cards(json.loads(line)))
  else:cards=seen_cards(read(file))
  history['files'][key]={'stamp':stamp,'cards':sorted(cards)}
 history['seen']=sorted(set(history.get('seen',[]))|{cid for f in history['files'].values()for cid in f['cards']})
 write(path,history);return history
def freeze(root,batch):
 from engine_performance_baseline import inventory
 root=Path(root);batch=Path(batch)
 files=inventory(root)
 extra=[*(root/'web_ui').rglob('*.py'),root/'web_ui/autoplay_decks.json',*(root/'examples').rglob('*.json')]
 files.update({p.relative_to(root).as_posix():file_hash(p)for p in extra})
 source=batch/'frozen-source';source.mkdir(exist_ok=False)
 for name in files:
  target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target)
 assert all(file_hash(root/name)==expected==file_hash(source/name)for name,expected in files.items()),'Source changed during freeze'
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
 dirty=subprocess.check_output(['git','status','--short'],cwd=root,text=True,encoding='utf8')
 write(batch/'source-manifest.json',{'head':head,'working_tree_status':dirty,'source':str(source),'files':files,'ignored_inputs_not_claimed_git_committed':True})
 return source
def worker(batch,phase):
 source=Path(batch)/'frozen-source'
 command=[sys.executable,'-B','-X','utf8',str(source/'tools/duel_audit.py'),'_worker','--batch',str(Path(batch).resolve()),'--phase',phase]
 try:
  log=Path(batch)/(phase+'-worker.log')
  with log.open('w',encoding='utf8')as stream:
   code=subprocess.run(command,cwd=source,timeout=read(Path(batch)/'config.json').get('timeout_seconds',1800),stdout=stream,stderr=subprocess.STDOUT,creationflags=0x08000000 if os.name=='nt'else 0).returncode
  print(log.read_text(encoding='utf8')[-6000:],flush=True)
  return code
 except subprocess.TimeoutExpired:
  status=read(Path(batch)/'run-status.json')if(Path(batch)/'run-status.json').exists()else{'games':[]}
  status.update(status='timeout',timeout_seconds=read(Path(batch)/'config.json').get('timeout_seconds',1800));write(Path(batch)/'run-status.json',status)
  phase=status.get('phase')or{}
  if phase.get('game'):
   folder=Path(batch)/'private'/phase['game'];inflight=folder/'inflight-command.json'
   if inflight.exists():
    row=read(inflight);row.update(accepted=None,failure='worker_timeout',exception_tail='Worker deadline exceeded; operation completion unknown',timeout_stage=phase.get('stage'))
    # A killed command is neither a successful slow sample nor a measured submit.
    with(folder/'steps.jsonl').open('a',encoding='utf8')as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
  return 124
def analyze(batch,partial=False):
 batch=Path(batch).resolve();config=read(batch/'config.json');identity=read(batch/'identity.json');plan=read(batch/'plan.json')
 progress=read(batch/'run-status.json')if(batch/'run-status.json').exists()else{'games':[],'status':'not_started'}
 if not partial:assert progress['status']=='finished','Use --partial while a run is active'
 rows=[]
 for path in sorted((batch/'private').glob('*/steps.jsonl')):
  with path.open(encoding='utf8')as stream:
   for line in stream:
    if line.endswith('\n'):rows.append(json.loads(line))
 slow=[r for r in rows if r.get('accepted')and(r['timings'].get('submit_ms',0)>config['slow_ms']or r['timings'].get('query_ms',0)>config['query_slow_ms'])]
 function=[r for r in rows if r.get('failure')or any(c['status']=='needs_review'for c in r.get('checks',[]))]
 counts=Counter(r.get('card_id')for r in rows if r.get('accepted')and r['action']['type']=='play_card')
 coverage=[{'card_id':c['id'],'name':c['name'],'plays':counts[c['id']],'verdict':'exercised_partial'if counts[c['id']]else'not_exercised'}for d in plan['decks'].values()for c in d['rows']]
 issues={'functionality':function,'performance':slow};handoffs={}
 fixture_dir=batch/'fixtures';fixture_dir.mkdir(exist_ok=True)
 for row in{r['id']:r for r in function+slow}.values():
  fixture={'source':identity['source'],'decks':str(batch/'plans'/(row['pair']+'.json')),'actor':row['actor'],'action':row['action'],'command':row.get('command'),'accepted':row.get('accepted'),'before':(row.get('before_snapshot')or{}).get('path'),'after':(row.get('after_snapshot')or{}).get('path'),'setup':row.get('setup'),'scene':{k:row.get(k)for k in('id','pair','game_id','step','card_id','card_name','failure','timings')},'exception':row.get('exception')}
  write(fixture_dir/(row['id']+'.json'),fixture)
 history=read(config['history']);delivered=history.get('deliveries',{})
 for kind,items in issues.items():
  groups=defaultdict(list)
  for row in items:
   signature={'engine':identity['engine_sha256'],'target':identity['target'],'kind':kind,'card_id':row.get('card_id'),'action':row['action']['type'],'failure':row.get('failure'),'cause':row.get('exception_tail')}
   groups[digest(signature)].append(row)
  packets=[]
  for key,items in groups.items():
   worst=sorted(items,key=lambda r:r['timings'].get('submit_ms',0)+r['timings'].get('query_ms',0),reverse=True)[:3]
   packets.append({'fingerprint':key,'previously_delivered':key in delivered,'occurrences':len(items),'examples':[{k:r.get(k)for k in('id','card_id','card_name','action','failure','exception_tail','timings','checks')}for r in worst],'fixtures':[str(fixture_dir/(r['id']+'.json'))for r in worst]})
  pending=[p for p in packets if not p['previously_delivered']]
  thread=config['function_thread']if kind=='functionality'else config['performance_thread']
  prompt=f"用户已要求发现{kind}问题直接转交对应会话修改。本轮工具化新卡测试：{batch}，引擎{identity['core']}，commit {identity['head']}，目标{identity['target']}。请查看 report.md、analysis.json、handoff/{kind}.json 与逐项fixture，实际复现、定位并修复，保留现有性能优化和规则/支付/回滚/恢复/回放/RNG及玩家信息边界。只读失败快照不改版本头，不裁池/白板化。性能只统计成功结算，普通日志不含Profiler；效果检查仅为已触发描述片段，needs_review尚需核实。新问题组数{len(pending)}。原始样本保留，修复后提供版本及相关测试收据。"
  data={'kind':kind,'destination':thread,'pending':pending,'all_groups':packets,'delivery_confirmed':bool(packets)and not pending,'connector_args':{'threadId':thread,'prompt':prompt}}
  write(batch/'handoff'/(kind+'.json'),data);handoffs[kind]={'pending_groups':len(pending),'path':str(batch/'handoff'/(kind+'.json'))}
 summary={'pipeline_complete':progress['status']=='finished','identity':identity,'games':progress['games'],'actions':len(rows),'accepted':sum(r.get('accepted')is True for r in rows),'failures':len(function),'all_games_completed':bool(progress['games'])and all(g['status']=='completed'for g in progress['games']),'timing':{k:stats([r['timings'][k]for r in rows if r.get('accepted')and k in r['timings']])for k in('query_ms','query_cpu_ms','submit_ms','submit_cpu_ms','snapshot_ms')},'slow_threshold_ms':config['slow_ms'],'slow_actions':len(slow),'slow_rows':[{k:r.get(k)for k in('id','card_id','card_name','action','timings')}for r in slow],'description_components':dict(Counter(c['status']for r in rows for c in r.get('checks',[]))),'coverage':coverage,'handoffs':handoffs,'limits':['Executed/component-observed is not full card or official CN rule certification.','Natural evolving caches; no comparison of different scenes as before/after. Query/submit excludes snapshots/logs.','CLI generates handoffs; only a successful connector send followed by ack marks delivery.']}
 if not partial:
  manifest=read(batch/'source-manifest.json');assert all(file_hash(Path(identity['source'])/p)==expected for p,expected in manifest['files'].items())
  summary['source_guard']=True
  history['seen']=sorted(set(history['seen'])|seen_cards(rows)|{c['card_id']for c in coverage})
  if str(batch)not in history['runs']:history['runs'].append(str(batch))
  write(config['history'],history)
 write(batch/'analysis.json',summary)
 lines=['# 双方自动出牌审计','',f"引擎 {identity['core']} / {identity['target']}，commit {identity['head']}。本批{len(progress['games'])}局、{len(rows)}操作，{summary['accepted']}接受。",'',f"正常结束{sum(g['status']=='completed'for g in progress['games'])}局；功能/资源/描述待复核行{len(function)}；成功操作超过阈值{len(slow)}次。",'', '|阶段|P50|P95|最大|','|---|---:|---:|---:|']
 for key,s in summary['timing'].items():
  if s:lines.append(f"|{key}|{s['median_ms']:.3f}|{s['p95_ms']:.3f}|{s['max_ms']:.3f}|")
 lines+=['',f"根卡打出{sum(c['plays']>0 for c in coverage)}/{len(coverage)}种。描述片段：{summary['description_components']}。未触发和无断言的效果不认定整卡正确。",'', '## 待交接','']
 for kind,data in handoffs.items():lines.append(f"- {kind}：{data['pending_groups']}个新组，[交接数据](handoff/{kind}.json)。CLI尚未发送消息。")
 lines+=['','## 慢操作','', '|操作|卡牌|query ms|submit ms|','|---|---|---:|---:|']
 for r in sorted(slow,key=lambda x:x['timings'].get('submit_ms',0),reverse=True):lines.append(f"|{r['id']}|{r.get('card_name')or r['action']['type']}|{r['timings'].get('query_ms',0):.3f}|{r['timings'].get('submit_ms',0):.3f}|")
 lines+=['','## 功能/资源待核实','']
 for r in function:lines.append(f"- {r['id']} {r.get('card_name')or r['action']['type']}：{r.get('failure')or r.get('checks')}；{r.get('exception_tail','')}。")
 lines+=['','每步command/返回/策略RNG、完整状态与引擎RNG在private，复现输入在fixtures，原生replay按局保存。私有文件不提供HTTP。','',*summary['limits']]
 (batch/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
 print(json.dumps({'event':'analysis_ready','batch':str(batch),'actions':len(rows),'slow':len(slow),'function':len(function),'handoffs':handoffs},ensure_ascii=False),flush=True)
 return summary

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('audit','plan','run','analyze','reproduce','restore-check','handoff','ack','_worker','_restore-worker'));p.add_argument('--batch',type=Path,required=True)
 p.add_argument('--classes',nargs='+',default=['mage','hunter','priest','rogue','shaman','warlock']);p.add_argument('--decks',type=Path);p.add_argument('--seeds',nargs='+',type=int,default=[17,23]);p.add_argument('--seed',type=int,default=17);p.add_argument('--history',type=Path,default=ROOT/'outputs/duel-audit-history.json');p.add_argument('--max-steps',type=int,default=600);p.add_argument('--max-turns',type=int,default=80);p.add_argument('--slow-ms',type=float,default=500);p.add_argument('--query-slow-ms',type=float,default=500);p.add_argument('--cpu-mask',type=int,default=4);p.add_argument('--kind',choices=('functionality','performance'));p.add_argument('--phase',choices=('plan','run'));p.add_argument('--fixture',type=Path);p.add_argument('--output',type=Path);p.add_argument('--partial',action='store_true');p.add_argument('--function-thread',default=FUNCTION_THREAD);p.add_argument('--performance-thread',default=PERFORMANCE_THREAD)
 p.add_argument('--receipt',type=Path);p.add_argument('--timeout-seconds',type=int,default=1800)
 a=p.parse_args();batch=a.batch.resolve()
 if a.command=='_restore-worker':return restore_worker(batch,a.output.resolve())
 if a.command=='_worker':
  set_affinity(read(batch/'config.json')['cpu_mask'])
  from duel_audit_runtime import plan,run
  return(plan if a.phase=='plan'else run)(batch)
 if a.command in('audit','plan'):
  if batch.exists():p.error('Use a new batch directory; evidence is never overwritten')
  if len(a.classes)%2 or len(set(a.classes))!=len(a.classes):p.error('Provide an even number of distinct classes')
  if not a.seeds or len(set(a.seeds))!=len(a.seeds)or min(a.max_steps,a.max_turns,a.timeout_seconds,a.cpu_mask,a.slow_ms,a.query_slow_ms)<=0:p.error('Unique seeds and positive budgets, CPU mask, thresholds are required')
  history=import_history(ROOT,a.history.resolve());batch.mkdir(parents=True)
  config={k:v for k,v in vars(a).items()if k not in('batch','history','fixture','output','decks','receipt')};config.update(history=str(a.history.resolve()),novelty_scope='Previous match decks and observed match entity/card IDs; excludes alias IDs and same printed names, not unit-test history.')
  if a.decks:write(batch/'deck-input.json',read(a.decks))
  write(batch/'config.json',config);write(batch/'history-input.json',{'seen':history['seen'],'imported_files':len(history['files'])})
  freeze(ROOT,batch);assert worker(batch,'plan')==0
  if a.command=='plan':return 0
 if a.command in('audit','run'):
  assert not(batch/'run-status.json').exists(),'Use a fresh run, not an overwritten trajectory'
  code=worker(batch,'run')
  if code==124:analyze(batch,True);return 2
  assert code==0
  result=analyze(batch);return 0 if result['all_games_completed']and not result['failures']else 2
 if a.command=='analyze':analyze(batch,a.partial);return 0
 if a.command=='restore-check':
  assert a.output and not a.output.exists(),'Use a new verification output directory'
  command=[sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'_restore-worker','--batch',str(batch),'--output',str(a.output.resolve())]
  a.output.parent.mkdir(parents=True,exist_ok=True);log=a.output.with_suffix('.log');assert not log.exists()
  with log.open('w',encoding='utf8')as stream:code=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT).returncode
  print(log.read_text(encoding='utf8')[-6000:],flush=True);return code
 if a.command=='handoff':
  assert a.kind;data=read(batch/'handoff'/(a.kind+'.json'));print(json.dumps(data['connector_args']if data['pending']else{'pending':False},ensure_ascii=False));return 0
 if a.command=='ack':
  assert a.kind and a.receipt;config=read(batch/'config.json');history=read(config['history']);data=read(batch/'handoff'/(a.kind+'.json'));receipt=read(a.receipt)
  assert receipt.get('confirmed')is True and receipt.get('thread_id')==data['destination'],'Actual connector success receipt required'
  for issue in data['pending']:history['deliveries'][issue['fingerprint']]={'batch':str(batch),'kind':a.kind,'destination':data['destination'],'receipt':str(a.receipt.resolve()),'receipt_sha256':file_hash(a.receipt)}
  data['delivery_confirmed']=True;data['pending']=[];write(batch/'handoff'/(a.kind+'.json'),data);write(config['history'],history);return 0
 if a.command=='reproduce':
  assert a.fixture and a.output and not a.output.exists()
  command=[sys.executable,'-B','-X','utf8',str(Path(read(batch/'identity.json')['source'])/'tools/duel_audit_runtime.py'),'--reproduce',str(a.fixture.resolve()),'--output',str(a.output.resolve())]
  return subprocess.run(command).returncode
if __name__=='__main__':sys.exit(main())
