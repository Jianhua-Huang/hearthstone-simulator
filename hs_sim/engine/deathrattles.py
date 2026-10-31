"""Captured Deathrattle identity and execution, without new death checkpoints.

R-136 preserves the prototype's captured callback window. A queued invocation is
not an activation; actual execution order is independent of capture order.
"""
from dataclasses import dataclass, replace
from .effects import Effect, _integer, _player
from .model import DeathrattleCapture, DeathrattleRecord, DeathrattleBatch, DeathrattlePayloadPlan, CardType, Keyword, Zone


def deathrattles_can_trigger(state):
    """Current global eligibility; never erase structural Deathrattle abilities."""
    return not any(e.zone == Zone.BOARD and e.kind == CardType.MINION and e.active
        and not e.doomed and e.health > 0 and Keyword.DEATHRATTLE_SUPPRESSOR in e.keywords
        for p in state.players.values() for i in p.board for e in (state.entities[i],))


def triggerable_deathrattles(state, entity):
    """Shared current eligibility for target predicates and active execution."""
    from .lifecycle import active_abilities
    return active_abilities(entity, 'deathrattle') if deathrattles_can_trigger(state) else ()


def capture_prohibition(r, death):
    """Finalize natural eligibility before publishing that death's reactions."""
    blocked = any(a.kind == 'deathrattle' and not a.consumed for a in death.abilities) and not deathrattles_can_trigger(r.state)
    saved = replace(death, deathrattles_blocked=blocked)
    index = next((i for i, d in enumerate(r.state.death_history) if d.id == death.id), None)
    if index is None or r.state.death_history[index] != death:
        raise ValueError('Natural Deathrattle prohibition lost its original physical death')
    r.state.death_history[index] = saved
    return saved


def validate_prohibition_carrier(registry, card_id, kind, abilities, components=()):
    flags = tuple(a for a in abilities if a.kind == 'keyword' and a.keyword == Keyword.DEATHRATTLE_SUPPRESSOR)
    if not flags:
        return
    if kind != CardType.MINION or components or len(flags) != 1 or Keyword.DEATHRATTLE_SUPPRESSOR not in registry.card(card_id).keywords:
        raise ValueError('Deathrattle prohibition carrier differs from its native declaration')
    for ability in flags:
        ability.__post_init__()
from .registry import RuleContext


@dataclass(frozen=True)
class InvokeDeathrattle(Effect):
    context: RuleContext

    def __post_init__(self):
        if type(self.context) is not RuleContext or self.context.deathrattle is None:
            raise ValueError('Deathrattle invocation requires its captured context')
        saved=record(self.context.state,self.context.deathrattle.id)
        if (saved.capture!=self.context.deathrattle or saved.execution_order is not None or
                saved.completed or saved.interrupted):
            raise ValueError('Queued Deathrattle invocation requires its unstarted acceptance view')


@dataclass(frozen=True)
class FinishDeathrattle(Effect):
    record_id: int

    def __post_init__(self): _integer(self.record_id,'Deathrattle completion',1)


@dataclass(frozen=True)
class FinishDeathrattleBatch(Effect):
    batch: DeathrattleBatch
    context: RuleContext

    def __post_init__(self):
        validate_acceptance(self)


def record(state, record_id):
    _integer(record_id,'Deathrattle record',1)
    if record_id>len(state.deathrattle_history): raise ValueError('Unknown Deathrattle invocation')
    return state.deathrattle_history[record_id-1]


def activated_deathrattles(state, player_id, *, completed=None, origin=None, turn=None):
    """Trusted-host query, in actual execution order; queued work is excluded."""
    _player(player_id)
    if completed is not None and type(completed) is not bool: raise ValueError('Invalid completion filter')
    if origin is not None and origin not in ('death','effect','stored','history'): raise ValueError('Invalid Deathrattle origin')
    if turn is not None: _integer(turn,'Deathrattle turn',1)
    return tuple(sorted((d for d in state.deathrattle_history if d.execution_order is not None
        and d.capture.player_id==player_id and (completed is None or d.completed==completed)
        and (origin is None or d.capture.origin==origin) and (turn is None or d.capture.turn==turn)),
        key=lambda d:d.execution_order))


