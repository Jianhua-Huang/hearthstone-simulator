"""Retain successive Rewind payloads without undoing the preceding outcome.

R-093/R-102: capture a non-stacking retention policy; pay and activate once, while
each payload sees the preceding outcome's resulting state. Ordinary reaction and
death checkpoints apply, including existing enclosing death deferrals.
"""
from .runtime_copy import deepcopy
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .lifecycle import active_abilities, attachment_id, refresh_entity
from .model import AbilityInstance, CardType, Keyword, RewindOutcomeRecord, Zone


def retention_sources(state, player_id):
    return tuple(i for i in state.players[player_id].board
        if state.entities[i].kind == CardType.MINION and state.entities[i].health > 0 and
        not state.entities[i].doomed and active_abilities(state.entities[i], 'rewind_retention'))


def active_outcome(state, source_id, player_id, *, power_id=None):
    return next((x for x in reversed(state.rewind_outcomes) if x.source_id == source_id and
        x.player_id == player_id and x.running and x.power_id == power_id), None)


@dataclass(frozen=True)
class GrantRewindRetention(Effect):
    target_id: int
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'Rewind retention carrier', 1)
        _source(self.source_id)
        if self.expires_turn is not None: _integer(self.expires_turn, 'retention expiry', 1)


@dataclass(frozen=True)
class StartRewindOutcome(Effect):
    record_id: int

    def __post_init__(self):
        _integer(self.record_id, 'Rewind outcome record', 1)


@dataclass(frozen=True)
class FinishRewindOutcome(StartRewindOutcome):
    pass


@dataclass(frozen=True)
class FinishRewindOutcomes(StartRewindOutcome):
    pass


def outcome(state, record_id):
    _integer(record_id, 'Rewind outcome record', 1)
    if record_id > len(state.rewind_outcomes): raise ResolutionError('Unknown retained outcome')
    return state.rewind_outcomes[record_id - 1]


def update(state, record, **changes):
    value = replace(record, **changes)
    state.rewind_outcomes[record.id - 1] = value
    return value


def eligibility(r, source_id, player_id, play, cast, power):
    if play is not None or (power is not None and power.origin == 'manual'):
        session = r.game._rewind
        if session is None or session.action.entity_id != source_id: return None, ()
        state = session.before
        entity = state.entities[source_id]
    else:
        state = r.state
        entity = state.entities[source_id]
    definition = r.registry.card((power or cast or play).card_id)
    if definition.rewind is None or Keyword.REWIND not in entity.keywords: return None, ()
    return definition.rewind, retention_sources(state, player_id)


def accept_combos(r, play, *, status=None, colossal_record_id=None):
    """Actual physical window, pure complete acceptance before finite consumption."""
    from .combos import capture
    from .combo_matching import capture_recipient
    from .combo_modifiers import capture_from_state, capture as capture_policies
    from .combo_repeats import capture_plan
    from .model import ComboAcceptanceReceipt
    from .play_history import accept_combos as install
    recipient=capture_recipient(r.state,r.registry,play.source_id)
    combos=capture(r.state.entities[play.source_id]) if status is None else ()
    status=status or ('activated' if combos and play.combo else 'disabled' if combos else 'no_payload')
    eligible=status=='activated'
    modifiers=capture_from_state(r.state,r.registry,play,'activation',recipient,eligible)
    plan=capture_plan(r,play,recipient,modifiers) if eligible else None
    if plan is not None and len(combos)*plan.repetitions>r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Complete Combo acceptance exceeds resolution budget')
    policy=capture_policies(r,play,'activation',recipient,eligible)
    accepted=ComboAcceptanceReceipt(play.player_id,recipient,status,combos,plan,policy.id,colossal_record_id)
    play=install(r.state,play.id,accepted)
    return play,policy


def canceled_combos(r, play, status, *, colossal_record_id=None):
    from .combo_acceptance import make_proof
    from .combo_modifiers import consume
    play,policy=accept_combos(r,play,status=status,colossal_record_id=colossal_record_id)
    proof=make_proof(r,play,'activation',policy)
    consume(r,policy)
    return [proof]


