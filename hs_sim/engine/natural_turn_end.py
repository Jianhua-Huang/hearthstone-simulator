"""Source-cast end requests applied only after the outer resolution's real tails."""
from dataclasses import dataclass,replace

from .effects import Effect,_integer
from .errors import ResolutionError
from .model import CardType


@dataclass(frozen=True)
class NaturalTurnEndRequest:
    cast_id: int
    owner_turn_id: int
    accepted_event: int
    status: str = 'pending'
    closed_event: int | None = None
    ended_event: int | None = None

    def __post_init__(self):
        _integer(self.cast_id,'natural end source cast',1)
        _integer(self.owner_turn_id,'natural end original interval',1)
        _integer(self.accepted_event,'natural end acceptance cursor',0)
        if self.status not in ('pending','applied','stale','interrupted'):
            raise ValueError('Unknown natural end request status')
        if self.status=='pending':
            if self.closed_event is not None or self.ended_event is not None:
                raise ValueError('Pending natural end cannot claim completion')
        else:
            _integer(self.closed_event,'natural end completion cursor',self.accepted_event)
            if self.status=='applied':
                _integer(self.ended_event,'actual natural end event',self.accepted_event+1)
                if self.closed_event!=self.ended_event:raise ValueError('Natural end changed its actual end event')
            elif self.ended_event is not None:
                raise ValueError('Unapplied natural end cannot claim a turn event')


def source_cast(state,registry,cast_id):
    _integer(cast_id,'natural end source cast',1)
    from .spell_casts import cast_record
    cast=cast_record(state,cast_id)
    if (not cast.payload_started or cast.failure is not None or
            registry.card(cast.card_id).kind!=CardType.SPELL):
        raise ValueError('Natural end requires a genuinely accepted original spell body')
    return cast


def record(state,cast_id):
    result=next((r for r in state.natural_turn_end_requests if r.cast_id==cast_id),None)
    if result is None:raise ValueError('Natural end lost its original request')
    return result


def validate_record(state,registry,row):
    if type(row) is not NaturalTurnEndRequest:raise ValueError('Natural end requires its complete typed request')
    row.__post_init__();cast=source_cast(state,registry,row.cast_id)
    if not 1<=row.owner_turn_id<=len(state.owner_turn_history):raise ValueError('Natural end borrowed an unknown owner interval')
    owner=state.owner_turn_history[row.owner_turn_id-1]
    if ((owner.id,owner.player_id,owner.turn)!=(row.owner_turn_id,cast.player_id,cast.turn) or
            cast.owner_turn_id!=owner.id or row.accepted_event<cast.recorded_event):
        raise ValueError('Natural end changed its original caster or actual turn')
    if row.status in ('applied','stale') and (not cast.completed or cast.interrupted):
        raise ValueError('Natural end preceded its original spell completion')
    if row.status=='applied' and owner.end_event!=row.ended_event:
        raise ValueError('Natural end lacks its original interval end')
    if row.status=='stale' and (owner.end_event is None or not row.accepted_event<owner.end_event<=row.closed_event):
        raise ValueError('Stale natural end lacks the already ended original interval')
    if row.status=='interrupted' and state.status=='playing':
        raise ValueError('Interrupted natural end requires a real terminal state')
    return cast,owner


def validate_history(state,registry):
    if type(state.natural_turn_end_requests) is not list:raise ValueError('Natural end history requires an ordered list')
    seen=set();cursor=-1
    for row in state.natural_turn_end_requests:
        validate_record(state,registry,row)
        if row.cast_id in seen or row.accepted_event<cursor:raise ValueError('Natural end duplicated/reordered an original request')
        seen.add(row.cast_id);cursor=row.accepted_event


@dataclass(frozen=True)
class RequestNaturalTurnEnd(Effect):
    cast_id: int

    def __post_init__(self):_integer(self.cast_id,'natural end source cast',1)

    def validate_in_state(self,state,registry):
        self.__post_init__();cast=source_cast(state,registry,self.cast_id)
        from .spell_casts import active_cast
        if cast.completed or cast.interrupted or active_cast(state,cast.source_id,cast.player_id)!=cast:
            raise ValueError('Natural end request lost its original running spell')
        return cast


@dataclass(frozen=True)
class FinishNaturalTurnEnd(Effect):
    cast_id: int

    def __post_init__(self):_integer(self.cast_id,'natural end source cast',1)

    def validate_in_state(self,state,registry):
        self.__post_init__();row=record(state,self.cast_id);validate_record(state,registry,row)
        if row.status!='pending':raise ValueError('Natural end tail is stale or already completed')
        return row


