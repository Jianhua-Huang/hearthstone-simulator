"""Captured Battlecry repetition batches, independent of Rewind outcomes (R-114).

The current hand-play policy retains the original target, repeats each captured
ability in attachment order, and uses ordinary death/choice checkpoints. It adds
neither another paid play nor the spell-repeat death deferral/choice cache.
"""
from dataclasses import dataclass, replace
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, BattlecryPayload, BattlecryRepeatSpec,
                    BattlecryRepeatPlan, BattlecryBatchRecord, CardType, Zone)
from .registry import RuleContext


def capture_plan_from_state(state, registry, player_id, recipient):
    """The complete max plan at the hand payload's original acceptance window."""
    from .battlecry_matching import capture_recipient, validate_recipient, battlecry_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration, qualifying_repeat_witnesses
    definition = validate_recipient(state, registry, recipient)
    if recipient != capture_recipient(state, registry, recipient.carrier_id):
        raise ValueError('Battlecry plan must capture its original physical recipient face')
    _player(player_id)
    repetitions = 1
    contributors = []
    for entity_id in state.players[player_id].board:
        entity = state.entities[entity_id]
        if entity.kind != CardType.MINION or not entity.active or entity.doomed or entity.health <= 0:
            continue
        for ability in active_abilities(entity, 'battlecry_repeat'):
            spec = ability.battlecry_repeat
            condition = validate_source_declaration(registry, spec)
            source_matches = condition is None or bool(qualifying_repeat_witnesses(
                state, registry, player_id=player_id, carrier_id=entity.id, eligibility=condition))
            recipient_matches = battlecry_repeat_recipient_matches(spec, recipient=recipient,
                recipient_definition=definition, carrier_id=entity.id)
            if source_matches and recipient_matches:
                repetitions = max(repetitions, ability.battlecry_repeat.repetitions)
                contributors.append(ability.id)
    consumable=[]
    for modifier in state.players[player_id].battlecry_modifiers:
        validate_source_declaration(registry, modifier.spec, allow_source=False)
        if battlecry_repeat_recipient_matches(modifier.spec, recipient=recipient,
                recipient_definition=definition):
            repetitions=max(repetitions,modifier.spec.repetitions)
            contributors.append(modifier.id)
            if modifier.uses_remaining is not None:consumable.append(modifier.id)
    return BattlecryRepeatPlan(repetitions, tuple(sorted(contributors)), tuple(consumable))


def capture_plan(r, player_id, recipient):
    plan = capture_plan_from_state(r.state, r.registry, player_id, recipient)
    if plan.repetitions > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Battlecry repetition exceeds resolution budget')
    return plan


def validate_plan(state, registry, plan, recipient):
    from .battlecry_matching import validate_recipient, battlecry_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration
    definition = validate_recipient(state, registry, recipient)
    if type(plan) is not BattlecryRepeatPlan: raise ValueError('Invalid Battlecry repeat plan')
    plan.__post_init__()
    if (tuple(sorted(plan.contributors)) != plan.contributors or
            any(i >= state.next_attachment_id for i in plan.contributors)):
        raise ValueError('Invalid captured Battlecry repeat contributor')
    # Sources may legitimately have been silenced, consumed or removed later.
    # An identity that still survives must nevertheless retain its own family;
    # a Hero Power or other attachment ID cannot stand in for a BC policy.
    from .spell_acceptance import _live_attachments
    live = _live_attachments(state)
    known = []
    for contributor in plan.contributors:
        surviving = live.get(contributor)
        if surviving is None:
            continue
        family, carrier_id, value = surviving
        if family == 'ability':
            ability = value
            if ability.kind != 'battlecry_repeat' or contributor in plan.consumable_ids:
                raise ValueError('Battlecry repeat contributor belongs to another policy family')
            spec = ability.battlecry_repeat
            validate_source_declaration(registry, spec)
        elif family == 'battlecry_modifiers':
            modifier = value; spec = modifier.spec
            carrier_id = None
            validate_source_declaration(registry, spec, allow_source=False)
            if (contributor in plan.consumable_ids) != (modifier.uses_remaining is not None):
                raise ValueError('Battlecry consumption differs from its surviving policy')
        else:
            raise ValueError('Battlecry repeat contributor belongs to another surviving attachment family')
        # This uses the stored original face and physical carrier identity,
        # never current witnesses, recipient face, control or presence.
        if not battlecry_repeat_recipient_matches(spec, recipient=recipient,
                recipient_definition=definition, carrier_id=carrier_id):
            raise ValueError('Battlecry repeat contributor does not match its accepted recipient')
        known.append(spec.repetitions)
    if (known and max(known) > plan.repetitions or
            len(known) == len(plan.contributors) and max(known, default=1) != plan.repetitions):
        raise ValueError('Battlecry repeat count differs from its surviving policy declarations')


