"""Independent two-window proofs for every paid physical Combo root.

The proof markers are interpreter control.  They preserve the original full
window until the enclosing play ends, including empty and canceled acceptances,
and add neither a game event nor a gameplay/death checkpoint.
"""
from copy import deepcopy
from dataclasses import dataclass, replace

from .effects import Effect, _integer
from .errors import ResolutionError
from .model import CardType, ComboPolicyReceipt, ComboRecipient, GameState, PlayRecord, Zone
from .registry import RuleContext


PHYSICAL_KINDS = (CardType.MINION, CardType.WEAPON, CardType.HERO)
ENTRY_FAILURES = ('countered', 'board_full', 'magnetized')


@dataclass(frozen=True)
class FinishComboAcceptance(Effect):
    context: RuleContext
    phase: str
    receipt_id: int

    def __post_init__(self):
        if (type(self.context) is not RuleContext or type(self.context.state) is not GameState or
                type(self.context.play) is not PlayRecord or
                self.context.play.kind not in PHYSICAL_KINDS):
            raise ValueError('Combo acceptance requires its original physical paid play context')
        if type(self.phase) is not str or self.phase not in ('play', 'activation'):
            raise ValueError('Unknown Combo acceptance proof phase')
        _integer(self.receipt_id, 'Combo acceptance receipt', 1)


def make_proof(r, play, phase, receipt):
    from .play_history import play_record
    from .combo_modifiers import receipt_at
    current = play_record(r.state, play.id)
    if (current != play or type(receipt) is not ComboPolicyReceipt or
            receipt_at(r.state, receipt.id) != receipt or receipt.consumption_applied or
            (receipt.play_id, receipt.phase) != (play.id, phase)):
        raise ValueError('Combo proof must capture its installed original staged receipt')
    work = FinishComboAcceptance(RuleContext(deepcopy(r.state), play.source_id,
        play.player_id, play.target_id, play=play), phase, receipt.id)
    validate_acceptance(work, r.registry)
    return work


def _original_receipt(work):
    from .combo_modifiers import receipt_at
    state = work.context.state
    receipt = receipt_at(state, work.receipt_id)
    if (receipt.id != len(state.combo_policy_receipts) or receipt.consumption_applied or
            (receipt.play_id, receipt.phase) != (work.context.play.id, work.phase) or
            any(not value.consumption_applied for value in state.combo_policy_receipts[:-1])):
        raise ValueError('Combo original proof lost its unique final staged capture')
    return receipt


def _validate_colossal_link(state, play, accepted, *, original=False):
    from .colossal import record_at, live_body
    entries = [value for value in state.colossal_history if value.play_id == play.id]
    if accepted.colossal_record_id is None:
        if entries:
            raise ValueError('Delayed Combo acceptance lost its paid Colossal entry')
        return
    record = record_at(state, accepted.colossal_record_id)
    if (len(entries) != 1 or entries[0] != record or record.reason != 'play' or
            (record.play_id, record.entity_id, record.player_id, record.card_id, record.turn) !=
            (play.id, play.source_id, play.player_id, play.card_id, play.turn) or
            not play.action <= record.action <= state.action_number or not record.completed):
        raise ValueError('Combo acceptance differs from its exact paid Colossal entry')
    if original:
        if (live_body(state, record) is None) != (accepted.status == 'colossal_canceled'):
            raise ValueError('Combo acceptance changed its original Colossal cancellation guard')


