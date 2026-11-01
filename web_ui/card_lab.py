"""Local testing fixtures and evidence, independent of simulator implementation.

Scaffolding is not a rules oracle. Only lab_cases.json's explicit expectations
receive an effect verdict; all other cards remain 'needs_review' after smoke.
"""
from functools import lru_cache
from dataclasses import fields, MISSING
from pathlib import Path
import json
import hashlib
import time
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.cards.constructed import build_registry

ROOT = Path(__file__).resolve().parents[1]
HEROES = {'warrior':'HERO_01','shaman':'HERO_02','rogue':'HERO_03','paladin':'HERO_04',
          'hunter':'HERO_05','druid':'HERO_06','warlock':'HERO_07','mage':'HERO_08',
          'priest':'HERO_09','demon_hunter':'HERO_10','death_knight':'HERO_11'}


@lru_cache(maxsize=1)
def content():
    registry = build_registry()
    # Read only reviewed input records for printed text, never card text as code.
    from .server import printed_metadata
    records = dict(printed_metadata()[1])
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get('id'), str) and value.get('id') in registry.cards and 'text' in value and 'name' in value:
                cid = value['id']
                if registry.card(cid).name == value['name']:
                    records[cid] = (value, '')
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    for path in sorted((ROOT / 'data/cards').glob('*.json')):
        visit(json.loads(path.read_text(encoding='utf-8')))
    cases = json.loads((Path(__file__).parent / 'lab_cases.json').read_text(encoding='utf-8'))['cases']
    # Plain native bodies get independent printed-stat checks. Any non-default
    # executable declaration excludes this template; it cannot certify effects.
    printed_fields={'id','name','kind','cost','attack','health','durability','keywords','metadata'}
    for cid, card in registry.cards.items():
        if cid in cases or card.kind.value not in ('minion','weapon') or not card.hand_playable: continue
        raw=records.get(cid, ({},''))[0]
        if any(f.name not in printed_fields and (f.default is MISSING or getattr(card,f.name)!=f.default) for f in fields(card)): continue
        if type(raw.get('attack')) is not int: continue
        prefix='own.board.0' if card.kind.value=='minion' else 'own.weapon'
        stat='health' if card.kind.value=='minion' else 'durability'
        amount=raw.get(stat)
        if type(amount) is not int: continue
        cases[cid]=dict(own_board=[],expect=[[prefix+'.attack',raw['attack']],[prefix+'.'+stat,amount]],
                        goal='按固定印刷记录核对入场攻击力与'+('生命值' if stat=='health' else '耐久')+'；关键词的触发行为仍需单独测试。')
    return registry, records, cases


def role(card):
    if card.choice_only or card.starship_for: return 'source_required'
    if card.kind.value == 'hero_power': return 'power'
    if card.kind.value == 'hero' and not card.hand_playable: return 'hero'
    if card.hand_playable and not card.starship_for: return 'hand'
    if card.kind.value == 'minion': return 'board'
    return 'source_required'


def defaults(cid):
    registry, _, cases = content()
    card = registry.card(cid)
    classes = [c.value for c in card.metadata.classes] if card.metadata else []
    hero = next((HEROES[c] for c in classes if c in HEROES and HEROES[c] in registry.cards), 'HERO_01')
    case = cases.get(cid, {})
    return dict(hero=hero, mana=max(10,min(40,card.cost)), own_board=case.get('own_board', ['CS2_182']),
                enemy_board=case.get('enemy_board', ['CS2_182','CS2_179']),
                deck=case.get('deck', ['CS2_029','CS2_182','CS2_024','EX1_019'] * 2),
                corpses=10, seed=29, hero_damage=case.get('hero_damage',0), minion_damage=case.get('minion_damage',0))


