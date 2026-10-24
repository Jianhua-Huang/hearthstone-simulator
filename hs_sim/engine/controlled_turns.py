"""Accepted Battlecry-controlled slots and native inputs through ordinary rules."""
import json
from dataclasses import dataclass, replace

from .actions import action_from_dict, action_to_dict
from .effects import Effect, _integer, _player
from .errors import IllegalAction, ResolutionError, ResolutionLimitExceeded
from .native_turn_policy import POLICY, ASCENT, DOMAIN


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class NativeTurnInput:
    action_number: int
    event_id: int
    command: str
    action: str
    observation_hash: str
    menu_hash: str

    def __post_init__(self):
        for value in (self.action_number, self.event_id): _integer(value, 'native input cursor', 1)
        for value in (self.command, self.action):
            if type(value) is not str or canonical(json.loads(value)) != value:
                raise ValueError('Native input requires canonical original JSON')
        action_from_dict(json.loads(self.action))
        for value in (self.observation_hash, self.menu_hash):
            if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Native input lost its player-view proof')


@dataclass(frozen=True)
class ControlledTurnRequest:
    id: int
    battlecry_id: int
    player_id: int
    source_id: int
    owner_turn_id: int
    accepted_event: int
    policy: str = POLICY
    status: str = 'requested'
    scheduled_event: int | None = None
    started_owner_turn_id: int | None = None
    ended_event: int | None = None
    closed_event: int | None = None
    opening_plan: tuple[str, ...] | None = None
    plan_event: int | None = None
    inputs: tuple[NativeTurnInput, ...] = ()

    def __post_init__(self):
        for name in ('id','battlecry_id','source_id','owner_turn_id'):
            _integer(getattr(self,name), 'controlled turn '+name, 1)
        _player(self.player_id); _integer(self.accepted_event,'controlled turn acceptance',0)
        if self.policy != POLICY or self.status not in ('requested','queued','active','ending','completed','skipped','interrupted'):
            raise ValueError('Unknown controlled turn policy or lifecycle')
        for name in ('scheduled_event','started_owner_turn_id','ended_event','closed_event','plan_event'):
            if getattr(self,name) is not None: _integer(getattr(self,name),'controlled turn '+name,1)
        if self.opening_plan is not None and (type(self.opening_plan) is not tuple or
                len(set(self.opening_plan)) != len(self.opening_plan) or
                any(type(v) is not str or not v for v in self.opening_plan)):
            raise ValueError('Controlled opening requires its original unique ability plan')
        if (self.opening_plan is None) != (self.plan_event is None):
            raise ValueError('Controlled opening lost its original plan proof')
        if type(self.inputs) is not tuple or any(type(v) is not NativeTurnInput for v in self.inputs):
            raise ValueError('Controlled turn requires complete ordered native inputs')
        for value in self.inputs: value.__post_init__()


def record(state, identity):
    _integer(identity,'controlled turn request',1)
    if identity > len(state.controlled_turn_requests): raise ValueError('Unknown controlled turn request')
    return state.controlled_turn_requests[identity-1]


def update(state, row, **values):
    value = replace(row, **values)
    state.controlled_turn_requests[row.id-1] = value
    return value


def source(state, registry, identity):
    from .battlecries import battlecry_record
    value = battlecry_record(state, identity)
    if not value.payload_started or value.failure is not None:
        raise ValueError('Controlled turn requires an actually accepted Battlecry body')
    if registry.card(value.payload.card_id).battlecry != value.payload.behavior_id:
        raise ValueError('Controlled turn lost its original declared Battlecry')
    return value


@dataclass(frozen=True)
class RequestControlledTurn(Effect):
    battlecry_id: int

    def __post_init__(self): _integer(self.battlecry_id,'controlled source Battlecry',1)

    def validate_in_state(self,state,registry):
        self.__post_init__();value=source(state,registry,self.battlecry_id)
        from .battlecries import active_battlecry
        if value.completed or value.interrupted or active_battlecry(state,value.source_id,value.player_id) != value:
            raise ValueError('Controlled request lost its running original Battlecry')
        return value


