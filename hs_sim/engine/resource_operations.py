"""Capped non-cost Resource consumption with explicit closed delivery profiles.

Only unfinished operations are stored. The debit fact is frozen before ordinary
reactions. The ordinary callback executes after those reactions; an explicitly
bound Hero-at-debit callback runs before the real fatal barrier's parked work.
"""
from dataclasses import dataclass,fields,is_dataclass,replace
from .effects import Effect,RequestChoice,_integer,_player
from .model import CardType,Event,GameState,Resource,Zone,_name,_optional_id

PROFILE='after_resource_reactions'
HERO_PROFILE='hero_lethal_at_debit'
from .hero_lethal_windows import HeroLethalReference

from .allocation_facts import SourceAllocationFact, allocation_from_payload

@dataclass(frozen=True)
class SpendUpToResource(Effect):
    player_id:int
    resource:Resource
    cap:int
    source_id:int|None=None
    on_result:str|None=None
    profile:str=PROFILE
    hero_lethal_reference:HeroLethalReference|None=None

    def __post_init__(self):
        _player(self.player_id);_integer(self.cap,'resource cap',0)
        if type(self.resource) is not Resource:raise ValueError('Expected a known Resource')
        _optional_id(self.source_id,'resource consumption source')
        if self.profile not in (PROFILE,HERO_PROFILE):raise ValueError('Unsupported resource consumption profile')
        if (self.profile==HERO_PROFILE)!=(type(self.hero_lethal_reference) is HeroLethalReference):raise ValueError('Hero-at-debit requires its exact fatal episode reference')
        if self.hero_lethal_reference is not None:
            self.hero_lethal_reference.__post_init__()
            if self.hero_lethal_reference.player_id!=self.player_id:raise ValueError('Hero debit cannot borrow another player account')
        if self.on_result is not None:
            _name(self.on_result,'resource result behavior')
            if self.source_id is None:raise ValueError('Resource result callback requires a physical source')

@dataclass(frozen=True)
class ResourceConsumptionResult:
    operation_id:int
    parent_id:int|None
    event_sequence:int
    action:int
    root_action_number:int
    turn:int
    active_player:int
    player_id:int
    resource:Resource
    cap:int
    balance_before:int
    balance_after:int
    actual_amount:int
    source_id:int|None
    source_card_id:str|None
    source_owner:int|None
    source_controller:int|None
    source_zone:Zone|None
    source_zone_epoch:int|None
    source_entered_order:int|None
    source_allocation:SourceAllocationFact|None
    profile:str=PROFILE
    hero_lethal_reference:HeroLethalReference|None=None

    def __post_init__(self):
        for n in ('operation_id','event_sequence','turn'):_integer(getattr(self,n),n,1)
        for n in ('action','root_action_number','cap','balance_before','balance_after','actual_amount'):_integer(getattr(self,n),n,0)
        if self.root_action_number>self.action:raise ValueError('Resource root is newer than original event action')
        _player(self.active_player);_player(self.player_id);_optional_id(self.parent_id,'resource parent')
        if self.parent_id is not None and self.parent_id>=self.operation_id:raise ValueError('Resource parent must precede its child')
        if type(self.resource) is not Resource or self.profile not in (PROFILE,HERO_PROFILE):raise ValueError('Unsupported resource result/profile')
        if (self.profile==HERO_PROFILE)!=(type(self.hero_lethal_reference) is HeroLethalReference):raise ValueError('Hero result lost its original fatal reference')
        if self.hero_lethal_reference is not None:
            self.hero_lethal_reference.__post_init__()
            if self.hero_lethal_reference.player_id!=self.player_id:raise ValueError('Hero result borrowed another player')
        if self.actual_amount!=min(self.balance_before,self.cap) or self.balance_after!=self.balance_before-self.actual_amount:
            raise ValueError('Capped resource result differs from its actual debit')
        _optional_id(self.source_id,'resource source')
        metadata=(self.source_card_id,self.source_owner,self.source_controller,self.source_zone,self.source_zone_epoch,self.source_entered_order)
        if self.source_id is None:
            if any(v is not None for v in metadata) or self.source_allocation is not None:raise ValueError('Source-less resource result has source metadata')
        else:
            _name(self.source_card_id,'resource source card');_player(self.source_owner);_player(self.source_controller)
            if type(self.source_zone) is not Zone:raise ValueError('Resource source has unknown zone')
            _integer(self.source_zone_epoch,'resource source epoch',0);_integer(self.source_entered_order,'resource source entry',0)
            if type(self.source_allocation) is not SourceAllocationFact:raise ValueError('Resource source requires complete original allocation fact')
            self.source_allocation.__post_init__();a=self.source_allocation
            if (a.entity_id,a.card_id,a.owner,a.controller,a.zone,a.zone_epoch,a.entered_order)!=(self.source_id,self.source_card_id,self.source_owner,self.source_controller,self.source_zone,self.source_zone_epoch,self.source_entered_order):
                raise ValueError('Resource result differs from its original source allocation identity')

    def payload(self):return tuple((f.name,getattr(self,f.name).payload() if getattr(self,f.name) is not None else None) if f.name in ('source_allocation','hero_lethal_reference') else (f.name,getattr(self,f.name)) for f in fields(self))