def _validate_status(state, registry, play, accepted, *, original=False):
    from .combo_matching import validate_recipient, capture_recipient
    from .combos import capture, validate_payload
    accepted.__post_init__()
    validate_recipient(state, registry, accepted.recipient, play)
    if accepted.player_id != play.player_id:
        raise ValueError('Combo acceptance changed its paid root player')
    for payload in accepted.payloads:
        validate_payload(state, registry, payload)
    if accepted.status in ENTRY_FAILURES:
        if (play.kind != CardType.MINION or play.minion_result != accepted.status or
                play.countered != (accepted.status == 'countered')):
            raise ValueError('Canceled Combo acceptance differs from its minion entry result')
    else:
        if (play.countered or play.kind == CardType.MINION and play.minion_result != 'summoned' or
                accepted.status == 'activated' and not play.combo or
                accepted.status == 'disabled' and play.combo):
            raise ValueError('Combo acceptance differs from its paid eligibility or entry')
    _validate_colossal_link(state, play, accepted, original=original)
    if not original:
        return
    if accepted.recipient != capture_recipient(state, registry, play.source_id):
        raise ValueError('Combo original acceptance changed its physical window face')
    if accepted.status in ENTRY_FAILURES:
        source = state.entities[play.source_id]
        if source.zone != Zone.GRAVEYARD or source.controller != play.player_id:
            raise ValueError('Canceled Combo original window lost its consumed physical hand carrier')
        return
    if accepted.status == 'colossal_canceled':
        return
    source = state.entities[play.source_id]
    expected_zone = {CardType.MINION: Zone.BOARD, CardType.WEAPON: Zone.WEAPON,
                     CardType.HERO: Zone.HERO}[play.kind]
    from .disguised import play_destination
    expected_controller = play_destination(registry, play) if play.kind == CardType.MINION else play.player_id
    if source.zone != expected_zone or source.controller != expected_controller:
        raise ValueError('Combo original acceptance lost its entered physical carrier')
    payloads = capture(source)
    status = 'activated' if payloads and play.combo else 'disabled' if payloads else 'no_payload'
    if (accepted.status, accepted.payloads) != (status, payloads):
        raise ValueError('Combo acceptance differs from its complete actual declaration set')


def validate_acceptance(work, registry):
    """Replay only the original window; never rejudge a later live recipient."""
    work.__post_init__()
    from .play_history import play_record
    from .combo_modifiers import capture_from_state, validate_receipts
    from .combo_matching import validate_recipient
    context = work.context; state = context.state; play = context.play
    if (play_record(state, play.id) != play or play.completed or play.interrupted or
            state.status != 'playing' or context.source_id != play.source_id or
            context.player_id != play.player_id or context.target_id != play.target_id or
            context.source_id not in state.entities or context.source.kind != play.kind or
            any(getattr(context, name) is not None for name in (
                'event', 'death', 'choice', 'player_effect', 'window', 'trigger', 'cast',
                'draw', 'power', 'battlecry', 'combo', 'deathrattle', 'power_payload', 'end_turn')) or
            context.rewind_attempt != 0):
        raise ValueError('Combo acceptance differs from its original bare paid play context')
    validate_receipts(state, registry)
    receipt = _original_receipt(work)
    validate_recipient(state, registry, receipt.recipient, play)
    if (receipt.turn, receipt.action) != (state.turn, state.action_number):
        raise ValueError('Combo proof changed its original capture clock')
    if work.phase == 'play':
        from .combos import capture
        if (play.combo_submission_receipt_id != receipt.id or play.combo_acceptance is not None or
                play.battlecry_acceptance is not None or play.minion_result is not None or play.countered or
                receipt.action != play.action or receipt.recipient !=
                ComboRecipient(play.source_id, play.card_id, play.kind) or
                context.source.zone != Zone.HAND or context.source.controller != play.player_id or
                context.source.card_id != play.card_id or capture(context.source) != play.combos or
                receipt.eligible != bool(play.combos)):
            raise ValueError('Combo submission proof differs from its complete committed declaration')
    else:
        accepted = play.combo_acceptance
        if (accepted is None or accepted.policy_receipt_id != receipt.id or
                accepted.recipient != receipt.recipient or receipt.eligible != (accepted.status == 'activated')):
            raise ValueError('Combo activation proof differs from its independent durable acceptance')
        _validate_status(state, registry, play, accepted, original=True)
        if accepted.status == 'activated':
            from .combo_repeats import capture_plan_from_state
            if accepted.plan != capture_plan_from_state(state, registry, play,
                    receipt.recipient, receipt.modifiers):
                raise ValueError('Combo plan differs from its complete original activation window')
    if receipt.modifiers != capture_from_state(state, registry, play, work.phase,
            receipt.recipient, receipt.eligible):
        raise ValueError('Combo phase policies differ from their complete original window')


