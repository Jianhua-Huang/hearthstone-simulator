"""Actual native Kindred components and one-use original max2 player sources."""
from copy import copy
from dataclasses import dataclass,replace
from .effects import Effect
from .model import CardType,ChoiceResult,KindredActivation,KindredProfile,KindredRecord,OwnerTurnQueryBoundaryFact,Zone
from .owner_turns import query_for_definition,query_previous_owner_turn,validate_accepted_prefix
from .player_effects import RemovePlayerEffect
from .registry import RuleContext


def validate_profile(registry,profile):
    if type(profile)is not KindredProfile:raise ValueError('Expected a complete native Kindred profile')
    profile.__post_init__();card=registry.card(profile.card_id)
    if card.kind not in(CardType.MINION,CardType.SPELL):raise ValueError('Kindred requires an actual minion or spell')
    if profile.mode=='cost':
        if len(card.intrinsic_costs)!=1 or card.intrinsic_costs[0].condition!='previous_owner_turn_type' or card.intrinsic_costs[0].delta!=-2:
            raise ValueError('Native Kindred cost requires its actual intrinsic two-Mana reduction')
    elif profile.wrapper not in(card.on_play,card.battlecry):raise ValueError('Kindred wrapper is not a real native entry')
    for name in('wrapper','active','prepare','inactive'):
        key=getattr(profile,name)
        if key is not None:registry.behavior(key)


def sources(state,registry,player_id):
    return tuple(sorted((x for x in state.players[player_id].player_effects
        if registry.player_effect(x.spec_id).kind=='next_kindred'),key=lambda x:x.id))


def validate_sources(registry,values):
    for x in values:
        x.__post_init__()
        if registry.player_effect(x.spec_id).kind!='next_kindred':raise ValueError('Kindred source borrowed another player effect kind')


def validate_activation(activation,registry):
    if type(activation)is not KindredActivation:raise ValueError('Expected original Kindred acceptance')
    activation.__post_init__();c=activation.original;profile=registry.kindred_profiles.get(activation.card_id)
    if profile is None or profile.mode!='body':raise ValueError('Kindred acceptance lost its native body declaration')
    validate_profile(registry,profile)
    if c.source_id not in c.state.entities or c.player_id not in c.state.players:raise ValueError('Kindred acceptance has an unknown caller')
    expected=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card(profile.card_id)))
    if expected!=activation.condition or activation.sources!=sources(c.state,registry,c.player_id):
        raise ValueError('Kindred acceptance changed its complete original condition or source inventory')
    if activation.record_id!=len(c.state.kindred_history)+1:
        raise ValueError('Kindred acceptance changed its original execution identity')
    validate_sources(registry,activation.sources)


def validate_request(effect,registry):
    effect.__post_init__();c=effect.caller;profile=registry.kindred_profiles.get(effect.card_id)
    if profile is None or profile.mode!='body':raise ValueError('Kindred request has no native body profile')
    if c.source_id not in c.state.entities or c.player_id not in c.state.players:raise ValueError('Kindred request has an unknown original caller')
    identities={c.source.card_id}
    for row in(c.play,c.cast):
        if row is not None and(row.source_id,row.player_id)==(c.source_id,c.player_id):identities.add(row.card_id)
    if effect.card_id not in identities:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Kindred body grants with another printed subject require an actual reviewed source policy')


def context_kwargs(c):
    return{name:getattr(c,name)for name in('event','death','choice','player_effect','window','play','trigger','cast','draw',
        'power','battlecry','combo','deathrattle','power_payload','end_turn','physical','discard')}


@dataclass(frozen=True)
class ResolveKindred(Effect):
    caller:RuleContext
    card_id:str
    def __post_init__(self):
        if type(self.caller)is not RuleContext or self.caller.kindred is not None or type(self.card_id)is not str or not self.card_id:
            raise ValueError('Kindred request requires its independent actual caller and definition')


