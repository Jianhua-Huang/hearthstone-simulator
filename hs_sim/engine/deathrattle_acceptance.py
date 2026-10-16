"""Whole-group Deathrattle proofs, including false and later source identities.

The original playing window remains separate from later execution views. These
checks are read-only; a terminal queue must be checked before it is abandoned.
"""
from dataclasses import replace

from .model import AbilityInstance, GameState
from .repeat_windows import original_acceptance_windows
from .repeat_provenance import (accepted_repeat_source_references,
    _static_compatible, _reference_matches)


def _attachments(state):
    from .deathrattle_repeats import checked_live_attachments
    return checked_live_attachments(state)


def _frozen_sources(state, inventory):
    """A removed natural self policy still has certified physical provenance."""
    result = dict(inventory)
    for death in state.death_history:
        for ability in death.abilities:
            if ability.kind != 'deathrattle_repeat':
                continue
            previous = result.get(ability.id)
            if previous is not None:
                family, carrier, value = previous
                if (family != 'ability' or carrier != death.entity_id or
                        type(value) is not AbilityInstance or
                        replace(value, consumed=ability.consumed) != ability):
                    raise ValueError('Frozen Deathrattle source has another global attachment identity')
                if ability.id in inventory:
                    if ability.consumed and not value.consumed:
                        raise ValueError('Frozen Deathrattle source reversed its later consumption')
                elif value.consumed and not ability.consumed:
                    raise ValueError('Deathrattle death history reversed a consumed source')
                elif ability.consumed:
                    result[ability.id] = ('ability', death.entity_id, ability)
            else:
                result[ability.id] = ('ability', death.entity_id, ability)
    return result










def _bind_prefix(state, original):
    if type(original) is not GameState or original.status != 'playing':
        raise ValueError('Deathrattle proof must retain its original playing acceptance window')
    for name in ('next_attachment_id', 'next_death_id', 'next_death_batch', 'next_deathrattle_id'):
        if getattr(state, name) < getattr(original, name):
            raise ValueError('Deathrattle proof allocation counters moved backwards')
    if (state.turn, state.action_number) < (original.turn, original.action_number):
        raise ValueError('Deathrattle proof precedes its current chronology')
    if state.death_history[:len(original.death_history)] != original.death_history:
        raise ValueError('Deathrattle proof changed its immutable death prefix')
    if state.deathrattle_batches[:len(original.deathrattle_batches)] != original.deathrattle_batches:
        raise ValueError('Deathrattle proof changed its complete accepted batch prefix')
    rows = state.deathrattle_history[:len(original.deathrattle_history)]
    if len(rows) != len(original.deathrattle_history):
        raise ValueError('Deathrattle proof truncated its original capture prefix')
    for old, new in zip(original.deathrattle_history, rows):
        if (new.capture != old.capture or old.execution_order is not None and new.execution_order != old.execution_order or
                old.source_attack is not None and new.source_attack!=old.source_attack or
                old.completed and not new.completed or old.interrupted and not new.interrupted):
            raise ValueError('Deathrattle proof rewrote its accepted prefix or execution progress')


def validate_surviving_sources(state, work, registry):
    from .paid_hand_acceptance import validate_history_prefix
    validate_history_prefix(work.context.state, state, registry)
    from .payment_projection import validate_cost_source_history
    validate_cost_source_history(work.context.state, state, registry)
    """Bind all original declarations and later typed acceptances, not witnesses."""
    original = work.context.state
    _bind_prefix(state, original)
    before = _frozen_sources(original, _attachments(original))
    live = _frozen_sources(state, _attachments(state))

    def is_source(item):
        family, _, value = item
        return (family == 'ability' and value.kind == 'deathrattle_repeat' or
                family == 'player_effects' and bool(registry.player_effect(value.spec_id).deathrattle_repeats))

    identities = {identity for identity, item in before.items() if is_source(item)}
    identities.update(identity for identity, item in live.items()
                      if identity < original.next_attachment_id and is_source(item))
    for identity in identities:
        accepted = before.get(identity)
        if accepted is None or not is_source(accepted):
            raise ValueError('Deathrattle original window lost an old repeat source identity')
        current = live.get(identity)
        if current is not None:
            family, carrier, old = accepted
            new_family, new_carrier, new = current
            if (family != new_family or carrier != new_carrier or
                    not _static_compatible(family, old, new)):
                raise ValueError('Deathrattle source changed its complete surviving identity')

    old_references = accepted_repeat_source_references(original)
    new_references = accepted_repeat_source_references(state)
    for key, reference in old_references.items():
        if new_references.get(key) != reference:
            raise ValueError('Deathrattle proof changed an already accepted source reference')
    # Check actual newly filled slots even if the enclosing play existed before
    # this window. New batch slots may reuse an earlier legitimate acceptance.
    earlier = {}
    for reference in old_references.values():
        earlier.setdefault(reference.identity, []).append(reference)
    remaining = {}
    for key, reference in new_references.items():
        if key in old_references or reference.identity >= original.next_attachment_id:
            continue
        item = before.get(reference.identity)
        if item is None:
            previous = earlier.get(reference.identity, ())
            if not any(old.family == reference.family and old.carrier == reference.carrier and
                       old.owner == reference.owner and old.value == reference.value and
                       old.spec_index == reference.spec_index and old.spec == reference.spec for old in previous):
                raise ValueError('Later repeat acceptance reused an absent or other-family old source ID')
        elif not _reference_matches(item, reference, registry):
            raise ValueError('Later repeat acceptance changed the original full source or typed family')
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
                raise ValueError('Accepted player repeat clock differs from its later surviving instance')
        if reference.family == 'player_effects' and reference.path[0] == 'deathrattle':
            instance = reference.value
            if instance.id in remaining:
                old = remaining[instance.id]
                if not _static_compatible('player_effects', old, instance):
                    raise ValueError('Later player Deathrattle source reversed its owner clock')
            remaining[instance.id] = instance


