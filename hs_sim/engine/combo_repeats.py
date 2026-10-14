"""Captured Combo repetition batches, independent of Rewind outcomes (R-128).

The current hand-play policy retains the original target, repeats each captured
ability in attachment order, and uses ordinary death/choice checkpoints. It adds
neither another paid play nor the spell-repeat death deferral/choice cache.
"""
from dataclasses import dataclass, replace
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, ComboPayload, ComboRepeatSpec,
                    ComboRepeatPlan, ComboBatchRecord, CardType, Zone)


def capture_plan_from_state(state, registry, play, recipient, activation_modifiers):
    """Paid caller keeps its earlier play policies; shared pure max has no fake play."""
    from .combo_modifiers import captured_modifiers
    from .combo_matching import validate_recipient
    from .combo_acceptance_matching import capture_repeat_plan
    validate_recipient(state, registry, recipient, play)
    return capture_repeat_plan(state, registry, play.player_id, recipient,
        (*captured_modifiers(state, play.id, 'play'), *activation_modifiers))


def capture_plan(r, play, recipient, activation_modifiers):
    plan=capture_plan_from_state(r.state,r.registry,play,recipient,activation_modifiers)
    repetitions=plan.repetitions
    if repetitions>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Combo repetition exceeds resolution budget')
    return plan


def validate_plan(state, plan):
    if type(plan) is not ComboRepeatPlan: raise ValueError('Invalid Combo repeat plan')
    plan.__post_init__()
    if any(i >= state.next_attachment_id for i in plan.contributors):
        raise ValueError('Invalid captured Combo repeat contributor')


def validate_compact_plan(state, registry, play, plan, recipient):
    """Stored face/static scope only; never re-evaluate later witnesses or presence."""
    from .combo_matching import validate_recipient, combo_repeat_recipient_matches
    from .combo_modifiers import captured_modifiers
    from .repeat_source_conditions import validate_source_declaration
    from .spell_acceptance import _live_attachments
    validate_plan(state,plan)
    if tuple(sorted(plan.contributors))!=plan.contributors:
        raise ValueError('Combo contributors require canonical global identity order')
    definition=validate_recipient(state,registry,recipient,play)
    policies={m.id:m for m in captured_modifiers(state,play.id)}
    if (not set(policies)<=set(plan.contributors) or
            set(plan.consumable_ids)!={m.id for m in policies.values() if m.uses_remaining is not None}):
        raise ValueError('Combo plan and complete accepted policies disagree')
    live=_live_attachments(state);known=[]
    for identity in plan.contributors:
        if identity in policies:
            # Its phase's original recipient was checked by the receipt ledger.
            known.append(policies[identity].spec.repetitions)
            continue
        item=live.get(identity)
        if item is None:continue
        family,carrier,ability=item
        if family!='ability' or ability.kind!='combo_repeat' or identity in plan.consumable_ids:
            raise ValueError('Combo contributor belongs to another surviving attachment family')
        validate_source_declaration(registry,ability.combo_repeat)
        if not combo_repeat_recipient_matches(ability.combo_repeat,recipient=recipient,
                recipient_definition=definition,carrier_id=carrier):
            raise ValueError('Combo contributor differs from its accepted physical recipient')
        known.append(ability.combo_repeat.repetitions)
    if (known and max(known)>plan.repetitions or
            len(known)==len(plan.contributors) and max(known,default=1)!=plan.repetitions):
        raise ValueError('Combo count differs from its stored surviving declarations')


@dataclass(frozen=True)
class GrantComboRepeatAura(Effect):
    target_id: int
    spec: ComboRepeatSpec = ComboRepeatSpec()
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'Combo repeat carrier', 1); _source(self.source_id)
        if type(self.spec) is not ComboRepeatSpec: raise ValueError('Combo repeat requires a specification')
        self.spec.__post_init__()
        if self.expires_turn is not None: _integer(self.expires_turn, 'Combo repeat expiry', 1)


@dataclass(frozen=True)
class BeginComboBatch(Effect):
    play_id: int
    player_id: int
    payloads: tuple[ComboPayload, ...]
    plan: ComboRepeatPlan
    outcome_id: int | None = None
    iteration: int = 1

    def __post_init__(self):
        # Same validation as a fresh persisted batch, without allocating identity.
        ComboBatchRecord(1, self.play_id, self.player_id, self.payloads, self.plan,
                             self.outcome_id, self.iteration)


@dataclass(frozen=True)
class StartComboIteration(Effect):
    batch_id: int

    def __post_init__(self):
        _integer(self.batch_id, 'Combo batch', 1)


@dataclass(frozen=True)
class FinishComboIteration(StartComboIteration):
    pass


@dataclass(frozen=True)
class FinishComboBatch(StartComboIteration):
    pass


