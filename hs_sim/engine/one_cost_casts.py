"""Native automatic cast repetition; originally introduced for one-cost spells."""
from dataclasses import dataclass,replace
import json
from .effects import Effect,_integer
from .errors import ResolutionError
from .arcane_dragon_providers import NativeRepeatPlan

ACCEPTED='native_spell_repeat_accepted'
STARTED='native_spell_repeat_started'


def native_spec(spec):
    return spec is not None and spec.match is not None and spec.match.recipient_cost is not None and spec.match.recipient_cost.basis=='cast_quote'


@dataclass(frozen=True)
class RepeatAutomaticSpell(Effect):
    cast_id: int
    behaviors: tuple[str,...]
    plan: NativeRepeatPlan
    def __post_init__(self):
        _integer(self.cast_id,'original native repeated cast',1)
        if type(self.behaviors)is not tuple or any(type(x)is not str or not x for x in self.behaviors):raise ValueError('Native repeat requires frozen original spell bodies')
        if type(self.plan)is not NativeRepeatPlan:raise ValueError('Native repeat requires its complete original plan')
        self.plan.__post_init__()


def capture_automatic(r,entity,player_id):
    from .arcane_dragon_providers import capture
    return capture(r,entity,player_id)


def accept_automatic(r,record,behaviors,captured):
    if captured is None:return ()
    work=RepeatAutomaticSpell(record.id,behaviors,captured)
    from .continuations import FrameCodec
    r.emit(ACCEPTED,source_id=record.source_id,player_id=record.player_id,cast_id=record.id,
        plan=json.dumps(FrameCodec(r.game.mechanics,r.registry).encode(work),ensure_ascii=False,sort_keys=True,separators=(',',':')),_capture=False)
    return (work,)


def validate_plan(state,registry,work,*,closed=False):
    from .spell_casts import cast_record
    from .arcane_dragon_providers import validate_plan as validate_sources
    work.__post_init__();row=cast_record(state,work.cast_id);source=work.plan.source
    if row.origin not in ('effect','draw','history')or row.failure is not None or(row.source_id,row.player_id,row.card_id)!=(source.entity_id,work.plan.player_id,source.card_id):
        raise ValueError('Native repeat borrowed another original automatic cast')
    validate_sources(state,registry,work.plan,closed=closed)
    for behavior in work.behaviors:registry.behavior(behavior)
    return row


def repeat(r,work):
    from .spell_casts import capture_target_origin,cast_owner_turn_id,note_payload,FinishSpellCast
    from .rewind_outcomes import payload
    parent=validate_plan(r.state,r.registry,work)
    if not parent.completed or parent.interrupted:raise ResolutionError('Native repeat requires its completed original cast')
    child=replace(parent,id=len(r.state.cast_history)+1,origin='native_repeat',iteration=2,recast_id=parent.id,
        turn=r.state.turn,action=r.state.action_number,
        play_id=None,draw_id=None,from_zone=None,completed=False,interrupted=False,payload_started=True,failure=None,
        recorded_event=len(r.game._events),owner_turn_id=cast_owner_turn_id(r.state),target_selection=None,
        target_origin=capture_target_origin(r.state,parent.target_id),local_spell_damage=(),spell_damage_effects=(),native_spell_value=None,aura_duration_grants=())
    r.state.cast_history.append(child)
    r.emit(STARTED,source_id=parent.source_id,player_id=parent.player_id,cast_id=parent.id,child_id=child.id,_capture=False)
    from .spell_casts import target_origin_receipt
    r.emit('spell_cast_started',source_id=child.source_id,target_id=child.target_id,player_id=child.player_id,cast_id=child.id,target_origin=target_origin_receipt(child))
    child=note_payload(r,child)
    return (*payload(r,child.source_id,child.player_id,child.target_id,work.behaviors,cast=child),FinishSpellCast(child.id))


def validate_boundary(game):
    from .hero_health_history import effective_events
    from .continuations import FrameCodec
    codec=FrameCodec(game.mechanics,game.registry);plans={};started={}
    for event in effective_events(game._events):
        if event.kind==ACCEPTED:
            data=dict(event.data);work=codec.decode(json.loads(data['plan']))
            if type(work)is not RepeatAutomaticSpell or data['cast_id']!=work.cast_id or work.cast_id in plans:
                raise ValueError('Native repeat acceptance lost its unique original plan')
            row=validate_plan(game._state,game.registry,work,closed=True)
            if(row.source_id,row.player_id)!=(event.source_id,event.player_id):raise ValueError('Native repeat acceptance changed its original actor')
            plans[work.cast_id]=work
        elif event.kind==STARTED:
            data=dict(event.data);parent=data['cast_id'];child=data['child_id']
            if parent not in plans or parent in started:raise ValueError('Native repeat has no unique accepted parent')
            row=game._state.cast_history[child-1]
            if(row.origin,row.recast_id,row.iteration,row.source_id,row.player_id)!=('native_repeat',parent,2,event.source_id,event.player_id):
                raise ValueError('Native repeat changed its actual child cast')
            started[parent]=child
    children={row.id for row in game._state.cast_history if row.origin=='native_repeat'}
    if children!=set(started.values()):raise ValueError('Native repeat child has no actual accepted plan')
    frame=game._frame;queued=(*frame.prefix,*frame.continuation)if frame else()
    pending=[w for w in queued if type(w)is RepeatAutomaticSpell]
    for work in pending:
        if plans.get(work.cast_id)!=work or work.cast_id in started:raise ValueError('Queued native repeat changed its original accepted work')
        validate_plan(game._state,game.registry,work)
    if game._state.status=='playing'and set(plans)-set(started)!={w.cast_id for w in pending}:
        raise ValueError('Native repeat lost its original owed continuation')


def register(mechanics):
    from .arcane_dragon_providers import register_payloads
    register_payloads(mechanics)
    mechanics.register(RepeatAutomaticSpell,repeat)