@dataclass(frozen=True)
class RunKindredComponent(Effect):
    activation:KindredActivation
    role:str='active'
    prepared_choice:ChoiceResult|None=None
    def __post_init__(self):
        if type(self.activation)is not KindredActivation or self.role not in('active','prepare','inactive'):
            raise ValueError('Kindred component requires an original acceptance and real role')
        self.activation.__post_init__()
        if self.prepared_choice is not None:
            if self.role!='active':raise ValueError('Prepared choice belongs to a real active Kindred component')
            validate_prepared_choice(self.activation,self.prepared_choice)


@dataclass(frozen=True)
class FinishKindredComponent(Effect):
    record_id:int
    index:int
    def __post_init__(self):
        if type(self.record_id)is not int or self.record_id<1 or type(self.index)is not int or self.index<0:
            raise ValueError('Kindred completion requires its exact component identity')


@dataclass(frozen=True)
class FinishKindred(Effect):
    activation:KindredActivation
    def __post_init__(self):
        if type(self.activation)is not KindredActivation:raise ValueError('Kindred completion lost its original acceptance')
        self.activation.__post_init__()


def plan(profile,condition,repetitions):
    if profile.prepare is not None:
        return('prepare',)+(('active',)*repetitions if condition.matched and profile.active is not None else())
    return('active',)*repetitions if condition.matched else(('inactive',)if profile.inactive is not None else())


def accepted_record(activation,event_cursor):
    from .allocation_facts import SourceAllocationFact
    c=activation.original;s=c.state
    boundary=OwnerTurnQueryBoundaryFact(s.turn,s.action_number,s.status,len(s.owner_turn_history),len(s.play_history),
        s.owner_turn_history[-1]if s.owner_turn_history else None,
        None if s.opening is None else s.opening.stage,None if s.opening is None else s.opening.first_player)
    return KindredRecord(activation.record_id,activation.card_id,SourceAllocationFact.capture(s,c.source),c.player_id,
        s.turn,s.action_number,event_cursor,boundary,activation.condition,activation.sources,activation.repetitions,())


def record(state,record_id):
    if type(record_id)is not int or not 1<=record_id<=len(state.kindred_history):raise ValueError('Unknown Kindred execution identity')
    value=state.kindred_history[record_id-1]
    if value.id!=record_id:raise ValueError('Kindred history lost its original order')
    return value


def validate_record_activation(state,registry,activation):
    validate_activation(activation,registry);value=record(state,activation.record_id)
    expected=accepted_record(activation,value.event_cursor)
    profile=registry.kindred_profiles[activation.card_id]
    expected=replace(expected,plan=plan(profile,activation.condition,activation.repetitions))
    if replace(value,started=(),stack=(),finished=(),completed=False,interruption=None)!=expected:
        raise ValueError('Kindred progress changed its complete accepted plan or original caller')
    validate_accepted_prefix(activation.original.state,state,registry)
    return value


def validate_component(effect,registry):
    effect.__post_init__();validate_activation(effect.activation,registry)
    profile=registry.kindred_profiles[effect.activation.card_id]
    if getattr(profile,effect.role)is None or effect.role not in plan(profile,effect.activation.condition,effect.activation.repetitions):
        raise ValueError('Kindred component contradicts its declared role or original qualification')
    if effect.prepared_choice is not None and profile.prepare is None:
        raise ValueError('Prepared Kindred group requires its original preparation profile')


def validate_prepared_choice(activation,result):
    if type(activation)is not KindredActivation or type(result)is not ChoiceResult:
        raise ValueError('Kindred group requires typed original acceptance and result')
    activation.__post_init__();result.__post_init__();old=activation.original;choice=result.choice
    if ((choice.source_id,choice.player_id)!=(old.source_id,old.player_id)or
            choice.min_count!=0 or choice.max_count!=0 or result.selected_ids or choice.repeat_key is not None):
        raise ValueError('Prepared Kindred group changed its original automatic caller')


def validate_preparation(state,registry,activation):
    value=validate_record_activation(state,registry,activation)
    profile=registry.kindred_profiles[activation.card_id]
    if (profile.prepare is None or value.completed or value.interruption is not None or
            not any(value.started[index]=='prepare' for index in value.stack)):
        raise ValueError('Kindred sampled callback lost its actual active preparation')
    return value


def request(c,card_id):return(ResolveKindred(c,card_id),)