# The frame codec uses the family-qualified spelling; the public engine hook
# uses the shorter module-local spelling. Both replay the same original proof.
validate_combo_acceptance = validate_acceptance


def _bind_prefix(state, work):
    original = work.context.state
    receipt = _original_receipt(work)
    current = state.combo_policy_receipts
    if (len(current) < receipt.id or
            current[:receipt.id-1] != original.combo_policy_receipts[:receipt.id-1] or
            current[receipt.id-1] != replace(receipt, consumption_applied=True)):
        raise ValueError('Combo acceptance changed its original immutable receipt prefix')


def validate_surviving_sources(state, work):
    """Bind every original policy, including false ones, and exact later uses."""
    _bind_prefix(state, work)
    validate_surviving_combo_sources(state, work.context.state, work.phase, work.receipt_id)


def validate_surviving_combo_sources(state, original, phase, receipt_id):
    from .spell_acceptance import _live_attachments
    before, live = _live_attachments(original), _live_attachments(state)
    def is_source(item):
        family, _, value = item
        return (family == 'combo_modifiers' or phase == 'activation' and
                family == 'ability' and value.kind == 'combo_repeat')
    identities = {identity for identity, item in before.items() if is_source(item)}
    identities.update(identity for identity, item in live.items()
        if identity < original.next_attachment_id and is_source(item))
    # A later receipt survives even when its last finite use removed the live
    # policy. It must still identify the original full declaration and owner.
    later = state.combo_policy_receipts[receipt_id-1:]
    for receipt in later:
        for modifier in receipt.modifiers:
            if modifier.id < original.next_attachment_id:
                accepted = before.get(modifier.id)
                if accepted is None or accepted[0] != 'combo_modifiers':
                    raise ValueError('Later Combo capture reused an absent or other-family original ID')
                identities.add(modifier.id)
    for identity in identities:
        current = live.get(identity)
        accepted = before.get(identity)
        if accepted is None or not is_source(accepted):
            raise ValueError('Combo original window lost a surviving repeat source')
        family, carrier, old = accepted
        remaining = None
        if family == 'combo_modifiers':
            from .combo_modifiers import receipt_player_id
            remaining = old.uses_remaining
            for receipt in later:
                captured = next((value for value in receipt.modifiers if value.id == identity), None)
                if captured is None:
                    continue
                if (receipt_player_id(state, receipt) != carrier or
                        remaining is not None and remaining < 1 or
                        captured != replace(old, uses_remaining=remaining)):
                    raise ValueError('Later Combo receipt changed its original full policy or pre-use value')
                if remaining is not None and receipt.consumption_applied:
                    remaining -= 1
        if current is None:
            continue
        new_family, new_carrier, new = current
        if (family, carrier) != (new_family, new_carrier):
            raise ValueError('Combo source changed its surviving family or physical carrier')
        if family == 'ability':
            if (replace(new, consumed=old.consumed) != old or old.consumed and not new.consumed):
                raise ValueError('Combo source changed its surviving full ability declaration')
        else:
            if (remaining is not None and remaining < 1 or
                    new != replace(old, uses_remaining=remaining)):
                raise ValueError('Combo policy changed its static identity or exact accepted use chain')


def _bind_play(state, work):
    from .play_history import play_record
    old = work.context.play; current = play_record(state, old.id)
    if work.phase == 'play':
        # Only the enclosing play's later outcomes/one-time acceptances may be
        # added. The paid identity, target and submission reference stay exact.
        comparable = replace(current, countered=old.countered, completed=old.completed,
            interrupted=old.interrupted, minion_result=old.minion_result,
            battlecry_acceptance=old.battlecry_acceptance, combo_acceptance=old.combo_acceptance)
    else:
        comparable = replace(current, completed=old.completed, interrupted=old.interrupted)
    if comparable != old:
        raise ValueError('Combo proof changed its immutable enclosing paid play')
    return current