def validate_ability(state, registry, ability):
    if ability.kind!='deathrattle': return
    from .discovered_deathrattles import validate_ability as validate_discovered
    validate_discovered(state,registry,ability)
    from .deathrattle_copies import validate_ability as validate_copied
    validate_copied(state, registry, ability)
    from .deathrattle_inheritance import validate_ability as validate_inherited
    validate_inherited(state,registry,ability)
    from .deathrattle_memory import validate_ability as validate_memory_ability
    validate_memory_ability(state,registry,ability)
    from .consumed_cards import validate_payload as validate_consumed_payload
    validate_consumed_payload(state,registry,ability)
    registry.behavior(ability.behavior_id)
    if ability.id>=state.next_attachment_id:
        raise ValueError('Deathrattle ID exceeds the current/historical attachment counter')
    if ability.source_id is not None and ability.source_id not in state.entities:
        raise ValueError('Deathrattle ability source is absent')
    if ability.deathrattle_card_id is not None and registry.card(ability.deathrattle_card_id).deathrattle!=ability.behavior_id:
        raise ValueError('Deathrattle differs from its declaration card')
    if ability.deathrattle_grant_card_id is not None: registry.card(ability.deathrattle_grant_card_id)


def validate_capture(state, registry, capture):
    capture.__post_init__();validate_ability(state,registry,capture.ability)
    if (capture.carrier_id not in state.entities or registry.card(capture.card_id).kind!=capture.kind
            or capture.turn>state.turn or capture.action>state.action_number):
        raise ValueError('Invalid Deathrattle carrier or chronology')
    if capture.trigger_source_id is not None:
        if capture.trigger_source_id not in state.entities: raise ValueError('Unknown Deathrattle trigger source')
        registry.card(capture.trigger_source_card_id)
    if capture.death_id is not None:
        death=next((d for d in state.death_history if d.id==capture.death_id),None)
        if (death is None or death.deathrattles_blocked or (death.entity_id,death.controller,death.card_id,death.turn)!=
                (capture.carrier_id,capture.player_id,capture.card_id,capture.turn) or capture.ability not in death.abilities):
            raise ValueError('Deathrattle capture differs from its death record')
    if capture.origin=='history':
        from .historical_deathrattles import validate_capture as validate_historical_capture
        validate_historical_capture(state,registry,capture)


def validate_context(context, registry):
    if context.deathrattle_followup is not None:
        from .assemble_death_programs import validate_context as validate_followup
        validate_followup(context,registry)
        return
    capture=context.deathrattle
    if capture is None: return
    validate_capture(context.state,registry,capture)
    saved=record(context.state,capture.id)
    if (saved.capture!=capture or context.source_id!=capture.carrier_id or context.player_id!=capture.player_id
            or context.target_id is not None or (context.death.id if context.death else None)!=capture.death_id):
        raise ValueError('Captured Deathrattle context disagrees with its invocation')
    batch=next((b for b in context.state.deathrattle_batches if b.id==capture.group_id),None)
    if batch is None: raise ValueError('Deathrattle context lost its batch')
    # Queued contexts prove acceptance-time sources. Extra iterations use a
    # fresh execution view and must not recalculate that already accepted plan.
    if saved.execution_order is None:
        if not deathrattles_can_trigger(context.state):
            raise ValueError('Deathrattle acceptance view contains an active prohibition source')
        from .deathrattle_repeats import capture_plan
        from .deathrattle_matching import recipient_from_capture
        recipient=recipient_from_capture(context.state,registry,capture)
        if any(p.plan!=capture_plan(context.state,registry,capture.player_id,recipient,p.ability,context.death)
                for p in batch.payloads):
            raise ValueError('Deathrattle plan differs from its acceptance window')
    elif capture.repeat_index==1 and capture.trigger_index==1:
        raise ValueError('First Deathrattle callback must retain its acceptance view')
    if capture.origin=='effect' and saved.execution_order is None:
        entity=context.source
        if (entity.card_id!=capture.card_id or entity.controller!=capture.player_id or not entity.active
                or capture.ability not in entity.abilities):
            raise ValueError('Effect Deathrattle differs from its captured carrier')
        from .lifecycle import active_abilities
        if batch.abilities!=tuple(active_abilities(entity,'deathrattle')):
            raise ValueError('Effect Deathrattle batch differs from its accepted ability set')
        if capture.trigger_source_id is not None and context.state.entities[capture.trigger_source_id].card_id!=capture.trigger_source_card_id:
            raise ValueError('Effect Deathrattle trigger identity changed in its capture')
    if capture.origin=='stored' and saved.execution_order is None:
        from .stored_deathrattles import validate_context as validate_stored_context
        validate_stored_context(context,registry)
        from .lifecycle import active_abilities
        if batch.abilities!=tuple(active_abilities(context.source,'deathrattle')):
            raise ValueError('Stored Deathrattle batch differs from its accepted complete ability set')
    if capture.origin=='history' and saved.execution_order is None:
        from .historical_deathrattles import validate_context as validate_historical_context
        validate_historical_context(context,registry,batch)