@dataclass(frozen=True)
class FinishBattlecryAcceptance(Effect):
    """One original proof retained through the whole play, including Rewind."""
    context: RuleContext
    payloads: tuple[BattlecryPayload, ...]
    plan: BattlecryRepeatPlan

    def __post_init__(self):
        if type(self.context) is not RuleContext or self.context.play is None:
            raise ValueError('Battlecry acceptance requires its original hand play context')
        BattlecryBatchRecord(1, self.context.play.id, self.context.player_id, self.payloads, self.plan)


def validate_acceptance(work, registry):
    work.__post_init__()
    context = work.context; state = context.state; play = context.play
    from .play_history import play_record
    from .battlecries import capture
    if (play_record(state, play.id) != play or play.completed or play.interrupted or play.countered or
            play.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO) or
            context.source_id != play.source_id or context.target_id != play.target_id or
            context.source_id not in state.entities or context.source.kind != play.kind or
            context.event is not None or context.death is not None or context.choice is not None or
            context.player_effect is not None or context.window is not None or context.trigger is not None or
            context.draw is not None or context.rewind_attempt != 0 or context.battlecry is not None or
            context.deathrattle is not None or context.power is not None or context.cast is not None or
            context.combo is not None or context.power_payload is not None or context.end_turn is not None):
        raise ValueError('Battlecry acceptance differs from its original hand play')
    definition = registry.card(play.card_id)
    if context.player_id != (context.source.controller if definition.colossal else play.player_id):
        raise ValueError('Battlecry acceptance changed its post-entry player')
    receipt = play.battlecry_acceptance
    if receipt is None or (receipt.player_id, receipt.payloads, receipt.plan) != (
            context.player_id, work.payloads, work.plan):
        raise ValueError('Battlecry proof differs from its durable root acceptance receipt')
    from .battlecry_matching import capture_recipient, validate_recipient
    validate_recipient(state, registry, receipt.recipient, play)
    if receipt.recipient != capture_recipient(state, registry, context.source_id):
        raise ValueError('Battlecry proof changed its original accepted physical face')
    if work.payloads != capture(context.source):
        raise ValueError('Battlecry acceptance differs from its complete original ability set')
    for payload in work.payloads:
        registry.behavior(payload.behavior_id)
        if registry.card(payload.card_id).battlecry != payload.behavior_id:
            raise ValueError('Battlecry acceptance differs from its declaration card')
    validate_plan(state, registry, work.plan, receipt.recipient)
    if work.plan != capture_plan_from_state(state, registry, context.player_id, receipt.recipient):
        raise ValueError('Battlecry plan differs from its complete original acceptance window')


def validate_accepted_batch(record, proof):
    if (record.play_id != proof.context.play.id or record.player_id != proof.context.player_id or
            record.payloads != proof.payloads or record.plan != proof.plan):
        raise ValueError('Battlecry batch differs from its original acceptance proof')


def validate_surviving_sources(state, proof):
    """An accepted global ID keeps its full declaration while it survives.

    Removing an attachment or transferring its whole physical carrier does not
    revoke the frozen plan. Reusing that ID on another carrier or rewriting its
    declaration is different from either legal lifecycle operation.
    """
    original = proof.context.state
    # Shared global-ID inventory includes other ability families, enchantments
    # and all player policy families, so changing type cannot hide a source.
    from .spell_acceptance import _live_attachments
    before, live = _live_attachments(original), _live_attachments(state)
    def is_source(item):
        kind, _, value = item
        return kind == 'battlecry_modifiers' or kind == 'ability' and value.kind == 'battlecry_repeat'
    identities = {i for i, item in before.items() if is_source(item)}
    identities.update(i for i, item in live.items() if i < original.next_attachment_id and is_source(item))
    for identity in identities:
        current = live.get(identity)
        if current is None:
            continue
        accepted = before.get(identity)
        if accepted is None or not is_source(accepted):
            raise ValueError('Battlecry original window lost a surviving repeat source')
        kind, carrier, old = accepted
        current_kind, current_carrier, new = current
        if kind != current_kind or carrier != current_carrier:
            raise ValueError('Battlecry source changed its surviving attachment type or physical carrier')
        if kind == 'ability':
            if (new.kind != 'battlecry_repeat' or replace(new, consumed=old.consumed) != old or
                    old.consumed and not new.consumed):
                raise ValueError('Battlecry source changed its surviving ability identity')
        else:
            allowed_uses = (None if old.uses_remaining is None else
                old.uses_remaining - int(identity in proof.plan.consumable_ids))
            if (replace(new, uses_remaining=old.uses_remaining) != old or
                    allowed_uses is None and new.uses_remaining is not None or
                    allowed_uses is not None and (new.uses_remaining is None or new.uses_remaining > allowed_uses)):
                raise ValueError('Battlecry modifier changed its surviving identity or consumed uses')


