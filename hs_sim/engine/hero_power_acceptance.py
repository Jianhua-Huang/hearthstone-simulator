"""Complete hero-power root proofs and their later typed acceptance windows.

Ordinary event views can precede successful acceptance, including mana_spent.
They are not original proof windows. These validators never rejudge current
witnesses, grant manual uses, emit events or add a gameplay checkpoint.
"""
from dataclasses import replace

from .model import CardType, GameState
from .repeat_provenance import (checked_live_attachments,
    accepted_repeat_source_references, _static_compatible, _reference_matches)
from .repeat_windows import original_acceptance_windows


def _same_root(old, new):
    return replace(new, completed=old.completed, interrupted=old.interrupted) == old


def _bind_prefix(state, original):
    if type(original) is not GameState or original.status != 'playing':
        raise ValueError('Hero power proof requires its original playing window')
    if ((state.turn, state.action_number) < (original.turn, original.action_number) or
            state.next_attachment_id < original.next_attachment_id or
            state.next_entity_id < original.next_entity_id or state.next_order < original.next_order or
            state.next_death_id < original.next_death_id or state.next_death_batch < original.next_death_batch):
        raise ValueError('Hero power proof moved its original chronology or allocation backwards')
    rows = state.hero_power_history[:len(original.hero_power_history)]
    if len(rows) != len(original.hero_power_history):
        raise ValueError('Hero power proof truncated its complete accepted root prefix')
    for old, new in zip(original.hero_power_history, rows):
        if (not _same_root(old, new) or old.completed and not new.completed or
                old.interrupted and not new.interrupted):
            raise ValueError('Hero power proof rewrote its complete accepted root prefix')
    if state.hero_power_payload_batches[:len(original.hero_power_payload_batches)] != original.hero_power_payload_batches:
        raise ValueError('Hero power proof changed its complete accepted payload batch prefix')
    rows = state.hero_power_payload_history[:len(original.hero_power_payload_history)]
    if len(rows) != len(original.hero_power_payload_history):
        raise ValueError('Hero power proof truncated its payload capture prefix')
    for old, new in zip(original.hero_power_payload_history, rows):
        if (new.capture != old.capture or old.execution_order is not None and
                new.execution_order != old.execution_order or old.completed and not new.completed or
                old.interrupted and not new.interrupted):
            raise ValueError('Hero power proof rewrote its payload identity or execution progress')
    if state.death_history[:len(original.death_history)] != original.death_history:
        raise ValueError('Hero power proof changed its immutable death prefix')
    rows = state.rewind_outcomes[:len(original.rewind_outcomes)]
    if len(rows) != len(original.rewind_outcomes):
        raise ValueError('Hero power proof truncated its accepted retained outcome prefix')
    for old, new in zip(original.rewind_outcomes, rows):
        if (replace(new, completed=old.completed, running=old.running,
                    finished=old.finished, interrupted=old.interrupted) != old or
                new.completed < old.completed or old.finished and not new.finished or
                old.interrupted and not new.interrupted):
            raise ValueError('Hero power proof rewrote its retained outcome identity or progress')


def _frozen_sources(state, inventory, registry):
    """Preserve removed HP declarations as provenance, never live contributors."""
    result = dict(inventory)
    for death in state.death_history:
        for ability in death.abilities:
            if ability.kind != 'hero_power_repeat':
                continue
            from .repeat_source_conditions import validate_source_declaration
            death.__post_init__()
            ability.__post_init__()
            validate_source_declaration(registry, ability.hero_power_repeat)
            if registry.card(death.card_id).kind != CardType.MINION:
                raise ValueError('Frozen hero power repeat source requires a minion carrier')
            current = result.get(ability.id)
            if current is not None:
                family, carrier, value = current
                if (family != 'ability' or carrier != death.entity_id or
                        replace(value, consumed=ability.consumed) != ability):
                    raise ValueError('Frozen hero power source changed its global attachment identity')
                if ability.id in inventory:
                    if ability.consumed and not value.consumed:
                        raise ValueError('Frozen hero power source reversed its later consumption')
                elif value.consumed and not ability.consumed:
                    raise ValueError('Hero power death history reversed a consumed source')
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
    """Bind every original source, including false policies and later receipts."""
    original = work.context.state
    _bind_prefix(state, original)
    before = _frozen_sources(original, checked_live_attachments(original), registry)
    live = _frozen_sources(state, checked_live_attachments(state), registry)
    def is_source(item):
        family, _, value = item
        return family == 'ability' and value.kind == 'hero_power_repeat'
    identities = {identity for identity, item in before.items() if is_source(item)}
    identities.update(identity for identity, item in live.items()
                      if identity < original.next_attachment_id and is_source(item))
    for identity in identities:
        accepted = before.get(identity)
        if accepted is None or not is_source(accepted):
            raise ValueError('Hero power original window lost an old repeat source identity')
        current = live.get(identity)
        if current is not None and (current[:2] != accepted[:2] or
                not _static_compatible(accepted[0], accepted[2], current[2])):
            raise ValueError('Hero power source changed its complete surviving identity')
    old_refs = accepted_repeat_source_references(original)
    new_refs = accepted_repeat_source_references(state)
    for key, reference in old_refs.items():
        if new_refs.get(key) != reference:
            raise ValueError('Hero power proof changed an already accepted source reference')
    earlier = {}
    for reference in old_refs.values():
        earlier.setdefault(reference.identity, []).append(reference)
    remaining = {}
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
        if reference.family == 'player_effects' and reference.path[0] == 'deathrattle':
            old = remaining.get(reference.identity)
            if old is not None and not _static_compatible('player_effects', old, reference.value):
                raise ValueError('Later player Deathrattle source reversed its owner clock')
            remaining[reference.identity] = reference.value