def catalog():
    from .server import plain_card_text
    registry, records, cases = content()
    cards = []
    for cid, c in sorted(registry.cards.items()):
        raw = records.get(cid, ({}, ''))[0]
        fixture_role = role(c)
        art = (ROOT / 'web_ui/static/assets' / (cid + '.webp')).is_file()
        cards.append(dict(id=cid, name=c.name, type=c.kind.value, cost=c.cost,
                          attack=c.attack, health=c.health, durability=c.durability,
                          keywords=[k.value for k in c.keywords], text=plain_card_text(raw.get('text','')),
                          classes=[x.value for x in c.metadata.classes] if c.metadata else [],
                          role=fixture_role, can_create=fixture_role != 'source_required',
                          art='/assets/'+cid+'.webp' if art else None,
                          focused=cid in cases, goal=cases.get(cid,{}).get('goal', '基础场景可检查操作与显示；完整效果需要补充专用断言和前置条件。'),
                          defaults=defaults(cid)))
    return dict(version=registry.version, fingerprint=registry.fingerprint(), cases_fingerprint=hashlib.sha256(json.dumps(cases,sort_keys=True).encode()).hexdigest(), total=len(cards),
                physical_count=sum(c['can_create'] for c in cards),
                focused_count=sum(c['focused'] for c in cards), cards=cards,
                note='目录自动包含当前完整已接入定义；基础场景、效果断言与界面检查分别记录。依赖/选择定义须通过来源生成，不冒充可直接出牌。')


class SceneError(ValueError):
    pass


def opening_scene(registry, cid, config, case, *, mode='release'):
    """Real opening provenance for starting-deck conditions; never fabricate it."""
    from hs_sim.engine import MatchSetup,DeckSpec,DeckPolicy,SelectChoice
    from hs_sim.engine.effects import AddToHand,ChangeManaCrystals,GainResource
    from hs_sim.engine.model import Resource
    from hs_sim.engine.zones import AddToDeck
    from hs_sim.engine.resolver import Resolution
    if config['own_board'] or config['enemy_board'] or len(config['deck'])<5: raise SceneError('opening_scene_options')
    hero=config['hero'];hero_class=registry.card(hero).metadata.classes[0]
    policy=DeckPolicy('ui.lab.opening','ui.lab.fixed','experimental',tuple(sorted(registry.cards)),deck_size=len(config['deck']),max_copies=30)
    decks=tuple(DeckSpec(hero,hero+'bp',hero_class,tuple(config['deck'])) for _ in (1,2))
    game=Game.from_decks(MatchSetup(decks,policy,'GAME_005',config['seed'],1),registry,mode=mode)
    while game._state.pending_choice is not None:
        ch=game._state.pending_choice
        if ch.purpose!='mulligan': raise SceneError('opening_scene_unavailable')
        game.apply(SelectChoice(ch.player_id,ch.id,()))
    effects=[ChangeManaCrystals(1,config['mana']-game._state.players[1].max_mana,filled=True),GainResource(1,Resource.CORPSES,config['corpses']),AddToHand(1,cid)]
    effects.extend(AddToHand(1,helper) for helper in case.get('helpers',[]))
    if case.get('generated_deck_cards'):
        effects.extend(AddToDeck(pid,'CS2_182','bottom') for pid in (1,2))
    game._state.action_number+=1;game._resolving=True
    try:
        Resolution(game).run(effects);game._information.sync(game);game._assert_stable()
    finally:game._resolving=False
    # New trusted testing segment retains native OpeningState facts. Previous
    # mulligan commands are not mislabeled as player actions after adjustment.
    return Game.from_snapshot(game.snapshot(),registry,mode=mode)


