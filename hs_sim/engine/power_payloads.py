"""Hero-power payload identities without additional gameplay checkpoints.

An activation pays once; its accepted abilities are independent child facts.
First executions in one result retain the shared capture window; repetitions
observe the preceding execution's resulting state without changing identities.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player
from .model import (HeroPowerPayloadBatch, HeroPowerPayloadCapture,
                    HeroPowerPayloadRecord)
from .registry import RuleContext


@dataclass(frozen=True)
class InvokeHeroPowerPayload(Effect):
    context: RuleContext

    def __post_init__(self):
        if type(self.context) is not RuleContext or self.context.power_payload is None:
            raise ValueError('Power payload invocation requires its captured context')
        saved=record(self.context.state,self.context.power_payload.id)
        if saved.capture!=self.context.power_payload or saved.execution_order is not None or saved.completed or saved.interrupted:
            raise ValueError('Power payload invocation requires its queued acceptance view')


@dataclass(frozen=True)
class FinishHeroPowerPayload(Effect):
    record_id: int

    def __post_init__(self): _integer(self.record_id, 'Power payload completion', 1)


def record(state, record_id):
    _integer(record_id, 'Power payload record', 1)
    if record_id > len(state.hero_power_payload_history):
        raise ValueError('Unknown hero power payload')
    return state.hero_power_payload_history[record_id-1]


def activated_power_payloads(state, player_id, *, power_id=None, completed=None, origin=None, turn=None):
    """Trusted-host query in actual execution order; exclude queued work."""
    _player(player_id)
    if completed is not None and type(completed) is not bool:
        raise ValueError('Invalid power payload completion filter')
    if origin is not None and origin not in ('manual', 'effect'):
        raise ValueError('Invalid power payload origin filter')
    for value in (power_id, turn):
        if value is not None: _integer(value, 'Power payload history bound', 1)
    from .hero_powers import power_record
    rows=[]
    for saved in state.hero_power_payload_history:
        root=power_record(state, saved.capture.power_id)
        if (saved.execution_order is not None and root.player_id==player_id and
                (power_id is None or root.id==power_id) and
                (completed is None or saved.completed==completed) and
                (origin is None or root.origin==origin) and (turn is None or root.turn==turn)):
            rows.append(saved)
    return tuple(sorted(rows, key=lambda row:row.execution_order))


def validate_ability(state, registry, ability):
    ability.__post_init__()
    if ability.kind!='on_use' or ability.consumed:
        raise ValueError('Expected accepted active on_use ability')
    registry.behavior(ability.behavior_id)
    if ability.id>=state.next_attachment_id or (ability.source_id is not None and ability.source_id not in state.entities):
        raise ValueError('Power payload ability has invalid historical provenance')


def validate_context(context, registry):
    capture=context.power_payload
    if capture is None: return
    if type(capture) is not HeroPowerPayloadCapture:
        raise ValueError('Invalid captured power payload')
    capture.__post_init__();validate_ability(context.state, registry, capture.ability)
    from .hero_powers import power_record
    root=power_record(context.state, capture.power_id)
    saved=record(context.state, capture.id)
    batch=next((b for b in context.state.hero_power_payload_batches if b.id==capture.batch_id), None)
    queued=saved.execution_order is None
    if (context.power!=root or saved.capture!=capture or batch is None or
            saved.completed or saved.interrupted or not queued and capture.repeat_index==1 or
            (context.source_id,context.player_id,context.target_id)!=(root.source_id,root.player_id,root.target_id) or
            root.failure is not None or root.completed or root.interrupted or
            batch.payloads!=root.payloads or batch.plan!=root.repeat_plan or
            (batch.power_id,batch.outcome_id,batch.iteration)!=(root.id,capture.outcome_id,capture.iteration) or
            not 0<=capture.id-batch.id<batch.total or
            batch.position(capture.id-batch.id)!=(capture.ability,capture.repeat_index)):
        raise ValueError('Captured power payload differs from its accepted root and position')
    if capture.outcome_id is not None:
        from .rewind_outcomes import outcome
        retained=outcome(context.state, capture.outcome_id)
        if (retained.power_id!=root.id or not retained.running or retained.finished or retained.interrupted or
                retained.completed+1!=capture.iteration or context.rewind_attempt!=retained.completed):
            raise ValueError('Captured power payload differs from its retained result')
    elif queued:
        from .lifecycle import active_abilities
        from .model import Zone
        from .hero_power_repeats import capture_plan
        if (context.source.zone!=Zone.HERO_POWER or context.source.controller!=root.player_id or
                context.source.id not in context.state.players[root.player_id].hero_power_ids or
                tuple(active_abilities(context.source,'on_use'))!=root.payloads):
            raise ValueError('Ordinary power payload differs from its complete accepted ability set')
        if root.repeat_plan!=capture_plan(context.state,registry,root.player_id):
            raise ValueError('Hero power repeat plan differs from its complete acceptance window')


def schedule(r, power, *, outcome_id=None, iteration=1):
    from .hero_powers import power_record
    if power_record(r.state,power.id)!=power or power.failure is not None or power.completed or power.interrupted:
        raise ValueError('Cannot schedule a settled or mismatched power payload')
    if not power.payloads: return []
    batch=HeroPowerPayloadBatch(len(r.state.hero_power_payload_history)+1, power.id, power.payloads,
                               outcome_id, iteration, power.repeat_plan)
    from .errors import ResolutionLimitExceeded
    if 3*batch.total>r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Hero power payload expansion exceeds resolution budget')
    captures=tuple(HeroPowerPayloadCapture(batch.id+i,batch.id,power.id,
                   batch.position(i)[0],outcome_id,iteration,batch.position(i)[1])
                   for i in range(batch.total))
    # Persist every position before any detached callback view is taken.
    r.state.hero_power_payload_batches.append(batch)
    r.state.hero_power_payload_history.extend(HeroPowerPayloadRecord(c) for c in captures)
    return [InvokeHeroPowerPayload(r.call(c.ability.behavior_id,power.source_id,power.player_id,
            power.target_id,power=power,power_payload=c).context) for c in captures]


def begin(r, work):
    work.__post_init__();validate_context(work.context,r.registry)
    capture=work.context.power_payload;saved=record(r.state,capture.id)
    if saved.capture!=capture or saved.execution_order is not None or saved.completed or saved.interrupted:
        raise ValueError('Power payload is already started or mismatched')
    order=1+sum(row.execution_order is not None for row in r.state.hero_power_payload_history)
    r.state.hero_power_payload_history[capture.id-1]=replace(saved,execution_order=order)
    from .resolver import BehaviorCall
    call=BehaviorCall(capture.ability.behavior_id,work.context)
    if capture.repeat_index>1:
        from .hero_powers import power_record
        power=power_record(r.state,capture.power_id)
        call=r.call(capture.ability.behavior_id,power.source_id,power.player_id,
                    power.target_id,power=power,power_payload=capture)
    return [call,FinishHeroPowerPayload(capture.id)]


def finish(r, work):
    saved=record(r.state,work.record_id)
    if saved.execution_order is None or saved.completed or saved.interrupted:
        raise ValueError('Power payload is not running')
    r.state.hero_power_payload_history[saved.id-1]=replace(saved,completed=True)


def interrupt(state):
    state.hero_power_payload_history=[replace(row,interrupted=True) if not(row.completed or row.interrupted) else row
                                     for row in state.hero_power_payload_history]


def validate_history(state, registry):
    from .hero_powers import power_record
    if type(state.hero_power_payload_history) is not list or type(state.hero_power_payload_batches) is not list:
        raise ValueError('Power payload history and batches require lists')
    for root in state.hero_power_history:
        from .hero_power_repeats import validate_plan
        validate_plan(state,registry,root.repeat_plan,root.player_id,root.turn)
        for ability in root.payloads: validate_ability(state,registry,ability)
    orders=[]
    for index,saved in enumerate(state.hero_power_payload_history,1):
        if type(saved) is not HeroPowerPayloadRecord: raise ValueError('Expected power payload record')
        saved.__post_init__();capture=saved.capture
        validate_ability(state,registry,capture.ability)
        root=power_record(state,capture.power_id)
        if capture.id!=index or root.failure is not None:
            raise ValueError('Invalid power payload capture identity')
        if saved.execution_order is not None: orders.append(saved.execution_order)
        if saved.interrupted and state.status=='playing':
            raise ValueError('Power payload interrupted before terminal state')
        if root.completed and not saved.completed or root.interrupted and not(saved.completed or saved.interrupted):
            raise ValueError('Settled hero power has unfinished payloads')
    if sorted(orders)!=list(range(1,len(orders)+1)):
        raise ValueError('Invalid power payload execution order')
    offset=0;keys=set();per_root={}
    for batch in state.hero_power_payload_batches:
        if type(batch) is not HeroPowerPayloadBatch: raise ValueError('Expected power payload batch')
        batch.__post_init__();root=power_record(state,batch.power_id)
        key=(batch.power_id,batch.outcome_id,batch.iteration)
        if (key in keys or batch.id!=offset+1 or offset+batch.total>len(state.hero_power_payload_history) or
                root.failure is not None or batch.payloads!=root.payloads or batch.plan!=root.repeat_plan):
            raise ValueError('Power payload batch coverage differs from its accepted root and complete acceptance view')
        keys.add(key);per_root.setdefault(root.id,[]).append(batch)
        rows=state.hero_power_payload_history[offset:offset+batch.total]
        for index,row in enumerate(rows):
            ability,repeat_index=batch.position(index)
            if (row.capture.batch_id,row.capture.power_id,row.capture.ability,row.capture.outcome_id,
                    row.capture.iteration,row.capture.repeat_index)!=(
                    batch.id,root.id,ability,batch.outcome_id,batch.iteration,repeat_index):
                raise ValueError('Power payload batch has an invalid complete position')
            if index and row.execution_order is not None and (not rows[index-1].completed or
                    row.execution_order<=rows[index-1].execution_order):
                raise ValueError('Power payload started before its previous position finished')
        if batch.outcome_id is not None:
            from .rewind_outcomes import outcome
            retained=outcome(state,batch.outcome_id)
            if retained.power_id!=root.id or batch.iteration>retained.total or batch.iteration>retained.completed+1:
                raise ValueError('Power payload belongs to a different or future retained result')
            if batch.iteration<=retained.completed and any(not row.completed for row in rows):
                raise ValueError('Completed retained result has unfinished power payloads')
        offset+=batch.total
    if offset!=len(state.hero_power_payload_history):
        raise ValueError('Power payload captures lack their complete batch')
    for root in state.hero_power_history:
        batches=per_root.get(root.id,[])
        retained=next((o for o in state.rewind_outcomes if o.power_id==root.id),None)
        if not root.payloads:
            if batches: raise ValueError('Empty power has payload batches')
        elif retained is None:
            # Captured payment/start-event contexts may precede scheduling.
            if len(batches)>1 or any(b.outcome_id is not None for b in batches) or root.completed and not batches:
                raise ValueError('Ordinary power payload batch coverage differs')
        else:
            iterations=[b.iteration for b in batches]
            if (any(b.outcome_id!=retained.id for b in batches) or iterations!=list(range(1,len(batches)+1)) or
                    len(batches)<retained.completed or len(batches)>retained.completed+int(retained.running or retained.interrupted)):
                raise ValueError('Retained power payload batch coverage differs')


def validate_queue(state, registry, queue, max_resolution_steps):
    from .hero_powers import power_record, FinishHeroPower
    from .rewind_outcomes import FinishRewindOutcome
    from .resolver import BehaviorCall
    queue = tuple(queue)
    if any(type(work) is BehaviorCall and work.context.power_payload is not None for work in queue):
        raise ValueError('Power payload callback cannot bypass its invocation control at a saved boundary')
    queued=[row.id for row in state.hero_power_payload_history if row.execution_order is None and not row.interrupted]
    running=sorted((row for row in state.hero_power_payload_history if row.execution_order is not None and
                    not(row.completed or row.interrupted)),key=lambda row:row.execution_order,reverse=True)
    starts=[w for w in queue if type(w) is InvokeHeroPowerPayload]
    finishes=[w.record_id for w in queue if type(w) is FinishHeroPowerPayload]
    if sorted(w.context.power_payload.id for w in starts)!=queued or finishes!=[row.id for row in running]:
        raise ValueError('Power payload progress and pending control work disagree')
    groups={}
    for work in starts:
        work.__post_init__()
        validate_context(work.context,registry);capture=work.context.power_payload
        if record(state,capture.id).capture!=capture:
            raise ValueError('Pending power payload capture differs from live history')
        live=next(b for b in state.hero_power_payload_batches if b.id==capture.batch_id)
        captured=next(b for b in work.context.state.hero_power_payload_batches if b.id==capture.batch_id)
        if live!=captured or power_record(state,capture.power_id)!=work.context.power:
            raise ValueError('Pending power payload changed its accepted batch or root')
        if capture.id<=groups.get(capture.batch_id,0):
            raise ValueError('Pending power payload positions are out of order')
        groups[capture.batch_id]=capture.id
    for index,work in enumerate(queue):
        if type(work) not in (InvokeHeroPowerPayload,FinishHeroPowerPayload): continue
        capture=work.context.power_payload if type(work) is InvokeHeroPowerPayload else record(state,work.record_id).capture
        root_finish=next((i for i,w in enumerate(queue) if type(w) is FinishHeroPower and w.record_id==capture.power_id),None)
        result_finish=next((i for i,w in enumerate(queue) if type(w) is FinishRewindOutcome and w.record_id==capture.outcome_id),None)
        if root_finish is None or index>=root_finish or capture.outcome_id is not None and (result_finish is None or index>=result_finish):
            raise ValueError('Power payload work must precede its root and retained-result completion')
        for child in state.hero_power_history:
            if child.completed or child.interrupted: continue
            parent_id=child.parent_id
            while parent_id is not None and parent_id!=capture.power_id:
                parent_id=power_record(state,parent_id).parent_id
            if parent_id==capture.power_id:
                child_finish=next((i for i,w in enumerate(queue) if type(w) is FinishHeroPower and w.record_id==child.id),None)
                if child_finish is None or child_finish>=index:
                    raise ValueError('Enclosing power payload cannot resume before its nested activation finishes')
        if type(work) is InvokeHeroPowerPayload and capture.id>capture.batch_id:
            previous=record(state,capture.id-1)
            if previous.execution_order is not None and not previous.completed:
                marker=next((i for i,w in enumerate(queue) if type(w) is FinishHeroPowerPayload and w.record_id==previous.id),None)
                if marker is None or marker>=index:
                    raise ValueError('Queued power payload precedes its running predecessor completion')
    for root in state.hero_power_history:
        batches=[b for b in state.hero_power_payload_batches if b.power_id==root.id]
        retained=next((o for o in state.rewind_outcomes if o.power_id==root.id),None)
        if root.payloads and retained is None and len(batches)!=1:
            raise ValueError('Live ordinary hero power lost its accepted payload batch')
        if root.payloads and retained is not None and not retained.interrupted and len(batches)!=retained.completed+int(retained.running):
            raise ValueError('Live retained hero power lost a started payload batch')
    if any(3*batch.total>max_resolution_steps for batch in state.hero_power_payload_batches):
        raise ValueError('Power payload batch exceeds resolution budget')


def validate_boundary(game):
    queue=(*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    validate_queue(game._state, game.registry, queue, game.ruleset.max_resolution_steps)


def register(mechanics):
    mechanics.register(InvokeHeroPowerPayload,begin)
    mechanics.register(FinishHeroPowerPayload,finish)
    from .hero_power_repeats import register as register_repeats
    register_repeats(mechanics)