def _root_batches(state, play, *, complete=False):
    accepted = play.combo_acceptance
    batches = [value for value in state.combo_batches if value.play_id == play.id]
    retained = [value for value in state.rewind_outcomes if value.play_id == play.id]
    if len(retained) > 1:
        raise ValueError('Combo root has duplicate retained outcome identities')
    if accepted is None:
        if batches or any(value.combos or value.combo_plan is not None for value in retained):
            raise ValueError('Unaccepted Combo root already contains execution results')
        return
    if any((value.player_id, value.payloads, value.plan) !=
            (accepted.player_id, accepted.payloads, accepted.plan) for value in batches):
        raise ValueError('Combo batch differs from its complete durable acceptance')
    if any((value.player_id, value.combos, value.combo_plan) !=
            (accepted.player_id, accepted.payloads, accepted.plan) for value in retained):
        raise ValueError('Retained Combo results differ from their original durable acceptance')
    if complete and retained and not retained[0].finished:
        raise ValueError('Combo acceptance closed before its complete retained results')
    if accepted.status != 'activated':
        if batches:
            raise ValueError('Inactive Combo acceptance cannot own an execution batch')
        return
    if retained:
        outcome = retained[0]
        if any(value.outcome_id != outcome.id or not 1 <= value.iteration <= outcome.total for value in batches):
            raise ValueError('Combo batch changed its retained result identity')
        expected = outcome.total
    else:
        if any(value.outcome_id is not None or value.iteration != 1 for value in batches):
            raise ValueError('Ordinary Combo root changed its execution iteration identity')
        expected = 1
    if complete and (len(batches) != expected or any(not value.finished for value in batches) or
            retained and not retained[0].finished or
            {value.iteration for value in batches} != set(range(1, expected+1))):
        raise ValueError('Combo acceptance closed before all its complete result batches')


def validate_history(state, registry):
    """Compact completed facts use stored faces and static declarations only."""
    from .combo_modifiers import receipt_at, validate_receipts
    from .combo_matching import validate_recipient
    from .combo_repeats import validate_compact_plan
    validate_receipts(state, registry)
    for play in state.play_history:
        receipts = [value for value in state.combo_policy_receipts if value.play_id == play.id]
        if play.kind not in PHYSICAL_KINDS:
            if play.combo_submission_receipt_id is not None or play.combo_acceptance is not None or receipts:
                raise ValueError('Nonphysical play cannot carry paid Combo phase receipts')
            continue
        if play.combo_submission_receipt_id is None:
            raise ValueError('Physical paid play lost its independent Combo submission receipt')
        submission = receipt_at(state, play.combo_submission_receipt_id)
        if ((submission.play_id, submission.phase, submission.action) != (play.id, 'play', play.action) or
                submission.recipient != ComboRecipient(play.source_id, play.card_id, play.kind) or
                submission.eligible != bool(play.combos)):
            raise ValueError('Physical paid play changed its mandatory submission facts')
        activation = [value for value in receipts if value.phase == 'activation']
        accepted = play.combo_acceptance
        if accepted is None:
            if activation or play.completed:
                raise ValueError('Physical play lost its independent late Combo acceptance')
        else:
            _validate_status(state, registry, play, accepted)
            if (len(activation) != 1 or activation[0].id != accepted.policy_receipt_id or
                    activation[0].recipient != accepted.recipient or
                    activation[0].eligible != (accepted.status == 'activated') or
                    activation[0].id <= submission.id):
                raise ValueError('Combo root changed its unique chronological activation receipt')
            validate_recipient(state, registry, accepted.recipient, play)
            if accepted.plan is not None:
                validate_compact_plan(state, registry, play, accepted.plan, accepted.recipient)
        _root_batches(state, play, complete=play.completed)


