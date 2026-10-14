"""complete original EndTurn batch and source proofs.

FinishEndTurnBatch.context is intentionally pre-install. The comparison-only
catalogue below adds its typed marker without querying subjects or witnesses.
No validator advances clocks, consumes a source, emits events or adds checkpoints.
"""
from copy import deepcopy
from dataclasses import replace

from .model import CardType, GameState, EndTurnCapture, EndTurnRecord
from .repeat_provenance import (accepted_repeat_source_references,
                               _static_compatible, _reference_matches)
from .repeat_windows import original_acceptance_windows


def validate_acceptance(work, registry):
    from .end_turns import validate_acceptance as validate_original_acceptance
    validate_original_acceptance(work, registry)


def _same_group(old, new):
    return replace(new, completed=old.completed, interrupted=old.interrupted) == old


def _captures(group):
    result = []
    for flat in range(group.total):
        index, repeat_index = group.position(flat)
        result.append(EndTurnCapture(group.first_id + flat, group.id, index,
            group.subjects[index], repeat_index, group.plans[index]))
    return tuple(result)


def _reference_window(work):
    """Derive typed own references only; never an acceptance query input."""
    original = work.context.state
    group = work.batch
    if group.id != len(original.end_turn_batches) + 1 or group.first_id != len(original.end_turn_history) + 1:
        raise ValueError('End-turn proof requires its actual pre-install batch window')
    compared = deepcopy(original)
    compared.end_turn_batches.append(group)
    compared.end_turn_history.extend(EndTurnRecord(capture) for capture in _captures(group))
    return compared


def _bind_prefix(state, work):
    original = work.context.state
    if type(original) is not GameState or original.status != 'playing':
        raise ValueError('End-turn proof requires its original playing window')
    if ((state.turn, state.action_number) < (original.turn, original.action_number) or
            state.next_attachment_id < original.next_attachment_id or
            state.next_entity_id < original.next_entity_id or state.next_order < original.next_order or
            state.next_death_id < original.next_death_id or state.next_death_batch < original.next_death_batch):
        raise ValueError('End-turn proof moved chronology or allocation backwards')
    groups = state.end_turn_batches[:len(original.end_turn_batches)]
    if len(groups) != len(original.end_turn_batches):
        raise ValueError('End-turn proof truncated its complete accepted batch prefix')
    for old, new in zip(original.end_turn_batches, groups):
        if (not _same_group(old, new) or old.completed and not new.completed or
                old.interrupted and not new.interrupted):
            raise ValueError('End-turn proof rewrote its accepted batch prefix')
    rows = state.end_turn_history[:len(original.end_turn_history)]
    if len(rows) != len(original.end_turn_history):
        raise ValueError('End-turn proof truncated its complete capture prefix')
    for old, new in zip(original.end_turn_history, rows):
        if (new.capture != old.capture or new.guard_id != old.guard_id or
                old.execution_order is not None and new.execution_order != old.execution_order or
                old.guard_event is not None and new.guard_event != old.guard_event or
                old.completed and not new.completed or old.interrupted and not new.interrupted or
                old.skipped and not new.skipped or old.guard_passed and not new.guard_passed):
            raise ValueError('End-turn proof rewrote its capture identity or execution progress')
    if state.death_history[:len(original.death_history)] != original.death_history:
        raise ValueError('End-turn proof changed its immutable death prefix')
    group = work.batch
    if group.id > len(state.end_turn_batches) or state.end_turn_batches[group.id - 1] != group:
        raise ValueError('End-turn proof lost its own complete pending batch marker')
    rows = state.end_turn_history[group.first_id - 1:group.first_id - 1 + group.total]
    if len(rows) != group.total or tuple(row.capture for row in rows) != _captures(group):
        raise ValueError('End-turn proof lost its whole accepted capture span')


def _frozen_sources(state, inventory, registry):
    result = dict(inventory)
    for death in state.death_history:
        for ability in death.abilities:
            if ability.kind != 'end_turn_repeat':
                continue
            from .repeat_source_conditions import validate_source_declaration
            death.__post_init__()
            ability.__post_init__()
            validate_source_declaration(registry, ability.end_turn_repeat)
            if registry.card(death.card_id).kind != CardType.MINION:
                raise ValueError('Frozen end-turn repeat source requires a minion carrier')
            current = result.get(ability.id)
            if current is not None:
                family, carrier, value = current
                if (family != 'ability' or carrier != death.entity_id or
                        replace(value, consumed=ability.consumed) != ability):
                    raise ValueError('Frozen end-turn source changed its global attachment identity')
                if ability.id in inventory:
                    if ability.consumed and not value.consumed:
                        raise ValueError('Frozen end-turn source reversed its later consumption')
                elif value.consumed and not ability.consumed:
                    raise ValueError('End-turn death history reversed a consumed source')
                elif ability.consumed:
                    result[ability.id] = ('ability', death.entity_id, ability)
            else:
                result[ability.id] = ('ability', death.entity_id, ability)
    return result


