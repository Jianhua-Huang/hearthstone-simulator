"""Physical matching draws with callbacks captured after the whole draw group."""
from dataclasses import dataclass
from .draw_casts import draw_one,draw_record
from .effects import Effect,_behavior,_integer,_player
from .errors import ResolutionError,ResolutionLimitExceeded
from .model import Zone
from .pools import PoolQuery
from .zones import CardReference,reference_entity,source_exists,zone_candidates


def links_value(links,player_id):
    if type(links)is not tuple:raise ValueError('Draw beneficiaries require an immutable ordered tuple')
    previous=0
    for item in links:
        if type(item)is not tuple or len(item)!=2:raise ValueError('Draw beneficiary requires draw ID and hand reference')
        number,card=item;_integer(number,'original draw ID',1)
        if number<=previous or type(card)is not CardReference:raise ValueError('Draw beneficiaries require ordered unique draw IDs')
        card.__post_init__()
        if card.player_id!=player_id or card.zone!=Zone.HAND:raise ValueError('Draw beneficiary differs from its original hand owner')
        previous=number


@dataclass(frozen=True)
class DrawFollowupRequest(Effect):
    player_id:int
    query:PoolQuery
    source_id:int
    behavior_id:str
    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'draw followup source',1);_behavior(self.behavior_id)
        if type(self.query)is not PoolQuery:raise ValueError('Matching draw requires a typed query')
        self.query.__post_init__()


@dataclass(frozen=True)
class DrawMatchingWithFollowup(DrawFollowupRequest):
    count:int=1
    def __post_init__(self):
        super().__post_init__();_integer(self.count,'matching draw count',1)


@dataclass(frozen=True)
class ContinueMatchingDraws(DrawFollowupRequest):
    remaining:int
    draws:tuple[tuple[int,CardReference],...]
    def __post_init__(self):
        super().__post_init__();_integer(self.remaining,'remaining matching draws',0);links_value(self.draws,self.player_id)


@dataclass(frozen=True)
class FinishMatchingDraws(DrawFollowupRequest):
    draws:tuple[tuple[int,CardReference],...]
    def __post_init__(self):
        super().__post_init__();links_value(self.draws,self.player_id)


@dataclass(frozen=True)
class CaptureMatchingDraw(Effect):
    request:ContinueMatchingDraws
    draw_id:int

    def __post_init__(self):
        if type(self.request)is not ContinueMatchingDraws:raise ValueError('Matching capture requires its original continuation')
        self.request.__post_init__();_integer(self.draw_id,'matching original draw',1)
        if self.request.remaining<1:raise ValueError('Matching capture requires an accepted draw slot')

    def validate_in_state(self,state,registry):
        self.__post_init__();validate_request(state,registry,self.request)
        row=draw_record(state,self.draw_id)
        if (row.player_id,row.source_id,row.parent_id)!=(self.request.player_id,self.request.source_id,None):
            raise ValueError('Matching capture borrowed another original draw')


def validate_request(state,registry,request):
    request.__post_init__()
    if request.source_id not in state.entities:raise ResolutionError('Draw followup source does not exist')
    registry.behavior(request.behavior_id)
    from .draw_transformations import hand_reference
    for number,card in getattr(request,'draws',()):
        record=draw_record(state,number);registry.card(card.card_id)
        if (record.player_id,record.source_id)!=(request.player_id,request.source_id)or not record.completed or hand_reference(state,record)!=card:
            raise ResolutionError('Draw beneficiary lost its original completed physical arrival')
        entity=state.entities.get(card.entity_id)
        if entity is None or card.zone_epoch>entity.zone_epoch:raise ResolutionError('Draw beneficiary has an impossible residency')


def validate(r,request):
    validate_request(r.state,r.registry,request)


def begin(r,request):
    validate(r,request)
    if request.count>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Matching draw group exceeds resolution budget')
    return (ContinueMatchingDraws(request.player_id,request.query,request.source_id,request.behavior_id,request.count,()),)


def advance(r,request):
    validate(r,request)
    if request.remaining>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Matching draw group exceeds resolution budget')
    if request.remaining==0:return (FinishMatchingDraws(request.player_id,request.query,request.source_id,request.behavior_id,request.draws),)
    candidates=zone_candidates(r,request.player_id,Zone.DECK,request.query,request.player_id,request.source_id)
    if not candidates:return (FinishMatchingDraws(request.player_id,request.query,request.source_id,request.behavior_id,request.draws),)
    index=len(r.state.draw_history);work=draw_one(r,request.player_id,card=r.game._rng.choice(candidates),source_id=request.source_id)
    record=r.state.draw_history[index]
    return (*work,CaptureMatchingDraw(request,record.id))


def capture(r,effect):
    from .draw_transformations import hand_reference
    effect.validate_in_state(r.state,r.registry);request=effect.request;row=draw_record(r.state,effect.draw_id)
    reference=hand_reference(r.state,row,completed=True);links=request.draws
    if reference is not None and(not request.query.kinds or r.registry.card(reference.card_id).kind in request.query.kinds):
        links=(*links,(row.id,reference))
    return (ContinueMatchingDraws(request.player_id,request.query,request.source_id,request.behavior_id,request.remaining-1,links),)


def finish(r,request):
    validate(r,request);calls=[]
    # Capture every callback against the same post-group state before executing
    # any reward. Stored-card effects preserve those exact original references.
    for number,card in request.draws:
        if reference_entity(r,card)is None:
            r.stale(request,card.entity_id);continue
        calls.append(r.call(request.behavior_id,request.source_id,request.player_id,
            target_id=card.entity_id,draw=draw_record(r.state,number)))
    return tuple(calls)


def register(mechanics):
    mechanics.register(CaptureMatchingDraw,capture)
    mechanics.register(DrawMatchingWithFollowup,begin)
    mechanics.register(ContinueMatchingDraws,advance)
    mechanics.register(FinishMatchingDraws,finish)