@dataclass(frozen=True)
class FinishControlledTurnRequest(Effect):
    request_id: int

    def __post_init__(self): _integer(self.request_id,'controlled original request',1)

    def validate_in_state(self,state,registry):
        self.__post_init__();row=record(state,self.request_id);source(state,registry,row.battlecry_id)
        if row.status != 'requested': raise ValueError('Controlled request tail already retired')
        return row


def request(r,effect):
    bc=effect.validate_in_state(r.state,r.registry)
    if any(v.player_id == bc.player_id and v.policy == POLICY for v in r.state.controlled_turn_requests): return ()
    from .owner_turns import current_owner_turn
    row=ControlledTurnRequest(len(r.state.controlled_turn_requests)+1,bc.id,bc.player_id,
        bc.source_id,current_owner_turn(r.state).id,len(r.game._events))
    r.state.controlled_turn_requests.append(row)
    r._work_queue.append(FinishControlledTurnRequest(row.id))
    return ()


def tail_types():
    from .natural_turn_end import FinishNaturalTurnEnd
    return (FinishNaturalTurnEnd,FinishControlledTurnRequest)


def finish(r,effect):
    row=effect.validate_in_state(r.state,r.registry);bc=source(r.state,r.registry,row.battlecry_id)
    if (not bc.completed or r.death_deferrals or r.state.pending_choice is not None or
            r.state.active_hero_lethal_root_id is not None or r.state.whole_card_replay_ledger.stack or
            any(not p.completed and not p.interrupted for p in r.state.play_history) or
            any(c.payload_started and not c.completed and not c.interrupted for c in r.state.cast_history) or
            any(type(w) not in tail_types() for w in r._work_queue)):
        raise ResolutionError('Controlled turn cannot bypass original outer resolution tails')
    schedule=r.state.turn_schedule
    if len(schedule.pending) >= r.rules.max_turns:
        raise ResolutionLimitExceeded('Engineering controlled-turn queue budget exhausted')
    r.state.turn_schedule=replace(schedule,pending=(*schedule.pending,row.player_id),
        controlled_slots=(*schedule.controlled_slots,(len(schedule.pending),row.id)),
        resume_player_id=schedule.resume_player_id or 3-r.state.active_player)
    event=r.emit('turns_scheduled',source_id=row.source_id,players=(row.player_id,))
    update(r.state,row,status='queued',scheduled_event=event.sequence)
    from .owner_turns import current_owner_turn
    owner=current_owner_turn(r.state)
    if owner.id == row.owner_turn_id and owner.player_id == row.player_id and owner.end_event is None and not r.ending_turn:
        from .resolver import EndTurnPhase,end_turn
        return end_turn(r,EndTurnPhase(row.player_id))
    return ()


def slot_identity(state):
    return next((identity for index,identity in state.turn_schedule.controlled_slots if index == 0),None)


def slot_skipped(r,identity,event):
    if identity is not None:
        update(r.state,record(r.state,identity),status='skipped',closed_event=event.sequence)


def interval_closed(state,cursor):
    for row in tuple(state.controlled_turn_requests):
        if row.status == 'ending': update(state,row,status='completed',closed_event=cursor)


def slot_started(state,identity):
    if identity is not None:
        from .owner_turns import current_owner_turn
        row=record(state,identity);owner=current_owner_turn(state)
        if row.status != 'queued' or owner.player_id != row.player_id:
            raise ValueError('Controlled slot changed its original scheduled owner')
        update(state,row,status='active',started_owner_turn_id=owner.id)


def interval_ended(state,event):
    for row in tuple(state.controlled_turn_requests):
        if row.status == 'active':
            owner=state.owner_turn_history[row.started_owner_turn_id-1]
            if owner.end_event == event.sequence:
                update(state,row,status='ending',ended_event=event.sequence)


def interrupt(r):
    for row in tuple(r.state.controlled_turn_requests):
        if row.status not in ('completed','skipped','interrupted'):
            update(r.state,row,status='interrupted',closed_event=len(r.game._events))


def active(state):
    values=[row for row in state.controlled_turn_requests if row.status in ('active','ending')]
    if len(values)>1: raise ValueError('Multiple native actors cannot own one actual interval')
    return values[0] if values else None


def validate_external(game,action):
    from .actions import Concede
    from .turn_clocks import AdvanceTurnTime
    if type(action) in (Concede,AdvanceTurnTime):return
    row=active(game._state)
    if row is not None and action.player_id == row.player_id:
        raise IllegalAction('This actual turn is controlled by its accepted native actor')


