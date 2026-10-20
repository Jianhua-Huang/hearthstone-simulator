"""Cost-filtered pool producers followed by one frozen stat permutation."""
from dataclasses import asdict,dataclass,fields,is_dataclass
import json
from random import Random

from .effects import Effect,SetStats,_integer,_player
from .model import CardType,GameState,Zone
from .pools import GenerateFromPool,PoolQuery,resolve_candidates
from .summon_quantities import SummonCause,validate_cause

ACCEPT='pool_stat_group_accepted'
START='summoned_stats_scramble_accepted'
FINISH='summoned_stats_scramble_finished'


@dataclass(frozen=True)
class SummonAndScramble(Effect):
    player_id:int
    pool_id:str
    costs:tuple[int,...]
    cause:SummonCause

    @property
    def source_id(self):return self.cause.source.entity_id

    def __post_init__(self):
        _player(self.player_id)
        if type(self.pool_id)is not str or not self.pool_id:
            raise ValueError('Stat scramble needs an explicit original pool')
        if type(self.costs)is not tuple or len(self.costs)!=2 or len(set(self.costs))!=2:
            raise ValueError('Stat scramble needs two distinct printed cost bands')
        for cost in self.costs:_integer(cost,'scramble printed cost',0)
        if type(self.cause)is not SummonCause or self.cause.player_id!=self.player_id:
            raise ValueError('Stat scramble needs its genuine attributed source')
        self.cause.__post_init__()


@dataclass(frozen=True)
class ScramblePoolSummons(Effect):
    request:SummonAndScramble
    roots:tuple[int,...]
    accept_event:int

    @property
    def source_id(self):return self.request.source_id

    def __post_init__(self):
        if type(self.request)is not SummonAndScramble:
            raise ValueError('Stat scramble lost its original typed request')
        self.request.__post_init__()
        _integer(self.accept_event,'stat group acceptance',1)
        if type(self.roots)is not tuple or len(self.roots)!=2 or self.roots[1]!=self.roots[0]+1:
            raise ValueError('Stat scramble lost its two complete original producer roots')
        for identity in self.roots:_integer(identity,'stat group producer root',1)


def request_json(request):return json.dumps(asdict(request),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def begin(r,request):
    request.__post_init__();validate_cause(r.state,r.registry,request.cause)
    from .pool_summons import accept_batch
    plans=[]
    for cost in request.costs:
        effect=GenerateFromPool(request.player_id,request.pool_id,
            PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost),
            source_id=request.source_id,destination='board',cause=request.cause)
        candidates=resolve_candidates(r.registry,r.game._generation_context,request.pool_id,effect.query,
            source_card_id=request.cause.source.card_id,player_id=request.player_id,exclude_source_by_rule=True)
        plans.append((effect,candidates))
    roots=[];work=[]
    for effect,candidates in plans:
        roots.append(r.state.next_pool_summon_id)
        work.extend(accept_batch(r,effect,candidates))
    event=r.emit(ACCEPT,source_id=request.source_id,player_id=request.player_id,
                 request=request_json(request),roots=tuple(roots))
    return (*work,ScramblePoolSummons(request,tuple(roots),event.sequence))


def validate_work(game,work):
    work.__post_init__();state=game._state
    validate_cause(state,game.registry,work.request.cause,closed=True)
    event=next((e for e in game._events if e.sequence==work.accept_event),None)
    if event is None or (event.kind,event.source_id,event.player_id,dict(event.data))!=(
            ACCEPT,work.source_id,work.request.player_id,dict(request=request_json(work.request),roots=work.roots)):
        raise ValueError('Stat scramble changed its original complete group acceptance')
    from .pool_summons import record
    result=tuple(record(state,i)for i in work.roots)
    for cost,root in zip(work.request.costs,result):
        basis=root.spec.basis
        if (root.spec.cause!=work.request.cause or root.spec.count!=1 or root.spec.producer_profile_id is not None or
                root.spec.fill_capacity is not None or root.spec.position is not None or
                (basis.player_id,basis.pool_id,basis.query)!=(work.request.player_id,work.request.pool_id,
                    PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost))):
            raise ValueError('Stat scramble borrowed another original cost-band producer')
    return result


def deliveries(state,roots):
    children={row.id:row for row in state.card_summon_history}
    return tuple(d.entity for root in roots for identity in root.entry_root_ids
        for d in children[identity].deliveries if d.entity is not None)


def scramble(r,work):
    from .resolver import _set_stats_on_entity
    from .serialization import end_turn_rng_to_json
    roots=validate_work(r.game,work)
    if any(root.status!='completed'for root in roots):
        raise ValueError('Stat scramble cannot precede its actual producer entries')
    originals=deliveries(r.state,roots);targets=[]
    for fact in originals:
        entity=r.state.entities.get(fact.entity_id)
        if entity is not None and entity.zone==Zone.BOARD and entity.entered_order==fact.entered_order:
            targets.append((entity,entity.attack,entity.health,entity.max_health,r.live_character(entity.id)is entity))
    values=tuple(value for _,attack,health,_,_ in targets for value in (attack,health))
    indices=list(range(len(values)));before=r.game._rng.getstate()
    r.game._rng.shuffle(indices);after=r.game._rng.getstate()
    event=r.emit(START,source_id=work.source_id,player_id=work.request.player_id,
        group_event=work.accept_event,roots=work.roots,
        originals=tuple((a.entity_id,a.entered_order)for a in originals),
        targets=tuple((e.id,e.entered_order,a,h,m,w)for e,a,h,m,w in targets),
        values=values,indices=tuple(indices),
        rng_before=json.dumps(end_turn_rng_to_json(before),separators=(',',':')),
        rng_after=json.dumps(end_turn_rng_to_json(after),separators=(',',':')))
    applied=[]
    # Freeze all operands before any writes; ordinary callbacks/deaths run only
    # after this one effect handler. The shared setter owns enchantments/healing.
    for index,(entity,attack,health,maximum,writable)in enumerate(targets):
        if not writable:continue  # Existing dormant stat-set admission, retained explicitly.
        a,h=values[indices[index*2]],values[indices[index*2+1]]
        _set_stats_on_entity(r,SetStats(entity.id,a,h,work.source_id),entity,
                             original_stats=(attack,health,maximum))
        applied.append((entity.id,entity.enchantments[-1].id,a,h))
    r.emit(FINISH,source_id=work.source_id,player_id=work.request.player_id,
        group_event=work.accept_event,scramble_event=event.sequence,applied=tuple(applied))
    return ()