def configure(session, body):
    if set(body) - {'card_id','options'} or not isinstance(body.get('card_id'), str):
        raise SceneError('invalid_lab_request')
    registry, records, cases = content()
    cid = body['card_id']
    if cid not in registry.cards: raise SceneError('unknown_card')
    card = registry.card(cid)
    fixture_role = role(card)
    if fixture_role == 'source_required': raise SceneError('source_required')
    opts = body.get('options', {})
    if type(opts) is not dict or set(opts) - set(defaults(cid)): raise SceneError('invalid_lab_options')
    config = defaults(cid)
    custom = any(v != config[k] for k,v in opts.items())
    config.update(opts)
    for key, low, high in (('mana',0,40),('corpses',0,30),('seed',0,2147483647),('hero_damage',0,20),('minion_damage',0,10)):
        if type(config[key]) is not int or not low <= config[key] <= high: raise SceneError('invalid_lab_options')
    if type(config['hero']) is not str or config['hero'] not in registry.cards or registry.card(config['hero']).kind.value != 'hero':
        raise SceneError('invalid_lab_hero')
    for key, limit in (('own_board',7),('enemy_board',7),('deck',30)):
        if type(config[key]) is not list or len(config[key]) > limit or any(type(x) is not str or x not in registry.cards for x in config[key]):
            raise SceneError('invalid_lab_options')
    # Custom scenes keep lifecycle requirements and helper preparation, while
    # their original effect expectations are explicitly removed.
    case = dict(cases.get(cid, {}))
    if custom: case.pop('expect',None)
    hero = cid if fixture_role == 'hero' else config['hero']
    power = cid if fixture_role == 'power' else hero+'bp' if hero+'bp' in registry.cards else None
    hand = ([cid] if fixture_role == 'hand' else []) + case.get('helpers', [])
    own_board = config['own_board'] + ([cid] if fixture_role == 'board' else [])
    try:
        from .server import printed_metadata
        game = opening_scene(registry,cid,config,case,mode=session.runtime_mode) if case.get('opening') else Game.from_scenario(Scenario((
            PlayerSetup(hero, hero_power_card_id=power, hand=tuple(hand), board=tuple(own_board),
                        deck=tuple(config['deck']), mana=config['mana'], max_mana=config['mana'], mana_cap=max(10,config['mana']),corpses=config['corpses']),
            PlayerSetup('HERO_01', hero_power_card_id='HERO_01bp', deck=('CS2_182',)*8, board=tuple(config['enemy_board']))),
            seed=config['seed'], name='Card UI test: '+cid,
            generation_context=GenerationContext(printed_metadata()[0], 'experimental')), registry,
            mode=session.runtime_mode)
    except Exception as exc:
        raise SceneError('scene_unavailable') from exc
    if config['hero_damage'] or config['minion_damage']:
        from hs_sim.engine.effects import Damage
        from hs_sim.engine.resolver import Resolution
        # Explicit fixture preparation, not a player command or a card effect.
        # Existing damage/health/lifecycle handling stays in the native kernel.
        game._resolving=True
        game._state.action_number+=1
        try:
            effects=[]
            if config['hero_damage']: effects.append(Damage(game._state.players[1].hero_id,config['hero_damage']))
            if config['minion_damage']:
                for eid in game._state.players[1].board:
                    entity=game._state.entities[eid]
                    if entity.kind.value=='minion' and entity.health>1:
                        effects.append(Damage(eid,min(config['minion_damage'],entity.health-1)))
            Resolution(game).run(effects)
            game._information.sync(game)
            game._assert_stable()
        except Exception as exc:
            raise SceneError('scene_unavailable') from exc
        finally: game._resolving=False
        if game._state.pending_choice is not None: raise SceneError('scene_unavailable')
        game._origin=game.snapshot()
    # A new independent match, never resets the caller's existing match.
    session.create('practice', 'human')
    session.registry, session.game, session.lab_records = registry, game, records
    try: view = game.for_player(1).observe()['observation']
    except Exception as exc: raise SceneError('scene_unavailable') from exc
    own = view['players'][0]
    source = (own['hero'] if fixture_role == 'hero' else own['hero_power'] if fixture_role == 'power' else
              next((c for c in own['hand'] + own['board'] if c.get('card_id') == cid),None))
    if source is None: raise SceneError('scene_unavailable')
    session.lab_context = dict(card_id=cid, role=fixture_role, subject=source['ref'], case=case,
                               custom=custom, config=config, before=view, acted=False, steps=[], error=None)
    session.lab_context['activation_ref']=next((c['ref'] for c in own['hand'] if c.get('card_id')==case.get('activation')),None)
    for prelude in case.get('preludes', []):
        port=game.for_player(1)
        dto=port.legal_actions()
        own=flatten(dto['observation'])['own']
        ref=next((c['ref'] for c in own['hand'] if c.get('card_id')==prelude['card_id']),None)
        wanted=target_ref(dto['observation'],session.lab_context,prelude.get('target'))
        action=next((a for a in dto.get('actions') or [] if a.get('card')==ref and a.get('target')==wanted),None)
        if action is None: raise SceneError('prelude_unavailable')
        reply=port.submit(dict(revision=dto['revision'],action=action))
        if not reply['accepted']: raise SceneError('prelude_unavailable')
        session.lab_context['steps'].append(dict(type=action['type'],accepted=True,preparation=True))
    session.lab_context['before']=game.for_player(1).observe()['observation']
    return dict(token=session.token, seat=1, card_id=cid, config=config, focused=bool(case.get('expect')))