@dataclass(frozen=True)
class ResourceConsumptionReceipt:
    request:SpendUpToResource
    result:ResourceConsumptionResult
    event:Event
    dispatched:bool=False

    def __post_init__(self):
        if type(self.request) is not SpendUpToResource or type(self.result) is not ResourceConsumptionResult or type(self.event) is not Event or type(self.dispatched) is not bool:
            raise ValueError('Resource receipt requires exactly typed request/result/event')
        self.request.__post_init__();self.result.__post_init__()
        if resource_result(self.event)!=self.result:raise ValueError('Resource receipt differs from its original event')
        if (self.request.player_id,self.request.resource,self.request.cap,self.request.source_id,self.request.profile,self.request.hero_lethal_reference)!=(self.result.player_id,self.result.resource,self.result.cap,self.result.source_id,self.result.profile,self.result.hero_lethal_reference):
            raise ValueError('Resource receipt result differs from its accepted request')
        if self.request.on_result is None and self.dispatched:raise ValueError('Callback-less resource operation cannot dispatch')

@dataclass(frozen=True)
class InvokeResourcePayload(Effect):
    operation_id:int
    def __post_init__(self):_integer(self.operation_id,'resource payload operation',1)

@dataclass(frozen=True)
class FinishResourceConsumption(Effect):
    operation_id:int
    def __post_init__(self):_integer(self.operation_id,'resource finish operation',1)

CONTROL=(InvokeResourcePayload,FinishResourceConsumption)

def resource_result(event):
    if event is None:return None
    if type(event) is not Event:raise ValueError('Resource result requires Event')
    if event.kind!='resource_spent' or 'result' not in dict(event.data):return None
    if len(event.data)!=3 or set(dict(event.data))!={'resource','result','corpse_spend'}:raise ValueError('Capped resource event requires exactly resource/result/corpse_spend')
    raw=dict(event.data)['result']
    if type(raw) is not tuple or any(type(row) is not tuple or len(row)!=2 or type(row[0]) is not str for row in raw):
        raise ValueError('Resource result requires immutable fields')
    values=dict(raw)
    if len(values)!=len(raw) or set(values)!={f.name for f in fields(ResourceConsumptionResult)}:raise ValueError('Resource result requires exactly declared fields')
    values['resource']=Resource(values['resource'])
    if values['source_zone'] is not None:values['source_zone']=Zone(values['source_zone'])
    values['source_allocation']=allocation_from_payload(values['source_allocation'])
    from .hero_lethal_windows import reference_from_payload
    if values['hero_lethal_reference'] is not None:values['hero_lethal_reference']=reference_from_payload(values['hero_lethal_reference'])
    result=ResourceConsumptionResult(**values)
    if (event.sequence,event.action,event.source_id,event.target_id,event.player_id,event.amount,dict(event.data)['resource'])!=(result.event_sequence,result.action,result.source_id,None,result.player_id,result.actual_amount,result.resource.value):
        raise ValueError('Resource event differs from captured result')
    return result