def drive(game):
    from .player_api import _decode
    from .native_turn_policy import choose
    from .serialization import canonical_hash,rng_to_json
    from .resolver import Resolution
    produced=0
    while game._state.status == 'playing' and (row:=active(game._state)) is not None:
        choice=game._state.pending_choice
        if choice is not None and choice.player_id != row.player_id: return
        if produced >= game.ruleset.max_resolution_steps:
            raise ResolutionLimitExceeded('Engineering native-input budget exhausted; action rolled back')
        message=game.for_player(row.player_id).legal_actions()
        if message['error'] is not None: raise ResolutionError('Controlled turn player rules are unsupported: '+message['error'])
        actor_ref=game._information.players[row.player_id].refs.get(str(row.source_id))
        if row.opening_plan is None and choice is None:
            options=tuple(dict.fromkeys(a['ability_id'] for a in message['actions'] if
                a['type']=='use_minion_ability' and a['minion']==actor_ref))
            before=game._rng.getstate()
            from .native_turn_policy import visible
            actor=visible(message['observation']).get(actor_ref,{})
            keywords=actor.get('keywords',())
            limit=5 if 'mega_windfury' in keywords else 3 if 'windfury' in keywords else 2
            plan=list(game._rng.sample(options,min(limit,len(options)))) if options else []
            if ASCENT in plan and DOMAIN in plan and plan.index(ASCENT)<plan.index(DOMAIN):
                i,j=plan.index(ASCENT),plan.index(DOMAIN);plan[i],plan[j]=plan[j],plan[i]
            proof=canonical(dict(request_id=row.id,options=options,selected=plan,limit=limit,
                observation=message['observation'],legal_actions=message['actions'],actor_ref=actor_ref,
                rng_before=rng_to_json(before),rng_after=rng_to_json(game._rng.getstate())))
            event=Resolution(game).emit('controlled_ability_plan',player_id=row.player_id,proof=proof,_capture=False)
            row=update(game._state,row,opening_plan=tuple(plan),plan_event=event.sequence)
        command=choose(message,actor_ref,row.opening_plan or ())
        action=_decode(game,row.player_id,command,message['observation']);game.validate(action)
        proof=dict(request_id=row.id,action_number=game._state.action_number+1,command=command,
            action=action_to_dict(action),observation_hash=canonical_hash(message['observation']),
            observation=message['observation'],actor_ref=actor_ref,legal_actions=message['actions'],policy=POLICY)
        event=Resolution(game).emit('controlled_input',player_id=row.player_id,proof=canonical(proof),_capture=False)
        value=NativeTurnInput(proof['action_number'],event.sequence,canonical(command),canonical(proof['action']),
            proof['observation_hash'],canonical_hash(message['actions']))
        update(game._state,row,inputs=(*row.inputs,value))
        game._resolve_action(action)
        produced+=1