def validate_acceptance(work,registry=None):
    """Retain the whole original group window through its last actual body.

Natural groups use the actual DeathRecord and the post-removal board window;
active groups retain their complete ability set and explicit trigger rounds.
Later callback views never replace this proof with an extra execution view.
"""
    if type(work.batch) is not DeathrattleBatch or type(work.context) is not RuleContext:
        raise ValueError('Deathrattle batch completion requires its complete acceptance proof')
    group=work.batch;group.__post_init__();context=work.context
    capture=context.deathrattle
    if capture is None or (capture.id,capture.group_id,capture.trigger_index,capture.repeat_index)!=(group.id,group.id,1,1):
        raise ValueError('Deathrattle batch proof lost its first accepted position')
    state=context.state
    saved=next((b for b in state.deathrattle_batches if b.id==group.id),None)
    rows=state.deathrattle_history[group.id-1:group.id-1+group.total]
    if (saved!=group or len(rows)!=group.total or
            (context.source_id,context.player_id,context.target_id)!=(capture.carrier_id,capture.player_id,None) or
            (context.death.id if context.death else None)!=capture.death_id):
        raise ValueError('Deathrattle batch proof differs from its complete accepted group')
    for index,row in enumerate(rows):
        ability,trigger_index,repeat_index=group.position(index)
        if (row.capture.id!=group.id+index or row.capture.group_id!=group.id or
                (row.capture.ability,row.capture.trigger_index,row.capture.repeat_index)!=(ability,trigger_index,repeat_index) or
                row.execution_order is not None or row.completed or row.interrupted):
            raise ValueError('Deathrattle batch proof must precede every accepted execution')
    if rows[0].capture!=capture:
        raise ValueError('Deathrattle batch proof changed its first capture')
    if registry is not None:
        validate_context(context,registry)
        # validate_context checks the complete active ability set and every
        # per-ability max plan. Natural coverage comes from its frozen death.
        if context.death is not None and group.abilities!=tuple(a for a in context.death.abilities
                if a.kind=='deathrattle' and not a.consumed):
            raise ValueError('Deathrattle batch proof differs from its complete death abilities')


def schedule_group(r, carrier_id, player_id, abilities, *, death=None, event=None, trigger_source_id=None, trigger_count=1, origin='effect', historical_root=None):
    from .deathrattle_repeats import capture_plan
    from .errors import ResolutionLimitExceeded
    entity=r.state.entities[carrier_id]
    if origin not in ('effect','stored','history') or death is not None and origin!='effect':
        raise ValueError('Unknown active/stored Deathrattle acceptance origin')
    if (origin=='history') != (historical_root is not None):
        raise ValueError('Historical Deathrattle requires its original selection')
    _integer(trigger_count,'Deathrattle trigger count',1)
    if death is not None and trigger_count!=1: raise ValueError('Natural death has one trigger round')
    if trigger_source_id is not None and trigger_source_id not in r.state.entities:
        raise ValueError('Unknown Deathrattle trigger source')
    if not abilities: return []
    if death is not None and death.deathrattles_blocked != (not deathrattles_can_trigger(r.state)):
        raise ValueError('Natural Deathrattle prohibition differs from its acceptance receipt')
    if not deathrattles_can_trigger(r.state):
        return []
    from .deathrattle_matching import capture_recipient_from_state
    recipient=capture_recipient_from_state(r.state,r.registry,carrier_id,death=death)
    batch=DeathrattleBatch(r.state.next_deathrattle_id,tuple(DeathrattlePayloadPlan(a,
        capture_plan(r.state,r.registry,player_id,recipient,a,death)) for a in abilities),trigger_count)
    if 3*batch.total+1>r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Deathrattle repetition exceeds resolution budget')
    captures=[]
    for index in range(batch.total):
        ability,trigger_index,repeat_index=batch.position(index)
        capture=DeathrattleCapture(batch.id+len(captures),batch.id,carrier_id,player_id,
            death.card_id if death else entity.card_id,entity.kind,ability,'death' if death else origin,
            death.id if death else None,trigger_source_id,
            (dict(historical_root.data)['issuer_card_id'] if historical_root is not None else
             r.state.entities[trigger_source_id].card_id if trigger_source_id else None),
            r.state.turn,r.state.action_number,repeat_index,trigger_index,historical_root)
        validate_capture(r.state,r.registry,capture);captures.append(capture)
    # All planned positions are persisted before any context is copied. This
    # makes missing/extra repetitions detectable even at suspended boundaries.
    r.state.deathrattle_batches.append(batch)
    r.state.deathrattle_history.extend(DeathrattleRecord(c) for c in captures)
    r.state.next_deathrattle_id+=batch.total
    if death is not None and death.zone==Zone.HERO:
        from .hero_lethal_windows import bind_deathrattle_group
        bind_deathrattle_group(r.state,death.id,batch.id)
    invocations=[InvokeDeathrattle(r.call(c.ability.behavior_id,carrier_id,player_id,
                event=event,death=death,deathrattle=c).context) for c in captures]
    return [*invocations,FinishDeathrattleBatch(batch,invocations[0].context)]