def validate_surviving_sources(state, work, registry):
    from .paid_hand_acceptance import validate_history_prefix
    validate_history_prefix(work.context.state, state, registry)
    from .payment_projection import validate_cost_source_history
    validate_cost_source_history(work.context.state, state, registry)
    from .end_turn_matching import validated_source_inventory
    original = work.context.state
    _bind_prefix(state, work)
    before = _frozen_sources(original, validated_source_inventory(original, registry), registry)
    live = _frozen_sources(state, validated_source_inventory(state, registry), registry)
    def is_source(item):
        family, _, value = item
        return (family == 'ability' and value.kind == 'end_turn_repeat' or
                family == 'player_effects' and bool(registry.player_effect(value.spec_id).end_turn_repeats))
    identities = {identity for identity, item in before.items() if is_source(item)}
    identities.update(identity for identity, item in live.items()
                      if identity < original.next_attachment_id and is_source(item))
    for identity in identities:
        accepted = before.get(identity)
        if accepted is None or not is_source(accepted):
            raise ValueError('End-turn original window lost an old repeat source identity')
        current = live.get(identity)
        if current is not None and (current[:2] != accepted[:2] or
                not _static_compatible(accepted[0], accepted[2], current[2])):
            raise ValueError('End-turn source changed its complete surviving identity')
    old_refs = accepted_repeat_source_references(_reference_window(work))
    new_refs = accepted_repeat_source_references(state)
    for key, reference in old_refs.items():
        if new_refs.get(key) != reference:
            raise ValueError('End-turn proof changed an already accepted source reference')
    earlier = {}
    for reference in old_refs.values():
        earlier.setdefault(reference.identity, []).append(reference)
    clocks = {'deathrattle': {}, 'end_turn': {}}
    for key, reference in new_refs.items():
        if key in old_refs or reference.identity >= original.next_attachment_id:
            continue
        item = before.get(reference.identity)
        if item is None:
            if not any((old.family, old.carrier, old.owner, old.value, old.spec_index, old.spec) ==
                       (reference.family, reference.carrier, reference.owner, reference.value,
                        reference.spec_index, reference.spec)
                       for old in earlier.get(reference.identity, ())):
                raise ValueError('Later repeat acceptance reused an absent or other-family original source ID')
        elif not _reference_matches(item, reference, registry):
            raise ValueError('Later repeat acceptance changed the complete original typed source')
        if item is not None and reference.value is None:
            current = live.get(reference.identity)
            if current is not None and (current[:2] != item[:2] or
                    not _static_compatible(item[0], item[2], current[2])):
                raise ValueError('Later ID-only repeat acceptance changed its complete physical source')
        if reference.family == 'player_effects':
            current = live.get(reference.identity)
            if current is not None and (current[0] != 'player_effects' or
                    current[1] != reference.owner or
                    not _static_compatible('player_effects', reference.value, current[2])):
                raise ValueError('Later player repeat source reversed its surviving owner clock')
            family = reference.path[0]
            if family in clocks:
                old = clocks[family].get(reference.identity)
                if old is not None and not _static_compatible('player_effects', old, reference.value):
                    raise ValueError('Later player repeat source reversed its accepted family clock')
                clocks[family][reference.identity] = reference.value


def _bind_windows(registry, proofs, work):
    from .end_turns import FinishEndTurnBatch
    for context, phase, identity in original_acceptance_windows(work):
        for proof in proofs:
            if work is proof:
                # Own complete typed marker is deliberately not in its context.
                if type(work) is not FinishEndTurnBatch or phase != 'end_turn' or identity != proof.batch.id:
                    raise ValueError('End-turn own proof changed its window identity')
                validate_acceptance(proof, registry)
                continue
            if len(context.state.end_turn_batches) < proof.batch.id:
                if not _window_precedes(proof.context.state, context, phase, identity, registry, work):
                    raise ValueError('Later typed acceptance lost its enclosing original end-turn batch')
                continue
            validate_surviving_sources(context.state, proof, registry)