def validate_history(state,registry):
    if type(state.controlled_turn_requests) is not list: raise ValueError('Controlled history requires an ordered list')
    players=set();pending=[]
    for identity,row in enumerate(state.controlled_turn_requests,1):
        if type(row) is not ControlledTurnRequest: raise ValueError('Controlled history requires complete typed records')
        row.__post_init__();bc=source(state,registry,row.battlecry_id)
        if row.id != identity or row.player_id in players or (row.player_id,row.source_id)!=(bc.player_id,bc.source_id):
            raise ValueError('Controlled request changed its source, order or once-per-game owner')
        players.add(row.player_id)
        if not 1<=row.owner_turn_id<=len(state.owner_turn_history):raise ValueError('Controlled request borrowed an unknown original interval')
        original=state.owner_turn_history[row.owner_turn_id-1]
        if original.turn != bc.turn: raise ValueError('Controlled request changed its original Battlecry turn')
        if row.status not in ('requested','interrupted') and (not bc.completed or row.scheduled_event is None):
            raise ValueError('Controlled slot preceded original Battlecry completion')
        if row.status=='requested' and row.scheduled_event is not None:
            raise ValueError('Requested controlled turn cannot claim an accepted queue slot')
        if row.status in ('active','ending','completed'):
            if row.started_owner_turn_id is None or not row.owner_turn_id<row.started_owner_turn_id<=len(state.owner_turn_history):
                raise ValueError('Controlled slot lost its later actual interval')
            owner=state.owner_turn_history[row.started_owner_turn_id-1]
            if owner.player_id != row.player_id or row.status=='active' and owner.end_event is not None:
                raise ValueError('Controlled actor changed its actual owner or end')
            if row.status in ('active','ending') and (owner.closed or row.closed_event is not None):
                raise ValueError('Live controlled actor cannot claim a closed actual interval')
            if row.status in ('ending','completed') and owner.end_event != row.ended_event:
                raise ValueError('Controlled actor lost its actual natural end')
            if row.status=='completed' and (not owner.closed or row.closed_event != owner.closed_event):
                raise ValueError('Controlled actor lost its actual interval closure')
        elif row.status in ('requested','queued','skipped') and (row.started_owner_turn_id is not None or row.inputs or row.plan_event is not None):
            raise ValueError('Unstarted controlled slot cannot claim native inputs')
        if row.status in ('completed','skipped','interrupted') and row.closed_event is None:
            raise ValueError('Retired controlled turn requires its original closing event')
        if row.status=='interrupted' and state.status=='playing':
            raise ValueError('Interrupted native actor requires a real terminal state')
        if row.status=='queued':pending.append(row.id)
        numbers=[v.action_number for v in row.inputs]
        if numbers != sorted(set(numbers)) or any(v>state.action_number for v in numbers):
            raise ValueError('Controlled inputs changed their real action order')
        events=[v.event_id for v in row.inputs]
        if events!=sorted(set(events)):
            raise ValueError('Controlled inputs duplicated or reordered their acceptance events')
    actual=[identity for _,identity in state.turn_schedule.controlled_slots]
    if state.status=='playing' and actual!=pending: raise ValueError('Controlled queue lost its complete original requests')
    for index,identity in state.turn_schedule.controlled_slots:
        row=record(state,identity)
        if row.player_id != state.turn_schedule.pending[index]:raise ValueError('Controlled queue changed an original slot owner')
    active(state)


def validate_queue(state,registry,queue):
    pending=[row.id for row in state.controlled_turn_requests if row.status=='requested']
    tails=[w.request_id for w in queue if type(w) is FinishControlledTurnRequest]
    if pending != tails:raise ValueError('Controlled requests lost or duplicated their ordered outer tails')
    for work in queue:
        if type(work) is FinishControlledTurnRequest:
            work.validate_in_state(state,registry)
            if any(type(v) not in tail_types() for v in queue[queue.index(work):]):
                raise ValueError('Controlled request bypassed original resolution work')