def _validate_queue(state, registry, queue, limit):
    from .play_history import play_record
    from .resolver import FinishPlay
    from .colossal import ColossalBattlecry, record_at
    from .minion_plays import MinionCounterPhase, ResolveMinionPlay
    from .combo_repeats import BeginComboBatch, FinishComboBatch
    from .rewind_outcomes import FinishRewindOutcomes
    from .battlecry_repeats import FinishBattlecryAcceptance
    validate_history(state, registry)
    if any(not value.consumption_applied for value in state.combo_policy_receipts):
        raise ValueError('Live Combo boundary contains an unapplied staged receipt')
    active = {play.id: play for play in state.play_history if play.kind in PHYSICAL_KINDS and
              not play.completed and not play.interrupted}
    proofs = {}; positions = {}; ends = {}
    for index, work in enumerate(queue):
        if type(work) is FinishPlay:
            play = play_record(state, work.play_id)
            if play.kind not in PHYSICAL_KINDS:
                continue
            if (play.id not in active or play.id in ends or
                    (work.source_id, work.player_id, work.target_id) !=
                    (play.source_id, play.player_id, play.target_id)):
                raise ValueError('Physical paid root changed its unique completion marker')
            ends[play.id] = index
        if type(work) is not FinishComboAcceptance:
            continue
        validate_acceptance(work, registry)
        validate_surviving_sources(state, work)
        current = _bind_play(state, work)
        key = current.id, work.phase
        if (current.id not in active or key in proofs or
                work.context.state.turn > state.turn or work.context.state.action_number > state.action_number):
            raise ValueError('Combo proof lost its unique active paid root or capture clock')
        accepted = current.combo_acceptance
        if accepted is not None and accepted.plan is not None and len(accepted.payloads)*accepted.plan.repetitions > limit:
            raise ValueError('Complete Combo acceptance exceeds resolution budget')
        proofs[key] = work; positions[key] = index
    # Coexisting roots retain full snapshots. A later original window is also
    # a surviving-source witness for every earlier active proof; checking only
    # the final live state would miss an old ID rewritten and then removed.
    chronological = sorted(proofs.values(), key=lambda value: value.receipt_id)
    for offset, earlier in enumerate(chronological):
        for later in chronological[offset+1:]:
            if earlier.receipt_id < later.receipt_id:
                validate_surviving_sources(later.context.state, earlier)
    for play_id, play in active.items():
        submission_key = play_id, 'play'; activation_key = play_id, 'activation'
        if (submission_key not in proofs or play_id not in ends or
                positions[submission_key] >= ends[play_id]):
            raise ValueError('Physical paid root lost its independent submission proof or completion')
        accepted = play.combo_acceptance
        if accepted is None:
            if activation_key in proofs:
                raise ValueError('Unaccepted physical root has an unexpected activation proof')
            windows = [value for value in state.action_windows if value.kind == 'minion' and value.play_id == play_id]
            delayed = [(index, value) for index, value in enumerate(queue)
                       if type(value) is ColossalBattlecry and value.play_id == play_id]
            if windows:
                if len(windows) != 1 or delayed or play.minion_result is not None:
                    raise ValueError('Combo root changed its unique pending minion acceptance window')
                window = windows[0]
                marker = (ResolveMinionPlay if window.counter_phase else MinionCounterPhase)(window.id)
                if queue.count(marker) != 1 or queue.index(marker) >= positions[submission_key]:
                    raise ValueError('Combo submission proof outlives no pending entry resolution')
            elif delayed:
                if len(delayed) != 1 or play.minion_result != 'summoned':
                    raise ValueError('Combo root changed its delayed Colossal activation window')
                index, marker = delayed[0]; record = record_at(state, marker.record_id)
                if (record.play_id, record.entity_id, record.player_id, record.reason) != (
                        play_id, play.source_id, play.player_id, 'play') or index >= positions[submission_key]:
                    raise ValueError('Delayed Combo root changed its exact pending Colossal origin')
            else:
                raise ValueError('Physical paid root lost its pending late Combo acceptance window')
            continue
        if (activation_key not in proofs or
                not positions[activation_key] < positions[submission_key] < ends[play_id]):
            raise ValueError('Physical paid root lost its independent ordered activation proof')
        activation_position = positions[activation_key]
        sibling = [(index, value) for index, value in enumerate(queue) if type(value) is FinishBattlecryAcceptance
                   and value.context.play.id == play_id]
        if any(not activation_position < index < positions[submission_key] for index, _ in sibling):
            raise ValueError('Combo activation and sibling Battlecry proofs changed close order')
        for batch in state.combo_batches:
            if batch.play_id != play_id or batch.finished or batch.interrupted:
                continue
            marker = FinishComboBatch(batch.id)
            if queue.count(marker) != 1 or queue.index(marker) >= activation_position:
                raise ValueError('Combo execution batch outlives its original activation proof')
        starts = [value for value in queue if type(value) is BeginComboBatch and value.play_id == play_id]
        for index, value in enumerate(queue):
            if type(value) is not BeginComboBatch or value.play_id != play_id:
                continue
            if (index >= activation_position or
                    (value.player_id, value.payloads, value.plan) !=
                    (accepted.player_id, accepted.payloads, accepted.plan)):
                raise ValueError('Queued Combo batch differs from its complete original root')
        retained = [value for value in state.rewind_outcomes if value.play_id == play_id]
        for outcome in retained:
            marker = FinishRewindOutcomes(outcome.id)
            if not outcome.finished and (queue.count(marker) != 1 or queue.index(marker) >= activation_position):
                raise ValueError('Retained Combo results outlive their original activation proof')
        if (accepted.status == 'activated' and not starts and
                not any(value.play_id == play_id for value in state.combo_batches) and not retained):
            raise ValueError('Activated Combo root lost its whole scheduled execution')
    if set(ends) != set(active):
        raise ValueError('Physical paid roots and completion inventory differ')


