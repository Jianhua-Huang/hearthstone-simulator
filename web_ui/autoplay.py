"""Two deterministic, player-projected bots plus an independent host audit.

No simulator patches. Runs are serial so the two environments do not compete
for CPU. Private replays/facts remain on disk; browser messages are projections.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import random
import threading
import time
import traceback

from hs_sim.engine import CardClass, DeckSpec, Game
from hs_sim.engine.player_api import _decode
from hs_sim.engine.replay import build_replay
from hs_sim.local_pool_format import build_cn37_local_pool_format
from . import server as ui
from .autoplay_checks import facts, compact_events, evaluate
from .bot import actor_for, choose_action

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    # Windows readers/virus scanners can briefly deny replacement of an open
    # report. A transient logging lock must not abort the simulated match.
    for attempt in range(20):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.005*(attempt+1))


def timed(fn):
    start, cpu = time.perf_counter(), time.thread_time()
    result = fn()
    return result, round((time.perf_counter()-start)*1000, 3), round((time.thread_time()-cpu)*1000, 3)


def flatten(observation):
    return {c['ref']: c for p in observation['players'] for c in
            [p['hero'], p.get('hero_power'), p.get('weapon'), *p['board'], *p['hand'],
             *p.get('additional_hero_powers', []), *p.get('pending_plays', [])] if c}


class Controller:
    def __init__(self, output, decks, *, seeds=None, max_turns=80, max_steps=600):
        self.output = Path(output); self.output.mkdir(parents=True, exist_ok=True)
        self.private = self.output/'private'; self.private.mkdir(exist_ok=True)
        self.deck_document = json.loads(Path(decks).read_text(encoding='utf-8'))
        self.fmt = build_cn37_local_pool_format()
        # Exactly the two historical demo aliases, bound to the complete current
        # minion inventory. No candidates removed or replaced with a sample.
        from dataclasses import replace
        original = self.fmt.registry.pool('constructed.minions', self.fmt.context)
        for pool_id in ('representative.attack-cost-minions', 'representative.legendary-dragons'):
            self.fmt.registry.register_pool(replace(original, id=pool_id,
                version='ui-standard-match-full-minions-v1:'+original.version))
        self.fmt.registry.validate()
        self.registry = self.fmt.registry
        self.records = dict(ui.printed_metadata()[1])
        def visit(v):
            if isinstance(v, dict):
                cid = v.get('id')
                if isinstance(cid, str) and cid in self.registry.cards and 'text' in v and 'name' in v and self.registry.card(cid).name == v['name']:
                    self.records[cid] = (v, '')
                for child in v.values(): visit(child)
            elif isinstance(v, list):
                for child in v: visit(child)
        for path in sorted((ROOT/'data/cards').glob('*.json')):
            visit(json.loads(path.read_text(encoding='utf-8')))
        self.lab_records=self.records
        self.catalog_cache=ui.Host.catalog(self)
        self.specs = {k: DeckSpec(d['hero_card_id'], d['hero_power_card_id'],
            CardClass(d['card_class']), tuple(d['cards'])) for k,d in self.deck_document['decks'].items()}
        self.seeds = seeds or self.deck_document['fixed_seed_pairs']
        self.max_turns, self.max_steps = max_turns, max_steps
        self.lock = threading.Lock(); self.pause = threading.Event(); self.pause.set()
        self.thread = None; self.rows = []; self.games = []; self.anomalies = []
        self.evidence_counts = Counter()
        self.views = {}; self.phase = {'state': 'ready', 'stage': None}
        self.coverage = Counter(); self.status = 'ready'
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.root_ids = {r['id'] for d in self.deck_document['decks'].values() for r in d['rows']}
        self.report = self.make_report()
        write_json(self.output/'source-loaded.json', {'root':str(ROOT), 'target':self.fmt.target_id,
            'mode':'release', 'engine_files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT/'hs_sim').rglob('*.py')}})

    def start(self):
        if self.thread is None:
            self.pause.clear(); self.status = 'running'
            self.thread = threading.Thread(target=self.run, daemon=True); self.thread.start()
        elif self.status not in ('finished', 'error'):
            self.pause.clear(); self.status = 'running'

    def pause_run(self):
        if self.status == 'running': self.pause.set(); self.status = 'pausing'

    def projected(self, game, viewer):
        port = game.for_player(viewer); result = port.observe()
        result['actions'] = []; result['error'] = None; result['events'] = port.events()[-15:]
        ids = set()
        def visit(v):
            if isinstance(v,dict):
                if isinstance(v.get('card_id'),str): ids.add(v['card_id'])
                for child in v.values(): visit(child)
            elif isinstance(v,list):
                for child in v: visit(child)
        visit(result)
        result.update(names={i:self.registry.card(i).name for i in ids},
            card_texts={i:ui.plain_card_text(self.records.get(i,({},''))[0].get('text','')) for i in ids},
            card_art={i:i+'.webp' for i in ids if (ui.STATIC/'assets'/(i+'.webp')).is_file()},
            seat=viewer, test_controls={'mana_enabled':False,'hand_enabled':False},
            opponent={'mode':'human','seat':3-viewer,'can_step':False,'error':None})
        return result

    def update_views(self, env, game):
        views = {str(p):self.projected(game,p) for p in (1,2)}
        with self.lock: self.views[env] = views

    def make_report(self):
        values = [r['timings']['submit_ms'] for r in self.rows if r['accepted']]
        ordered = sorted(values)
        percentile = lambda q: ordered[min(len(ordered)-1,int((len(ordered)-1)*q))] if ordered else None
        checks = Counter(c['status'] for r in self.rows for c in r.get('effect_checks',()))
        per_card = {cid:Counter(c['status'] for r in self.rows for c in r.get('effect_checks',()) if c.get('card_id')==cid) for cid in self.root_ids}
        plays = Counter(r.get('card_id') for r in self.rows if r['action']['type']=='play_card' and r['accepted'])
        public_findings=[]
        for finding in self.anomalies[-30:]:
            item={k:deepcopy(finding[k]) for k in ('id','reason','game_id','step','action_type','timings','accepted','error')}
            item['card_id']=finding['card_id'] if finding['card_id'] in self.root_ids else None
            item['card_name']=finding['card_name'] if item['card_id'] else '技能或生成牌（私有日志可核对）'
            public_findings.append(item)
        return {'status':self.status,'phase':dict(self.phase),'target':self.fmt.target_id,
            'run_id':self.run_id,'games':deepcopy(self.games),'action_count':len(self.rows),
            'timing':{'median_ms':percentile(.5),'p95_ms':percentile(.95),'max_ms':max(values,default=0)},
            'effect_components':dict(checks),'anomalies':public_findings,
            'coverage':[{'card_id':cid,'name':self.registry.card(cid).name,'actions':self.coverage[cid],
                'plays':plays[cid],'checks':dict(per_card[cid]),
                'verdict':'partial' if self.coverage[cid] or per_card[cid] else 'not_exercised'} for cid in sorted(self.root_ids)],
            'decks':self.deck_document['decks'],
            'limits':['策略仅接收本人玩家DTO与合法动作；两环境串行执行。',
                '效果结论按描述片段列出；复杂组合、未触发条件和未出场卡不标成完整正确。',
                '宿主私有事实/回放不通过HTTP提供。服务仅提供当前玩家投影和聚合统计。']}

    def publish(self):
        with self.lock: self.report = self.make_report()
        write_json(self.output/'report.json',self.report)

    def evidence(self, game, row, reason):
        name = f"{row['game_id']}-{row['step']:04d}"
        key=(reason,row.get('card_id'),row['action']['type'])
        self.evidence_counts[key]+=1
        immediate=self.evidence_counts[key]<=2
        replay_path=f'private/{name}-replay.json' if immediate else f"private/{row['game_id']}-final-replay.json"
        if immediate:
            write_json(self.private/(name+'-replay.json'), build_replay(game))
            write_json(self.private/(name+'-snapshot.json'), game.snapshot())
        anomaly = {'id':name,'reason':reason,'game_id':row['game_id'],'step':row['step'],
            'card_id':row.get('card_id'),'card_name':row.get('card_name'),'action_type':row['action']['type'],
            'actor':row.get('actor'),'action':row['action'],
            'timings':row['timings'],'accepted':row['accepted'],'error':row.get('error'),
            'effect_checks':row.get('effect_checks',[]),'replay':replay_path,
            'replay_prefix_length':len(game._history)-int(row['accepted']),
            'replay_note':'Accepted: remove final replay action to reconstruct before. Rejected/query: replay already ends before attempted action.'}
        self.anomalies.append(anomaly);write_json(self.output/(name+'-finding.json'), anomaly)

    def run(self):
        try:
            for index, seed in enumerate(self.seeds):
                for env, order in [('A',('shaman','priest')),('B',('priest','shaman'))]:
                    try:self.run_game(env,order,seed,index)
                    except Exception:
                        gid=f'{env}-{index+1}'
                        (self.output/(gid+'-runner-error.txt')).write_text(traceback.format_exc(),encoding='utf-8')
                        if self.games and self.games[-1]['id']==gid:self.games[-1]['status']='runner_error'
                        else:self.games.append({'id':gid,'environment':env,'seed':seed,'order':order,'status':'runner_error','steps':0,'turn':0})
                        self.publish()
            self.status = 'finished'; self.phase = {'state':'finished','stage':None}; self.publish()
        except Exception:
            self.status = 'error'; self.phase['state'] = 'error'
            (self.output/'runner-error.txt').write_text(traceback.format_exc(),encoding='utf-8');self.publish()

    def run_game(self, env, order, seed, index):
        gid = f'{env}-{index+1}'; path = self.private/(gid+'-steps.jsonl')
        game = Game.from_decks(self.fmt.match_setup(tuple(self.specs[k] for k in order),
            seed=seed,first_player=1),self.registry,mode='release')
        rngs = {p:random.Random(seed*7+p) for p in (1,2)}
        entry = {'id':gid,'environment':env,'seed':seed,'order':order,'status':'running','steps':0,'turn':1}
        self.games.append(entry); self.update_views(env,game); self.publish()
        counts = Counter(); previous_window = None
        for step in range(self.max_steps):
            while self.pause.is_set():
                self.status = 'paused';self.publish();time.sleep(.25)
            if game._state.status != 'playing':
                entry.update(status='completed',winner=game._state.winner);break
            if game._state.turn > self.max_turns:
                entry['status'] = 'turn_limit';break
            actor = game._state.pending_choice.player_id if game._state.pending_choice else game._state.active_player
            self.phase = {'state':'running','game_id':gid,'step':step,'actor':actor,'stage':'legal_actions','started_at':time.time()};self.publish()
            before,capture_ms,_ = timed(lambda:facts(game)); cursor = len(game._events)
            message, query_ms, query_cpu = timed(lambda:game.for_player(actor).legal_actions())
            window = (game._state.turn,actor)
            if window != previous_window: counts.clear();previous_window=window
            if message.get('error') is not None and not (message['error']=='enumeration_limit' and message['observation']['pending_choice'] is not None):
                row={'game_id':gid,'step':step,'actor':actor,'turn':before['turn'],'accepted':False,'error':message['error'],
                    'action':{'type':'legal_actions'},'timings':{'query_ms':query_ms,'query_cpu_ms':query_cpu,'submit_ms':0},'effect_checks':[]}
                self.rows.append(row);self.evidence(game,row,'legal_query_error');entry['status']='error';break
            action, policy_ms, _ = timed(lambda:choose_action(message,rngs[actor],force_end=counts['ordinary']>=24))
            source_ref = next((action[k] for k in ('card','attacker','power','location','minion','starship','object') if action.get(k)),None)
            source = flatten(message['observation']).get(source_ref,{})
            pending = message['observation'].get('pending_choice')
            if not source and pending: source=pending.get('source') or {}
            card_id = source.get('card_id')
            native,adapter_ms,_ = timed(lambda:_decode(game,actor,action,message['observation']))
            source_id = next((getattr(native,k) for k in ('entity_id','attacker_id','hero_power_id','source_id') if getattr(native,k,None) is not None),None)
            self.phase.update(stage='submit',started_at=time.time());self.publish()
            reply, submit_ms, submit_cpu = timed(lambda:game.for_player(actor).submit({'revision':message['revision'],'action':action}))
            self.phase.update(stage='audit',started_at=time.time())
            audit_start=time.perf_counter();after=facts(game);events=compact_events(game._events[cursor:])
            checks=evaluate(card_id,source_id,actor,native,before,after,events,self.registry) if reply['accepted'] else []
            audit_ms=(time.perf_counter()-audit_start)*1000
            row={'game_id':gid,'step':step,'at':datetime.now(timezone.utc).isoformat(),'actor':actor,'turn':before['turn'],'action':action,'card_id':card_id,
                'card_name':self.registry.card(card_id).name if card_id else None,
                'description':ui.plain_card_text(self.records.get(card_id,({},''))[0].get('text','')),
                'accepted':reply['accepted'],'error':reply['error'],
                'timings':{'capture_ms':capture_ms,'query_ms':query_ms,'query_cpu_ms':query_cpu,'policy_ms':policy_ms,'adapter_ms':adapter_ms,
                    'submit_ms':submit_ms,'submit_cpu_ms':submit_cpu,'audit_ms':round(audit_ms,3)},
                'events':events,'effect_checks':checks,'before':before,'after':after}
            self.rows.append(row)
            if card_id:self.coverage[card_id]+=1
            if submit_ms>=1000 or query_ms>=500:self.evidence(game,row,'slow_action' if submit_ms>=1000 else 'slow_legal_query')
            if not reply['accepted']:
                self.evidence(game,row,'command_rejected')
                try:
                    diagnostic=game.clone();diagnostic.runtime_mode='debug';diagnostic.apply(native)
                except Exception:
                    (self.private/f'{gid}-{step:04d}-failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
                with path.open('a',encoding='utf-8')as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
                entry['status']='error';break
            if any(c['status']=='fail' for c in checks):self.evidence(game,row,'description_component_mismatch')
            counts['ordinary' if action['type']!='select_choice' else 'choices']+=1
            if counts['choices']>64:
                entry['status']='choice_limit';break
            entry.update(steps=step+1,turn=game._state.turn)
            _,view_ms,_=timed(lambda:self.update_views(env,game));row['timings']['projection_ms']=view_ms
            with path.open('a',encoding='utf-8')as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            self.publish()
        else:entry['status']='step_limit'
        if entry['status']=='running':entry['status']='completed' if game._state.status!='playing' else 'stopped'
        write_json(self.private/(gid+'-final-replay.json'),build_replay(game))
        write_json(self.private/(gid+'-final-snapshot.json'),game.snapshot())
        self.update_views(env,game);self.publish()


class AuditHandler(ui.Handler):
    def do_GET(self):
        if not self.local_request():return self.send(403,{'error':'origin_rejected'})
        path=self.path.split('?',1)[0]
        files={'/':('autoplay.html','text/html; charset=utf-8'),'/autoplay.js':('autoplay.js','text/javascript; charset=utf-8'),'/autoplay.css':('autoplay.css','text/css; charset=utf-8')}
        if path in files:
            name,mime=files[path];return self.send(200,(ui.STATIC/name).read_bytes(),mime)
        if path=='/battle':
            page=(ui.STATIC/'index.html').read_text(encoding='utf-8').replace('对手：双人手动','双方自动 · 观察画面')
            return self.send(200,page.encode('utf-8'),'text/html; charset=utf-8')
        if path=='/audit/status':
            with self.server.controller.lock:result=deepcopy(self.server.controller.report)
            return self.send(200,result)
        if path=='/audit/view':
            from urllib.parse import parse_qs,urlsplit
            q=parse_qs(urlsplit(self.path).query);env=q.get('env',['A'])[0];seat=q.get('seat',['1'])[0]
            with self.server.controller.lock:result=deepcopy(self.server.controller.views.get(env,{}).get(seat))
            return self.send(200,{'data':result})
        return super().do_GET()

    def do_POST(self):
        if self.path not in ('/audit/start','/audit/pause','/api/catalog'):return self.send(404,{'error':'not_found'})
        if not self.local_request():return self.send(403,{'error':'origin_rejected'})
        try:
            if self.headers.get('Content-Type')!='application/json' or int(self.headers.get('Content-Length','0'))!=2 or self.rfile.read(2)!=b'{}':raise ValueError()
        except ValueError:return self.send(400,{'error':'invalid_request'})
        if self.path=='/api/catalog':return self.send(200,self.server.controller.catalog_cache)
        c=self.server.controller;c.start() if self.path.endswith('start') else c.pause_run()
        return self.send(200,{'status':c.status})


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--decks',type=Path,required=True)
    p.add_argument('--port',type=int,default=8772);p.add_argument('--seeds',type=int,nargs='+');p.add_argument('--autostart',action='store_true');p.add_argument('--max-turns',type=int,default=80);p.add_argument('--max-steps',type=int,default=600);p.add_argument('--static',type=Path)
    a=p.parse_args()
    if a.static:ui.STATIC=a.static.resolve()
    c=Controller(a.output,a.decks,seeds=a.seeds,max_turns=a.max_turns,max_steps=a.max_steps)
    from http.server import ThreadingHTTPServer
    server=ThreadingHTTPServer(('127.0.0.1',a.port),AuditHandler);server.controller=c
    write_json(c.output/'server.json',{'url':f'http://127.0.0.1:{a.port}/','target':c.fmt.target_id,'source':str(ROOT),'two_environments':True,'both_players_automatic':True})
    if a.autostart:c.start()
    print(f'Dual bot audit on http://127.0.0.1:{a.port}/',flush=True);server.serve_forever()


if __name__=='__main__':main()