def validate_result(state,registry,result):
    if type(result) is not ResourceConsumptionResult:raise ValueError('Expected ResourceConsumptionResult')
    result.__post_init__()
    if result.hero_lethal_reference is not None:
        from .hero_lethal_windows import validate_reference
        validate_reference(state,registry,result.hero_lethal_reference)
    if result.operation_id>=state.next_resource_operation_id or result.action>state.action_number or result.turn>state.turn:
        raise ValueError('Unknown/future resource operation')
    if result.source_id is not None:
        source=state.entities.get(result.source_id)
        if source is None or result.source_id>=state.next_entity_id or result.source_zone_epoch>source.zone_epoch or result.source_entered_order>=state.next_order:
            raise ValueError('Unknown/future resource physical source')
        if result.source_owner!=source.owner:raise ValueError('Resource source physical owner differs')
        registry.card(result.source_card_id)
        a=result.source_allocation
        if registry.card(a.card_id).kind!=a.kind or a.next_entity_id>state.next_entity_id or a.next_order>state.next_order:
            raise ValueError('Source allocation differs from registered kind/original allocator scope')
        # Faces/controllers are historical fact fields. Rewind may restore an
        # earlier face with the same epoch; the committed event binds this value.

def validate_request(state,registry,request):
    request.__post_init__()
    if request.hero_lethal_reference is not None:
        from .hero_lethal_windows import validate_reference
        validate_reference(state,registry,request.hero_lethal_reference)
    if request.source_id is not None and request.source_id not in state.entities:raise ValueError('Unknown resource consumption source')
    if request.on_result is not None:registry.behavior(request.on_result)

def validate_state(state,registry):
    _integer(state.next_resource_operation_id,'next resource operation ID',1)
    if type(state.resource_operations) is not list:raise ValueError('Resource operations require a list')
    previous=0
    for saved in state.resource_operations:
        if type(saved) is not ResourceConsumptionReceipt:raise ValueError('Expected ResourceConsumptionReceipt')
        saved.__post_init__();validate_request(state,registry,saved.request);validate_result(state,registry,saved.result)
        if saved.result.parent_id!=(previous or None) or saved.result.operation_id<=previous:raise ValueError('Resource operation active parent/LIFO mismatch')
        previous=saved.result.operation_id

def receipt(state,operation_id):
    _integer(operation_id,'resource operation',1)
    row=next((r for r in state.resource_operations if r.result.operation_id==operation_id),None)
    if row is None:raise ValueError('Unknown/already finished resource operation')
    return row

