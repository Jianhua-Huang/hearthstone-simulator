"""Per-player future minion templates; physical entities keep ordinary rules.

Replacement records retain complete pools and replay their own RNG locally.
Summon recipes freeze a family revision, then delegate each actual entry to
SummonByCard. Empty cost tiers retain explicit vacant roles, never fake cards.
"""
from dataclasses import asdict,dataclass
import json
from random import Random

from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .model import CardType,_name,validate_end_turn_rng
from .pools import GenerationContext,GenerationPolicy,PoolMember,PoolQuery,resolve_candidates,sample_candidates
from .summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial,validate_cause


@dataclass(frozen=True)
class MinionFamilyProfile:
    id:str
    version:str
    base_card_ids:tuple[str,...]
    pool_id:str
    tribe:str

    def __post_init__(self):
        for field in ('id','version','pool_id','tribe'):_name(getattr(self,field),'minion family '+field)
        if(type(self.base_card_ids)is not tuple or not self.base_card_ids or
                any(type(x)is not str or not x for x in self.base_card_ids)or
                len(set(self.base_card_ids))!=len(self.base_card_ids)):
            raise ValueError('Minion family requires ordered distinct base roles')


@dataclass(frozen=True)
class FamilyMember:
    card_id:str|None
    cost:int

    def __post_init__(self):
        if self.card_id is not None:_name(self.card_id,'family member card')
        _integer(self.cost,'family member printed cost or vacant tier',0)


@dataclass(frozen=True)
class FamilyReference:
    family_id:str
    player_id:int
    revision:int=0

    def __post_init__(self):
        _name(self.family_id,'minion family');_player(self.player_id)
        _integer(self.revision,'original family revision',0)


@dataclass(frozen=True)
class UpgradeMinionFamily(Effect):
    family_id:str
    cause:SummonCause
    increment:int

    def __post_init__(self):
        _name(self.family_id,'minion family')
        if type(self.cause)is not SummonCause:raise ValueError('Family replacement requires its original card cause')
        self.cause.__post_init__();_integer(self.increment,'future family cost increase',1)


@dataclass(frozen=True)
class SummonFamilyMember(Effect):
    family:FamilyReference
    cause:SummonCause
    slot:int|None=None

    def __post_init__(self):
        if type(self.family)is not FamilyReference or type(self.cause)is not SummonCause:
            raise ValueError('Family entry requires typed original family and cause')
        self.family.__post_init__();self.cause.__post_init__()
        if self.family.player_id!=self.cause.player_id:raise ValueError('Family entry borrowed another player')
        if self.slot is not None:_integer(self.slot,'original family role',0)


@dataclass(frozen=True)
class FamilyReplacementRecord:
    id:int
    event_cursor:int
    turn:int
    action:int
    request:UpgradeMinionFamily
    previous:FamilyReference
    profile_version:str
    context:GenerationContext
    pool_version:str
    old_members:tuple[FamilyMember,...]
    candidates:tuple[tuple[PoolMember,...],...]
    members:tuple[FamilyMember,...]
    rng_before:tuple
    rng_after:tuple

    def __post_init__(self):
        for field in ('id','turn'):_integer(getattr(self,field),'family replacement '+field,1)
        for field in ('event_cursor','action'):_integer(getattr(self,field),'family replacement '+field,0)
        if type(self.request)is not UpgradeMinionFamily or type(self.previous)is not FamilyReference:
            raise ValueError('Replacement requires its typed request and previous revision')
        self.request.__post_init__();self.previous.__post_init__()
        if(self.previous.family_id,self.previous.player_id)!=(self.request.family_id,self.request.cause.player_id):
            raise ValueError('Replacement borrowed another family or player')
        for field in ('profile_version','pool_version'):_name(getattr(self,field),'original '+field)
        if type(self.context)is not GenerationContext:raise ValueError('Original host generation context required')
        self.context.__post_init__()
        for field in ('old_members','members'):
            values=getattr(self,field)
            if type(values)is not tuple or not values or any(type(x)is not FamilyMember for x in values):
                raise ValueError('Complete ordered family roles required')
            for value in values:value.__post_init__()
        if(type(self.candidates)is not tuple or len(self.candidates)!=len(self.old_members)or
                len(self.members)!=len(self.old_members)):
            raise ValueError('Each original role requires its complete candidate inventory and result')
        for pool in self.candidates:
            if type(pool)is not tuple or any(type(x)is not PoolMember for x in pool):
                raise ValueError('Typed complete replacement pool required')
            for member in pool:member.__post_init__()
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)