def _window_precedes(original, context, phase, identity, registry, work):
    """Compare the actual accepted marker, never merely an ID or action number."""
    foreign = context.state
    if phase == 'power':
        if identity > len(original.hero_power_history) or identity > len(foreign.hero_power_history):
            return False
        old, new = original.hero_power_history[identity-1], foreign.hero_power_history[identity-1]
        return old.failure is None and new.failure is None and _same_root(new, old)
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
        return _same_root(new, old)
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


def _bind_windows(registry, proofs, work):
    for context, phase, identity in original_acceptance_windows(work):
        for proof in proofs:
            if len(context.state.hero_power_history) < proof.record_id:
                if not _window_precedes(proof.context.state, context, phase, identity, registry, work):
                    raise ValueError('Later typed acceptance lost its enclosing original hero power root')
                continue
            validate_surviving_sources(context.state, proof, registry)


def validate_control_work(r, work):
    """Bind a foreign original window before the popped control can erase it."""
    from .hero_powers import FinishHeroPower
    if not original_acceptance_windows(work):
        return
    proofs = [item for item in r._work_queue if type(item) is FinishHeroPower]
    if type(work) is FinishHeroPower:
        proofs.insert(0, work)
    for proof in proofs:
        validate_surviving_sources(r.state, proof, r.registry)
    _bind_windows(r.registry, proofs, work)


def validate_queue(state, registry, queue, max_resolution_steps, *, terminal=False, closing=None):
    from .hero_powers import FinishHeroPower, power_record, validate_acceptance
    from .power_payloads import validate_queue as validate_payload_queue
    from .power_payloads import validate_history as validate_payload_history
    from .rewind_outcomes import (validate_history as validate_outcome_history,
                                 validate_queue as validate_outcome_queue)
    if type(state) is not GameState or type(terminal) is not bool:
        raise ValueError('Hero power queue requires its state and explicit boundary mode')
    queue = tuple(queue)
    if not terminal and state.status != 'playing' and queue:
        raise ValueError('Settled hero power boundary cannot retain queued work')
    if closing is not None:
        if type(closing) is not FinishHeroPower:
            raise ValueError('Hero power closing requires the actual popped root proof')
        queue = (closing, *queue)
    validate_payload_history(state, registry)
    validate_outcome_history(state, registry)
    pending = [p for p in state.hero_power_history if not p.completed and not p.interrupted]
    proofs = [work for work in queue if type(work) is FinishHeroPower]
    if [work.record_id for work in proofs] != [p.id for p in reversed(pending)]:
        raise ValueError('Hero power progress and complete root proof markers differ')
    for proof in proofs:
        validate_acceptance(proof, registry)
        if proof.context.power != power_record(state, proof.record_id):
            raise ValueError('Hero power changed its complete original accepted root')
        validate_surviving_sources(state, proof, registry)
    for child in pending:
        if child.parent_id is not None and power_record(state, child.parent_id) not in pending:
            raise ValueError('Hero power activation lost its enclosing operation')
    for parent in proofs:
        for child in proofs:
            if child.record_id > parent.record_id:
                validate_surviving_sources(child.context.state, parent, registry)
    for work in queue:
        _bind_windows(registry, proofs, work)
    validate_payload_queue(state, registry, queue, max_resolution_steps)
    validate_outcome_queue(state, queue, max_resolution_steps)


def validate_terminal_queue(r, queue):
    validate_queue(r.state, r.registry, queue, r.rules.max_resolution_steps, terminal=True)