def spend(r,work):
    validate_request(r.state,r.registry,work)
    if work.profile==HERO_PROFILE:
        from .hero_lethal_windows import validate_reference
        validate_reference(r.state,r.registry,work.hero_lethal_reference,active=True)
    elif r.state.active_hero_lethal_root_id is not None:
        raise ValueError('Ordinary after_resource_reactions is unsupported inside a Hero fatal barrier; request explicit hero_lethal_at_debit')
    player=r.player(work.player_id);before=player.resources[work.resource]
    actual=min(before,work.cap);source=r.state.entities.get(work.source_id)
    result=ResourceConsumptionResult(r.state.next_resource_operation_id,
        r.state.resource_operations[-1].result.operation_id if r.state.resource_operations else None,
        len(r.game._events)+1,r.state.action_number,r.root_action_number,r.state.turn,r.state.active_player,work.player_id,
        work.resource,work.cap,before,before-actual,actual,work.source_id,
        source.card_id if source else None,source.owner if source else None,source.controller if source else None,
        source.zone if source else None,source.zone_epoch if source else None,source.entered_order if source else None,
        SourceAllocationFact.capture(r.state,source),work.profile,work.hero_lethal_reference)
    r.state.next_resource_operation_id+=1;player.resources[work.resource]=result.balance_after
    from .resources import commit_corpse_spend
    corpse_row=commit_corpse_spend(r.state,work.player_id,before,actual,'capped',work.source_id,result.operation_id)
    event=Event(result.event_sequence,result.action,'resource_spent',result.source_id,None,result.player_id,result.actual_amount,
        tuple(sorted(dict(resource=result.resource.value,result=result.payload(),corpse_spend=corpse_row.payload()).items())))
    r.state.resource_operations.append(ResourceConsumptionReceipt(work,result,event))
    emitted=r.emit('resource_spent',source_id=work.source_id,player_id=work.player_id,amount=actual,
        resource=work.resource.value,result=result.payload(),_corpse_spend_record=corpse_row)
    if emitted!=event:raise ValueError('Resource debit emission changed its original fact')
    return ([InvokeResourcePayload(result.operation_id)] if work.on_result is not None else [])+[FinishResourceConsumption(result.operation_id)]

def invoke(r,work):
    saved=receipt(r.state,work.operation_id)
    if saved is not r.state.resource_operations[-1] or saved.dispatched or saved.request.on_result is None:raise ValueError('Resource payload is not the pending LIFO operation')
    r.state.resource_operations[-1]=replace(saved,dispatched=True)
    return [r.call(saved.request.on_result,saved.result.source_id,saved.result.player_id,event=saved.event)]

def finish(r,work):
    saved=receipt(r.state,work.operation_id)
    if saved is not r.state.resource_operations[-1] or saved.request.on_result is not None and not saved.dispatched:
        raise ValueError('Resource operation cannot finish before payload/child')
    r.state.resource_operations.pop()

def validate_queue(state,registry,queue):
    validate_state(state,registry)
    actual=[(type(w),w.operation_id) for w in queue if type(w) in CONTROL];expected=[]
    for saved in reversed(state.resource_operations):
        if saved.request.on_result is not None and not saved.dispatched:expected.append((InvokeResourcePayload,saved.result.operation_id))
        expected.append((FinishResourceConsumption,saved.result.operation_id))
    if actual!=expected:raise ValueError('Resource progress and complete ordered Invoke/Finish LIFO disagree')

def reject_choice_control(value):
    def visit(v,depth):
        if depth>64:raise ValueError('Resource choice nesting exceeds codec limit')
        if type(v) in CONTROL:raise ValueError('Resource control work cannot be offered in a choice')
        if isinstance(v,(tuple,list)):
            for item in v:visit(item,depth+1)
        elif isinstance(v,dict):
            for item in v.values():visit(item,depth+1)
        elif is_dataclass(v) and not isinstance(v,type):
            for f in fields(v):visit(getattr(v,f.name),depth+1)
    visit(value,0)