def request(r,effect):
    cast=effect.validate_in_state(r.state,r.registry)
    if (r.ending_turn or cast.player_id!=r.state.active_player or cast.turn!=r.state.turn):return ()
    from .owner_turns import current_owner_turn
    owner=current_owner_turn(r.state)
    if owner.end_event is not None:return ()
    if any(row.cast_id==cast.id for row in r.state.natural_turn_end_requests):return ()
    row=NaturalTurnEndRequest(cast.id,owner.id,len(r.game._events));validate_record(r.state,r.registry,row)
    r.state.natural_turn_end_requests.append(row)
    r._work_queue.append(FinishNaturalTurnEnd(cast.id))
    return ()


def close(state,row,status,cursor,end_event=None):
    value=replace(row,status=status,closed_event=cursor,ended_event=end_event)
    state.natural_turn_end_requests=[value if old.cast_id==row.cast_id else old for old in state.natural_turn_end_requests]


def finish(r,effect):
    row=effect.validate_in_state(r.state,r.registry);cast,owner=validate_record(r.state,r.registry,row)
    from .owner_turns import current_owner_turn
    current=current_owner_turn(r.state)
    from .controlled_turns import tail_types
    if current.id!=owner.id or owner.end_event is not None:
        close(r.state,row,'stale',len(r.game._events));return ()
    if (r.ending_turn or r.death_deferrals or r.state.pending_choice is not None or
            r.state.active_hero_lethal_root_id is not None or r.state.whole_card_replay_ledger.stack or
            any(c.payload_started and not c.completed and not c.interrupted for c in r.state.cast_history) or
            any(not p.completed and not p.interrupted for p in r.state.play_history) or
            any(type(work) not in tail_types() for work in r._work_queue)):
        raise ResolutionError('Natural end cannot bypass unfinished original resolution work')
    from .resolver import EndTurnPhase,end_turn
    work=end_turn(r,EndTurnPhase(cast.player_id))
    ended=r.state.owner_turn_history[owner.id-1].end_event
    close(r.state,row,'applied',ended,ended)
    return work


def interrupt(r):
    for row in tuple(r.state.natural_turn_end_requests):
        if row.status=='pending':close(r.state,row,'interrupted',len(r.game._events))


def validate_queue(state,registry,queue):
    tails=tuple(w for w in queue if type(w) is FinishNaturalTurnEnd)
    pending=tuple(row.cast_id for row in state.natural_turn_end_requests if row.status=='pending')
    if tuple(w.cast_id for w in tails)!=pending:raise ValueError('Natural end lost or duplicated its complete original tail')
    for tail in tails:tail.validate_in_state(state,registry)
    from .controlled_turns import tail_types
    if tails and any(type(w) not in tail_types() for w in queue[queue.index(tails[0]):]):
        raise ValueError('Natural end moved ahead of original resolution work')


def validate_boundary(game):
    state=game._state;validate_history(state,game.registry)
    for row in state.natural_turn_end_requests:
        if row.accepted_event>len(game._events) or row.closed_event is not None and row.closed_event>len(game._events):
            raise ValueError('Natural end borrowed a future event')
        if row.status=='applied':
            event=game._events[row.ended_event-1]
            owner=state.owner_turn_history[row.owner_turn_id-1]
            if (event.sequence,event.kind,event.player_id)!=(row.ended_event,'turn_ended',owner.player_id):
                raise ValueError('Natural end substituted its actual natural event')
        if row.status=='interrupted' and not any(e.kind=='game_ended' and row.accepted_event<e.sequence<=row.closed_event for e in game._events):
            raise ValueError('Interrupted natural end lost its terminal event')
    frame=game._frame;queue=(*frame.prefix,*frame.continuation) if frame is not None else ()
    validate_queue(state,game.registry,queue)
    if frame is not None:
        original=frame.paid_hand_choice_boundary
        if original is not None:
            validate_queue(original.state,game.registry,original.work)
            if (state.natural_turn_end_requests!=original.state.natural_turn_end_requests or
                    tuple(w for w in queue if type(w) is FinishNaturalTurnEnd)!=
                    tuple(w for w in original.work if type(w) is FinishNaturalTurnEnd)):
                raise ValueError('Natural end rewrote its genuine choice-boundary obligation')


def record_from_dict(raw):
    from .serialization import _row
    return NaturalTurnEndRequest(**_row(raw,NaturalTurnEndRequest))


def register(mechanics):
    mechanics.register_payload_type(NaturalTurnEndRequest)
    mechanics.register(RequestNaturalTurnEnd,request)
    mechanics.register(FinishNaturalTurnEnd,finish)