def finish_acceptance(r, effect):
    validate_acceptance(effect, r.registry)
    validate_surviving_sources(r.state, effect)
    from .play_history import play_record
    play = play_record(r.state, effect.context.play.id)
    if play.completed or play.interrupted:
        raise ResolutionError('Battlecry acceptance requires an active play')
    batches = [b for b in r.state.battlecry_batches if b.play_id == play.id]
    if not batches or any(not b.finished for b in batches):
        raise ResolutionError('Battlecry acceptance closed before its complete batches')
    for record in batches: validate_accepted_batch(record, effect)


@dataclass(frozen=True)
class GrantBattlecryRepeatAura(Effect):
    target_id: int
    spec: BattlecryRepeatSpec = BattlecryRepeatSpec()
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'Battlecry repeat carrier', 1); _source(self.source_id)
        if type(self.spec) is not BattlecryRepeatSpec: raise ValueError('Battlecry repeat requires a specification')
        self.spec.__post_init__()
        if self.expires_turn is not None: _integer(self.expires_turn, 'Battlecry repeat expiry', 1)


@dataclass(frozen=True)
class BeginBattlecryBatch(Effect):
    play_id: int
    player_id: int
    payloads: tuple[BattlecryPayload, ...]
    plan: BattlecryRepeatPlan
    outcome_id: int | None = None
    iteration: int = 1

    def __post_init__(self):
        # Same validation as a fresh persisted batch, without allocating identity.
        BattlecryBatchRecord(1, self.play_id, self.player_id, self.payloads, self.plan,
                             self.outcome_id, self.iteration)


@dataclass(frozen=True)
class StartBattlecryIteration(Effect):
    batch_id: int

    def __post_init__(self):
        _integer(self.batch_id, 'Battlecry batch', 1)


@dataclass(frozen=True)
class FinishBattlecryIteration(StartBattlecryIteration):
    pass


@dataclass(frozen=True)
class FinishBattlecryBatch(StartBattlecryIteration):
    pass


def batch_record(state, batch_id):
    _integer(batch_id, 'Battlecry batch', 1)
    if batch_id > len(state.battlecry_batches): raise ValueError('Unknown Battlecry batch')
    return state.battlecry_batches[batch_id-1]


def update(state, record, **changes):
    value = replace(record, **changes)
    state.battlecry_batches[record.id-1] = value
    return value


def validate_provenance(state, registry, record):
    from .play_history import play_record
    play = play_record(state, record.play_id)
    definition = registry.card(play.card_id)
    receipt = play.battlecry_acceptance
    if receipt is None or (receipt.player_id, receipt.payloads, receipt.plan) != (
            record.player_id, record.payloads, record.plan):
        raise ValueError('Battlecry batch differs from its durable root acceptance receipt')
    validate_plan(state, registry, record.plan, receipt.recipient)
    if (play.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO) or play.countered or
            not definition.colossal and record.player_id != play.player_id or
            play.completed and not record.finished or
            record.interrupted and state.status == 'playing' or
            play.interrupted and not (record.finished or record.interrupted)):
        raise ValueError('Invalid Battlecry batch play provenance')
    for payload in record.payloads:
        registry.behavior(payload.behavior_id)
        if payload.ability_id >= state.next_attachment_id or registry.card(payload.card_id).battlecry != payload.behavior_id:
            raise ValueError('Invalid Battlecry batch payload')
    if record.outcome_id is not None:
        from .rewind_outcomes import outcome
        retained = outcome(state, record.outcome_id)
        if (retained.play_id != record.play_id or retained.cast_id is not None or retained.power_id is not None or
                retained.player_id != record.player_id or retained.battlecries != record.payloads or
                retained.battlecry_plan != record.plan or record.iteration > retained.total or
                record.iteration > retained.completed + int(retained.running or retained.interrupted) or
                not (record.finished or record.interrupted) and not retained.running):
            raise ValueError('Battlecry batch and retained outcome disagree')
    elif any(x.play_id == record.play_id and x.battlecries for x in state.rewind_outcomes):
        raise ValueError('Retained Battlecry batch lost its outcome')


