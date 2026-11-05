"""Frozen-source worker for duel_audit. Host audit only, no engine patches."""
from pathlib import Path
from collections import Counter
import argparse,gzip,json,random,re,sys,time,traceback,weakref
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from duel_audit import read,write,digest,file_hash,validate_pairs
from web_ui.autoplay import Controller,timed,flatten
from web_ui.autoplay_checks import facts,compact_events
from web_ui.bot import choose_action
from web_ui.server import plain_card_text
from hs_sim.engine import Game,CardClass,DeckSpec
from hs_sim.engine.model import Runes
from hs_sim.engine.sideboards import SideboardSpec,ContrabandSideboardProfile,DeckCopySideboardProfile
from hs_sim.engine.construction import validate_deck
from hs_sim.engine.modular_decks import construction_identity
from hs_sim.engine.replay import build_replay
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.player_api import _decode
HEROS={'warrior':'01','shaman':'02','rogue':'03','paladin':'04','hunter':'05','druid':'06','warlock':'07','mage':'08','priest':'09','demon_hunter':'10','death_knight':'11'}
THEMES={'mage':'法术|冻结|法术伤害|奥秘','hunter':'野兽|奥秘|亡语','priest':'治疗|恢复|生命|亡语','rogue':'连击|回手|返回|发现','shaman':'过载|图腾|法术伤害|元素','warlock':'恶魔|弃|抽|消灭','warrior':'护甲|武器|受伤','paladin':'圣盾|增益|白银','druid':'抉择|法力|野兽','demon_hunter':'流放|攻击|突袭'}
NUMBERS={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
KEYWORDS={'嘲讽':'taunt','圣盾':'divine_shield','冲锋':'charge','突袭':'rush','风怒':'windfury','剧毒':'poisonous','吸血':'lifesteal','复生':'reborn'}
def catalog(batch,phase,deck=None):return Controller(batch/('catalog-'+phase),deck or ROOT/'web_ui/autoplay_decks.json',seeds=[17],max_steps=0)
def spec(d):return DeckSpec(d['hero_card_id'],d['hero_power_card_id'],CardClass(d['card_class']),tuple(d['cards']),None if not d.get('runes')else Runes(**d['runes']),tuple(SideboardSpec(b['source_card_id'],tuple(b['cards']))for b in d.get('sideboards',[])))

def automatic_exclusions(registry):
 """Construction limitations of the singleton planner, never generation filters."""
 result={cid:'requires_explicit_sideboard'for cid,p in registry.sideboards.items()if type(p)in(ContrabandSideboardProfile,DeckCopySideboardProfile)}
 result.update({cid:'requires_complete_fabled_bundle'for cid in registry.fabled})
 result.update({cid:'requires_explicit_deck_size'for cid in registry.deck_size_rules})
 return result
def profiles(row):
 """Only unambiguous printed fragments. Uncovered text stays unverified."""
 text=row['text'].strip();result=[]
 for pattern,kind in[(r'^(?:战吼[：:]\s*)?抽([一二两三四五六七八九十\d]+)张牌。?$','draw_min'),(r'^(?:战吼[：:]\s*)?获得(\d+)点护甲值。?$','armor_min')]:
  m=re.fullmatch(pattern,text)
  if m:
   value=m[1];result.append({'type':kind,'amount':int(value)if value.isdigit()else NUMBERS[value]})
 if row['kind']=='minion':
  for word,keyword in KEYWORDS.items():
   if re.match('^'+word+r'(?:[，。 、\n]|$)',text):result.append({'type':'intrinsic_keyword','keyword':keyword})
 return result

def validate_checks(checks,registry):
 if not isinstance(checks,dict):raise ValueError('checks must map known card IDs to explicit clauses')
 for cid,clauses in checks.items():
  if cid not in registry.cards or type(clauses)is not list:raise ValueError('Unknown check card or invalid clause list: '+cid)
  for clause in clauses:
   kind=clause.get('type')if isinstance(clause,dict)else None
   if kind in('draw_min','armor_min'):
    if type(clause.get('amount'))is not int or clause['amount']<1:raise ValueError('Check amount must be a positive integer')
   elif kind=='intrinsic_keyword':
    if clause.get('keyword')not in KEYWORDS.values():raise ValueError('Unknown check keyword')
   else:raise ValueError('Unknown check type: '+str(kind))
def plan(batch):
 config=read(batch/'config.json');c=catalog(batch,'plan');history=set(read(batch/'history-input.json')['seen'])
 seen_names={c.registry.card(cid).name for cid in history if cid in c.registry.cards};seen_ids={cid.removeprefix('CORE_')for cid in history}
 candidates=[]
 for cid in sorted(c.fmt.root_card_ids):
  if cid not in c.registry.cards:continue
  card=c.registry.card(cid);meta=card.metadata
  if not meta or card.kind.value not in('minion','spell','weapon','location','hero'):continue
  raw=c.records.get(cid,({},''))[0]
  eligible=construction_identity(c.registry,cid)in c.fmt.policy.allowed_card_ids and cid not in c.fmt.policy.banned_card_ids and construction_identity(c.registry,cid)not in c.fmt.policy.banned_card_ids and meta.collectible and card.hand_playable
  candidates.append({'id':cid,'name':card.name,'classes':[x.value for x in meta.classes],'kind':card.kind.value,'cost':card.cost,'text':plain_card_text(raw.get('text','')),'construction_eligible':eligible,'new':cid.removeprefix('CORE_')not in seen_ids and card.name not in seen_names})
 write(batch/'catalog.json',candidates)
 decks={};pairs=[];checks={};taken=set();names=set();rng=random.Random(config['seed']);exclusions=automatic_exclusions(c.registry);allow_shared_cards=False
 if(batch/'deck-input.json').exists():
  doc=read(batch/'deck-input.json');decks=doc['decks'];pairs=doc.get('pairs')or[list(decks)[i:i+2]for i in range(0,len(decks),2)];checks=doc.get('checks',{})
  allow_shared_cards=doc.get('allow_shared_cards',False)
  for key,d in decks.items():
   d.setdefault('label',key);d.setdefault('rows',[{'id':cid,'name':c.registry.card(cid).name,'cost':c.registry.card(cid).cost,'text':plain_card_text(c.records.get(cid,({},''))[0].get('text','')),'count':n}for cid,n in Counter(d['cards']).items()])
 else:
  for klass in config['classes']:
   if klass not in HEROS or klass=='death_knight':raise ValueError('Autoplan class unsupported; DK can use --decks with explicit runes: '+klass)
   pool=[dict(row,rank=rng.random()+.35*bool(re.search(THEMES.get(klass,'^$'),row['text'])))for row in candidates if row['new']and row['construction_eligible']and klass in row['classes']and row['id']not in taken and row['name']not in names and row['id']not in exclusions]
   chosen=[]
   for low,high in[(0,2)]*8+[(3,5)]*14+[(6,10)]*8:
    options=[r for r in pool if r['id']not in taken and r['name']not in names]
    if not options:raise ValueError('Not enough unused implemented root cards for '+klass)
    def score(row):
     distance=max(low-row['cost'],row['cost']-high,0);count=sum(r['kind']==row['kind']for r in chosen)
     return row['rank']-distance*2-count*.09
    row=max(options,key=score);chosen.append(row);taken.add(row['id']);names.add(row['name']);checks[row['id']]=profiles(row)
   hero='HERO_'+HEROS[klass];decks[klass]={'label':klass+' · 新卡机制测试','card_class':klass,'hero_card_id':hero,'hero_power_card_id':hero+'bp','cards':[r['id']for r in chosen],'runes':None,'rows':[{**{k:r[k]for k in('id','name','kind','cost','text')},'count':1}for r in chosen]}
  pairs=[config['classes'][i:i+2]for i in range(0,len(config['classes']),2)]
 validate_checks(checks,c.registry)
 for d in decks.values():validate_deck(spec(d),c.registry,c.fmt.policy).require_valid()
 validate_pairs(decks,pairs,allow_shared_cards)
 for i,pair in enumerate(pairs):
  write(batch/'plans'/f'pair-{i+1}.json',{'decks':{k:decks[k]for k in pair},'fixed_seed_pairs':config['seeds'],'target':c.fmt.target_id})
 manifest=read(batch/'source-manifest.json');engine={p:d for p,d in manifest['files'].items()if p.startswith('hs_sim/')and p.endswith('.py')}
 identity={'head':manifest['head'],'source':str(ROOT),'core':CORE_EFFECTS_VERSION,'schema':SNAPSHOT_SCHEMA_VERSION,'target':c.fmt.target_id,'engine_sha256':digest(engine),'engine_files':len(engine),'frozen_files':len(manifest['files'])}
 write(batch/'identity.json',identity);write(batch/'plan.json',{'decks':decks,'pairs':pairs,'checks':checks,'allow_shared_cards':allow_shared_cards,'automatic_construction_exclusions':exclusions,'novelty_scope':config['novelty_scope'],'only_unused':not(batch/'deck-input.json').exists(),'native_construction_valid':True,'root_types':len({cid for d in decks.values()for cid in d['cards']})})
 print(json.dumps({'event':'plan_ready','pairs':len(pairs),'decks':len(decks),'new_root_types':len(taken),'profiles':sum(bool(x)for x in checks.values()),'identity':identity},ensure_ascii=False),flush=True);return 0
def snapshot(folder,name,game):
 path=folder/(name+'.json.gz');raw=json.dumps(game.snapshot(),ensure_ascii=False,separators=(',',':')).encode()
 with gzip.open(path,'wb',compresslevel=1)as stream:stream.write(raw)
 import hashlib
 return{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
def check_components(clauses,source,actor,before,after,events):
 result=[]
 for clause in clauses:
  status='not_exercised';evidence={};kind=clause['type'];amount=clause.get('amount')
  if after.get('pending')or any(e['kind']in('spell_countered','minion_countered')for e in events):evidence={'deferred_or_countered':True}
  elif kind=='draw_min':
   expected=min(amount,len(before['players'][str(actor)]['deck']));observed=sum(e['kind']in('card_drawn','card_burned')and e['player_id']==actor for e in events);evidence={'minimum':expected,'draw_or_burn':observed};status=('pass'if observed>=expected else'needs_review')if expected else'not_exercised'
  elif kind=='armor_min':
   observed=sum(e['amount']for e in events if e['kind']=='armor_gained'and e['player_id']==actor);evidence={'minimum':amount,'armor_gained':observed};status='pass'if observed>=amount else'needs_review'
  elif kind=='intrinsic_keyword':
   entity=after['entities'].get(str(source));lost=any(e['kind']=='shield_lost'and(e['target_id']==source or e['source_id']==source)for e in events)
   if entity and entity['zone']=='board'and not entity['silenced']and not entity['dormant']and not lost:
    evidence={'expected':clause['keyword'],'keywords':entity['keywords']};status='pass'if clause['keyword']in entity['keywords']else'needs_review'
  result.append({'clause':clause,'status':status,'evidence':evidence,'scope':'observed_fragment_only'})
 return result
def detached_facts(game):return json.loads(json.dumps(facts(game),ensure_ascii=False))
def set_affinity(mask):
 if sys.platform=='win32':
  import ctypes
  k=ctypes.WinDLL('kernel32');k.GetCurrentProcess.restype=ctypes.c_void_p;k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];assert k.SetProcessAffinityMask(k.GetCurrentProcess(),mask)
def run(batch):
 config=read(batch/'config.json');set_affinity(config['cpu_mask']);plan=read(batch/'plan.json');c=catalog(batch,'run',batch/'plans/pair-1.json')
 identity=read(batch/'identity.json');assert identity['core']==CORE_EFFECTS_VERSION and identity['target']==c.fmt.target_id
 state={'status':'running','games':[],'actions':0};write(batch/'run-status.json',state)
 for pair_index,pair in enumerate(plan['pairs'],1):
  for seed_index,seed in enumerate(config['seeds'],1):
   for env,order in(('A',pair),('B',pair[::-1])):
    gid=f'{env}-{seed_index}';game_key=f'pair-{pair_index}-{gid}';folder=batch/'private'/game_key;folder.mkdir(parents=True,exist_ok=False)
    entry={'id':game_key,'pair':f'pair-{pair_index}','seed':seed,'order':order,'status':'running','steps':0};state['games'].append(entry)
    try:game=Game.from_decks(c.fmt.match_setup(tuple(spec(plan['decks'][k])for k in order),seed=seed,first_player=1),c.registry,mode='release')
    except Exception:
     trace=traceback.format_exc();path=folder/'setup-exception.txt';path.write_text(trace,encoding='utf8')
     row={'id':game_key+'-setup','pair':entry['pair'],'game_id':gid,'step':0,'actor':1,'action':{'type':'setup'},'accepted':None,'timings':{},'failure':'setup_error','exception':str(path),'exception_tail':trace.splitlines()[-1],'setup':{'seed':seed,'order':order}}
     (folder/'steps.jsonl').write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf8');entry['status']='setup_error';entry['steps']=1;state['actions']+=1;write(batch/'run-status.json',state);continue
    original=type(game).apply;reference=weakref.ref(game);raw_exception={}
    def capture(action,*args,**kwargs):
     try:return original(reference(),action,*args,**kwargs)
     except Exception:
      raw_exception['text']=traceback.format_exc();raise
    game.apply=capture;rngs={p:random.Random(seed*7+p)for p in(1,2)};counts=Counter();window=None;previous=None
    try:previous=snapshot(folder,'initial',game)
    except Exception:
     trace=traceback.format_exc();path=folder/'setup-exception.txt';path.write_text(trace,encoding='utf8');entry['status']='setup_error'
     row={'id':game_key+'-setup-snapshot','pair':entry['pair'],'game_id':gid,'step':0,'actor':1,'action':{'type':'setup'},'accepted':None,'timings':{},'failure':'setup_snapshot_error','exception':str(path),'exception_tail':trace.splitlines()[-1],'setup':{'seed':seed,'order':order}}
     (folder/'steps.jsonl').write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf8');entry['steps']=1;state['actions']+=1;write(batch/'run-status.json',state);continue
    for step in range(config['max_steps']):
     if game._state.status!='playing':entry.update(status='completed',winner=game._state.winner);break
     if game._state.turn>config['max_turns']:entry['status']='turn_limit';break
     actor=game._state.pending_choice.player_id if game._state.pending_choice else game._state.active_player
     row={'id':f'{game_key}-step{step:04d}','pair':entry['pair'],'game_id':gid,'step':step,'actor':actor,'turn':game._state.turn,'card_id':None,'card_name':None,'action':{'type':'legal_actions'},'accepted':None,'timings':{},'before_snapshot':previous,'after_snapshot':None,'checks':[]}
     stage='query';raw_exception.clear();state['phase']={'game':game_key,'step':step,'stage':stage};write(folder/'inflight-command.json',row);write(batch/'run-status.json',state)
     try:
      before=detached_facts(game);cursor=len(game._events)
      view,wall,cpu=timed(lambda:game.for_player(actor).legal_actions());row['timings'].update(query_ms=wall,query_cpu_ms=cpu)
      if view.get('error')and not(view['error']=='enumeration_limit'and view['observation']['pending_choice']):raise ValueError('Legal query: '+view['error'])
      if window!=(game._state.turn,actor):counts.clear();window=(game._state.turn,actor)
      rng_before=rngs[actor].getstate();action=choose_action(view,rngs[actor],force_end=counts['ordinary']>=24);row.update(action=action,command={'revision':view['revision'],'action':action},policy_rng_before=rng_before,policy_rng_after=rngs[actor].getstate())
      source_ref=next((action[k]for k in('card','attacker','power','location','minion','starship','object')if action.get(k)),None);face=flatten(view['observation']).get(source_ref,{})
      if not face and view['observation'].get('pending_choice'):face=view['observation']['pending_choice'].get('source')or{}
      cid=face.get('card_id');row.update(card_id=cid,card_name=c.registry.card(cid).name if cid else None)
      native=_decode(game,actor,action,view['observation']);source_id=next((getattr(native,k)for k in('entity_id','attacker_id','hero_power_id','source_id')if getattr(native,k,None)is not None),None)
      write(folder/'inflight-command.json',row);stage='submit';state['phase']['stage']=stage;write(batch/'run-status.json',state)
      reply,wall,cpu=timed(lambda:game.for_player(actor).submit(row['command']));row['timings'].update(submit_ms=wall,submit_cpu_ms=cpu);row.update(accepted=reply['accepted'],error=reply['error'],reply=reply)
      after=detached_facts(game);events=compact_events(game._events[cursor:]);row.update(before=before,after=after,events=events)
      if not reply['accepted']:row['failure']='rejected_enumerated_action'
      if raw_exception:
       (folder/(f'{step:04d}-release-exception.txt')).write_text(raw_exception['text'],encoding='utf8');row.update(exception=str(folder/f'{step:04d}-release-exception.txt'),exception_tail=raw_exception['text'].splitlines()[-1])
      stage='snapshot';ref,wall,_=timed(lambda:snapshot(folder,f'{step:04d}-after',game));row['after_snapshot']=ref;row['timings']['snapshot_ms']=wall;previous=ref
      stage='component_audit'
      if reply['accepted']and action['type']=='play_card':row['checks']=check_components(plan['checks'].get(cid,[]),source_id,actor,before,after,events)
      counts['choices'if action['type']=='select_choice'else'ordinary']+=1
     except Exception:
      trace=traceback.format_exc();path=folder/f'{step:04d}-{stage}-exception.txt';path.write_text(trace,encoding='utf8');row.update(failure=stage+'_error',exception=str(path),exception_tail=trace.splitlines()[-1])
     with(folder/'steps.jsonl').open('a',encoding='utf8')as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
     entry['steps']=step+1;state['actions']+=1
     if row.get('failure'):
      entry['status']='error';print(json.dumps({'event':'issue','id':row['id'],'failure':row['failure'],'card':row['card_name']},ensure_ascii=False),flush=True);break
     if counts['choices']>64:entry['status']='choice_limit';break
    else:entry['status']='step_limit'
    if entry['status']=='running':entry['status']='completed'if game._state.status!='playing'else'stopped'
    try:write(folder/'final-replay.json',build_replay(game))
    except Exception:(folder/'replay-exception.txt').write_text(traceback.format_exc(),encoding='utf8')
    write(batch/'run-status.json',state);print(json.dumps({'event':'game_complete',**entry},ensure_ascii=False),flush=True)
 state['status']='finished';state['phase']=None;write(batch/'run-status.json',state);return 0
def reproduce(fixture,output):
 f=read(fixture);output.mkdir(parents=True,exist_ok=False);assert not f.get('source')or Path(f['source']).resolve()==ROOT,'Fixture belongs to another frozen source';c=catalog(output,'reproduce',Path(f['decks']));result={'source':str(ROOT),'core':CORE_EFFECTS_VERSION,'profiled':False};g=None;stage='restore'
 try:
  if f.get('before'):
   before=json.loads(gzip.decompress(Path(f['before']).read_bytes()));g=Game.from_snapshot(before,c.registry,mode='release');assert g.snapshot()==before
  else:
   stage='setup';setup=f['setup'];decks=read(f['decks'])['decks'];g=Game.from_decks(c.fmt.match_setup(tuple(spec(decks[k])for k in setup['order']),seed=setup['seed'],first_player=1),c.registry,mode='release')
  if f['action']['type']=='setup':snapshot(output,'actual-setup',g);result.update(setup_accepted=True)
  else:
   stage='query';view,q,cpu=timed(lambda:g.for_player(f['actor']).legal_actions());result.update(query_ms=q,query_cpu_ms=cpu)
   if f['action']['type']=='legal_actions':result.update(query_error=view.get('error'))
   else:
    stage='submit';reply,t,cpu=timed(lambda:g.for_player(f['actor']).submit({'revision':view['revision'],'action':f['action']}));result.update(submit_ms=t,submit_cpu_ms=cpu,accepted=reply['accepted'],error=reply['error'])
   stage='snapshot';snap=g.snapshot();expected=json.loads(gzip.decompress(Path(f['after']).read_bytes()))if f.get('after')else None
   result['full_after_match']=snap==expected if expected else None;snapshot(output,'actual-after',g)
   if expected is not None:assert snap==expected,'Full reproduced after differs'
 except Exception:
  trace=traceback.format_exc();(output/'exception.txt').write_text(trace,encoding='utf8');result.update(failure=stage+'_error',exception_tail=trace.splitlines()[-1])
 write(output/'result.json',result);print(json.dumps(result),flush=True)
 return 2 if result.get('failure')else 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--reproduce',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();sys.exit(reproduce(a.reproduce,a.output))