def payload(r, source_id, player_id, target_id, behavior_ids, *, play=None, cast=None, power=None, battlecries=(), colossal_record_id=None):
    """One activation; the wrapper never invents another play, cast or power use."""
    physical=play is not None and play.kind in (CardType.MINION,CardType.WEAPON,CardType.HERO)
    combos=();combo_plan=None;combo_policy=None;combo_acceptance=[]
    from .battlecry_repeats import capture_plan, FinishBattlecryAcceptance
    from .battlecry_matching import capture_recipient
    recipient = (capture_recipient(r.state, r.registry, source_id)
        if physical else None)
    battlecry_plan = capture_plan(r, player_id, recipient) if battlecries else None
    if physical:
        from .model import BattlecryAcceptanceReceipt
        from .play_history import accept_battlecries
        play = accept_battlecries(r.state, play.id,
            BattlecryAcceptanceReceipt(player_id, battlecries, battlecry_plan, recipient))
        # Both durable roots must precede either original proof: BC binds the
        # whole PlayRecord, so a later Combo installation would invalidate it.
        play,combo_policy=accept_combos(r,play,colossal_record_id=colossal_record_id)
        combos,combo_plan=play.combo_acceptance.payloads,play.combo_acceptance.plan
        from .combo_acceptance import make_proof
        combo_acceptance=[make_proof(r,play,'activation',combo_policy)]
    # Capture before finite policies consume, and before generic on_play bodies
    # can remove a source. This proof is independent of every callback's view.
    if battlecry_plan is not None:
        from .registry import RuleContext
        battlecry_acceptance = [FinishBattlecryAcceptance(
            RuleContext(deepcopy(r.state), source_id, player_id, target_id, play=play),
            battlecries, battlecry_plan)]
    else:
        battlecry_acceptance = []
    if battlecry_plan is not None:
        from .battlecry_modifiers import consume
        consume(r, player_id, battlecry_plan, play.id)
    if combo_policy is not None:
        from .combo_modifiers import consume as consume_combo
        consume_combo(r,combo_policy)
    spec, contributors = eligibility(r, source_id, player_id, play, cast, power)
    if not contributors:
        return [*ordinary_payload(r, source_id, player_id, target_id, behavior_ids, play=play, cast=cast, power=power, battlecries=battlecries,battlecry_plan=battlecry_plan,combos=combos,combo_plan=combo_plan),
                *combo_acceptance,*battlecry_acceptance]
    if spec.retries + 1 > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Retained Rewind outcomes exceed resolution budget')
    record = RewindOutcomeRecord(len(r.state.rewind_outcomes)+1, source_id, player_id,
        (power or cast or play).card_id, r.state.turn, r.state.action_number, target_id,
        behavior_ids, contributors, spec.retries+1, play_id=play.id if play else None,
        cast_id=cast.id if cast else None,power_id=power.id if power else None,battlecries=battlecries,battlecry_plan=battlecry_plan,combos=combos,combo_plan=combo_plan)
    r.state.rewind_outcomes.append(record)
    return [StartRewindOutcome(record.id), FinishRewindOutcomes(record.id), *combo_acceptance,*battlecry_acceptance]


def ordinary_payload(r, source_id, player_id, target_id, behavior_ids, *, play=None, cast=None, power=None, extra_outcome=False, battlecries=(), outcome_id=None, iteration=1, battlecry_plan=None, combos=(), combo_plan=None):
    if cast is not None:
        from .spell_casts import payload_effects
        return payload_effects(r, cast, behavior_ids, play=play, extra_outcome=extra_outcome)
    if power is not None:
        if behavior_ids!=tuple(a.behavior_id for a in power.payloads):
            raise ValueError('Hero power payload differs from its accepted ability identities')
        from .power_payloads import schedule
        return schedule(r,power,outcome_id=outcome_id,iteration=iteration)
    from .combo_repeats import BeginComboBatch
    from .battlecry_repeats import BeginBattlecryBatch
    from .native_active_targets import accept, FinishNativeActiveTarget
    native=accept(r,'on_play',play,behavior_ids) if play is not None else None
    body_target=target_id if native is None else native.selection.target_id
    # Native on_play wrappers still accept their real conditions and one-use
    # programs when no target survives. Their bodies already handle None.
    return [*[r.call(b, source_id, player_id, body_target, play=play, power=power) for b in behavior_ids],
            *(()if native is None else(FinishNativeActiveTarget(native),)),
            *([BeginBattlecryBatch(play.id, player_id, battlecries, battlecry_plan, outcome_id, iteration)] if battlecries else []),
            *([BeginComboBatch(play.id,player_id,combos,combo_plan,outcome_id,iteration)] if combo_plan is not None else [])]