def validate_control_work(r, work):
    from .end_turns import FinishEndTurnBatch
    if not original_acceptance_windows(work):
        return
    proofs = [item for item in r._work_queue if type(item) is FinishEndTurnBatch]
    if type(work) is FinishEndTurnBatch:
        proofs.insert(0, work)
    for proof in proofs:
        validate_surviving_sources(r.state, proof, r.registry)
    _bind_windows(r.registry, proofs, work)


def _validate_completion_stack(state, queue):
    from .end_turns import (InvokeEndTurn, CheckActiveEndTurn, FinishEndTurn,
                            FinishEndTurnBatch, batch, record)
    from .hero_powers import CheckHeroPowerTrigger
    from .limited_triggers import CheckLimitedTrigger
    # All active batches are already accepted and form the chain independently
    # checked by _validate_queue_controls. A parent can have no running body
    # while its ordinary reaction tail still owns a pending complete proof.
    stack = [group.id for group in state.end_turn_batches
             if not (group.completed or group.interrupted)]
    for work in queue:
        context = (work.context if type(work) in (InvokeEndTurn, CheckActiveEndTurn, CheckHeroPowerTrigger)
                   else work.end_turn_context if type(work) is CheckLimitedTrigger else None)
        if context is not None and context.end_turn is not None:
            if not stack or stack[-1] != context.end_turn.batch_id:
                raise ValueError('End-turn queued body crosses its acceptance nesting stack')
        elif type(work) is FinishEndTurn:
            if not stack or stack[-1] != record(state, work.record_id).capture.batch_id:
                raise ValueError('End-turn body completion crosses its enclosing batch')
        elif type(work) is FinishEndTurnBatch:
            identity = work.batch.id
            if not stack or stack[-1] != identity:
                raise ValueError('End-turn batch completion crosses its acceptance nesting stack')
            stack.pop()
    if stack:
        raise ValueError('End-turn queued work lost its complete closing stack')


def validate_queue(state, registry, queue, max_resolution_steps, *, events,
                   ending_turn, terminal=False, closing=None):
    from .end_turns import FinishEndTurnBatch, validate_history
    if type(state) is not GameState or type(terminal) is not bool or type(ending_turn) is not bool:
        raise ValueError('End-turn queue requires its state and explicit boundary mode')
    queue = tuple(queue)
    if not terminal and state.status != 'playing' and queue:
        raise ValueError('Settled end-turn boundary cannot retain queued work')
    if closing is not None:
        if type(closing) is not FinishEndTurnBatch:
            raise ValueError('End-turn closing requires the actual popped batch proof')
        queue = (closing, *queue)
    validate_history(state, registry)
    _validate_queue_controls(state, registry, queue, max_resolution_steps,
                             events=events, ending_turn=ending_turn,
                             stable=not terminal and closing is None)
    proofs = [work for work in queue if type(work) is FinishEndTurnBatch]
    for proof in proofs:
        validate_surviving_sources(state, proof, registry)
    for work in queue:
        _bind_windows(registry, proofs, work)
    _validate_completion_stack(state, queue)


def validate_boundary(game):
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    validate_queue(game._state, game.registry, queue, game.ruleset.max_resolution_steps,
                   events=game._events, ending_turn=bool(game._frame and game._frame.ending_turn))


def validate_terminal_queue(r, queue):
    validate_queue(r.state, r.registry, queue, r.rules.max_resolution_steps,
                   events=r.game._events, ending_turn=r.ending_turn, terminal=True)


# prepare_v115_proposed_end_turn_patch.py appends two complete source-derived
# pure functions here: _window_precedes and _validate_queue_controls. It preserves
# each current full function in the proposal manifest before adapting arguments.