def flatten(observation):
    result = {'dormant_count':sum(bool(c.get('dormancy')) for p in observation['players'] for c in p['board'])}
    for prefix, pid in (('own',1),('enemy',2)):
        p = next(p for p in observation['players'] if p['id'] == pid)
        result[prefix] = dict(p, hand_count=len(p['hand']), board_count=len(p['board']),poisonous_count=sum('poisonous' in c.get('keywords',[]) for c in p['board']))
    return result


def path_value(value, path):
    for part in path.split('.'):
        try: value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError): return None
    return value


def report(session):
    context = session.lab_context
    view = session.game.for_player(1).observe()['observation']
    values = flatten(view)
    checks = [dict(path=path, expected=expected, actual=path_value(values,path),
                   passed=path_value(values,path)==expected) for path,expected in context['case'].get('expect', [])]
    if context['error']=='no_subject_action': status='needs_setup'
    elif context['error']: status='execution_error'
    elif not context['acted']: status='not_run'
    elif view['pending_choice']: status='choice_pending'
    elif checks: status='passed' if all(x['passed'] for x in checks) else 'assertion_failed'
    else: status='needs_review'
    return dict(card_id=context['card_id'], status=status, checks=checks, steps=context['steps'],
                error=context['error'], custom=context['custom'],
                goal=context['case'].get('goal','当前只有执行与呈现检查，尚无该条件下的效果断言。'),
                note='通过仅代表列出的断言，不覆盖该卡全部条件、组合或国服校准。')


def note_action(session, action, accepted):
    c = getattr(session, 'lab_context', None)
    if not c or not accepted or session.seat!=1: return
    if any(action.get(key) == c['subject'] for key in ('card','power','location','minion','object')):
        c['acted'] = True
    if c.get('activation_ref') and action.get('card')==c['activation_ref']:c['acted']=True
    c['steps'].append(dict(type=action.get('type'), accepted=True))


def target_ref(view, context, selector):
    p = flatten(view)
    if selector == 'subject': return context['subject']
    if selector in ('own_hero','enemy_hero'): return p['own' if selector=='own_hero' else 'enemy']['hero']['ref']
    if selector in ('own_minion','enemy_minion'):
        board = p['own' if selector=='own_minion' else 'enemy']['board']
        return board[0]['ref'] if board else None
    return None