def resolve(r,effect):
    validate_request(effect,r.registry);c=effect.caller;profile=r.registry.kindred_profiles.get(effect.card_id)
    if profile is None or profile.mode!='body':raise ValueError('Kindred request has no complete native body profile')
    validate_profile(r.registry,profile)
    # The body window is real and current; its roots retain original provenance.
    key=profile.prepare or profile.active
    accepted=r.call(key,c.source_id,c.player_id,c.target_id,**context_kwargs(c)).context
    condition=query_previous_owner_turn(accepted.state,c.player_id,query_for_definition(r.registry.card(effect.card_id)))
    original_sources=sources(accepted.state,r.registry,c.player_id)
    activation=KindredActivation(effect.card_id,accepted,condition,original_sources,2 if original_sources else 1,len(r.state.kindred_history)+1)
    validate_activation(activation,r.registry)
    value=accepted_record(activation,len(r.game._events))
    r.state.kindred_history.append(replace(value,plan=plan(profile,condition,activation.repetitions)))
    result=[RemovePlayerEffect(c.player_id,x.id)for x in original_sources]
    if profile.prepare is not None:result.append(RunKindredComponent(activation,'prepare'))
    elif condition.matched:result.extend(RunKindredComponent(activation)for _ in range(activation.repetitions))
    elif profile.inactive is not None:result.append(RunKindredComponent(activation,'inactive'))
    result.append(FinishKindred(activation))
    return result


def run(r,effect):
    validate_component(effect,r.registry);activation=effect.activation
    profile=r.registry.kindred_profiles[activation.card_id];key=getattr(profile,effect.role)
    value=validate_record_activation(r.state,r.registry,activation);index=len(value.started)
    if value.completed or value.interruption is not None or index>=len(value.plan)or value.plan[index]!=effect.role:
        raise ValueError('Kindred component lost its next accepted execution identity')
    r.state.kindred_history[value.id-1]=replace(value,started=(*value.started,effect.role),stack=(*value.stack,index))
    c=activation.original
    validate_accepted_prefix(c.state,r.state,r.registry)
    kwargs=context_kwargs(c)
    if effect.prepared_choice is not None:
        validate_preparation(r.state,r.registry,activation)
        if effect.prepared_choice.choice.id>=r.state.next_choice_id:raise ValueError('Prepared Kindred group has a future choice identity')
        kwargs['choice']=effect.prepared_choice
    return(r.call(key,c.source_id,c.player_id,c.target_id,**kwargs,kindred=activation),FinishKindredComponent(value.id,index))


def finish_component(r,effect):
    value=record(r.state,effect.record_id)
    if value.completed or value.interruption is not None or not value.stack or value.stack[-1]!=effect.index:
        raise ValueError('Kindred component completion changed its accepted nesting or identity')
    r.state.kindred_history[value.id-1]=replace(value,stack=value.stack[:-1],finished=(*value.finished,effect.index))
    return()


def finish(r,effect):
    value=validate_record_activation(r.state,r.registry,effect.activation)
    if value.completed or value.interruption is not None or value.stack or value.started!=value.plan or len(value.finished)!=len(value.plan):
        raise ValueError('Kindred completion truncated or duplicated its accepted plan')
    r.state.kindred_history[value.id-1]=replace(value,completed=True)
    return()


def condition_prefix(state,registry,value):
    boundary=value.boundary
    if boundary.owner_history_length>len(state.owner_turn_history)or boundary.play_history_length>len(state.play_history)or boundary.turn>state.turn or boundary.action>state.action_number:
        raise ValueError('Kindred lost its complete accepted history prefix')
    before=copy(state)
    before.turn,before.action_number,before.status=boundary.turn,boundary.action,boundary.status
    before.owner_turn_history=list(state.owner_turn_history[:boundary.owner_history_length])
    before.play_history=list(state.play_history[:boundary.play_history_length])
    if before.owner_turn_history:
        before.owner_turn_history[-1]=boundary.last_owner_turn;before.active_player=boundary.last_owner_turn.player_id
    if boundary.opening_stage is None:
        if before.opening is not None:raise ValueError('Kindred changed its actual opening origin')
    else:
        if before.opening is None or before.opening.first_player!=boundary.opening_first_player:raise ValueError('Kindred changed its original opening identity')
        before.opening=replace(before.opening,stage=boundary.opening_stage,
            starting_hands=before.opening.starting_hands if boundary.opening_stage=='complete'else None)
    validate_accepted_prefix(before,state,registry)
    if query_previous_owner_turn(before,value.player_id,query_for_definition(registry.card(value.card_id)))!=value.condition:
        raise ValueError('Kindred changed its complete frozen true/false relation')