def batch_record(state, batch_id):
    _integer(batch_id, 'Combo batch', 1)
    if batch_id > len(state.combo_batches): raise ValueError('Unknown Combo batch')
    return state.combo_batches[batch_id-1]


def update(state, record, **changes):
    value = replace(record, **changes)
    state.combo_batches[record.id-1] = value
    return value


def validate_provenance(state, registry, record):
    from .play_history import play_record
    play = play_record(state, record.play_id)
    accepted=play.combo_acceptance
    if accepted is None or accepted.status!='activated' or (
            accepted.player_id,accepted.payloads,accepted.plan)!=(record.player_id,record.payloads,record.plan):
        raise ValueError('Combo batch differs from its complete accepted physical root')
    validate_compact_plan(state,registry,play,record.plan,accepted.recipient)
    from .combo_modifiers import captured_modifiers
    modifiers=captured_modifiers(state,play.id)
    if (not {m.id for m in modifiers} <= set(record.plan.contributors) or
            set(record.plan.consumable_ids)!={m.id for m in modifiers if m.uses_remaining is not None} or
            any(m.spec.repetitions>record.plan.repetitions for m in modifiers)):
        raise ValueError('Combo plan and captured policy receipts disagree')
    if (play.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO) or not play.combo or play.countered or
            play.minion_result in ('countered','board_full','magnetized') or record.player_id != play.player_id or
            play.completed and not record.finished or
            record.interrupted and state.status == 'playing' or
            play.interrupted and not (record.finished or record.interrupted)):
        raise ValueError('Invalid Combo batch play provenance')
    for payload in record.payloads:
        registry.behavior(payload.behavior_id)
        if payload.ability_id >= state.next_attachment_id or registry.card(payload.card_id).combo != payload.behavior_id:
            raise ValueError('Invalid Combo batch payload')
    if record.outcome_id is not None:
        from .rewind_outcomes import outcome
        retained = outcome(state, record.outcome_id)
        if (retained.play_id != record.play_id or retained.cast_id is not None or retained.power_id is not None or
                retained.player_id != record.player_id or retained.combos != record.payloads or
                retained.combo_plan != record.plan or record.iteration > retained.total or
                record.iteration > retained.completed + int(retained.running or retained.interrupted) or
                not (record.finished or record.interrupted) and not retained.running):
            raise ValueError('Combo batch and retained outcome disagree')
    elif any(x.play_id == record.play_id and x.combos for x in state.rewind_outcomes):
        raise ValueError('Retained Combo batch lost its outcome')


def key(record):
    return record.play_id, record.outcome_id, record.iteration


def begin(r, effect):
    from .play_history import play_record
    effect.__post_init__()
    play = play_record(r.state, effect.play_id)
    if play.completed or play.interrupted: raise ResolutionError('Combo batch requires an active play')
    record = ComboBatchRecord(len(r.state.combo_batches)+1, effect.play_id, effect.player_id,
        effect.payloads, effect.plan, effect.outcome_id, effect.iteration)
    validate_provenance(r.state, r.registry, record)
    if record.total > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Combo batch exceeds resolution budget')
    if any(key(b) == key(record) for b in r.state.combo_batches):
        raise ResolutionError('Combo batch already started')
    r.state.combo_batches.append(record)
    return [StartComboIteration(record.id), FinishComboBatch(record.id)]