def begin(r, work):
    work.__post_init__();validate_context(work.context,r.registry)
    capture=work.context.deathrattle;saved=record(r.state,capture.id)
    if saved.capture!=capture or saved.execution_order is not None or saved.completed or saved.interrupted:
        raise ValueError('Deathrattle invocation is already started or mismatched')
    order=1+sum(d.execution_order is not None for d in r.state.deathrattle_history)
    fresh=capture.repeat_index>1 or capture.trigger_index>1
    source=r.state.entities[capture.carrier_id]if fresh else work.context.source
    attack=max(0,work.context.death.attack if work.context.death is not None else source.attack)
    r.state.deathrattle_history[capture.id-1]=replace(saved,execution_order=order,source_attack=attack)
    from .resolver import BehaviorCall
    call=BehaviorCall(capture.ability.behavior_id,work.context)
    if capture.repeat_index>1 or capture.trigger_index>1:
        call=r.call(capture.ability.behavior_id,capture.carrier_id,capture.player_id,
                    event=work.context.event,death=work.context.death,deathrattle=capture)
    return [call,FinishDeathrattle(capture.id)]


def finish(r, work):
    saved=record(r.state,work.record_id)
    if saved.execution_order is None or saved.completed or saved.interrupted:
        raise ValueError('Deathrattle is not running')
    r.state.deathrattle_history[saved.id-1]=replace(saved,completed=True)


def finish_batch(r,work):
    validate_acceptance(work,r.registry)
    from .deathrattle_acceptance import validate_queue
    validate_queue(r.state,r.registry,r._work_queue,r.rules.max_resolution_steps,closing=work)
    live=next((b for b in r.state.deathrattle_batches if b.id==work.batch.id),None)
    rows=r.state.deathrattle_history[work.batch.id-1:work.batch.id-1+work.batch.total]
    original=work.context.state.deathrattle_history[work.batch.id-1:work.batch.id-1+work.batch.total]
    if (live!=work.batch or len(rows)!=work.batch.total or
            tuple(row.capture for row in rows)!=tuple(row.capture for row in original) or
            any(not row.completed or row.interrupted for row in rows)):
        raise ValueError('Deathrattle batch must complete its full accepted span')


def interrupt(state):
    state.deathrattle_history=[replace(d,interrupted=True) if not d.completed and not d.interrupted else d
                              for d in state.deathrattle_history]