def validate_boundary(game):
    if game._frame is None and not any(e.kind in (ACCEPT,START,FINISH)for e in game._events):
        return
    from .hero_health_history import effective_events
    from .serialization import end_turn_rng_from_json,canonical_hash
    events=tuple(effective_events(game._events));accepts={e.sequence:e for e in events if e.kind==ACCEPT}
    starts={};finishes={}
    for event in events:
        if event.kind not in (START,FINISH):continue
        key=dict(event.data).get('group_event');_integer(key,'scramble original group',1)
        if key not in accepts:raise ValueError('Stat scramble lost its original producer group')
        table=starts if event.kind==START else finishes
        if key in table:raise ValueError('Stat scramble repeated an original group')
        table[key]=event
    pending=[];seen=set()
    def visit(value):
        if value is None or type(value)is GameState or id(value)in seen:return
        seen.add(id(value))
        if type(value)is ScramblePoolSummons:
            validate_work(game,value);pending.append(value.accept_event)
        if is_dataclass(value):
            for field in fields(value):visit(getattr(value,field.name))
        elif type(value)in(tuple,list):
            for child in value:visit(child)
    if game._frame is not None:
        visit(game._frame.prefix);visit(game._frame.continuation)
        count=len(pending);visit(game._frame.options)
        if len(pending)!=count:raise ValueError('Private stat group cannot be a choice option')
    if len(pending)!=len(set(pending))or any(key not in accepts or key in finishes for key in pending):
        raise ValueError('Stat scramble changed its owed original continuation')
    if game._state.status=='playing'and set(accepts)-set(finishes)!=set(pending):
        raise ValueError('Stat scramble omitted an owed producer group')
    for key,start in starts.items():
        d=dict(start.data);group=accepts[key]
        if (start.source_id,start.player_id)!=(group.source_id,group.player_id)or start.sequence<=key:
            raise ValueError('Stat scramble borrowed another causing source')
        roots=tuple(game._state.pool_summon_history[i-1]for i in d['roots'])
        actual=tuple((x.entity_id,x.entered_order)for x in deliveries(game._state,roots))
        if d['roots']!=dict(group.data)['roots']or d['originals']!=actual:
            raise ValueError('Stat scramble truncated its actual complete producer outputs')
        if len({row[0]for row in d['targets']})!=len(d['targets'])or any((row[0],row[1])not in actual for row in d['targets']):
            raise ValueError('Stat scramble borrowed or duplicated another minion')
        values=tuple(value for _,_,a,h,_,_ in d['targets']for value in(a,h))
        if d['values']!=values:raise ValueError('Stat scramble changed its original individual stat operands')
        rng=Random();rng.setstate(end_turn_rng_from_json(json.loads(d['rng_before'])))
        indices=list(range(len(values)));rng.shuffle(indices)
        if tuple(indices)!=d['indices']or rng.getstate()!=end_turn_rng_from_json(json.loads(d['rng_after'])):
            raise ValueError('Stat scramble changed its original permutation or random state')
        finish=finishes.get(key)
        if finish is None:raise ValueError('Atomic stat scramble lost its original completion')
        changes=[e for e in events if start.sequence<e.sequence<finish.sequence and e.kind=='stats_changed']
        writers=[(i,row)for i,row in enumerate(d['targets'])if row[5]]
        if len(changes)!=len(writers):raise ValueError('Stat scramble lost an ordinary stat assignment')
        applied=[]
        for event,(index,row)in zip(changes,writers):
            _,_,attack,health,maximum,_=row;data=dict(event.data)
            a,h=values[indices[index*2]],values[indices[index*2+1]]
            if (event.source_id,event.target_id,data.get('operation'),data.get('old_attack'),data.get('old_health'),data.get('old_max_health'))!=(
                    start.source_id,row[0],'SetStats',attack,health,maximum):
                raise ValueError('Stat scramble changed its accepted original stat target')
            # Auras may alter visible output; the ordinary local layer is exact.
            applied.append((row[0],data['enchantment_id'],a,h))
            entity=game._state.entities.get(row[0])
            layer=next((x for x in entity.enchantments if x.id==data['enchantment_id']),None)if entity is not None else None
            if layer is not None and (layer.source_id,layer.set_attack,layer.set_health)!=(start.source_id,a,h):
                raise ValueError('Stat scramble changed its actual surviving local stat layer')
        expected=dict(group_event=key,scramble_event=start.sequence,applied=tuple(applied))
        if (finish.source_id,finish.player_id)!=(start.source_id,start.player_id)or canonical_hash(dict(finish.data))!=canonical_hash(expected):
            raise ValueError('Stat scramble changed its complete original result')


def register(mechanics):
    mechanics.register(SummonAndScramble,begin)
    mechanics.register(ScramblePoolSummons,scramble)