def _window_precedes(original, context, phase, identity, registry, work):
    """Compare the actual accepted marker, never merely an ID or action number."""
    foreign = context.state
    if phase == 'power':
        if identity > len(original.hero_power_history) or identity > len(foreign.hero_power_history):
            return False
        old, new = original.hero_power_history[identity-1], foreign.hero_power_history[identity-1]
        return old.failure is None and new.failure is None and _same_group(new, old)
    if phase == 'power_payload':
        old = next((b for b in original.hero_power_payload_batches if b.id == identity), None)
        new = next((b for b in foreign.hero_power_payload_batches if b.id == identity), None)
        return old is not None and old == new
    if phase == 'deathrattle':
        old = next((b for b in original.deathrattle_batches if b.id == identity), None)
        new = next((b for b in foreign.deathrattle_batches if b.id == identity), None)
        return old is not None and old == new
    if phase == 'end_turn':
        from .end_turns import FinishEndTurnBatch
        if identity > len(original.end_turn_batches):
            return False
        # The whole-batch proof deliberately precedes installing that batch;
        # its complete accepted marker lives on the typed control itself.
        new = work.batch if type(work) is FinishEndTurnBatch else (
            foreign.end_turn_batches[identity-1] if identity <= len(foreign.end_turn_batches) else None)
        if new is None or new.id != identity:
            return False
        old = original.end_turn_batches[identity-1]
        return _same_group(new, old)
    if phase == 'combo_policy':
        if identity > len(original.combo_policy_receipts) or identity > len(foreign.combo_policy_receipts):
            return False
        old, new = original.combo_policy_receipts[identity-1], foreign.combo_policy_receipts[identity-1]
        return replace(old, consumption_applied=new.consumption_applied) == new
    if identity > len(original.play_history) or identity > len(foreign.play_history):
        return False
    field = {'battlecry_activation': 'battlecry_acceptance',
             'spell_submission': 'spell_submission', 'spell_payload': 'spell_payload'}[phase]
    old, new = getattr(original.play_history[identity-1], field), getattr(foreign.play_history[identity-1], field)
    if phase in ('spell_submission', 'spell_payload'):
        from .spell_acceptance import capture_submission, capture_payload, _identity
        play = foreign.play_history[identity-1]
        if _identity(original.play_history[identity-1]) != _identity(play):
            return False
        if phase == 'spell_submission':
            new = capture_submission(foreign, registry, play)
        else:
            if play.countered:
                return original.play_history[identity-1].countered and old is None
            new = capture_payload(foreign, registry, play, context.target_id)
    return old is not None and old == new