def validate_history(state, registry):
    if type(state.deathrattle_history) is not list: raise ValueError('Deathrattle history requires a list')
    _integer(state.next_deathrattle_id,'Deathrattle allocation counter',1)
    if state.next_deathrattle_id!=len(state.deathrattle_history)+1:
        raise ValueError('Deathrattle allocation counter differs from its complete captured history')
    previous=(0,0);orders=[];deaths=set();groups={}
    for index,saved in enumerate(state.deathrattle_history,1):
        if type(saved) is not DeathrattleRecord: raise ValueError('Expected Deathrattle record')
        saved.__post_init__();c=saved.capture;validate_capture(state,registry,c)
        if c.death_id is not None and saved.execution_order is not None:
            death=next(d for d in state.death_history if d.id==c.death_id)
            if saved.source_attack!=max(0,death.attack):raise ValueError('Deathrattle execution changed its original death Attack')
        if c.id!=index or not previous<=(c.turn,c.action)<=(state.turn,state.action_number):
            raise ValueError('Invalid Deathrattle capture chronology')
        previous=(c.turn,c.action)
        identity=(c.carrier_id,c.player_id,c.card_id,c.origin,c.death_id,c.trigger_source_id,c.trigger_source_card_id,c.turn,c.action,c.historical_root)
        if c.group_id not in groups:
            if c.group_id!=c.id: raise ValueError('Deathrattle group has no first invocation')
            groups[c.group_id]=(identity,set(),[])
        original,abilities,executions=groups[c.group_id]
        key=(c.ability.id,c.trigger_index,c.repeat_index)
        if identity!=original or key in abilities: raise ValueError('Deathrattle group identity or ability differs')
        abilities.add(key)
        if saved.execution_order is not None:
            if executions and saved.execution_order<=executions[-1]: raise ValueError('Deathrattle group executed out of order')
            executions.append(saved.execution_order)
        if saved.execution_order is not None: orders.append(saved.execution_order)
        if saved.interrupted and state.status=='playing': raise ValueError('Deathrattle interrupted before terminal state')
        if state.status!='playing' and not (saved.completed or saved.interrupted): raise ValueError('Unsettled terminal Deathrattle')
        if c.origin=='death':
            key=c.death_id,c.ability.id,c.repeat_index
            if key in deaths: raise ValueError('Duplicate natural Deathrattle invocation')
            deaths.add(key)
    if sorted(orders)!=list(range(1,len(orders)+1)): raise ValueError('Invalid Deathrattle execution order')
    validate_batches(state,registry)


def validate_batches(state, registry):
    from .deathrattle_repeats import validate_plan
    if type(state.deathrattle_batches) is not list: raise ValueError('Deathrattle batches require a list')
    offset=0
    for batch in state.deathrattle_batches:
        if type(batch) is not DeathrattleBatch: raise ValueError('Expected Deathrattle batch')
        batch.__post_init__()
        if batch.id!=offset+1 or offset+batch.total>len(state.deathrattle_history):
            raise ValueError('Deathrattle batch capture coverage differs')
        rows=state.deathrattle_history[offset:offset+batch.total];first=rows[0].capture
        death=next((d for d in state.death_history if d.id==first.death_id),None)
        from .deathrattle_matching import recipient_from_capture
        recipient=recipient_from_capture(state,registry,first)
        for payload in batch.payloads:
            validate_plan(state,registry,payload.plan,first.player_id,first.turn,recipient,payload.ability,death)
        for index,row in enumerate(rows):
            ability,trigger_index,repeat_index=batch.position(index)
            if (row.capture.group_id,row.capture.ability,row.capture.trigger_index,row.capture.repeat_index)!=(batch.id,ability,trigger_index,repeat_index):
                raise ValueError('Deathrattle batch order or repeat position differs')
            if index and row.execution_order is not None and not rows[index-1].completed:
                raise ValueError('Deathrattle repetition started before the previous position finished')
        if first.death_id is not None:
            if batch.trigger_count!=1: raise ValueError('Natural Deathrattle batch has one trigger round')
            death=next(d for d in state.death_history if d.id==first.death_id)
            if batch.abilities!=tuple(a for a in death.abilities if a.kind=='deathrattle' and not a.consumed):
                raise ValueError('Deathrattle batch payload differs from its death')
        offset+=batch.total
    if offset!=len(state.deathrattle_history): raise ValueError('Deathrattle captures lack their batch')


def validate_boundary(game):
    from .deathrattle_acceptance import validate_queue
    queue=(*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    validate_queue(game._state,game.registry,queue,game.ruleset.max_resolution_steps)
    from .historical_deathrattles import validate_boundary as validate_historical_boundary
    validate_historical_boundary(game)


def register(mechanics):
    from .deathrattle_repeats import register as register_repeats
    register_repeats(mechanics)
    from .historical_deathrattles import register as register_historical
    register_historical(mechanics)
    mechanics.register(InvokeDeathrattle,begin)
    mechanics.register(FinishDeathrattle,finish)
    mechanics.register(FinishDeathrattleBatch,finish_batch)