def key(record):
    return record.play_id, record.outcome_id, record.iteration


def begin(r, effect):
    from .play_history import play_record
    effect.__post_init__()
    play = play_record(r.state, effect.play_id)
    if play.completed or play.interrupted: raise ResolutionError('Battlecry batch requires an active play')
    record = BattlecryBatchRecord(len(r.state.battlecry_batches)+1, effect.play_id, effect.player_id,
        effect.payloads, effect.plan, effect.outcome_id, effect.iteration)
    validate_provenance(r.state, r.registry, record)
    if record.total > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Battlecry batch exceeds resolution budget')
    if any(key(b) == key(record) for b in r.state.battlecry_batches):
        raise ResolutionError('Battlecry batch already started')
    r.state.battlecry_batches.append(record)
    return [StartBattlecryIteration(record.id), FinishBattlecryBatch(record.id)]


def expected_activation(record, index):
    # Each ability is exhausted before the next inherited ability begins.
    return record.payloads[index // record.plan.repetitions], index % record.plan.repetitions + 1


def start(r, effect):
    from .battlecries import BeginBattlecry
    record = batch_record(r.state, effect.batch_id)
    if record.running or record.finished or record.interrupted or record.completed >= record.total:
        raise ResolutionError('Invalid Battlecry iteration start')
    update(r.state, record, running=True)
    payload, repeat_index = expected_activation(record, record.completed)
    return [BeginBattlecry(record.play_id, record.player_id, payload, record.id, repeat_index,
                          record.outcome_id, record.iteration), FinishBattlecryIteration(record.id)]


def finish_one(r, effect):
    record = batch_record(r.state, effect.batch_id)
    if not record.running or record.finished or record.interrupted:
        raise ResolutionError('Invalid Battlecry iteration completion')
    payload, repeat_index = expected_activation(record, record.completed)
    activation = next((b for b in reversed(r.state.battlecry_history) if b.batch_id == record.id), None)
    if activation is None or (activation.payload,activation.repeat_index) != (payload,repeat_index) or not activation.completed:
        raise ResolutionError('Battlecry iteration did not finish its activation')
    record = update(r.state, record, running=False, completed=record.completed+1)
    return [StartBattlecryIteration(record.id)] if record.completed < record.total else []


def finish(r, effect):
    record = batch_record(r.state, effect.batch_id)
    if record.running or record.finished or record.interrupted or record.completed != record.total:
        raise ResolutionError('Invalid Battlecry batch completion')
    update(r.state, record, finished=True)


def grant(r, effect):
    from .resolver import validate_attachment_source
    from .repeat_source_conditions import validate_source_declaration
    validate_source_declaration(r.registry, effect.spec)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id); return
    ability = AbilityInstance(attachment_id(r.state), 'battlecry_repeat', source_id=effect.source_id,
        battlecry_repeat=effect.spec, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def validate_history(state, registry):
    if type(state.battlecry_batches) is not list: raise ValueError('Battlecry batches require a list')
    keys = set()
    for index, record in enumerate(state.battlecry_batches, 1):
        if type(record) is not BattlecryBatchRecord: raise ValueError('Invalid Battlecry batch')
        record.__post_init__(); validate_provenance(state, registry, record)
        if record.id != index or key(record) in keys: raise ValueError('Invalid Battlecry batch identity')
        keys.add(key(record))
        children = [b for b in state.battlecry_history if b.batch_id == record.id]
        if not record.completed <= len(children) <= record.completed + int(record.running or record.interrupted):
            raise ValueError('Battlecry batch progress and activations disagree')
        for offset, activation in enumerate(children):
            if offset >= record.total or (activation.payload,activation.repeat_index) != expected_activation(record,offset):
                raise ValueError('Battlecry batch activation order differs')
            if offset < record.completed and not activation.completed:
                raise ValueError('Incomplete activation in completed Battlecry iteration')


def validate_boundary(game):
    from .battlecries import BeginBattlecry, FinishBattlecry
    from .resolver import FinishPlay
    from .rewind_outcomes import FinishRewindOutcome, FinishRewindOutcomes
    from .play_history import play_record, requires_battlecry_acceptance
    from .colossal import ColossalBattlecry
    from .combo_repeats import BeginComboBatch, FinishComboBatch
    state = game._state
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    pending = [b for b in state.battlecry_batches if not b.finished and not b.interrupted]
    proofs = {}
    proof_positions = {}
    for index, work in enumerate(queue):
        if type(work) is not FinishBattlecryAcceptance: continue
        validate_acceptance(work, game.registry)
        validate_surviving_sources(state, work)
        play = work.context.play; current = play_record(state, play.id)
        if (play.id in proofs or current != play or current.completed or current.interrupted or
                work.context.state.turn > state.turn or work.context.state.action_number > state.action_number):
            raise ValueError('Battlecry acceptance proof lost its unique active play')
        if len(work.payloads) * work.plan.repetitions > game.ruleset.max_resolution_steps:
            raise ValueError('Battlecry acceptance exceeds resolution budget')
        play_end = next((i for i,w in enumerate(queue) if type(w) is FinishPlay and w.play_id == play.id), None)
        if play_end is None or index >= play_end:
            raise ValueError('Battlecry acceptance must close before its play')
        proofs[play.id] = work; proof_positions[play.id] = index
    # The enclosing paid play carries an independent obligation, even before
    # the first batch/history exists. Deleting the entire queued root cannot
    # turn an accepted nonempty set into an apparent no-Battlecry play.
    for work in queue:
        if type(work) is not FinishPlay: continue
        play = play_record(state, work.play_id); receipt = play.battlecry_acceptance
        delayed = any(type(w) is ColossalBattlecry and w.play_id == play.id for w in queue)
        if requires_battlecry_acceptance(state, play, game.registry) and receipt is None and not delayed:
            raise ValueError('Post-entry physical play lost its durable Battlecry acceptance receipt')
        if receipt is not None:
            if bool(receipt.payloads) != (play.id in proofs):
                raise ValueError('Accepted Battlecry root lost its unique complete original proof')
            if receipt.payloads and (receipt.player_id, receipt.payloads, receipt.plan) != (
                    proofs[play.id].context.player_id, proofs[play.id].payloads, proofs[play.id].plan):
                raise ValueError('Battlecry proof differs from its durable accepted root')
    for play_id, proof in proofs.items():
        if (not any(b.play_id == play_id for b in state.battlecry_batches) and
                not any(type(w) is BeginBattlecryBatch and w.play_id == play_id for w in queue) and
                not any(x.play_id == play_id and x.battlecries for x in state.rewind_outcomes)):
            raise ValueError('Battlecry acceptance lost its complete scheduled root')
        for combo in state.combo_batches:
            if combo.play_id != play_id or combo.finished or combo.interrupted: continue
            closer = FinishComboBatch(combo.id)
            if closer not in queue or queue.index(closer) >= proof_positions[play_id]:
                raise ValueError('Combo batch must finish before the enclosing Battlecry acceptance')
        if any(type(w) is BeginComboBatch and w.play_id == play_id and index >= proof_positions[play_id]
                for index,w in enumerate(queue)):
            raise ValueError('Queued Combo batch outlives the enclosing Battlecry acceptance')
    # Finished early abilities and retained results remain bound to the same
    # original root while later bodies, choices or Combo reactions are pending.
    for record in state.battlecry_batches:
        play = play_record(state, record.play_id)
        if play.completed or play.interrupted: continue
        if record.play_id not in proofs:
            raise ValueError('Battlecry batch lost its complete original acceptance proof')
        validate_accepted_batch(record, proofs[record.play_id])
    for retained in state.rewind_outcomes:
        # Physical results carry their own complete acceptance/body proof and
        # close before FinishPhysicalBody. This loop binds paid batch roots.
        if retained.physical_child_id is not None or not retained.battlecries: continue
        play = play_record(state, retained.play_id)
        if play.completed or play.interrupted: continue
        proof = proofs.get(play.id)
        if proof is None or (retained.battlecries, retained.battlecry_plan, retained.player_id) != (
                proof.payloads, proof.plan, proof.context.player_id):
            raise ValueError('Retained Battlecry results lost their complete original acceptance proof')
        closer = FinishRewindOutcomes(retained.id)
        if not retained.finished and (closer not in queue or queue.index(closer) >= proof_positions[play.id]):
            raise ValueError('Retained results must finish before their Battlecry acceptance')
    expected = []
    for record in reversed(pending):
        if record.total > game.ruleset.max_resolution_steps: raise ValueError('Battlecry batch exceeds resolution budget')
        if record.running: expected.append(FinishBattlecryIteration(record.id))
        elif record.completed < record.total: expected.append(StartBattlecryIteration(record.id))
        expected.append(FinishBattlecryBatch(record.id))
        end = queue.index(FinishBattlecryBatch(record.id)) if FinishBattlecryBatch(record.id) in queue else None
        play_end = next((i for i,w in enumerate(queue) if type(w) is FinishPlay and w.play_id == record.play_id), None)
        if end is None or play_end is None or end >= play_end: raise ValueError('Battlecry batch must finish before its play')
        if end >= proof_positions[record.play_id]:
            raise ValueError('Battlecry batch must finish before its original acceptance')
        if record.outcome_id is not None:
            marker = FinishRewindOutcome(record.outcome_id)
            if marker not in queue or end >= queue.index(marker): raise ValueError('Battlecry batch must finish before its outcome')
        if record.running:
            closer = FinishBattlecryIteration(record.id)
            if closer not in queue or queue.index(closer) >= end: raise ValueError('Battlecry iteration must finish before its batch')
            children = [b for b in state.battlecry_history if b.batch_id == record.id]
            if len(children) == record.completed:
                payload, repeat_index = expected_activation(record,record.completed)
                start = BeginBattlecry(record.play_id,record.player_id,payload,record.id,repeat_index,record.outcome_id,record.iteration)
                if start not in queue or queue.index(start) >= queue.index(closer): raise ValueError('Missing Battlecry activation start')
            else:
                activation = children[-1]
                marker = FinishBattlecry(activation.id)
                if not activation.completed and (marker not in queue or queue.index(marker) >= queue.index(closer)):
                    raise ValueError('Battlecry activation must finish before its iteration')
    if [w for w in queue if isinstance(w,StartBattlecryIteration)] != expected:
        raise ValueError('Battlecry batch progress and continuation markers differ')
    starts=set()
    for index, work in enumerate(queue):
        if type(work) is BeginBattlecry:
            record=batch_record(state,work.batch_id)
            if (not record.running or record.finished or record.interrupted or
                    (work.payload,work.repeat_index) != expected_activation(record,record.completed)):
                raise ValueError('Unexpected queued Battlecry activation')
        if type(work) is not BeginBattlecryBatch: continue
        work.__post_init__()
        record=BattlecryBatchRecord(1,work.play_id,work.player_id,work.payloads,work.plan,work.outcome_id,work.iteration)
        validate_provenance(state,game.registry,record)
        if work.play_id not in proofs or index >= proof_positions[work.play_id]:
            raise ValueError('Queued Battlecry batch lost its complete original acceptance proof')
        validate_accepted_batch(record, proofs[work.play_id])
        if key(record) in starts or any(key(b)==key(record) for b in state.battlecry_batches):
            raise ValueError('Duplicate queued Battlecry batch')
        if record.total > game.ruleset.max_resolution_steps: raise ValueError('Queued Battlecry batch exceeds resolution budget')
        starts.add(key(record))
        if not any(type(w) is FinishPlay and w.play_id==work.play_id for w in queue[index+1:]):
            raise ValueError('Queued Battlecry batch lost its play')
        if work.outcome_id is not None and FinishRewindOutcome(work.outcome_id) not in queue[index+1:]:
            raise ValueError('Queued Battlecry batch lost its retained outcome')


def register(mechanics):
    from .battlecry_modifiers import register as register_modifiers
    register_modifiers(mechanics)
    for effect,handler in ((GrantBattlecryRepeatAura,grant),(BeginBattlecryBatch,begin),
        (StartBattlecryIteration,start),(FinishBattlecryIteration,finish_one),(FinishBattlecryBatch,finish),
        (FinishBattlecryAcceptance,finish_acceptance)):
        mechanics.register(effect,handler)