def validate_terminal_queue(r, queue):
    validate_queue(r.state, r.registry, tuple(queue), r.rules.max_resolution_steps, terminal=True)




def _original_windows(work):
    # Preserve this family's established chronology while the common inventory
    # distinguishes retained power payload batches for new family validators.
    return tuple((context, 'power', context.power_payload.power_id)
                 if phase == 'power_payload' else (context, phase, identity)
                 for context, phase, identity in original_acceptance_windows(work))


def _window_was_already_accepted(state, phase, identity):
    if phase == 'combo_policy':
        return identity <= len(state.combo_policy_receipts)
    if phase == 'end_turn':
        return identity <= len(state.end_turn_batches)
    if phase == 'power':
        return identity <= len(state.hero_power_history)
    if phase == 'deathrattle':
        return any(batch.id == identity for batch in state.deathrattle_batches)
    if identity > len(state.play_history):
        return False
    play = state.play_history[identity - 1]
    field = {'battlecry_activation': 'battlecry_acceptance',
             'spell_submission': 'spell_submission', 'spell_payload': 'spell_payload'}[phase]
    return getattr(play, field) is not None


def _bind_windows(registry, proofs, work):
    for context, phase, identity in _original_windows(work):
        for proof in proofs:
            original = proof.context.state
            present = any(batch.id == proof.batch.id for batch in context.state.deathrattle_batches)
            if not present:
                if not _window_was_already_accepted(original, phase, identity):
                    raise ValueError('Later acceptance window lost its enclosing original Deathrattle group')
                continue
            # Older foreign windows may precede this particular DR allocation.
            # Windows retaining the group are later/equal and bind its prefix.
            validate_surviving_sources(context.state, proof, registry)


def validate_control_work(r, work):
    """Before original foreign windows disappear, bind their complete sources."""
    from .deathrattles import FinishDeathrattleBatch
    if not _original_windows(work):
        return
    proofs = [item for item in r._work_queue if type(item) is FinishDeathrattleBatch]
    if proofs:
        for proof in proofs:
            validate_surviving_sources(r.state, proof, r.registry)
        _bind_windows(r.registry, proofs, work)