def validate_boundary(game):
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    _validate_queue(game._state, game.registry, queue, game.ruleset.max_resolution_steps)


def validate_terminal_queue(r, queue):
    """Run before terminal cleanup, without demanding unfinished completion."""
    _validate_queue(r.state, r.registry, tuple(queue), r.rules.max_resolution_steps)


def finish(r, work):
    validate_acceptance(work, r.registry)
    validate_history(r.state, r.registry)
    validate_surviving_sources(r.state, work)
    play = _bind_play(r.state, work)
    if play.completed or play.interrupted:
        raise ResolutionError('Combo acceptance requires its active enclosing paid play')
    if play.combo_acceptance is None:
        raise ResolutionError('Combo submission cannot close before its independent actual window')
    _root_batches(r.state, play, complete=True)
    if any(value.play_id == play.id and not value.finished for value in r.state.battlecry_batches):
        raise ResolutionError('Combo acceptance closed before its sibling Battlecry batches')
    from .battlecry_repeats import FinishBattlecryAcceptance
    from .resolver import FinishPlay
    remaining = tuple(r._work_queue)
    ends = [value for value in remaining if type(value) is FinishPlay and value.play_id == play.id]
    if (len(ends) != 1 or (ends[0].source_id, ends[0].player_id, ends[0].target_id) !=
            (play.source_id, play.player_id, play.target_id)):
        raise ResolutionError('Combo proof lost its exact enclosing paid completion')
    from .costs import defer_paid_minion_root
    if defer_paid_minion_root(r,work,play.id):return
    if work.phase == 'play' and any(
            type(value) is FinishComboAcceptance and value.context.play.id == play.id or
            type(value) is FinishBattlecryAcceptance and value.context.play.id == play.id
            for value in remaining):
        raise ResolutionError('Combo submission closed before its sibling actual-window proofs')


def register(mechanics):
    mechanics.register(FinishComboAcceptance, finish)
