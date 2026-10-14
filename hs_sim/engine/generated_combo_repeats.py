"""Actual generated Combo identities and activation-only family acceptance.

Generated bodies use their actual whole-card child rather than paid hand IDs.
The complete max and all matched finite policies are accepted once; every
captured payload then receives its own actual Combo record per repetition.
Single and Battlecry-only origins accept one actual Combo without querying or
consuming Combo repetition sources. Family and retained origins accept max plans.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer
from .errors import ResolutionError
from .model import CardType, ComboAcceptanceReceipt, ComboPolicyReceipt, ComboRecord, ComboPayload

PROFILE = 'generated_family_repeat_after_install_v1'
RETAINED_PROFILE = 'generated_retained_family_after_install_v1'
REPEAT_PROFILES = (PROFILE, RETAINED_PROFILE)
SINGLE_PROFILES = ('generated_after_install_v1', 'generated_battlecry_repeat_after_install_v1')
PROFILES = (*SINGLE_PROFILES, *REPEAT_PROFILES)
KINDS = (CardType.MINION, CardType.WEAPON, CardType.HERO)


def capture(state, registry, activation, profile_id):
    if profile_id not in PROFILES or activation.source.kind not in KINDS:
        return None, None
    if activation.profile_id != profile_id:
        raise ValueError('Generated Combo cannot substitute its actual origin profile')
    from .combo_acceptance_matching import capture_generated_activation
    from .combo_matching import capture_recipient
    from .combos import capture as capture_payloads
    payloads = capture_payloads(state.entities[activation.source.entity_id])
    plan, modifiers = capture_generated_activation(state, registry, activation, payloads)
    recipient = capture_recipient(state, registry, activation.source.entity_id)
    status = 'activated' if plan is not None else 'disabled' if payloads else 'no_payload'
    policy = ComboPolicyReceipt(len(state.combo_policy_receipts) + 1, None, 'activation',
        activation.turn, activation.action, recipient, plan is not None, modifiers, False,
        origin='generated_body', physical_child_id=activation.child_id, player_id=activation.player_id)
    accepted = ComboAcceptanceReceipt(activation.player_id, recipient, status, payloads, plan, policy.id)
    return accepted, policy


def install_policy(state, progress, policy):
    if policy is None:
        if progress.combo_repeat_acceptance is not None:
            raise ResolutionError('Generated Combo erased its actual policy acceptance')
        return
    if (policy.id != len(state.combo_policy_receipts) + 1 or
            progress.combo_repeat_acceptance is None or
            progress.combo_repeat_acceptance.policy_receipt_id != policy.id or
            policy.physical_child_id != progress.child_id or
            any(not r.consumption_applied for r in state.combo_policy_receipts)):
        raise ResolutionError('Generated Combo policy lost its unique original capture')
    policy.__post_init__()
    state.combo_policy_receipts.append(policy)


def consume(r, progress):
    accepted = progress.combo_repeat_acceptance
    if accepted is None:
        return
    from .combo_modifiers import consume as consume_policy, receipt_at
    consume_policy(r, receipt_at(r.state, accepted.policy_receipt_id))


def validate_policy(state, registry, receipt):
    from .whole_card_physical import child_for
    from .generated_activation_receipts import validate as validate_activation
    receipt.__post_init__()
    if receipt.origin != 'generated_body' or receipt.phase != 'activation':
        raise ValueError('Generated Combo cannot borrow a paid policy window')
    child = child_for(state, receipt.physical_child_id)
    progress = child.physical
    accepted = None if progress is None else progress.combo_repeat_acceptance
    if (accepted is None or progress.activation is None or progress.activation.profile_id not in PROFILES
            or accepted.policy_receipt_id != receipt.id or
            (accepted.player_id, accepted.recipient, accepted.status == 'activated') !=
                (receipt.player_id, receipt.recipient, receipt.eligible) or
            (receipt.turn, receipt.action) != (progress.activation.turn, progress.activation.action)):
        raise ValueError('Generated Combo policies differ from their independent original acceptance')
    root = state.whole_card_replay_ledger.roots[child.root_id - 1]
    validate_activation(state, registry, progress.activation, root, child)
    if accepted.status not in ('activated', 'disabled', 'no_payload') or accepted.colossal_record_id is not None:
        raise ValueError('Generated Combo borrowed a paid entry result')
    if (accepted.status == 'activated') != bool(accepted.payloads and progress.activation.combo):
        raise ValueError('Generated Combo changed its frozen eligibility')
    if accepted.status == 'disabled' and (not accepted.payloads or progress.activation.combo):
        raise ValueError('Disabled generated Combo changed its original declarations')
    if progress.combos != (accepted.payloads if receipt.eligible else ()):
        raise ValueError('Generated Combo erased or substituted its complete accepted payloads')
    if progress.activation.profile_id in SINGLE_PROFILES:
        from .model import ComboRepeatPlan
        if receipt.modifiers or (accepted.plan is not None and accepted.plan != ComboRepeatPlan()):
            raise ValueError('Single generated Combo cannot borrow repetition policies or counts')
    if accepted.plan is not None:
        from .combo_repeats import validate_plan
        validate_plan(state, accepted.plan)
        if (not set(m.id for m in receipt.modifiers) <= set(accepted.plan.contributors) or
                accepted.plan.consumable_ids != tuple(m.id for m in receipt.modifiers if m.uses_remaining is not None)):
            raise ValueError('Generated Combo plan changed its complete accepted policy roles')
    return receipt.player_id


@dataclass(frozen=True)
class BeginGeneratedCombo(Effect):
    physical_child_id: int
    payload: ComboPayload
    repeat_index: int

    def __post_init__(self):
        _integer(self.physical_child_id, 'actual generated Combo child', 1)
        _integer(self.repeat_index, 'actual generated Combo repetition', 1)
        if type(self.payload) is not ComboPayload:
            raise ValueError('Generated Combo requires its typed accepted payload')
        self.payload.__post_init__()


def validate_record(state, registry, record, *, before_binding=False):
    from .generated_body_targets import target_for,validate_failure
    from .whole_card_physical import child_for
    from .combos import validate_payload
    from .combo_modifiers import receipt_at
    record.__post_init__()
    validate_payload(state, registry, record.payload)
    child = child_for(state, record.physical_child_id)
    progress = child.physical
    accepted = None if progress is None else progress.combo_repeat_acceptance
    if (accepted is None or accepted.status != 'activated' or record.play_id is not None
            or record.batch_id is not None
            or record.payload not in progress.combos or record.repeat_index > accepted.plan.repetitions
            or (record.source_id, record.player_id, record.card_id, record.target_id) !=
                (progress.source.entity_id, progress.player_id, progress.card_id, target_for(progress,record.payload,'combo'))
            or (record.turn, record.action) < (progress.activation.turn, progress.activation.action)
            or (record.turn, record.action) > (state.turn, state.action_number)
            or record.interrupted and state.status == 'playing'
            or not before_binding and record.id not in progress.combo_ids
            or progress.phase == 'completed' and not record.completed):
        raise ValueError('Generated Combo activation differs from its actual accepted body')
    validate_failure(progress,record.payload,'combo',record.failure)
    from .generated_retained_outcomes import validate_actual_iteration
    from .whole_card_physical import iteration_at, family_position, combo_repetitions
    validate_actual_iteration(state, progress, record.outcome_id, record.iteration)
    if before_binding:
        if record.iteration != iteration_at(progress, progress.cursor - 1):
            raise ValueError('Generated Combo changed its actual result start position')
    else:
        ordinal = progress.combo_ids.index(record.id)
        payload, repeated, iteration = family_position(progress, ordinal, progress.combos, combo_repetitions(progress))
        if (record.payload, record.repeat_index, record.iteration) != (payload, repeated, iteration):
            raise ValueError('Generated Combo changed its full ordered actual result identity')
    validate_policy(state, registry, receipt_at(state, accepted.policy_receipt_id))


def begin(r, work):
    from .generated_body_targets import target_for,failure_for
    from .whole_card_physical import (child_for, put, FinishPhysicalBody, same_progress,
        segment_at, combo_repetition_at, iteration_at)
    from .combos import FinishCombo, key
    work.__post_init__()
    progress = child_for(r.state, work.physical_child_id).physical
    proof = next((w.proof for w in r._work_queue if type(w) is FinishPhysicalBody
        and w.proof.accepted.child_id == work.physical_child_id), None)
    if (proof is None or progress is None or not same_progress(progress, proof.accepted)
            or progress.phase != 'running' or progress.cursor < 1 or progress.active_combo_id is not None
            or segment_at(progress, progress.cursor - 1) != ('combo', work.payload)
            or combo_repetition_at(progress, progress.cursor - 1) != work.repeat_index):
        raise ResolutionError('Generated Combo lost its unique original owed invocation')
    record = ComboRecord(len(r.state.combo_history) + 1, progress.source.entity_id, progress.player_id,
        progress.card_id, r.state.turn, r.state.action_number, target_for(progress,work.payload,'combo'), None,
        work.payload, batch_id=None, repeat_index=work.repeat_index, physical_child_id=progress.child_id,
        outcome_id=progress.outcome_id, iteration=iteration_at(progress, progress.cursor - 1),
        failure=failure_for(r,progress,work.payload,'combo'))
    validate_record(r.state, r.registry, record, before_binding=True)
    if any(key(old) == key(record) for old in r.state.combo_history):
        raise ResolutionError('Generated Combo invocation already exists')
    # Bind the real identity before a start listener captures any RuleContext.
    r.state.combo_history.append(record)
    progress = replace(progress, active_combo_id=record.id, combo_ids=(*progress.combo_ids, record.id))
    put(r.state, progress)
    r.emit('combo_started', source_id=record.source_id, target_id=record.target_id,
        player_id=record.player_id, combo_id=record.id, play_id=None, physical_child_id=progress.child_id)
    if record.failure is not None:
        r.emit('body_target_skipped',source_id=record.source_id,target_id=record.target_id,
            player_id=record.player_id,physical_child_id=progress.child_id,family='combo',reason=record.failure)
        return (FinishCombo(record.id),)
    return (r.call(record.payload.behavior_id, record.source_id, record.player_id, record.target_id,
        combo=record, physical=progress), FinishCombo(record.id))


def register(mechanics):
    mechanics.register(BeginGeneratedCombo, begin)


def validate_compact_plan(state, registry, progress, receipt):
    """Stored static roles only; never re-evaluate a later live source witness."""
    from .combo_matching import validate_recipient, combo_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration
    from .spell_acceptance import _live_attachments
    accepted = progress.combo_repeat_acceptance
    plan = accepted.plan
    if plan is None:
        return
    definition = validate_recipient(state, registry, accepted.recipient)
    policies = {m.id: m for m in receipt.modifiers}
    if (tuple(sorted(plan.contributors)) != plan.contributors or
            tuple(sorted(plan.consumable_ids)) != plan.consumable_ids or
            not set(policies) <= set(plan.contributors) or
            set(plan.consumable_ids) != {m.id for m in policies.values() if m.uses_remaining is not None}):
        raise ValueError('Generated Combo lost its complete canonical policy roles')
    live = _live_attachments(state)
    known = []
    for identity in plan.contributors:
        if identity in policies:
            known.append(policies[identity].spec.repetitions)
            continue
        item = live.get(identity)
        if item is None:
            continue
        family, carrier, ability = item
        if family != 'ability' or ability.kind != 'combo_repeat' or identity in plan.consumable_ids:
            raise ValueError('Generated Combo contributor borrowed another surviving global family')
        validate_source_declaration(registry, ability.combo_repeat)
        if not combo_repeat_recipient_matches(ability.combo_repeat, recipient=accepted.recipient,
                recipient_definition=definition, carrier_id=carrier):
            raise ValueError('Generated Combo contributor differs from its accepted recipient')
        known.append(ability.combo_repeat.repetitions)
    if (known and max(known) > plan.repetitions or
            len(known) == len(plan.contributors) and max(known, default=1) != plan.repetitions):
        raise ValueError('Generated Combo count differs from its stored surviving declarations')


def validate_physical_progress(state, registry, progress):
    from .combo_modifiers import receipt_at
    from .whole_card_physical import combo_start, combo_repetitions, started_combo_count, family_position, result_total
    actual = tuple(r for r in state.combo_history if r.physical_child_id == progress.child_id)
    accepted = progress.combo_repeat_acceptance
    if accepted is None:
        if actual or progress.combo_ids or progress.active_combo_id is not None:
            raise ValueError('Legacy generated body fabricated Combo execution identities')
        return
    receipt = receipt_at(state, accepted.policy_receipt_id)
    validate_policy(state, registry, receipt)
    validate_compact_plan(state, registry, progress, receipt)
    expected_count = started_combo_count(progress)
    if len(actual) != expected_count or tuple(r.id for r in actual) != progress.combo_ids:
        raise ValueError('Physical body erased, reordered or invented actual generated Combo attempts')
    for index, record in enumerate(actual):
        validate_record(state, registry, record)
        payload, repeated, iteration = family_position(progress, index, progress.combos, combo_repetitions(progress))
        if ((record.payload, record.repeat_index, record.iteration) != (payload, repeated, iteration) or
                index < len(actual) - 1 and (not record.completed or record.interrupted)):
            raise ValueError('Generated Combo changed its accepted full ordered execution')
        if progress.active_combo_id == record.id:
            if index != len(actual) - 1 or record.interrupted and state.status == 'playing':
                raise ValueError('Generated Combo active identity differs from its actual latest attempt')
        elif not record.completed:
            raise ValueError('Generated Combo abandoned its owed actual completion')
    if progress.active_combo_id is not None and (not actual or actual[-1].id != progress.active_combo_id):
        raise ValueError('Physical body borrowed an unrelated active Combo identity')
    if progress.phase == 'completed' and (expected_count != len(progress.combos) * combo_repetitions(progress) * result_total(progress)
            or any(not r.completed or r.interrupted for r in actual)):
        raise ValueError('Completed physical body abandoned an accepted Combo segment')


def validate_original_binding(state, registry, proof):
    """Bind the full old window and exact cross-origin use chain while active."""
    accepted = proof.accepted.combo_repeat_acceptance
    if accepted is None:
        return
    from .combo_modifiers import receipt_at
    from .combo_acceptance import validate_surviving_combo_sources
    original = proof.before_state
    recaptured, policy = capture(original, registry, proof.accepted.activation,
        proof.acceptance.request.physical_profile)
    if recaptured != accepted:
        raise ValueError('Generated Combo changed its complete original acceptance')
    if (policy.id != len(original.combo_policy_receipts) + 1 or
            state.combo_policy_receipts[:policy.id - 1] != original.combo_policy_receipts or
            receipt_at(state, policy.id) != replace(policy, consumption_applied=True)):
        raise ValueError('Generated Combo changed its original full policy prefix or one-time application')
    validate_surviving_combo_sources(state, original, 'activation', policy.id)
