"""Runtime bridge for one real generated carrier and cumulative result groups."""
from dataclasses import replace

from .errors import ResolutionError
from .generated_activation_receipts import RETAINED_PROFILE
from .generated_retained_acceptance import GeneratedRetainedAcceptance, RetentionHolderFact
from .model import RewindOutcomeRecord


PROFILE = RETAINED_PROFILE


def planned_record(progress):
    receipt = progress.retained_acceptance
    if (receipt is None or receipt.status != 'retained' or progress.outcome_id != receipt.before_outcome_id
            or progress.activation.profile_id != PROFILE):
        raise ValueError('Generated retained record requires its actual original accepted quota')
    return RewindOutcomeRecord(receipt.before_outcome_id, progress.source.entity_id, progress.player_id,
        progress.card_id, progress.activation.turn, progress.activation.action, progress.selection.target_id,
        receipt.on_play, tuple(h.source.entity_id for h in receipt.holders), receipt.total,
        battlecries=receipt.battlecries, combos=receipt.combos,
        battlecry_plan=receipt.battlecry_plan, combo_plan=receipt.combo_plan,
        physical_child_id=progress.child_id)


def install(r, progress):
    if progress.outcome_id is None:
        return
    record = planned_record(progress)
    if record.id != len(r.state.rewind_outcomes) + 1:
        raise ResolutionError('Generated result allocation changed before original acceptance')
    validate_record(r.state, r.registry, record, before_binding=True)
    r.state.rewind_outcomes.append(record)


def record_for(state, progress):
    from .rewind_outcomes import outcome
    if progress.outcome_id is None:
        return None
    return outcome(state, progress.outcome_id)


def validate_record(state, registry, record, *, before_binding=False):
    from .whole_card_physical import child_for, result_segment_count, segment_count
    from .generated_retained_acceptance import validate_compact
    record.__post_init__()
    child = child_for(state, record.physical_child_id)
    progress = child.physical
    if progress is None or progress.outcome_id != record.id or progress.retained_acceptance is None:
        raise ValueError('Generated retained outcome lost its actual physical-body binding')
    validate_compact(state, registry, progress.retained_acceptance)
    normalized = replace(record, completed=0, running=False, finished=False, interrupted=False)
    if normalized != planned_record(progress):
        raise ValueError('Generated retained outcome changed its complete original body or independent family plans')
    if not before_binding and (record.id > len(state.rewind_outcomes) or state.rewind_outcomes[record.id - 1] != record):
        raise ValueError('Generated retained result borrowed another actual history identity')
    base = result_segment_count(progress)
    low = record.completed * base
    high = min(segment_count(progress), low + base)
    if (record.interrupted and state.status == 'playing'
            or not low <= progress.cursor <= high
            or not(record.running or record.interrupted) and progress.cursor != low
            or record.finished and progress.cursor != segment_count(progress)
            or progress.phase == 'completed' and not record.finished):
        raise ValueError('Generated retained progress abandoned or fabricated an actual result group')


def validate_original_binding(state, registry, proof):
    from .generated_retained_acceptance import capture_from_state
    receipt = proof.accepted.retained_acceptance
    if receipt is None:
        return
    expected = capture_from_state(proof.before_state, registry, proof.accepted, proof.rules.max_resolution_steps)
    if receipt != expected:
        raise ValueError('Generated retained receipt differs from its complete original window')
    if proof.accepted.outcome_id is None:
        if receipt.status == 'retained':
            raise ValueError('Generated physical body erased its originally accepted result root')
        return
    from .whole_card_physical import child_for
    actual = record_for(state, child_for(state, proof.accepted.child_id).physical)
    original = proof.before_state.rewind_outcomes
    if (receipt.before_outcome_id != len(original) + 1 or
            state.rewind_outcomes[:len(original)] != original or
            replace(actual, completed=0, running=False, finished=False, interrupted=False) != planned_record(proof.accepted)):
        raise ValueError('Generated retained root changed its original allocation prefix or accepted body')


def start_physical(r, record):
    from .whole_card_physical import FinishPhysicalBody, AdvancePhysicalBody, child_for, result_segment_count
    from .rewind_outcomes import FinishRewindOutcome
    proof = next((w.proof for w in r._work_queue if type(w) is FinishPhysicalBody
        and w.proof.accepted.child_id == record.physical_child_id), None)
    progress = child_for(r.state, record.physical_child_id).physical
    if proof is None or progress is None or progress.cursor != record.completed * result_segment_count(progress):
        raise ResolutionError('Generated result start lost its original physical continuation')
    validate_record(r.state, r.registry, record)
    validate_original_binding(r.state, r.registry, proof)
    return (AdvancePhysicalBody(proof), FinishRewindOutcome(record.id))


def validate_progress(state, registry, progress):
    from .generated_retained_acceptance import validate_compact
    expected = progress.activation is not None and progress.activation.profile_id == PROFILE
    if expected != (progress.retained_acceptance is not None):
        raise ValueError('Physical body lost or fabricated its declared retained-family acceptance')
    if not expected:
        if progress.outcome_id is not None:
            raise ValueError('Legacy physical body fabricated an intrinsic retained root')
        return
    validate_compact(state, registry, progress.retained_acceptance)
    if (progress.retained_acceptance.status == 'retained') != (progress.outcome_id is not None):
        raise ValueError('Generated result identity differs from the original retained quota')
    if progress.outcome_id is not None:
        validate_record(state, registry, record_for(state, progress))


def validate_actual_iteration(state, progress, outcome_id, iteration):
    if outcome_id != progress.outcome_id:
        raise ValueError('Generated family invocation borrowed another retained result')
    if outcome_id is None:
        if iteration != 1:
            raise ValueError('Extra generated family result requires an actual retained root')
        return
    record = record_for(state, progress)
    if (not 1 <= iteration <= record.total or
            iteration > record.completed + int(record.running or record.interrupted)):
        raise ValueError('Generated family invocation fabricated an unstarted retained result')


def register(mechanics):
    for kind in (GeneratedRetainedAcceptance, RetentionHolderFact):
        mechanics.register_payload_type(kind)
