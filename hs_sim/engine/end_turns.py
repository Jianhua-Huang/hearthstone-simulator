"""Explicit end-of-turn bodies, separate from a natural turn's clocks.

Diagnostic invocation/completion controls replace existing callback positions;
they never add a gameplay checkpoint or a second turn event.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace

from .effects import Effect, _integer, _player
from .model import (CardType, Zone, Event, EndTurnSubject, EndTurnBatch,
                    EndTurnCapture, EndTurnRecord, EndTurnRequest, EndTurnActivation)
from .registry import RuleContext
from .errors import ResolutionError, ResolutionLimitExceeded


def listeners(state):
    ids=[i for p in state.players.values() for i in
         (p.hero_id,*p.board,*p.quests,*p.secrets,*([p.weapon_id] if p.weapon_id is not None else []),*p.hero_power_ids)]
    rows=[(state.entities[i].controller,state.entities[i].entered_order,i,None) for i in ids]
    rows.extend((p.id,e.entered_order,e.source_id,e) for p in state.players.values() for e in p.player_effects)
    return sorted(rows,key=lambda row:(row[0]!=state.active_player,row[1],row[2]))


def eligible(state,registry,subject,event):
    spec=subject.spec
    if (spec.turn_scope=='controller' and event.player_id!=subject.player_id or
            spec.turn_scope=='opponent' and event.player_id==subject.player_id): return False
    context=RuleContext(deepcopy(state),subject.source_id,subject.player_id,event.target_id,event,
                        player_effect=subject.player_effect,trigger=subject.ability)
    result=registry.trigger_condition(spec.condition_id)(context)
    if type(result) is not bool: raise ResolutionError('End-turn condition must return bool')
    return result


def accepted_subjects(state,registry,event):
    """Pure acceptance query on the window before adding diagnostic records."""
    from .lifecycle import active_abilities
    from .limited_triggers import capture as capture_finite
    subjects=[]
    for player_id,order,source_id,player_effect in listeners(state):
        entity=state.entities[source_id]
        if player_effect is not None:
            for index,trigger in enumerate(registry.player_effect(player_effect.spec_id).triggers):
                if trigger.end_turn is None or trigger.event!=event.kind: continue
                subject=EndTurnSubject(source_id,player_id,player_effect.source_card_id,order,
                    entity.zone_epoch,player_effect=player_effect,trigger=trigger,trigger_index=index)
                if eligible(state,registry,subject,event): subjects.append(subject)
            continue
        if entity.zone in (Zone.SECRET,Zone.QUEST): continue
        abilities=sorted((*active_abilities(entity,'trigger'),*active_abilities(entity,'dormant_trigger'),
                          *active_abilities(entity,'limited_trigger')),key=lambda a:a.id)
        for ability in abilities:
            if ability.end_turn_spec is None: continue
            if ability.kind=='limited_trigger' and capture_finite(
                    SimpleNamespace(state=state,registry=registry),entity,ability,event,()) is None: continue
            subject=EndTurnSubject(source_id,player_id,entity.card_id,order,entity.zone_epoch,ability=ability)
            if eligible(state,registry,subject,event): subjects.append(subject)
    return tuple(subjects)


def callback_target(group, registry):
    if group.activation.kind == 'natural': return group.event.target_id
    profile=registry.end_turn_profile(group.activation.request.profile_id)
    return group.event.target_id if profile.target_policy=='cause' and group.event is not None else None


def active_eligible(state,registry,subject,event,profile):
    if profile.turn_scope=='respect':
        if event is None or event.player_id not in (1,2):
            raise ResolutionError('Respecting end-turn scope requires a real beneficiary event')
        if (subject.spec.turn_scope=='controller' and event.player_id!=subject.player_id or
                subject.spec.turn_scope=='opponent' and event.player_id==subject.player_id): return False
    target=event.target_id if profile.target_policy=='cause' and event is not None else None
    context=RuleContext(deepcopy(state),subject.source_id,subject.player_id,target,event,
                        player_effect=subject.player_effect,trigger=subject.ability)
    conditions=[subject.spec.condition_id]
    if subject.ability is not None and subject.ability.kind=='limited_trigger':
        conditions.append(subject.ability.limited_trigger.condition_id)
    for condition in conditions:
        result=registry.trigger_condition(condition)(context)
        if type(result) is not bool: raise ResolutionError('End-turn condition must return bool')
        if not result: return False
    return True


def selected_subjects(state,registry,event,activation):
    """The selector chooses physical carriers; the profile chooses eligibility."""
    from .lifecycle import active_abilities
    from .limited_triggers import live_source
    request=activation.request;selector=request.selector
    profile=registry.end_turn_profile(request.profile_id)
    if profile.kind!=activation.kind: raise ValueError('End-turn profile changed its origin')
    if profile.kind=='phase' and (event is None or event.kind not in profile.cause_events):
        raise ResolutionError('End-turn phase requires its registered real cause')
    if profile.cause_events and (event is None or event.kind not in profile.cause_events):
        raise ResolutionError('End-turn cause is outside its registered profile')
    if any(i not in state.entities for i in selector.entity_ids):
        raise ResolutionError('Unknown selected end-turn carrier')
    if any(i>=state.next_attachment_id for i in selector.player_effect_ids):
        raise ResolutionError('Unknown selected end-turn player effect')
    kinds={CardType.MINION:'minion',CardType.WEAPON:'weapon',CardType.HERO_POWER:'hero_power',CardType.LOCATION:'location',CardType.HERO:'hero'}
    result=[]
    for player_id,order,source_id,instance in listeners(state):
        entity=state.entities[source_id]
        kind='player_effect' if instance is not None else kinds.get(entity.kind)
        if player_id not in selector.player_ids or kind not in selector.carrier_kinds: continue
        if selector.mode=='selected' and (instance.id not in selector.player_effect_ids if instance is not None else
                                         source_id not in selector.entity_ids): continue
        if instance is not None:
            for index,trigger in enumerate(registry.player_effect(instance.spec_id).triggers):
                if trigger.end_turn is None: continue
                subject=EndTurnSubject(source_id,player_id,instance.source_card_id,order,entity.zone_epoch,
                    player_effect=instance,trigger=trigger,trigger_index=index)
                if active_eligible(state,registry,subject,event,profile): result.append(subject)
            continue
        abilities=sorted((*active_abilities(entity,'trigger'),*active_abilities(entity,'dormant_trigger'),
                          *active_abilities(entity,'limited_trigger')),key=lambda a:a.id)
        for ability in abilities:
            if ability.end_turn_spec is None: continue
            if ability.kind=='limited_trigger' and not live_source(entity): continue
            subject=EndTurnSubject(source_id,player_id,entity.card_id,order,entity.zone_epoch,ability=ability)
            if active_eligible(state,registry,subject,event,profile): result.append(subject)
    return tuple(result)


def running_parent(state):
    rows=[row for row in state.end_turn_history if row.execution_order is not None and
          not(row.completed or row.interrupted)]
    return max(rows,key=lambda row:row.execution_order).capture.id if rows else None


def parent_batch(state):
    return max((b.id for b in state.end_turn_batches if not(b.completed or b.interrupted)),default=None)


@dataclass(frozen=True)
class TriggerEndTurnEffects(Effect):
    player_id: int
    request: EndTurnRequest
    source_id: int | None = None
    cause: Event | None = None

    def __post_init__(self):
        _player(self.player_id)
        if type(self.request) is not EndTurnRequest: raise ValueError('Expected end-turn request')
        self.request.__post_init__()
        if self.source_id is not None: _integer(self.source_id,'End-turn issuer',1)
        if self.cause is not None and type(self.cause) is not Event: raise ValueError('Expected real end-turn cause')


@dataclass(frozen=True)
class CheckActiveEndTurn(Effect):
    context: RuleContext
    acceptance: RuleContext

    def __post_init__(self):
        if type(self.context) is not RuleContext or self.context!=self.acceptance or self.context.end_turn is None:
            raise ValueError('Active end-turn guard requires its original acceptance')
        capture=self.context.end_turn
        if capture.repeat_index or batch(self.context.state,capture.batch_id).activation.kind=='natural':
            raise ValueError('Active end-turn guard requires a first effect/phase position')
        ability=capture.subject.ability
        if (ability is None or ability.kind!='limited_trigger' and
                not(self.context.source.kind==CardType.HERO_POWER and ability.kind=='trigger')):
            raise ValueError('Active end-turn guard requires a finite or installed-power subject')
        row=record(self.context.state,capture.id)
        if row.capture!=capture or row.guard_passed or row.execution_order is not None or row.skipped:
            raise ValueError('Active end-turn guard requires a queued first position')


def record(state,record_id):
    _integer(record_id,'End-turn record',1)
    if record_id>len(state.end_turn_history): raise ValueError('Unknown end-turn activation')
    return state.end_turn_history[record_id-1]


def batch(state,batch_id):
    _integer(batch_id,'End-turn batch',1)
    if batch_id>len(state.end_turn_batches): raise ValueError('Unknown end-turn batch')
    return state.end_turn_batches[batch_id-1]


def activated_end_turns(state,player_id,*,source_id=None,completed=None,turn=None):
    """Trusted-host actual execution facts; never part of a player observation."""
    _player(player_id)
    for value in (source_id,turn):
        if value is not None: _integer(value,'End-turn history bound',1)
    if completed is not None and type(completed) is not bool: raise ValueError('Invalid end-turn completion filter')
    return tuple(sorted((row for row in state.end_turn_history if row.execution_order is not None and
        row.capture.subject.player_id==player_id and
        (source_id is None or row.capture.subject.source_id==source_id) and
        (completed is None or row.completed==completed) and
        (turn is None or batch(state,row.capture.batch_id).turn==turn)),key=lambda row:row.execution_order))


@dataclass(frozen=True)
class InvokeEndTurn(Effect):
    context: RuleContext
    acceptance: RuleContext

    def __post_init__(self):
        if type(self.context) is not RuleContext or type(self.acceptance) is not RuleContext:
            raise ValueError('End-turn invocation requires both callback and acceptance contexts')
        capture=self.acceptance.end_turn
        if capture is None or self.context.end_turn!=capture:
            raise ValueError('End-turn invocation lost its accepted subject')
        saved=record(self.acceptance.state,capture.id)
        if saved.capture!=capture or saved.execution_order is not None or saved.completed or saved.interrupted or saved.skipped or saved.guard_passed:
            raise ValueError('End-turn invocation requires its queued acceptance view')
        group=batch(self.acceptance.state,capture.batch_id)
        if any(x.execution_order is not None or x.completed or x.interrupted or x.skipped or x.guard_passed
               for x in self.acceptance.state.end_turn_history[group.first_id-1:group.first_id-1+group.total]):
            raise ValueError('End-turn acceptance must precede all original reactions')
        subject=capture.subject
        if self.acceptance.trigger!=subject.ability:
            raise ValueError('End-turn acceptance lost its original ability')
        if capture.repeat_index:
            if self.context!=self.acceptance:
                raise ValueError('Queued extra end-turn must retain its original acceptance view')
        elif subject.ability is not None and subject.ability.kind=='limited_trigger':
            a=subject.ability
            if self.context.trigger!=replace(a,uses_remaining=a.uses_remaining-1,consumed=a.uses_remaining==1):
                raise ValueError('Finite end-turn callback requires its post-consumption window')


@dataclass(frozen=True)
class FinishEndTurn(Effect):
    record_id: int
    def __post_init__(self): _integer(self.record_id,'End-turn completion',1)


@dataclass(frozen=True)
class FinishEndTurnBatch(Effect):
    batch: EndTurnBatch
    context: RuleContext

    def __post_init__(self):
        if type(self.batch) is not EndTurnBatch or type(self.context) is not RuleContext:
            raise ValueError('End-turn batch completion requires its whole acceptance proof')
        self.batch.__post_init__()
        if self.batch.completed or self.batch.interrupted: raise ValueError('End-turn acceptance proof is already settled')


def prepare_group(r,event,activation,subjects):
    from .end_turn_matching import validated_source_inventory
    validated_source_inventory(r.state, r.registry)
    from .end_turn_repeats import capture_plan
    plans=tuple(capture_plan(r.state,r.registry,subject) for subject in subjects)
    if 3*sum(p.repetitions for p in plans)+sum(guarded(s,r.registry) for s in subjects)+1>r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('End-turn subject expansion exceeds resolution budget')
    group=EndTurnBatch(len(r.state.end_turn_batches)+1,len(r.state.end_turn_history)+1,event,r.state.turn,subjects,
                       plans=plans,activation=activation)
    proof=RuleContext(deepcopy(r.state),activation.issuer_id,activation.issuer_player_id,event=event)
    r.state.end_turn_batches.append(group)
    captures=[]
    for flat in range(group.total):
        index,repeat_index=group.position(flat)
        captures.append(EndTurnCapture(group.first_id+flat,group.id,index,subjects[index],repeat_index,plans[index]))
    r.state.end_turn_history.extend(EndTurnRecord(c) for c in captures)
    return {s.key:tuple(c for c in captures if c.index==i) for i,s in enumerate(subjects)},FinishEndTurnBatch(group,proof)


def prepare(r,event):
    if any(not(b.completed or b.interrupted) for b in r.state.end_turn_batches):
        raise ResolutionError('A natural turn cannot end inside an unfinished end-turn activation')
    issuer=r.state.entities[r.state.players[event.player_id].hero_id]
    activation=EndTurnActivation('natural',issuer.id,issuer.card_id,event.player_id,r.state.action_number,
        event.sequence,issuer.zone_epoch,issuer.entered_order)
    return prepare_group(r,event,activation,accepted_subjects(r.state,r.registry,event))


def trigger(r,effect,*,selection=None):
    effect.__post_init__()
    profile=r.registry.end_turn_profile(effect.request.profile_id)
    if effect.cause is not None and effect.cause not in r.game._events:
        raise ResolutionError('An end-turn activation cannot invent a cause event')
    issuer_id=effect.source_id if effect.source_id is not None else r.player(effect.player_id).hero_id
    issuer=r.state.entities.get(issuer_id)
    if issuer is None: raise ResolutionError('Unknown end-turn activation issuer')
    activation=EndTurnActivation(profile.kind,issuer.id,issuer.card_id,effect.player_id,r.state.action_number,
        len(r.game._events),issuer.zone_epoch,issuer.entered_order,effect.request,running_parent(r.state),parent_batch(r.state),selection,
        'random_one' if selection is not None else 'direct')
    if profile.kind=='phase':
        starts=[e for e in r.game._events if e.kind=='turn_started' and dict(e.data).get('turn')==r.state.turn]
        if effect.cause is None or starts and effect.cause.sequence<starts[-1].sequence or\
                effect.cause.kind=='turn_started' and dict(effect.cause.data).get('turn')!=r.state.turn:
            raise ResolutionError('End-turn phase cause is outside the current real turn')
    subjects=selected_subjects(r.state,r.registry,effect.cause,activation)
    captures,finish=prepare_group(r,effect.cause,activation,subjects)
    work=[]
    for subject in subjects: work.extend(schedule(r,captures[subject.key]))
    return [*work,finish]


def schedule(r,captures):
    """Expand only this old listener slot, preserving intervening ordinary work."""
    from .hero_powers import CheckHeroPowerTrigger
    from .limited_triggers import CheckLimitedTrigger,candidate
    work=[]
    for capture in captures:
        subject=capture.subject;group=batch(r.state,capture.batch_id);event=group.event
        call=r.call(subject.behavior_id,subject.source_id,subject.player_id,callback_target(group,r.registry),event=event,
                    trigger=subject.ability,player_effect=subject.player_effect,end_turn=capture)
        if not capture.repeat_index and group.activation.kind!='natural' and guarded(subject,r.registry):
            work.append(CheckActiveEndTurn(call.context,call.context))
        elif not capture.repeat_index and subject.ability is not None and subject.ability.kind=='limited_trigger':
            work.append(CheckLimitedTrigger(candidate(r.state.entities[subject.source_id],subject.ability),event,call.context))
        elif not capture.repeat_index and subject.ability is not None and r.registry.card(subject.card_id).kind==CardType.HERO_POWER:
            work.append(CheckHeroPowerTrigger(call.behavior_id,call.context,subject.ability.id))
        else: work.append(InvokeEndTurn(call.context,call.context))
    return work


def validate_subject(state,registry,subject):
    subject.__post_init__();registry.card(subject.card_id);registry.behavior(subject.behavior_id)
    registry.trigger_condition(subject.spec.condition_id)
    if (subject.source_id not in state.entities or subject.entered_order>=state.next_order or
            subject.zone_epoch>state.entities[subject.source_id].zone_epoch):
        raise ValueError('End-turn subject has invalid historical provenance')
    if subject.ability is not None:
        a=subject.ability
        if a.id>=state.next_attachment_id or a.source_id is not None and a.source_id not in state.entities:
            raise ValueError('End-turn ability has invalid provenance')
        if registry.card(subject.card_id).kind not in (CardType.MINION,CardType.WEAPON,CardType.LOCATION,CardType.HERO_POWER,CardType.HERO):
            raise ValueError('End-turn subject has an unsupported physical carrier')
        if a.kind=='limited_trigger': registry.validate_limited_trigger(a.limited_trigger)
        for entity in state.entities.values():
            current=next((x for x in entity.abilities if x.id==a.id),None)
            if current is None: continue
            comparable=replace(current,uses_remaining=a.uses_remaining,consumed=a.consumed) if a.kind=='limited_trigger' else replace(current,consumed=a.consumed)
            if entity.id!=subject.source_id or comparable!=a:
                raise ValueError('Historical end-turn ability differs from its surviving attachment')
            if a.kind=='limited_trigger' and current.uses_remaining>a.uses_remaining:
                raise ValueError('Historical end-turn finite uses moved backwards')
    else:
        effect=subject.player_effect;spec=registry.player_effect(effect.spec_id)
        if (effect.id>=state.next_attachment_id or effect.created_turn>state.turn or
                (effect.remaining_turns is None)!=(spec.duration is None) or
                spec.duration is not None and effect.remaining_turns>spec.duration or
                subject.trigger_index>=len(spec.triggers) or spec.triggers[subject.trigger_index]!=subject.trigger):
            raise ValueError('End-turn player subject differs from its registered declaration')
        for player in state.players.values():
            current=next((e for e in player.player_effects if e.id==effect.id),None)
            if current is not None and (player.id!=subject.player_id or replace(current,remaining_turns=effect.remaining_turns)!=effect):
                raise ValueError('Historical end-turn player effect differs from its surviving instance')


def validate_context(context,registry):
    capture=context.end_turn
    if capture is None: return
    if type(capture) is not EndTurnCapture: raise ValueError('Invalid end-turn capture')
    capture.__post_init__();validate_subject(context.state,registry,capture.subject)
    saved=record(context.state,capture.id);group=batch(context.state,capture.batch_id);subject=capture.subject
    if (saved.capture!=capture or saved.completed or saved.interrupted or saved.skipped or
            group.completed or group.interrupted or not 0<=capture.index<len(group.subjects) or group.subjects[capture.index]!=subject or
            group.plans[capture.index]!=capture.plan or
            capture.id!=group.first_id+sum(p.repetitions for p in group.plans[:capture.index])+capture.repeat_index or context.event!=group.event or
            (context.source_id,context.player_id,context.target_id)!=(subject.source_id,subject.player_id,callback_target(group,registry)) or
            context.player_effect!=subject.player_effect):
        raise ValueError('End-turn context differs from its accepted position')
    from .end_turn_repeats import validate_plan
    validate_plan(context.state,registry,capture.plan,subject,group.turn)
    started=saved.execution_order is not None
    if started and (not capture.repeat_index or not record(context.state,saved.guard_id).completed):
        raise ValueError('Only a started extra may use a fresh end-turn callback view')
    if subject.ability is not None:
        if context.trigger!=subject.ability:
            # Finite callbacks preserve their old post-consumption capture window.
            a=subject.ability
            updated=replace(a,uses_remaining=a.uses_remaining-1,consumed=a.uses_remaining==1) if a.kind=='limited_trigger' else None
            if context.trigger!=updated: raise ValueError('End-turn callback changed its accepted ability')
        if started and context.trigger!=callback_ability(subject):
            raise ValueError('Fresh extra changed its accepted callback ability')
        if not started and context.trigger not in context.source.abilities:
            raise ValueError('End-turn captured ability is absent from its callback window')
    elif not started and subject.player_effect not in context.state.players[subject.player_id].player_effects:
        raise ValueError('End-turn captured player effect is absent from its window')


def started_extra_context(context):
    """Specific codec exemption, after validate_context has checked the phase."""
    return (context.end_turn is not None and context.end_turn.repeat_index>0 and
            record(context.state,context.end_turn.id).execution_order is not None)


def callback_ability(subject):
    a=subject.ability
    return replace(a,uses_remaining=a.uses_remaining-1,consumed=a.uses_remaining==1) if a is not None and a.kind=='limited_trigger' else a


def validate_acceptance(work,registry):
    from .end_turn_repeats import capture_plan
    work.__post_init__();group=work.batch;context=work.context;state=context.state
    from .end_turn_matching import validated_source_inventory
    validated_source_inventory(state, registry)
    if state.status != 'playing': raise ValueError('End-turn proof requires its original playing window')
    origin=group.activation
    validate_activation(state,registry,group)
    from .end_turn_producers import validate_selection
    validate_selection(state,registry,origin,acceptance=True)
    issuer=state.entities[origin.issuer_id]
    expected=accepted_subjects(state,registry,group.event) if origin.kind=='natural' else selected_subjects(state,registry,group.event,origin)
    if (context.end_turn is not None or context.event!=group.event or context.player_id!=origin.issuer_player_id or
            context.source_id!=origin.issuer_id or context.target_id is not None or
            state.turn!=group.turn or state.action_number!=origin.action or
            (issuer.card_id,issuer.zone_epoch,issuer.entered_order)!=(origin.issuer_card_id,origin.issuer_zone_epoch,origin.issuer_entered_order) or
            running_parent(state)!=origin.parent_id or parent_batch(state)!=origin.parent_batch_id or
            group.id!=len(state.end_turn_batches)+1 or group.first_id!=len(state.end_turn_history)+1 or
            expected!=group.subjects or
            tuple(capture_plan(state,registry,s) for s in group.subjects)!=group.plans):
        raise ValueError('End-turn batch differs from its complete acceptance window')
    if origin.kind=='natural' and (state.active_player!=context.player_id or context.source_id!=state.players[context.player_id].hero_id):
        raise ValueError('Natural end-turn acceptance differs from its ending player')


def validate_activation(state,registry,group):
    origin=group.activation;origin.__post_init__()
    entity=state.entities.get(origin.issuer_id)
    registry.card(origin.issuer_card_id)
    if (entity is None or origin.issuer_zone_epoch>entity.zone_epoch or
            origin.issuer_entered_order>=state.next_order or origin.action>state.action_number):
        raise ValueError('End-turn activation has invalid issuer provenance')
    from .end_turn_producers import validate_selection
    validate_selection(state,registry,origin)
    if origin.kind!='natural':
        profile=registry.end_turn_profile(origin.request.profile_id)
        if profile.kind!=origin.kind or profile.kind=='phase' and (group.event is None or group.event.kind not in profile.cause_events):
            raise ValueError('End-turn activation differs from its registered profile')
        if profile.cause_events and (group.event is None or group.event.kind not in profile.cause_events):
            raise ValueError('End-turn activation has an unsupported cause')
        if profile.turn_scope=='respect' and (group.event is None or group.event.player_id not in (1,2)):
            raise ValueError('End-turn activation lost its explicit beneficiary')
    if origin.parent_batch_id is not None:
        if origin.parent_batch_id>=group.id or batch(state,origin.parent_batch_id).turn!=group.turn:
            raise ValueError('End-turn activation has an invalid enclosing window')
    if origin.parent_id is not None:
        parent=record(state,origin.parent_id)
        if parent.capture.batch_id>=group.id or parent.execution_order is None:
            raise ValueError('End-turn activation has an invalid parent')
        if batch(state,parent.capture.batch_id).turn!=group.turn:
            raise ValueError('Nested end-turn activation changed its enclosing turn')
        ancestors=set();ancestor=origin.parent_batch_id
        while ancestor is not None:
            if ancestor in ancestors: raise ValueError('End-turn enclosing windows form a cycle')
            ancestors.add(ancestor);ancestor=batch(state,ancestor).activation.parent_batch_id
        if parent.capture.batch_id not in ancestors:
            raise ValueError('End-turn parent body is outside its enclosing window ancestry')


def check_active(r,work):
    """A first finite/installed-power guard; neither fabricates a turn event."""
    from .lifecycle import active_abilities,refresh_entity
    from .limited_triggers import live_source
    work.__post_init__();validate_context(work.context,r.registry)
    capture=work.context.end_turn;subject=capture.subject;old=work.context.source
    current=r.state.entities.get(subject.source_id)
    if (current is None or (current.controller,current.card_id,current.zone_epoch,current.entered_order)!=
            (subject.player_id,subject.card_id,old.zone_epoch,subject.entered_order)):
        return skip(r,capture)
    ability=subject.ability
    if ability.kind=='limited_trigger':
        if not live_source(current) or ability not in active_abilities(current,'limited_trigger'):
            return skip(r,capture)
        updated=callback_ability(subject)
        current.abilities[current.abilities.index(ability)]=updated
        refresh_entity(current)
        r.emit('limited_trigger_used',source_id=current.id,player_id=subject.player_id,
            amount=updated.uses_remaining,trigger_keyword=None,_end_turn_guard=capture,
            end_turn_guard_id=capture.id,end_turn_ability_id=ability.id)
        group=batch(r.state,capture.batch_id)
        call=r.call(subject.behavior_id,subject.source_id,subject.player_id,callback_target(group,r.registry),
            event=group.event,trigger=updated,end_turn=capture)
        return [InvokeEndTurn(call.context,work.acceptance)]
    if (current.zone!=Zone.HERO_POWER or current.id not in r.player(subject.player_id).hero_power_ids or
            ability not in active_abilities(current,'trigger')):
        return skip(r,capture)
    pass_guard(r.state,capture)
    return [InvokeEndTurn(work.context,work.acceptance)]


def skip(r,capture):
    state=r.state;saved=record(state,capture.id)
    if saved.capture!=capture or saved.execution_order is not None or saved.completed or saved.interrupted or saved.skipped:
        raise ValueError('Cannot skip a started end-turn subject')
    if capture.repeat_index: raise ValueError('Only the original guard may reject an end-turn subject')
    for i in range(capture.id,capture.id+capture.plan.repetitions):
        row=record(state,i)
        if row.guard_id!=capture.id or row.execution_order is not None or row.guard_passed:
            raise ValueError('End-turn skip has a mismatched or already started repetition')
        state.end_turn_history[i-1]=replace(row,skipped=True)
    queue=r._work_queue
    remaining=[w for w in queue if not(type(w) is InvokeEndTurn and
        w.acceptance.end_turn is not None and record(state,w.acceptance.end_turn.id).guard_id==capture.id)]
    queue.clear();queue.extend(remaining)


def pass_guard(state,capture,event=None):
    saved=record(state,capture.id)
    if saved.capture!=capture or saved.execution_order is not None or saved.completed or saved.interrupted or saved.skipped or saved.guard_passed:
        raise ValueError('Cannot accept an already settled end-turn guard')
    if capture.repeat_index: raise ValueError('Extra end-turn execution cannot consume another guard')
    for i in range(capture.id,capture.id+capture.plan.repetitions):
        row=record(state,i)
        if row.guard_id!=capture.id or row.execution_order is not None or row.guard_passed or row.skipped:
            raise ValueError('End-turn guard has a mismatched repetition')
        state.end_turn_history[i-1]=replace(row,guard_passed=True,guard_event=event)


def guarded(subject,registry):
    return subject.ability is not None and (subject.ability.kind=='limited_trigger' or registry.card(subject.card_id).kind==CardType.HERO_POWER)


def validate_guard_event(group,first,action_number):
    """Bind finite consumption to this exact accepted ability and first slot."""
    if first.guard_event is None: return
    subject=first.capture.subject;ability=subject.ability;event=first.guard_event
    data=dict(event.data)
    for key in ('end_turn_guard_id','end_turn_ability_id'):
        _integer(data.get(key),'End-turn consumption identity',1)
    expected=dict(end_turn_guard_id=first.capture.id,end_turn_ability_id=ability.id,
                  trigger_keyword=ability.limited_trigger.keyword.value if ability.limited_trigger.keyword else None)
    if (event.kind!='limited_trigger_used' or event.source_id!=subject.source_id or event.player_id!=subject.player_id or
            event.target_id is not None or event.amount!=ability.uses_remaining-1 or
            not group.activation.action<=event.action<=action_number or event.sequence<=group.activation.event_cursor or data!=expected):
        raise ValueError('Finite end-turn guard differs from its actual consumption event')


def begin(r,work):
    from .resolver import BehaviorCall
    work.__post_init__();validate_context(work.acceptance,r.registry);validate_context(work.context,r.registry)
    capture=work.context.end_turn;saved=record(r.state,capture.id)
    if saved.capture!=capture or saved.execution_order is not None or saved.completed or saved.interrupted or saved.skipped:
        raise ValueError('End-turn subject is already started or mismatched')
    if saved.guard_passed!=guarded(capture.subject,r.registry):
        raise ValueError('End-turn invocation bypassed its original live guard')
    if capture.repeat_index and not record(r.state,capture.id-1).completed:
        raise ValueError('Extra end-turn invocation preceded its completed original work')
    r.state.end_turn_history[capture.id-1]=replace(saved,execution_order=1+sum(x.execution_order is not None for x in r.state.end_turn_history))
    context=work.context
    if capture.repeat_index:
        group=batch(r.state,capture.batch_id)
        context=r.call(capture.subject.behavior_id,capture.subject.source_id,capture.subject.player_id,
            callback_target(group,r.registry),event=group.event,
            trigger=callback_ability(capture.subject),player_effect=capture.subject.player_effect,end_turn=capture).context
        validate_context(context,r.registry)
    return [BehaviorCall(capture.subject.behavior_id,context),FinishEndTurn(capture.id)]


def finish(r,work):
    saved=record(r.state,work.record_id)
    if saved.execution_order is None or saved.completed or saved.interrupted or saved.skipped:
        raise ValueError('End-turn subject is not running')
    r.state.end_turn_history[saved.capture.id-1]=replace(saved,completed=True)


def finish_batch(r,work):
    validate_acceptance(work,r.registry)
    if batch(r.state,work.batch.id)!=work.batch: raise ValueError('End-turn live batch lost its frozen identity')
    rows=r.state.end_turn_history[work.batch.first_id-1:work.batch.first_id-1+work.batch.total]
    if len(rows)!=work.batch.total or any(not(x.completed or x.skipped) for x in rows):
        raise ValueError('End-turn batch has unfinished subjects')
    from .end_turn_acceptance import validate_queue
    validate_queue(r.state, r.registry, r._work_queue, r.rules.max_resolution_steps,
                   events=r.game._events, ending_turn=r.ending_turn, closing=work)
    r.state.end_turn_batches[work.batch.id-1]=replace(work.batch,completed=True)


def interrupt(state):
    state.end_turn_history=[replace(x,interrupted=True) if not(x.completed or x.interrupted or x.skipped) else x for x in state.end_turn_history]
    state.end_turn_batches=[replace(x,interrupted=True) if not(x.completed or x.interrupted) else x for x in state.end_turn_batches]


def validate_history(state,registry):
    from .end_turn_repeats import validate_plan
    if type(state.end_turn_history) is not list or type(state.end_turn_batches) is not list:
        raise ValueError('End-turn facts require lists')
    offset=0;orders=[];previous_cursor=0;previous_action=0;previous_turn=0;natural_turn=0;natural_event=0
    for index,group in enumerate(state.end_turn_batches,1):
        if type(group) is not EndTurnBatch: raise ValueError('Expected end-turn batch')
        group.__post_init__()
        if group.interrupted and state.status=='playing': raise ValueError('Playing end-turn window cannot be interrupted')
        origin=group.activation;validate_activation(state,registry,group)
        if (group.id!=index or group.first_id!=offset+1 or group.turn<previous_turn or group.turn>state.turn or
                origin.event_cursor<previous_cursor or origin.action<previous_action):
            raise ValueError('End-turn batches have invalid activation positions')
        if origin.kind=='natural':
            if group.turn<=natural_turn or group.event.sequence<=natural_event:
                raise ValueError('Natural end-turn batches have invalid unique turn positions')
            natural_turn=group.turn;natural_event=group.event.sequence
        rows=state.end_turn_history[offset:offset+group.total]
        if len(rows)!=group.total: raise ValueError('End-turn batch lost its complete repetition positions')
        for subject,plan in zip(group.subjects,group.plans):
            validate_subject(state,registry,subject)
            validate_plan(state,registry,plan,subject,group.turn)
        for position,saved in enumerate(rows):
            subject_index,repeat_index=group.position(position)
            subject=group.subjects[subject_index];plan=group.plans[subject_index]
            if type(saved) is not EndTurnRecord: raise ValueError('Expected end-turn record')
            saved.__post_init__();capture=saved.capture
            if (capture.id,capture.batch_id,capture.index,capture.subject,capture.repeat_index,capture.plan)!=\
                    (offset+position+1,index,subject_index,subject,repeat_index,plan):
                raise ValueError('End-turn history differs from its complete batch positions')
            first=rows[position-repeat_index]
            if (saved.guard_id!=first.capture.id or saved.guard_passed!=first.guard_passed or
                    saved.guard_event!=first.guard_event or saved.skipped!=first.skipped):
                raise ValueError('End-turn repetitions lost their single original guard receipt')
            if not repeat_index: validate_guard_event(group,first,state.action_number)
            if saved.execution_order is not None: orders.append(saved.execution_order)
            if saved.guard_passed and not guarded(subject,registry) or saved.execution_order is not None and saved.guard_passed!=guarded(subject,registry):
                raise ValueError('End-turn activation has inconsistent guard evidence')
            if saved.skipped and (subject.ability is None or subject.ability.kind!='limited_trigger' and registry.card(subject.card_id).kind!=CardType.HERO_POWER):
                raise ValueError('Only guarded end-turn subjects may be skipped')
            if not(group.completed or group.interrupted) and first.guard_passed and subject.ability.kind=='limited_trigger':
                current=next((a for a in state.entities[subject.source_id].abilities if a.id==subject.ability.id),None)
                expected=callback_ability(subject)
                later=sum(x.guard_event is not None and not x.capture.repeat_index and
                    x.guard_event.sequence>first.guard_event.sequence and x.capture.subject.ability is not None and
                    x.capture.subject.ability.id==subject.ability.id for x in state.end_turn_history)
                if current is not None and (current.uses_remaining!=expected.uses_remaining-later or
                        current.consumed!=(expected.uses_remaining-later==0) or
                        replace(current,uses_remaining=expected.uses_remaining,consumed=expected.consumed)!=expected):
                    raise ValueError('End-turn finite uses lack their exact subsequent consumption receipts')
            if group.completed and not(saved.completed or saved.skipped) or group.interrupted and not(saved.completed or saved.skipped or saved.interrupted):
                raise ValueError('Settled end-turn batch contains unsettled subjects')
            if not group.interrupted and saved.interrupted: raise ValueError('Playing end-turn batch contains interrupted subjects')
            if position and saved.execution_order is not None and not(rows[position-1].completed or rows[position-1].skipped):
                raise ValueError('End-turn subject started before its predecessor settled')
            previous_orders=[x.execution_order for x in rows[:position] if x.execution_order is not None]
            if saved.execution_order is not None and previous_orders and saved.execution_order<=max(previous_orders):
                raise ValueError('End-turn actual execution reordered accepted positions')
        if origin.parent_id is not None:
            parent=record(state,origin.parent_id)
            if any(row.execution_order is not None and row.execution_order<=parent.execution_order for row in rows):
                raise ValueError('Nested end-turn body started before its parent')
        previous_cursor=origin.event_cursor;previous_action=origin.action;previous_turn=group.turn;offset+=len(rows)
    if offset!=len(state.end_turn_history) or sorted(orders)!=list(range(1,len(orders)+1)):
        raise ValueError('End-turn history coverage or actual execution order is invalid')
    from .end_turn_repeats import validate_source_history
    validate_source_history(state, registry)


def validate_boundary(game):
    from .end_turn_acceptance import validate_boundary as validate_complete_boundary
    validate_complete_boundary(game)


def register(mechanics):
    mechanics.register(TriggerEndTurnEffects,trigger)
    mechanics.register(CheckActiveEndTurn,check_active)
    mechanics.register(InvokeEndTurn,begin)
    mechanics.register(FinishEndTurn,finish)
    mechanics.register(FinishEndTurnBatch,finish_batch)
