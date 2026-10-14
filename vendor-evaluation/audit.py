"""External audit harness; upstream checkout is kept unchanged."""
import ast
import collections
import concurrent.futures
import importlib
import inspect
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'fireplaceAharaLab' / 'fireplaceAharaLab'
OUT = ROOT / 'results'
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(SOURCE))

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def initialize():
    from fireplace.config import Config
    Config.HEARTHSTONE = 1
    Config.LOGINFO = 0
    Config.GAMELOG = 0
    from fireplace import cards
    cards.db.initialize(locale='enUS')
    return cards

def inventory():
    cards = initialize()
    from hearthstone import cardxml
    from fireplace.utils import get_script_definition
    db, _ = cardxml.load(locale='enUS')
    set_names = ['CORE','THE_BARRENS','STORMWIND','ALTERAC_VALLEY','THE_SUNKEN_CITY','REVENDRETH','RETURN_OF_THE_LICH_KING','PATH_OF_ARTHAS']
    rows = []
    for set_name in set_names:
        expected = [c for c in db.values() if c.collectible and c.card_set.name == set_name]
        loaded = [c for c in expected if c.id in cards.db]
        missing = [{'id': c.id, 'name': c.name} for c in expected if c.id not in cards.db]
        scriptless = [{'id': c.id, 'name': c.name, 'text': str(c.description)} for c in loaded if get_script_definition(c.id) is None]
        rows.append(dict(set=set_name, database_collectible=len(expected), registered=len(loaded), missing=missing, no_script=scriptless))
    syntax_errors = []
    cases = []
    file_count = 0
    for path in SOURCE.rglob('*.py'):
        file_count += 1
        try:
            tree = ast.parse(path.read_bytes())
        except Exception as exc:
            syntax_errors.append({'file':str(path.relative_to(SOURCE)), 'error': str(exc)})
            continue
        if path.parent.name != 'card_test':
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id == 'Preset_Play' for b in node.bases):
                assertions = sum(isinstance(n, ast.Assert) or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('assertion','asserting')) for n in ast.walk(node))
                cases.append(dict(module='card_test.'+path.stem, case=node.name, static_assertions=assertions, line=node.lineno))
    save('inventory.json', dict(python=sys.version, registered_total=len(cards.db), sets=rows, python_files=file_count, syntax_errors=syntax_errors, preset_cases=cases))
    print(json.dumps({'registered':len(cards.db),'sets':[{k:v for k,v in r.items() if k not in ('missing','no_script')} for r in rows],'syntax_errors':syntax_errors,'preset_cases':len(cases)}))

def worker(module, case, seed):
    random.seed(seed)
    assertions = [0]
    result = {'module':module,'case':case,'seed':seed}
    started = time.monotonic()
    try:
        from fireplace.config import Config
        Config.HEARTHSTONE=1
        Config.LOGINFO=0
        Config.GAMELOG=0
        from card_test.simulate_game import PresetGame, Preset_Play
        for name in ('assertion','asserting'):
            original = getattr(Preset_Play,name)
            def counted(self, *args, _original=original, **kwargs):
                assertions[0] += 1
                return _original(self,*args,**kwargs)
            setattr(Preset_Play,name,counted)
        cls = getattr(importlib.import_module(module),case)
        PresetGame(cls)
        result['status']='completed'
    except Exception as exc:
        result.update(status='failed',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
    result.update(assertion_calls=assertions[0],seconds=round(time.monotonic()-started,3))
    save(f'{module}.{case}.seed{seed}.json',result)
    print('AUDIT_RESULT '+json.dumps(result,ensure_ascii=True))

def game(seed, class1, class2):
    random.seed(seed)
    result=dict(seed=seed,class1=class1,class2=class2)
    started=time.monotonic()
    try:
        initialize()
        from hearthstone.enums import CardClass
        from agent_Standard import StandardAgent
        from utils import play_one_game
        from fireplace.utils import random_draft
        a=StandardAgent('A',StandardAgent.StandardRandom,myClass=CardClass[class1])
        b=StandardAgent('B',StandardAgent.StandardRandom,myClass=CardClass[class2])
        result['deck1']=random_draft(a.myClass)
        result['deck2']=random_draft(b.myClass)
        winner=play_one_game(a,b,deck1=result['deck1'],deck2=result['deck2'],debugLog=False)
        result.update(status='completed',winner=winner)
    except Exception as exc:
        result.update(status='failed',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
    result['seconds']=round(time.monotonic()-started,3)
    save(f'game.{seed}.{class1}.{class2}.json',result)

def batch():
    inv=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
    selected=[c for c in inv['preset_cases'] if c['module'].startswith(('card_test.t_lich_','card_test.t_arthas_','card_test.t_rev_'))]
    commands=[('preset',c,[str(ROOT/'audit.py'),'worker',c['module'],c['case'],'0']) for c in selected]
    classes=['DEATHKNIGHT','DEMONHUNTER','DRUID','HUNTER','MAGE','PALADIN','PRIEST','ROGUE','SHAMAN','WARLOCK','WARRIOR']
    for seed in range(22):
        a,b=classes[seed%11],classes[(seed+4)%11]
        commands.append(('game',dict(seed=seed,class1=a,class2=b),[str(ROOT/'audit.py'),'game',str(seed),a,b]))
    def run(item):
        kind, meta, args=item
        label=('.'.join((meta['module'],meta['case'])) if kind=='preset' else f"game.{meta['seed']}.{meta['class1']}.{meta['class2']}")
        with (OUT/(label+'.log')).open('w',encoding='utf-8') as log:
            try:
                process=subprocess.run([sys.executable,*args],cwd=SOURCE,stdout=log,stderr=subprocess.STDOUT,timeout=60,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
                return dict(kind=kind,**meta,returncode=process.returncode)
            except subprocess.TimeoutExpired:
                return dict(kind=kind,**meta,status='timeout')
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for value in pool.map(run,commands):
            results.append(value)
            if len(results)%20==0:
                print(f'Finished {len(results)}/{len(commands)}',flush=True)
            save('batch-progress.json',results)
    save('batch.json',results)
    print('DONE',len(results))

if __name__=='__main__':
    command=sys.argv[1]
    if command=='inventory': inventory()
    elif command=='worker': worker(sys.argv[2],sys.argv[3],int(sys.argv[4]))
    elif command=='game': game(int(sys.argv[2]),sys.argv[3],sys.argv[4])
    elif command=='batch': batch()