def _validate_queue_controls(state, registry, queue, max_resolution_steps, *, events, ending_turn, stable):
    from .resolver import BehaviorCall
    from .end_turns import (InvokeEndTurn, CheckActiveEndTurn, FinishEndTurn,
        FinishEndTurnBatch, validate_context, record, batch, guarded)
    from .hero_powers import CheckHeroPowerTrigger
    from .limited_triggers import CheckLimitedTrigger
    controls=[];finishes=[];group_finishes=[]
    for index,work in enumerate(queue):
        if type(work) is BehaviorCall and work.context.end_turn is not None:
            raise ValueError('End-turn callback bypassed its invocation control')
        context=work.context if type(work) in (InvokeEndTurn,CheckHeroPowerTrigger,CheckActiveEndTurn) else work.end_turn_context if type(work) is CheckLimitedTrigger else None
        if context is not None and context.end_turn is not None:
            if type(work) is CheckActiveEndTurn: work.__post_init__()
            validate_context(context,registry);capture=context.end_turn
            if record(state,capture.id).capture!=capture or batch(state,capture.batch_id)!=batch(context.state,capture.batch_id):
                raise ValueError('Pending end-turn work changed its frozen identity')
            if type(work) is InvokeEndTurn:
                work.__post_init__();validate_context(work.acceptance,registry)
                if work.acceptance.end_turn!=capture: raise ValueError('End-turn invocation lost its proof')
                if stable and not capture.repeat_index and capture.subject.ability is not None and registry.card(capture.subject.card_id).kind==CardType.HERO_POWER:
                    raise ValueError('A first installed-power end-turn cannot suspend between its check and invocation')
                if not capture.repeat_index and capture.subject.ability is not None and capture.subject.ability.kind=='limited_trigger' and\
                        (record(context.state,capture.id).guard_event!=record(state,capture.id).guard_event or
                         context.state.action_number!=record(state,capture.id).guard_event.action):
                    raise ValueError('Pending finite end-turn callback lost its actual consumption event')
            if capture.repeat_index and type(work) is not InvokeEndTurn:
                raise ValueError('Extra end-turn work cannot repeat an original live guard')
            expected_guard=(record(state,capture.id-capture.repeat_index).guard_passed if capture.repeat_index else
                            type(work) is InvokeEndTurn and guarded(capture.subject,registry))
            if record(state,capture.id).guard_passed!=expected_guard:
                raise ValueError('Pending end-turn guard phase differs from its activation fact')
            controls.append((index,capture.id))
        if type(work) is FinishEndTurn: finishes.append((index,work.record_id))
        if type(work) is FinishEndTurnBatch:
            validate_acceptance(work,registry)
            if batch(state,work.batch.id)!=work.batch: raise ValueError('Pending end-turn completion changed its accepted batch')
            group_finishes.append((index,work.batch.id))
    queued=[x.capture.id for x in state.end_turn_history if x.execution_order is None and not(x.interrupted or x.skipped)]
    running=sorted((x for x in state.end_turn_history if x.execution_order is not None and not(x.completed or x.interrupted)),key=lambda x:x.execution_order,reverse=True)
    if sorted(i for _,i in controls)!=queued or [i for _,i in finishes]!=[x.capture.id for x in running]:
        raise ValueError('End-turn facts and pending controls disagree')
    for group in state.end_turn_batches:
        positions=[i for _,i in controls if record(state,i).capture.batch_id==group.id]
        if positions!=sorted(positions): raise ValueError('Pending end-turn work reordered its own accepted group')
    active=[x.id for x in state.end_turn_batches if not(x.completed or x.interrupted)]
    if sorted(i for _,i in group_finishes)!=active: raise ValueError('End-turn window lost its complete acceptance proof')
    naturals=[i for i in active if batch(state,i).activation.kind=='natural']
    if naturals and (len(naturals)!=1 or not ending_turn or
            state.turn!=batch(state,naturals[0]).turn or state.active_player!=batch(state,naturals[0]).event.player_id):
        raise ValueError('Natural end-turn window is outside its original turn boundary')
    for position,group_id in enumerate(active):
        group=batch(state,group_id);origin=group.activation
        if group.turn!=state.turn or origin.parent_batch_id!=(active[position-1] if position else None):
            raise ValueError('Active end-turn windows lost their complete nesting chain')
        end=next(i for i,g in group_finishes if g==group_id)
        if origin.parent_batch_id is not None:
            parent_end=next(i for i,g in group_finishes if g==origin.parent_batch_id)
            if end>=parent_end: raise ValueError('Nested end-turn window completes after its parent')
        if origin.parent_id is not None:
            parent=record(state,origin.parent_id)
            marker=next((i for i,rid in finishes if rid==origin.parent_id),None)
            if parent.completed or parent.interrupted or marker is None or end>=marker:
                raise ValueError('Nested end-turn window outlived its running parent body')
    for index,record_id in (*controls,*finishes):
        capture=record(state,record_id).capture
        boundary=next((i for i,b in group_finishes if b==capture.batch_id),None)
        if boundary is None or index>=boundary: raise ValueError('End-turn subject must precede its window completion')
        if capture.id>batch(state,capture.batch_id).first_id:
            previous=record(state,record_id-1)
            if previous.execution_order is not None and not previous.completed:
                marker=next((i for i,rid in finishes if rid==previous.capture.id),None)
                if marker is None or marker>=index: raise ValueError('End-turn subject precedes its running predecessor')
    for group in state.end_turn_batches:
        origin=group.activation
        if origin.event_cursor>len(events): raise ValueError('End-turn activation invents an event cursor')
        if group.event is not None and (group.event.sequence>origin.event_cursor or
                events[group.event.sequence-1]!=group.event):
            raise ValueError('End-turn cause is absent from its actual event prefix')
        if origin.kind=='phase':
            starts=[e for e in events[:origin.event_cursor] if e.kind=='turn_started' and dict(e.data).get('turn')==group.turn]
            if (starts and group.event.sequence<starts[-1].sequence or
                    group.event.kind=='turn_started' and dict(group.event.data).get('turn')!=group.turn):
                raise ValueError('End-turn phase cause is outside its real accepted turn')
        if 3*group.total+sum(guarded(s,registry) for s in group.subjects)+1>max_resolution_steps:
            raise ValueError('End-turn expansion exceeds budget')
    if [x.event for x in state.end_turn_batches if x.activation.kind=='natural']!=[e for e in events if e.kind=='turn_ended']:
        raise ValueError('End-turn windows do not cover all natural boundary facts')
    receipts=[x.guard_event for x in state.end_turn_history if not x.capture.repeat_index and x.guard_event is not None]
    marked=[e for e in events if e.kind=='limited_trigger_used' and 'end_turn_guard_id' in dict(e.data)]
    if (len({e.sequence for e in receipts})!=len(receipts) or
            sorted(receipts,key=lambda e:e.sequence)!=marked):
        raise ValueError('End-turn finite guards do not uniquely cover their real consumption facts')