def advance_face(r, record):
    if record.completed == 0: return
    from .rewind import attempt_card_id
    previous = attempt_card_id(r.registry, record.card_id, record.completed - 1)
    card_id = attempt_card_id(r.registry, record.card_id, record.completed)
    entity = r.state.entities[record.source_id]
    # A transformation has its own identity; never transform it back just to
    # display the budget of an already captured activation.
    if entity.card_id != previous or card_id == previous: return
    from .choose_branch_state import rebind_face
    rebind_face(entity, r.registry, card_id)
    entity.card_id = card_id
    entity.zone_epoch += 1
    if r.registry.card(card_id).rewind is None:
        entity.abilities = [a for a in entity.abilities if not (a.kind == 'keyword' and a.keyword == Keyword.REWIND)]
    refresh_entity(entity)
    if entity.zone != Zone.DECK:
        for viewer, knowledge in r.game._information.players.items():
            if (entity.controller == viewer or str(entity.id) in knowledge.known or
                    entity.zone in (Zone.BOARD, Zone.WEAPON, Zone.HERO, Zone.QUEST)):
                knowledge.remember(entity)
    r.emit('rewind_face_changed', source_id=entity.id, target_id=entity.id,
        player_id=record.player_id, amount=record.completed, _capture=False)


def start(r, effect):
    record = outcome(r.state, effect.record_id)
    if record.running or record.finished or record.interrupted or record.completed >= record.total:
        raise ResolutionError('Invalid retained outcome start')
    record = update(r.state, record, running=True)
    advance_face(r, record)
    from .play_history import play_record
    from .spell_casts import cast_record
    play = play_record(r.state, record.play_id) if record.play_id is not None else None
    cast = cast_record(r.state, record.cast_id) if record.cast_id is not None else None
    from .hero_powers import power_record
    power = power_record(r.state,record.power_id) if record.power_id is not None else None
    r.emit('rewind_outcome_started', source_id=record.source_id, player_id=record.player_id,
        amount=record.completed + 1, _capture=False)
    if record.physical_child_id is not None:
        from .generated_retained_outcomes import start_physical
        return start_physical(r, record)
    return [*ordinary_payload(r, record.source_id, record.player_id, record.target_id,
        record.behavior_ids, play=play, cast=cast, power=power, extra_outcome=record.completed > 0,
        battlecries=record.battlecries,outcome_id=record.id,iteration=record.completed+1,battlecry_plan=record.battlecry_plan,combos=record.combos,combo_plan=record.combo_plan),
        FinishRewindOutcome(record.id)]


def finish_one(r, effect):
    record = outcome(r.state, effect.record_id)
    if not record.running or record.finished or record.interrupted:
        raise ResolutionError('Invalid retained outcome completion')
    if record.physical_child_id is not None:
        from .whole_card_physical import child_for, result_segment_count
        progress = child_for(r.state, record.physical_child_id).physical
        if (progress is None or progress.cursor != (record.completed + 1) * result_segment_count(progress)
                or progress.active_battlecry_id is not None or progress.active_combo_id is not None):
            raise ResolutionError('Retained result Finish abandoned its complete actual physical body')
    record = update(r.state, record, running=False, completed=record.completed+1)
    r.emit('rewind_outcome_finished', source_id=record.source_id, player_id=record.player_id,
        amount=record.completed, _capture=False)
    return [StartRewindOutcome(record.id)] if record.completed < record.total else []


def finish_all(r, effect):
    record = outcome(r.state, effect.record_id)
    if record.running or record.finished or record.interrupted or record.completed != record.total:
        raise ResolutionError('Invalid retained outcome closure')
    update(r.state, record, finished=True)


def grant(r, effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id); return
    ability = AbilityInstance(attachment_id(r.state), 'rewind_retention', source_id=effect.source_id,
        expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
        ability_id=ability.id, ability_kind=ability.kind)