def expected_activation(record, index):
    # Each ability is exhausted before the next inherited ability begins.
    return record.payloads[index // record.plan.repetitions], index % record.plan.repetitions + 1


def start(r, effect):
    from .combos import BeginCombo
    record = batch_record(r.state, effect.batch_id)
    if record.running or record.finished or record.interrupted or record.completed >= record.total:
        raise ResolutionError('Invalid Combo iteration start')
    update(r.state, record, running=True)
    payload, repeat_index = expected_activation(record, record.completed)
    return [BeginCombo(record.play_id, record.player_id, payload, record.id, repeat_index,
                          record.outcome_id, record.iteration), FinishComboIteration(record.id)]


def finish_one(r, effect):
    record = batch_record(r.state, effect.batch_id)
    if not record.running or record.finished or record.interrupted:
        raise ResolutionError('Invalid Combo iteration completion')
    payload, repeat_index = expected_activation(record, record.completed)
    activation = next((b for b in reversed(r.state.combo_history) if b.batch_id == record.id), None)
    if activation is None or (activation.payload,activation.repeat_index) != (payload,repeat_index) or not activation.completed:
        raise ResolutionError('Combo iteration did not finish its activation')
    record = update(r.state, record, running=False, completed=record.completed+1)
    return [StartComboIteration(record.id)] if record.completed < record.total else []


def finish(r, effect):
    record = batch_record(r.state, effect.batch_id)
    if record.running or record.finished or record.interrupted or record.completed != record.total:
        raise ResolutionError('Invalid Combo batch completion')
    update(r.state, record, finished=True)


def grant(r, effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    from .repeat_source_conditions import validate_source_declaration
    validate_source_declaration(r.registry,effect.spec)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id); return
    ability = AbilityInstance(attachment_id(r.state), 'combo_repeat', source_id=effect.source_id,
        combo_repeat=effect.spec, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def validate_history(state, registry):
    if type(state.combo_batches) is not list: raise ValueError('Combo batches require a list')
    keys = set()
    for index, record in enumerate(state.combo_batches, 1):
        if type(record) is not ComboBatchRecord: raise ValueError('Invalid Combo batch')
        record.__post_init__(); validate_provenance(state, registry, record)
        if record.id != index or key(record) in keys: raise ValueError('Invalid Combo batch identity')
        keys.add(key(record))
        children = [b for b in state.combo_history if b.batch_id == record.id]
        if not record.completed <= len(children) <= record.completed + int(record.running or record.interrupted):
            raise ValueError('Combo batch progress and activations disagree')
        for offset, activation in enumerate(children):
            if offset >= record.total or (activation.payload,activation.repeat_index) != expected_activation(record,offset):
                raise ValueError('Combo batch activation order differs')
            if offset < record.completed and not activation.completed:
                raise ValueError('Incomplete activation in completed Combo iteration')


def validate_boundary(game):
    from .combos import BeginCombo, FinishCombo
    from .resolver import FinishPlay
    from .rewind_outcomes import FinishRewindOutcome
    state = game._state
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    pending = [b for b in state.combo_batches if not b.finished and not b.interrupted]
    expected = []
    for record in reversed(pending):
        if record.total > game.ruleset.max_resolution_steps: raise ValueError('Combo batch exceeds resolution budget')
        if record.running: expected.append(FinishComboIteration(record.id))
        elif record.completed < record.total: expected.append(StartComboIteration(record.id))
        expected.append(FinishComboBatch(record.id))
        end = queue.index(FinishComboBatch(record.id)) if FinishComboBatch(record.id) in queue else None
        play_end = next((i for i,w in enumerate(queue) if type(w) is FinishPlay and w.play_id == record.play_id), None)
        if end is None or play_end is None or end >= play_end: raise ValueError('Combo batch must finish before its play')
        if record.outcome_id is not None:
            marker = FinishRewindOutcome(record.outcome_id)
            if marker not in queue or end >= queue.index(marker): raise ValueError('Combo batch must finish before its outcome')
        if record.running:
            closer = FinishComboIteration(record.id)
            if closer not in queue or queue.index(closer) >= end: raise ValueError('Combo iteration must finish before its batch')
            children = [b for b in state.combo_history if b.batch_id == record.id]
            if len(children) == record.completed:
                payload, repeat_index = expected_activation(record,record.completed)
                start = BeginCombo(record.play_id,record.player_id,payload,record.id,repeat_index,record.outcome_id,record.iteration)
                if start not in queue or queue.index(start) >= queue.index(closer): raise ValueError('Missing Combo activation start')
            else:
                activation = children[-1]
                marker = FinishCombo(activation.id)
                if not activation.completed and (marker not in queue or queue.index(marker) >= queue.index(closer)):
                    raise ValueError('Combo activation must finish before its iteration')
    if [w for w in queue if isinstance(w,StartComboIteration)] != expected:
        raise ValueError('Combo batch progress and continuation markers differ')
    starts=set()
    for index, work in enumerate(queue):
        if type(work) is BeginCombo:
            record=batch_record(state,work.batch_id)
            if (not record.running or record.finished or record.interrupted or
                    (work.payload,work.repeat_index) != expected_activation(record,record.completed)):
                raise ValueError('Unexpected queued Combo activation')
        if type(work) is not BeginComboBatch: continue
        work.__post_init__()
        record=ComboBatchRecord(1,work.play_id,work.player_id,work.payloads,work.plan,work.outcome_id,work.iteration)
        validate_provenance(state,game.registry,record)
        if key(record) in starts or any(key(b)==key(record) for b in state.combo_batches):
            raise ValueError('Duplicate queued Combo batch')
        if record.total > game.ruleset.max_resolution_steps: raise ValueError('Queued Combo batch exceeds resolution budget')
        starts.add(key(record))
        if not any(type(w) is FinishPlay and w.play_id==work.play_id for w in queue[index+1:]):
            raise ValueError('Queued Combo batch lost its play')
        if work.outcome_id is not None and FinishRewindOutcome(work.outcome_id) not in queue[index+1:]:
            raise ValueError('Queued Combo batch lost its retained outcome')


def register(mechanics):
    from .combo_modifiers import register as register_modifiers
    register_modifiers(mechanics)
    for effect,handler in ((GrantComboRepeatAura,grant),(BeginComboBatch,begin),
        (StartComboIteration,start),(FinishComboIteration,finish_one),(FinishComboBatch,finish)):
        mechanics.register(effect,handler)