def validate_boundary(game):
    from .serialization import canonical_hash,rng_from_json
    state=game._state;validate_history(state,game.registry)
    frame=game._frame;queue=(*frame.prefix,*frame.continuation) if frame else ()
    validate_queue(state,game.registry,queue)
    seen_inputs=[];seen_plans=[]
    for row in state.controlled_turn_requests:
        if row.accepted_event>len(game._events):raise ValueError('Controlled request borrowed a future acceptance')
        starts=[e for e in game._events if e.kind=='battlecry_started' and dict(e.data).get('battlecry_id')==row.battlecry_id]
        finishes=[e for e in game._events if e.kind=='battlecry_finished' and dict(e.data).get('battlecry_id')==row.battlecry_id]
        if len(starts)!=1 or starts[0].sequence>row.accepted_event or finishes and finishes[0].sequence<=row.accepted_event:
            raise ValueError('Controlled request lost its running original Battlecry window')
        if row.scheduled_event is not None:
            event=game._events[row.scheduled_event-1]
            if (not finishes or finishes[0].sequence>=row.scheduled_event or event.kind!='turns_scheduled' or
                    event.source_id!=row.source_id or tuple(dict(event.data)['players'])!=(row.player_id,)):
                raise ValueError('Controlled slot lost its real post-Battlecry scheduling event')
        if row.status=='skipped':
            event=game._events[row.closed_event-1]
            if (event.kind,event.player_id)!=('turn_skipped',row.player_id):
                raise ValueError('Skipped controlled slot lost its actual skipped event')
        if row.status=='interrupted' and not any(e.kind=='game_ended' and row.accepted_event<e.sequence<=row.closed_event for e in game._events):
            raise ValueError('Interrupted native actor lost its real terminal event')
        for value in row.inputs:
            seen_inputs.append(value.event_id)
            if value.event_id>len(game._events):raise ValueError('Native input borrowed a future event')
            event=game._events[value.event_id-1];proof=json.loads(dict(event.data)['proof'])
            if (event.kind,event.player_id)!=('controlled_input',row.player_id) or (
                    proof['request_id'],proof['action_number'],canonical(proof['command']),canonical(proof['action']),
                    proof['observation_hash'],canonical_hash(proof['legal_actions']),proof['policy']) != (
                    row.id,value.action_number,value.command,value.action,value.observation_hash,value.menu_hash,row.policy):
                raise ValueError('Native input changed its original player command proof')
            from .native_turn_policy import choose
            selected=choose(dict(observation=proof['observation'],actions=proof['legal_actions'],error=None),
                proof['actor_ref'],row.opening_plan or ())
            if (proof['command'] not in proof['legal_actions'] or selected!=proof['command'] or
                    canonical_hash(proof['observation'])!=value.observation_hash or
                    json.loads(value.action)['player_id']!=row.player_id):
                raise ValueError('Native input was not an originally legal own command')
        if row.plan_event is not None:
            seen_plans.append(row.plan_event)
            event=game._events[row.plan_event-1];proof=json.loads(dict(event.data)['proof'])
            if (event.kind,event.player_id,proof['request_id'],tuple(proof['selected'])) != (
                    'controlled_ability_plan',row.player_id,row.id,row.opening_plan):
                raise ValueError('Controlled opening lost its original plan event')
            from .native_turn_policy import visible
            actor=visible(proof['observation']).get(proof['actor_ref'],{})
            keywords=actor.get('keywords',())
            limit=5 if 'mega_windfury' in keywords else 3 if 'windfury' in keywords else 2
            options=list(dict.fromkeys(a['ability_id'] for a in proof['legal_actions'] if
                a['type']=='use_minion_ability' and a['minion']==proof['actor_ref']))
            if proof['limit']!=limit or proof['options']!=options:
                raise ValueError('Controlled opening changed its complete original candidates or allowance')
            import random
            rng=random.Random();rng.setstate(rng_from_json(proof['rng_before']))
            expected=rng.sample(proof['options'],min(proof['limit'],len(proof['options']))) if proof['options'] else []
            if ASCENT in expected and DOMAIN in expected and expected.index(ASCENT)<expected.index(DOMAIN):
                i,j=expected.index(ASCENT),expected.index(DOMAIN);expected[i],expected[j]=expected[j],expected[i]
            if expected!=proof['selected'] or rng.getstate()!=rng_from_json(proof['rng_after']):
                raise ValueError('Controlled opening changed its original equal selection or RNG')
    if (sorted(seen_inputs)!=[e.sequence for e in game._events if e.kind=='controlled_input'] or
            sorted(seen_plans)!=[e.sequence for e in game._events if e.kind=='controlled_ability_plan']):
        raise ValueError('Controlled history omitted or duplicated its original private proofs')
    if frame is not None and frame.paid_hand_choice_boundary is not None:
        original=frame.paid_hand_choice_boundary
        validate_queue(original.state,game.registry,original.work)
        if ([replace(v,inputs=()) for v in state.controlled_turn_requests] !=
                [replace(v,inputs=()) for v in original.state.controlled_turn_requests]):
            raise ValueError('Controlled turn rewrote its genuine paid choice boundary')


def record_from_dict(raw):
    from .serialization import _row,_list
    value=_row(raw,ControlledTurnRequest)
    value['inputs']=tuple(NativeTurnInput(**_row(v,NativeTurnInput)) for v in _list(value['inputs'],'native inputs'))
    if value['opening_plan'] is not None:value['opening_plan']=tuple(_list(value['opening_plan'],'controlled opening plan'))
    return ControlledTurnRequest(**value)


def register(mechanics):
    mechanics.register_payload_type(NativeTurnInput)
    mechanics.register_payload_type(ControlledTurnRequest)
    mechanics.register(RequestControlledTurn,request)
    mechanics.register(FinishControlledTurnRequest,finish)