def validate_history(state, registry):
    if type(state.rewind_outcomes) is not list: raise ValueError('Retained outcomes require a list')
    keys = set(); previous = (0, 0)
    from .play_history import play_record
    from .spell_casts import cast_record
    from .hero_powers import power_record
    for index, record in enumerate(state.rewind_outcomes, 1):
        if type(record) is not RewindOutcomeRecord: raise ValueError('Invalid retained outcome record')
        record.__post_init__()
        definition = registry.card(record.card_id)
        if (record.id != index or definition.rewind is None or record.total != definition.rewind.retries+1 or
                record.source_id not in state.entities or any(i not in state.entities for i in record.contributors) or
                record.target_id is not None and record.target_id not in state.entities or
                not previous <= (record.turn, record.action) <= (state.turn, state.action_number) or
                record.interrupted and state.status == 'playing'):
            raise ValueError('Invalid retained outcome provenance')
        previous = (record.turn, record.action)
        if record.physical_child_id is not None:
            from .generated_retained_outcomes import validate_record as validate_generated_retained
            validate_generated_retained(state, registry, record)
            continue
        play = play_record(state, record.play_id) if record.play_id is not None else None
        cast = cast_record(state, record.cast_id) if record.cast_id is not None else None
        power = power_record(state,record.power_id) if record.power_id is not None else None
        origin = power or cast or play
        key = ('power',power.id) if power else ('cast',cast.id) if cast else ('play',play.id)
        if (key in keys or (record.source_id, record.player_id, record.card_id, record.turn) !=
                (origin.source_id, origin.player_id, origin.card_id, origin.turn) or
                record.action < origin.action or record.target_id != origin.target_id or
                bool(cast) != (definition.kind == CardType.SPELL) or
                bool(power) != (definition.kind == CardType.HERO_POWER) or power is not None and power.failure is not None or
                cast is not None and (cast.play_id != record.play_id or not cast.payload_started or cast.failure) or
                origin.completed and not record.finished or origin.interrupted and not(record.finished or record.interrupted)):
            raise ValueError('Retained outcomes and their activation disagree')
        keys.add(key)
        for behavior in record.behavior_ids: registry.behavior(behavior)
        if power is not None and record.behavior_ids!=tuple(a.behavior_id for a in power.payloads):
            raise ValueError('Retained hero power changed its accepted abilities')
        if record.battlecry_plan is not None:
            from .battlecry_repeats import validate_plan
            if play.battlecry_acceptance is None:
                raise ValueError('Retained Battlecries lost their original recipient acceptance')
            validate_plan(state, registry, record.battlecry_plan, play.battlecry_acceptance.recipient)
            receipt = play.battlecry_acceptance
            if receipt is None or (receipt.player_id, receipt.payloads, receipt.plan) != (
                    record.player_id, record.battlecries, record.battlecry_plan):
                raise ValueError('Retained Battlecry outcomes differ from their durable acceptance receipt')
        if (record.combo_plan is not None) != bool(record.combos and play and play.combo):
            raise ValueError('Retained Combo condition and repeat plan disagree')
        if record.combo_plan is not None:
            from .combo_repeats import validate_plan as validate_combo_plan
            validate_combo_plan(state,record.combo_plan)
        from .combos import validate_payload
        for payload in record.combos: validate_payload(state,registry,payload)
        for payload in record.battlecries:
            registry.behavior(payload.behavior_id)
            if payload.ability_id >= state.next_attachment_id or registry.card(payload.card_id).battlecry != payload.behavior_id:
                raise ValueError('Invalid retained Battlecry payload')


def validate_queue(state, queue, max_resolution_steps):
    queue = tuple(queue)
    pending = [r for r in state.rewind_outcomes if not r.finished and not r.interrupted]
    markers = [w for w in queue if isinstance(w, StartRewindOutcome)]
    expected = []
    from .resolver import FinishPlay
    from .spell_casts import FinishSpellCast
    from .hero_powers import FinishHeroPower
    from .whole_card_physical import FinishPhysicalBody
    for record in reversed(pending):
        if record.total > max_resolution_steps:
            raise ValueError('Retained outcomes exceed resolution budget')
        if record.running: expected.append(FinishRewindOutcome(record.id))
        elif record.completed < record.total: expected.append(StartRewindOutcome(record.id))
        closer = FinishRewindOutcomes(record.id)
        expected.append(closer)
        activation = next((i for i,w in enumerate(queue) if
            (type(w) is FinishPhysicalBody and w.proof.accepted.child_id == record.physical_child_id) or
            (type(w) is FinishSpellCast and w.cast_id == record.cast_id) or
            (type(w) is FinishHeroPower and w.record_id == record.power_id) or
            (record.cast_id is None and type(w) is FinishPlay and w.play_id == record.play_id)), None)
        if closer not in queue or activation is None or queue.index(closer) >= activation:
            raise ValueError('Retained outcomes must close before their activation')
    if markers != expected: raise ValueError('Retained outcome progress and continuations differ')


def validate_boundary(game):
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    validate_queue(game._state, queue, game.ruleset.max_resolution_steps)


def register(mechanics):
    for effect, handler in ((GrantRewindRetention, grant), (StartRewindOutcome, start),
        (FinishRewindOutcome, finish_one), (FinishRewindOutcomes, finish_all)):
        mechanics.register(effect, handler)