def validate_profiles(registry):
    for profile in registry.minion_family_profiles.values():
        profile.__post_init__()
        for cid in profile.base_card_ids:
            if registry.card(cid).kind!=CardType.MINION:raise ValueError('Family base must be a complete minion')


def capture(state,registry,family_id,player_id):
    registry.minion_family_profile(family_id);_player(player_id)
    revision=next((row.id for row in reversed(state.minion_family_history)
        if(row.request.family_id,row.request.cause.player_id)==(family_id,player_id)),0)
    return FamilyReference(family_id,player_id,revision)


def members(state,registry,reference):
    reference.__post_init__();profile=registry.minion_family_profile(reference.family_id)
    if not reference.revision:
        return tuple(FamilyMember(cid,registry.card(cid).cost)for cid in profile.base_card_ids)
    if reference.revision>len(state.minion_family_history):raise ValueError('Future or missing family revision')
    row=state.minion_family_history[reference.revision-1]
    if(row.id,row.request.family_id,row.request.cause.player_id)!=(reference.revision,reference.family_id,reference.player_id):
        raise ValueError('Original family revision borrowed another player or family')
    return row.members


def candidates(registry,profile,context,cause,old_members,increment):
    source=cause.cast_card_id if cause.origin=='spell_cast'else cause.source.card_id
    # Resolve every tier before selecting even the first role. Missing adapters
    # and unknown complete host inventories cannot consume RNG or crop a pool.
    return tuple(resolve_candidates(registry,context,profile.pool_id,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=(profile.tribe,),
            min_cost=old.cost+increment,max_cost=old.cost+increment),
        source_card_id=source,player_id=cause.player_id,exclude_source_by_rule=True)
        for old in old_members)


def select(registry,pools,old_members,increment,rng):
    selected=[]
    for pool,old in zip(pools,old_members):
        chosen=sample_candidates(rng,pool,1,replacement=True)
        cid=chosen[0]if chosen else None
        selected.append(FamilyMember(cid,registry.card(cid).cost if cid is not None else old.cost+increment))
    return tuple(selected)


def validate_request(state,registry,request,*,closed=False):
    request.__post_init__();registry.minion_family_profile(request.family_id)
    validate_cause(state,registry,request.cause,closed=closed)


def upgrade(r,request):
    validate_request(r.state,r.registry,request)
    profile=r.registry.minion_family_profile(request.family_id)
    previous=capture(r.state,r.registry,profile.id,request.cause.player_id)
    old=members(r.state,r.registry,previous)
    context=r.game._generation_context
    pool=r.registry.pool(profile.pool_id,context)
    pools=candidates(r.registry,profile,context,request.cause,old,request.increment)
    before=r.game._rng.getstate()
    selected=select(r.registry,pools,old,request.increment,r.game._rng)
    row=FamilyReplacementRecord(len(r.state.minion_family_history)+1,len(r.game._events),
        r.state.turn,r.state.action_number,request,previous,profile.version,context,pool.version,
        old,pools,selected,before,r.game._rng.getstate())
    r.state.minion_family_history.append(row)
    r.emit('minion_family_replaced',source_id=request.cause.source.entity_id,
        player_id=request.cause.player_id,amount=request.increment,
        record=json.dumps(asdict(row),sort_keys=True,separators=(',',':')),_capture=False)
    return ()


def validate_summon(state,registry,request,*,closed=False):
    request.__post_init__();validate_cause(state,registry,request.cause,closed=closed)
    values=members(state,registry,request.family)
    if request.slot is not None and request.slot>=len(values):raise ValueError('Unknown original family role')
    for value in values:
        if value.card_id is not None and(registry.card(value.card_id).kind!=CardType.MINION or
                registry.card(value.card_id).cost!=value.cost):
            raise ValueError('Family entry lost its complete printed minion material')