def run(session):
    c = session.lab_context
    if c['acted']: raise SceneError('scene_already_run')
    definition=session.registry.card(c['card_id'])
    if c['role']=='hero' or definition.passive_hero_power and not c.get('activation_ref'): return dict(report(session),status='display_only')
    started = time.perf_counter()
    def perform(action):
        port = session.game.for_player(1)
        reply = port.submit(dict(revision=port.observe()['revision'], action=action))
        if not reply['accepted']:
            c['error'] = reply['error']
            c['steps'].append(dict(type=action['type'], accepted=False, error=reply['error']))
            return False
        note_action(session, action, True)
        return True
    def choose_for(ref, target=None, branch=None):
        port = session.game.for_player(1)
        view = port.observe()['observation']
        actions = port.legal_actions()
        if actions.get('error'):
            c['error'] = actions['error']; return None
        candidates = [a for a in actions['actions'] if any(a.get(k)==ref for k in ('card','power','location','minion','object'))]
        if branch: candidates = [a for a in candidates if a.get('branch')==branch]
        if target:
            wanted = target_ref(view,c,target)
            candidates = [a for a in candidates if a.get('target')==wanted]
        return candidates[0] if candidates else None
    action = choose_for(c.get('activation_ref') or c['subject'], c['case'].get('target'), c['case'].get('branch'))
    if action is None:
        c['error'] = c['error'] or 'no_subject_action'
    elif perform(action):
        # Deliberately bounded smoke policy; private opponent choices never enter
        # the page, and user can finish unresolved choices by hand.
        for _ in range(4):
            ch = session.game.for_player(1).observe()['observation']['pending_choice']
            if not ch or ch.get('player_id') != 1 or not ch.get('options'): break
            chosen = [o['ref'] for o in ch['options'][:ch['min_count']]]
            if not perform(dict(type='select_choice',choice=ch['ref'],options=chosen)): break
        if not c['error'] and not session.game.state.pending_choice:
            for extra in c['case'].get('followups', []):
                own = flatten(session.game.for_player(1).observe()['observation'])['own']
                ref = next((e['ref'] for e in own['hand'] if e.get('card_id')==extra['card_id']), None)
                action = choose_for(ref, extra.get('target')) if ref else None
                if action is None or not perform(action):
                    c['error'] = c['error'] or 'followup_unavailable'; break
    result = report(session)
    result['elapsed_ms'] = round((time.perf_counter()-started)*1000,2)
    return result


def route(host, path, body, token):
    from .server import Host
    if path == '/api/lab/catalog':
        if body: return 400, {'error':'invalid_request'}
        return 200, catalog()
    if path == '/api/lab/baseline' and not body:
        path=Path(__file__).parent/'lab_baseline.json'
        if not path.is_file(): return 200,dict(available=False)
        data=json.loads(path.read_text(encoding='utf-8'))
        current=catalog()
        compatible=data.get('registry_fingerprint')==current['fingerprint'] and data.get('cases_fingerprint')==current['cases_fingerprint']
        return 200,dict(available=compatible,version=data.get('registry_version'),results=data['results'] if compatible else {},note='历史巡检仅在卡池与用例指纹一致时载入。')
    if path in ('/api/lab/create','/api/lab/probe'):
        session = Host(mode=host.runtime_mode)
        try: created = configure(session, body)
        except SceneError as exc:
            if path.endswith('/probe') and str(exc) in ('source_required','scene_unavailable','prelude_unavailable','opening_scene_options','opening_scene_unavailable'):
                return 200,dict(report=dict(card_id=body['card_id'],status='source_required' if str(exc)=='source_required' else 'needs_setup',error=str(exc),checks=[],steps=[]),preview=None)
            return 400, {'error':str(exc)}
        if path.endswith('/probe'):
            try: result=run(session)
            except Exception: result=dict(card_id=body['card_id'],status='execution_error',error='probe_failed',checks=[],steps=[])
            return 200, dict(report=result, preview=session.listing())
        if len(host.sessions)>=32:
            old=next((key for key,value in host.sessions.items() if hasattr(value,'lab_context')),None)
            if old is None:return 429,{'error':'lab_capacity'}
            host.sessions.pop(old)
        host.sessions[session.token]=session
        return 200, created
    session=host.sessions.get(token)
    if session is None: return 403, {'error':'seat_session_required'}
    if not hasattr(session,'lab_context'): return 409, {'error':'not_lab_session'}
    if session.handoff:return 409,{'error':'handoff_pending'}
    if session.seat!=1:return 409,{'error':'lab_owner_required'}
    if path=='/api/lab/check' and not body: return 200, report(session)
    if path=='/api/lab/run' and set(body)=={'revision'}:
        if body['revision']!=session.game.for_player(1).observe()['revision']: return 409, {'error':'stale_observation'}
        try: result=run(session)
        except SceneError as exc: return 409, {'error':str(exc)}
        except Exception: result=dict(card_id=session.lab_context['card_id'],status='execution_error',error='probe_failed',checks=[],steps=[])
        session.refresh_opponent_ticket()
        return 200, dict(report=result, view=session.listing())
    return 400, {'error':'invalid_request'}