def validate_records(state,registry):
    from .allocation_facts import validate_allocation
    if type(state.kindred_history)is not list:raise ValueError('Kindred history requires an ordered list')
    used=set();paid={x.id for row in state.cost_use_history for x in row.kindred_sources}
    previous=None
    for index,value in enumerate(state.kindred_history,1):
        if type(value)is not KindredRecord:raise ValueError('Kindred history requires typed original records')
        value.__post_init__();profile=registry.kindred_profiles.get(value.card_id)
        if value.id!=index or profile is None or profile.mode!='body' or value.plan!=plan(profile,value.condition,value.repetitions):
            raise ValueError('Kindred history changed its declared complete plan')
        if previous is not None and(value.turn<previous.turn or value.action<previous.action or value.event_cursor<previous.event_cursor):
            raise ValueError('Kindred history changed its original chronology')
        validate_allocation(state,registry,value.source)
        validate_sources(registry,value.sources)
        for source in value.sources:
            if source.id>=state.next_attachment_id or source.entered_order>=state.next_order or source.created_turn>value.turn or source.source_id not in state.entities or source.id in used or source.id in paid:
                raise ValueError('Kindred source changed its allocation, owner use or one-use identity')
            used.add(source.id)
        condition_prefix(state,registry,value);previous=value


def validate_boundary(game):
    from .resolver import BehaviorCall,ResolveChoiceResult
    from .effects import RequestChoice
    state=game._state;validate_records(state,game.registry)
    queue=(*game._frame.prefix,*game._frame.continuation)if game._frame else()
    known={x.id for x in state.kindred_history}
    if any(type(x)is FinishKindredComponent and x.record_id not in known or type(x)in(RunKindredComponent,FinishKindred)and x.activation.record_id not in known for x in queue):
        raise ValueError('Kindred continuation references an unknown accepted root')
    for value in state.kindred_history:
        roots=[x for x in queue if type(x)is FinishKindred and x.activation.record_id==value.id]
        runs=[x for x in queue if type(x)is RunKindredComponent and x.activation.record_id==value.id]
        ends=[x.index for x in queue if type(x)is FinishKindredComponent and x.record_id==value.id]
        if value.event_cursor>len(game._events):raise ValueError('Kindred event cursor is newer than its actual history')
        if value.interruption is not None:
            event,action=value.interruption
            matches=[e for e in game._events if(e.sequence,e.action,e.kind)==(event,action,'game_ended')]
            if state.status=='playing'or game._frame is not None or len(matches)!=1 or event<=value.event_cursor:
                raise ValueError('Kindred interruption lost its actual terminal witness')
        if value.completed or value.interruption is not None:
            if roots or runs or ends:raise ValueError('Closed Kindred root retained executable work')
        else:
            if len(roots)!=1 or ends!=list(reversed(value.stack)):
                raise ValueError('Pending Kindred root lost its unique completion or component identities')
            end_index=queue.index(roots[0])
            if any(i>=end_index for i,x in enumerate(queue)if type(x)is FinishKindredComponent and x.record_id==value.id or type(x)is RunKindredComponent and x.activation.record_id==value.id):
                raise ValueError('Pending Kindred completion precedes its accepted component work')
            validate_record_activation(state,game.registry,roots[0].activation)
            profile=game.registry.kindred_profiles[value.card_id]
            preparing=any(type(x)is BehaviorCall and x.behavior_id==profile.prepare and x.context.kindred is not None and x.context.kindred.record_id==value.id for x in queue)
            deferred=[x for x in queue if type(x)in(RequestChoice,ResolveChoiceResult)and
                x.kindred is not None and x.kindred.record_id==value.id]
            if deferred:
                if len(deferred)!=1 or deferred[0].kindred!=roots[0].activation:
                    raise ValueError('Kindred preparation duplicated or changed its original sampled callback')
                validate_preparation(state,game.registry,deferred[0].kindred)
                callback_index=queue.index(deferred[0])
                preparation_ends=[i for i,x in enumerate(queue)if type(x)is FinishKindredComponent and
                    x.record_id==value.id and value.started[x.index]=='prepare']
                if len(preparation_ends)!=1 or callback_index>=preparation_ends[0]:
                    raise ValueError('Sampled Kindred callback follows its original preparation completion')
                preparing=True
            expected=(('prepare',)if not value.started else()if preparing else value.plan[len(value.started):])if profile.prepare is not None else value.plan[len(value.started):]
            if tuple(x.role for x in runs)!=expected:raise ValueError('Pending Kindred root truncated or reordered its accepted component plan')
            for item in runs:
                validate_component(item,game.registry);validate_record_activation(state,game.registry,item.activation)
        pending={x.instance_id for x in queue if type(x)is RemovePlayerEffect and x.player_id==value.player_id}
        live={x.id for x in state.players[value.player_id].player_effects}
        if any(x.id in live and x.id not in pending for x in value.sources):raise ValueError('Accepted Kindred retained an already consumed one-use source')