def summon(r,request):
    validate_summon(r.state,r.registry,request)
    values=members(r.state,r.registry,request.family)
    if len(r.player(request.cause.player_id).board)>=r.rules.max_board:
        r.emit('random_choice_skipped',source_id=request.cause.source.entity_id,reason='board_full')
        return ()
    slot=request.slot
    if slot is None:
        slot=r.game._rng.randrange(len(values))
        r.emit('random_choice',source_id=request.cause.source.entity_id,
            candidates=tuple(str(i)for i in range(len(values))),selected=str(slot))
    cid=values[slot].card_id
    if cid is None:
        r.emit('random_choice_skipped',source_id=request.cause.source.entity_id,reason='vacant_family_role')
        return ()
    return(SummonByCard(request.cause.player_id,(SummonEntryMaterial(cid),),request.cause),)


def validate_state(state,registry):
    if type(state.minion_family_history)is not list:raise ValueError('Ordered minion family history required')
    latest={};last_window=(0,0,-1)
    for index,row in enumerate(state.minion_family_history,1):
        if type(row)is not FamilyReplacementRecord:raise ValueError('Typed family replacement record required')
        row.__post_init__();validate_request(state,registry,row.request,closed=True)
        profile=registry.minion_family_profile(row.request.family_id)
        key=(profile.id,row.request.cause.player_id)
        if(row.id!=index or row.previous.revision!=latest.get(key,0)or
                row.profile_version!=profile.version or row.turn>state.turn or row.action>state.action_number or
                row.request.cause.turn>row.turn or row.request.cause.action>row.action or
                (row.turn,row.action,row.event_cursor)<=last_window):
            raise ValueError('Family replacement lost its original ordered acceptance or profile')
        if row.old_members!=members(state,registry,row.previous):raise ValueError('Replacement rewrote its original family')
        if registry.pool(profile.pool_id,row.context).version!=row.pool_version:
            raise ValueError('Replacement host pool version changed')
        expected=candidates(registry,profile,row.context,row.request.cause,row.old_members,row.request.increment)
        if expected!=row.candidates:raise ValueError('Replacement cropped or changed its complete original pools')
        rng=Random();rng.setstate(row.rng_before)
        if(select(registry,expected,row.old_members,row.request.increment,rng)!=row.members or
                rng.getstate()!=row.rng_after):
            raise ValueError('Replacement members differ from the original pools and RNG')
        latest[key]=row.id;last_window=(row.turn,row.action,row.event_cursor)


def validate_boundary(game):
    from .hero_health_history import effective_events
    rows=game._state.minion_family_history
    events=[e for e in effective_events(game._events)if e.kind=='minion_family_replaced']
    if len(rows)!=len(events):raise ValueError('Family replacement lost its complete committed event inventory')
    for row,event in zip(rows,events):
        if(row.context!=game._generation_context or event.sequence!=row.event_cursor+1 or
                (event.source_id,event.player_id,event.amount,event.target_id)!=(
                    row.request.cause.source.entity_id,row.request.cause.player_id,row.request.increment,None)or
                dict(event.data)!={'record':json.dumps(asdict(row),sort_keys=True,separators=(',',':'))}):
            raise ValueError('Family replacement changed its host context or original event receipt')


def from_dict(cls,value):
    from .serialization import _list,_row,end_turn_rng_from_json
    from .summon_quantities import from_dict as entry_from_dict
    row=_row(value,cls)
    if cls is FamilyReplacementRecord:
        row['request']=from_dict(UpgradeMinionFamily,row['request'])
        row['previous']=from_dict(FamilyReference,row['previous'])
        row['context']=GenerationContext.from_dict(row['context'])
        for field in ('old_members','members'):
            row[field]=tuple(from_dict(FamilyMember,x)for x in _list(row[field],'Family roles'))
        row['candidates']=tuple(tuple(PoolMember(**_row(x,PoolMember))for x in _list(pool,'Family pool'))
            for pool in _list(row['candidates'],'All family pools'))
        for field in ('rng_before','rng_after'):row[field]=end_turn_rng_from_json(row[field])
    elif cls in(UpgradeMinionFamily,SummonFamilyMember):
        row['cause']=entry_from_dict(SummonCause,row['cause'])
        if cls is SummonFamilyMember:row['family']=from_dict(FamilyReference,row['family'])
    elif cls not in(FamilyReference,FamilyMember):raise ValueError('Unknown minion family codec type')
    return cls(**row)


def register(mechanics):
    mechanics.register(UpgradeMinionFamily,upgrade)
    mechanics.register(SummonFamilyMember,summon)
    for cls in(FamilyReference,FamilyMember):mechanics.register_payload_type(cls)