def validate_queue(state, registry, queue, max_resolution_steps, *, terminal=False, closing=None):
    from .deathrattles import (InvokeDeathrattle, FinishDeathrattle, FinishDeathrattleBatch,
                              record, validate_acceptance, validate_context)
    if type(terminal) is not bool or type(state) is not GameState:
        raise ValueError('Deathrattle queue requires its state and explicit boundary mode')
    if not terminal and state.status != 'playing' and queue:
        raise ValueError('Settled Deathrattle boundary cannot retain queued work')
    queue=tuple(queue)
    if closing is not None:
        if type(closing) is not FinishDeathrattleBatch:
            raise ValueError('Deathrattle queue closing requires the actual popped batch proof')
        queue=(closing,*queue)
    queued=[d.id for d in state.deathrattle_history if d.execution_order is None and not d.interrupted]
    running=sorted((d for d in state.deathrattle_history if d.execution_order is not None and not(d.completed or d.interrupted)),
                   key=lambda d:d.execution_order,reverse=True)
    starts=[w for w in queue if type(w) is InvokeDeathrattle]
    finishes=[w.record_id for w in queue if type(w) is FinishDeathrattle]
    if sorted(w.context.deathrattle.id for w in starts)!=queued or finishes!=[d.id for d in running]:
        raise ValueError('Deathrattle progress and pending control work disagree')
    pending_groups={d.capture.group_id for d in state.deathrattle_history if not(d.completed or d.interrupted)}
    if closing is not None:
        pending_groups.add(closing.batch.id)
    proofs=[w for w in queue if type(w) is FinishDeathrattleBatch]
    if (len(proofs)!=len(pending_groups) or {w.batch.id for w in proofs}!=pending_groups):
        raise ValueError('Pending Deathrattle groups require one complete batch acceptance proof')
    for work in proofs:
        validate_acceptance(work,registry)
        validate_surviving_sources(state,work,registry)
        live=next((b for b in state.deathrattle_batches if b.id==work.batch.id),None)
        rows=state.deathrattle_history[work.batch.id-1:work.batch.id-1+work.batch.total]
        original=work.context.state.deathrattle_history[work.batch.id-1:work.batch.id-1+work.batch.total]
        if (live!=work.batch or len(rows)!=work.batch.total or
                tuple(row.capture for row in rows)!=tuple(row.capture for row in original)):
            raise ValueError('Pending Deathrattle group differs from its complete acceptance proof')
        end=next(i for i,w in enumerate(queue) if w is work)
        if any(i>=end for i,w in enumerate(queue) if
                type(w) is InvokeDeathrattle and w.context.deathrattle.group_id==work.batch.id or
                type(w) is FinishDeathrattle and record(state,w.record_id).capture.group_id==work.batch.id):
            raise ValueError('Deathrattle batch closes before its full invocation span')
        parents=[d for d in work.context.state.deathrattle_history if d.execution_order is not None
                 and not(d.completed or d.interrupted)]
        if parents:
            parent=max(parents,key=lambda d:d.execution_order)
            current=record(state,parent.id)
            parent_end=next((i for i,w in enumerate(queue) if type(w) is FinishDeathrattle and w.record_id==parent.id),None)
            if (current.capture!=parent.capture or current.completed or current.interrupted or
                    parent_end is None or end>=parent_end):
                raise ValueError('Nested Deathrattle batch must finish before its accepted running parent')
    # Bind later original windows too: a false source may disappear before
    # the current boundary, while its identity was rewritten in a child proof.
    for parent in proofs:
        for child in proofs:
            if child.batch.id > parent.batch.id:
                validate_surviving_sources(child.context.state,parent,registry)
    for work in queue:
        _bind_windows(registry, proofs, work)
    # A queued Invoke expands in place. Batch closures form a stack over the
    # actual running roots and future groups, so siblings cannot cross and a
    # nested group cannot close its parent or resume a parent body prematurely.
    stack=[]
    for saved in reversed(running):
        group_id=saved.capture.group_id
        if group_id not in stack: stack.append(group_id)
    if closing is not None:
        stack.append(closing.batch.id)
    for work in queue:
        if type(work) is InvokeDeathrattle:
            group_id=work.context.deathrattle.group_id
            if not stack or stack[-1]!=group_id:
                if group_id in stack: raise ValueError('Deathrattle invocation crosses an unfinished nested batch')
                stack.append(group_id)
        elif type(work) is FinishDeathrattle:
            if not stack or stack[-1]!=record(state,work.record_id).capture.group_id:
                raise ValueError('Deathrattle completion crosses an unfinished nested batch')
        elif type(work) is FinishDeathrattleBatch:
            if not stack or stack[-1]!=work.batch.id:
                raise ValueError('Deathrattle batch completion order differs from nested execution')
            stack.pop()
    if stack: raise ValueError('Deathrattle invocation span lost its batch completion')
    for work in starts:
        validate_context(work.context,registry)
        if record(state,work.context.deathrattle.id).capture!=work.context.deathrattle:
            raise ValueError('Pending Deathrattle capture differs from live history')
        group_id=work.context.deathrattle.group_id
        live=next(b for b in state.deathrattle_batches if b.id==group_id)
        saved=next(b for b in work.context.state.deathrattle_batches if b.id==group_id)
        if live!=saved: raise ValueError('Pending Deathrattle plan differs from its accepted batch')
        for proof in proofs:
            if proof.batch.id <= group_id:
                validate_surviving_sources(work.context.state,proof,registry)
    groups={}
    for work in starts:
        c=work.context.deathrattle
        if c.id<=groups.get(c.group_id,0): raise ValueError('Pending Deathrattle group is out of order')
        groups[c.group_id]=c.id
    expected={(d.id,a.id) for d in state.death_history if not d.deathrattles_blocked for a in d.abilities if a.kind=='deathrattle' and not a.consumed}
    actual={(d.capture.death_id,d.capture.ability.id) for d in state.deathrattle_history if d.capture.origin=='death'}
    if actual!=expected: raise ValueError('Natural Deathrattle capture coverage differs from death history')
    if any(3*b.total+1>max_resolution_steps for b in state.deathrattle_batches):
        raise ValueError('Deathrattle batch exceeds resolution budget')