def interrupt(r,queue):
    unfinished=[x for x in r.state.kindred_history if not x.completed and x.interruption is None]
    if not unfinished:return
    terminal=[e for e in r.game._events if e.kind=='game_ended']
    if len(terminal)!=1:raise ValueError('Kindred interruption requires an actual terminal event')
    event=terminal[0]
    for value in unfinished:
        roots=[x for x in queue if type(x)is FinishKindred and x.activation.record_id==value.id]
        if len(roots)!=1:raise ValueError('Interrupted Kindred root lost its original completion witness')
        validate_record_activation(r.state,r.registry,roots[0].activation)
        r.state.kindred_history[value.id-1]=replace(value,interruption=(event.sequence,event.action))


def rows_from_dict(value):
    from .serialization import _list,_row,_owner_turn_from_dict,_previous_owner_match_from_dict,player_effect_from_dict
    from .allocation_facts import allocation_from_dict
    rows=[]
    for raw in _list(value['kindred_history'],'Kindred history'):
        item=_row(raw,KindredRecord);item['source']=allocation_from_dict(item['source'])
        boundary=_row(item['boundary'],OwnerTurnQueryBoundaryFact)
        if boundary['last_owner_turn']is not None:boundary['last_owner_turn']=_owner_turn_from_dict(boundary['last_owner_turn'])
        item['boundary']=OwnerTurnQueryBoundaryFact(**boundary)
        item['condition']=_previous_owner_match_from_dict(item['condition'])
        item['sources']=tuple(player_effect_from_dict(x)for x in _list(item['sources'],'Kindred sources'))
        for name in('plan','started','stack','finished'):item[name]=tuple(_list(item[name],'Kindred '+name))
        if item['interruption']is not None:item['interruption']=tuple(_list(item['interruption'],'Kindred interruption'))
        rows.append(KindredRecord(**item))
    value['kindred_history']=rows


def current_source(c):
    from .board_presence import resolve_board_presence
    from .model import BoardPresenceReference
    old=c.kindred.original.source
    if old.zone!=Zone.BOARD or old.kind!=CardType.MINION:return None
    current=resolve_board_presence(c.state,BoardPresenceReference(old.id,old.board_presence_id))
    return current if current is not None and current.active and current.health>0 and not current.doomed else None


def repeat_components(c,*,prepared_choice=None):
    if c.kindred is None:raise ValueError('Kindred preparation lost its original component plan')
    return tuple(RunKindredComponent(c.kindred,prepared_choice=prepared_choice)for _ in range(c.kindred.repetitions))if c.kindred.condition.matched else()


def register(mechanics):
    mechanics.register(ResolveKindred,resolve)
    mechanics.register(RunKindredComponent,run)
    mechanics.register(FinishKindredComponent,finish_component)
    mechanics.register(FinishKindred,finish)