def validate_boundary(game):
    frame=game._frame
    validate_queue(game._state,game.registry,(*frame.prefix,*frame.continuation) if frame else ())
    def committed(event,limit=None):
        if event.sequence>len(game._events) or limit is not None and event.sequence>limit or game._events[event.sequence-1]!=event:
            raise ValueError('Resource receipt differs from original committed event/window')
    def state_events(state,limit=None):
        validate_state(state,game.registry)
        for saved in state.resource_operations:committed(saved.event,limit)
    state_events(game._state)
    if frame is None:return
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    def visit(value,scope,forbid=False,limit=None,depth=0):
        if depth>64:raise ValueError('Resource frame nesting exceeds codec limit')
        if type(value) in CONTROL and forbid:raise ValueError('Resource control work cannot be forged in a choice/payload')
        if type(value) is SpendUpToResource:validate_request(scope,game.registry,value)
        if type(value) is RuleContext:
            state_events(value.state,limit)
            for f in fields(value):
                if f.name!='state':visit(getattr(value,f.name),value.state,forbid,limit,depth+1)
            return
        if type(value) is PaidHandChoiceBoundaryProof:
            # This is the original accepted work, never today's active stack.
            state_events(value.state,value.event.sequence)
            validate_queue(value.state,game.registry,value.work)
            visit(value.event,value.state,False,value.event.sequence,depth+1)
            visit(value.work,value.state,False,value.event.sequence,depth+1)
            return
        if type(value) is GameState:return
        if type(value) is Event:
            result=resource_result(value)
            if result is not None:validate_result(scope,game.registry,result);committed(value,limit)
            return
        if type(value) is ResourceConsumptionResult:
            validate_result(scope,game.registry,value)
            if value.event_sequence>len(game._events) or limit is not None and value.event_sequence>limit or resource_result(game._events[value.event_sequence-1])!=value:
                raise ValueError('Resource result differs from original committed result/window')
        if isinstance(value,(tuple,list)):
            for item in value:visit(item,scope,forbid,limit,depth+1)
        elif isinstance(value,dict):
            for item in value.values():visit(item,scope,forbid,limit,depth+1)
        elif is_dataclass(value) and not isinstance(value,type):
            for f in fields(value):visit(getattr(value,f.name),scope,forbid,limit,depth+1)
    for work in (*frame.prefix,*frame.continuation):visit(work,game._state)
    visit(frame.options,game._state,True)
    visit(frame.paid_hand_choice_boundary,game._state)

def interrupt(r,queue):
    validate_queue(r.state,r.registry,queue);r.state.resource_operations.clear()

def validate_committed_events(game):
    """Outer real restore only. Virtual/captured states keep their own scopes.

    Retry retains events, allocator clocks and source facts while deleting newly
    created entities. Its old source is proved by the complete original narrow
    allocation fact, rather than a blanket missing-entity exception or today's
    source face/zone. This is structural validation, not signed provenance.
    """
    from .hero_lethal_windows import validate_committed_events as validate_hero_facts
    hero_facts=validate_hero_facts(game)
    state=game._state;seen={};previous=0
    for event in game._events:
        result=resource_result(event)
        if result is None:continue
        if not previous<result.operation_id<state.next_resource_operation_id or result.action>state.action_number or result.turn>state.turn:
            raise ValueError('Committed resource fact has unknown/future operation or event clock')
        if result.hero_lethal_reference is not None and hero_facts.get(result.hero_lethal_reference.episode_id)!=result.hero_lethal_reference:raise ValueError('Committed Hero resource result lost its genuine original fatal fact')
        if result.parent_id is not None:
            parent=seen.get(result.parent_id)
            if parent is None or parent.root_action_number!=result.root_action_number:raise ValueError('Committed resource parent is absent from original root')
        if result.source_id is not None:
            a=result.source_allocation
            a.__post_init__()
            if game.registry.card(a.card_id).kind!=a.kind or a.next_entity_id>state.next_entity_id or a.next_order>state.next_order:
                raise ValueError('Committed resource source allocation is unknown/future or unregistered')
            # Owner identifies this physical source. Current form/zone/epoch may
            # legitimately differ, or Retry may have removed this identity.
            current=state.entities.get(a.entity_id)
            if current is not None and current.owner!=a.owner:raise ValueError('Committed resource source has another physical owner')
        seen[result.operation_id]=result;previous=result.operation_id

def register(mechanics):
    mechanics.register(SpendUpToResource,spend).register(InvokeResourcePayload,invoke).register(FinishResourceConsumption,finish)
    mechanics.register_payload_type(ResourceConsumptionResult).register_payload_type(ResourceConsumptionReceipt)
    mechanics.register_payload_type(SourceAllocationFact)
