"""Resumable repetitions of one spell payload, sharing payment and play windows.

Only manually played spells currently enter this contract. Deaths are deferred
through the captured execution quota; ordinary reactions still run between
effects. Exact live-server windows remain a separately tracked calibration task.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, CardClass, CardType, SpellChoiceMemo,
                    SpellRepeatRecord, SpellRepeatSpec, Zone)
from .play_history import play_record


@dataclass(frozen=True)
class GrantSpellRepeatAura(Effect):
    target_id: int
    spec: SpellRepeatSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'spell repeat holder', 1)
        _source(self.source_id)
        if type(self.spec) is not SpellRepeatSpec:
            raise ValueError('Spell repeat requires SpellRepeatSpec')
        self.spec.__post_init__()
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'spell repeat expiry', 1)


@dataclass(frozen=True)
class StartSpellIteration(Effect):
    play_id: int

    def __post_init__(self):
        _integer(self.play_id, 'repeated spell play ID', 1)


@dataclass(frozen=True)
class FinishSpellIteration(StartSpellIteration):
    pass


@dataclass(frozen=True)
class FinishSpellRepeat(StartSpellIteration):
    pass


def repeat_record(state, play_id):
    record = next((x for x in state.spell_repeats if x.play_id == play_id), None)
    if record is None:
        raise ResolutionError('Missing spell repeat record')
    return record


def update(state, record, **changes):
    state.spell_repeats[state.spell_repeats.index(record)] = replace(record, **changes)


def execution_count(r, play):
    """Read an accepted quota; this helper cannot open an acceptance window."""
    if (play.kind != CardType.SPELL or play.countered or
            play.spell_submission is None or play.spell_payload is None):
        raise ResolutionError('Spell count requires its explicit accepted payload')
    if any(window.play_id == play.id for window in r.state.action_windows):
        raise ResolutionError('Spell count requires its closed original action window')
    count = play.spell_payload.casts
    if count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Spell repetition exceeds resolution budget')
    return count


def payload(r, play, target_id, behavior_ids, *, repeated=False):
    """Activate the physical spell once; repeat activations allocate new entities."""
    from .spell_casts import begin_played, FinishSpellCast
    iteration = repeat_record(r.state, play.id).completed + 1 if repeated else 1
    cast = begin_played(r, play, target_id, iteration=iteration)
    from .rewind_outcomes import payload as outcomes_payload
    return [*outcomes_payload(r, play.source_id, play.player_id, target_id, behavior_ids,
        play=play, cast=cast), FinishSpellCast(cast.id)]


def begin(r, play, target_id, count, behavior_ids):
    if any(x.play_id == play.id for x in r.state.spell_repeats):
        raise ResolutionError('A played spell can enter repetition only once')
    r.state.spell_repeats.append(SpellRepeatRecord(play.id, target_id, count, behavior_ids))
    r.death_deferrals += 1
    return [StartSpellIteration(play.id), FinishSpellRepeat(play.id)]


def start_iteration(r, effect):
    record = repeat_record(r.state, effect.play_id)
    if record.running or record.finished or record.interrupted or record.completed >= record.casts:
        raise ResolutionError('Invalid spell iteration start')
    update(r.state, record, running=True)
    play = play_record(r.state, effect.play_id)
    return [*payload(r, play, record.target_id, record.behavior_ids, repeated=record.completed > 0),
            FinishSpellIteration(record.play_id)]


def finish_iteration(r, effect):
    record = repeat_record(r.state, effect.play_id)
    if not record.running or record.finished or record.interrupted:
        raise ResolutionError('Invalid spell iteration completion')
    completed = record.completed + 1
    update(r.state, record, running=False, completed=completed)
    if completed < record.casts:
        return [StartSpellIteration(record.play_id)]


def finish_repeat(r, effect):
    record = repeat_record(r.state, effect.play_id)
    if record.running or record.finished or record.interrupted or record.completed != record.casts or r.death_deferrals < 1:
        raise ResolutionError('Invalid spell repeat completion')
    update(r.state, record, finished=True)
    r.death_deferrals -= 1


def active_choice_record(state, choice):
    if choice.repeat_key is None:
        return None
    for record in reversed(state.spell_repeats):
        if not record.running:
            continue
        play = play_record(state, record.play_id)
        if (play.source_id, play.player_id) == (choice.source_id, choice.player_id):
            return record
    return None


def remembered_choice(state, choice):
    record = active_choice_record(state, choice)
    if record is not None:
        return next((m.selected_ids for m in record.choices if m.key == choice.repeat_key), None)
    return None


def remember_choice(state, result):
    record = active_choice_record(state, result.choice)
    if record is not None:
        if any(m.key == result.choice.repeat_key for m in record.choices):
            raise ResolutionError('A repeated branch choice was selected more than once')
        update(state, record, choices=(*record.choices,
            SpellChoiceMemo(result.choice.repeat_key, result.selected_ids)))


def grant(r, effect):
    from .repeat_source_conditions import validate_source_declaration
    validate_source_declaration(r.registry, effect.spec)
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id)
        return
    ability = AbilityInstance(attachment_id(r.state), 'spell_repeat', source_id=effect.source_id,
                             spell_repeat=effect.spec, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def validate_history(state, registry):
    if type(state.spell_repeats) is not list:
        raise ValueError('Spell repeat history must be a list')
    last_id = 0
    for record in state.spell_repeats:
        if type(record) is not SpellRepeatRecord:
            raise ValueError('Invalid spell repeat history')
        record.__post_init__()
        play = play_record(state, record.play_id)
        if (record.play_id <= last_id or play.kind != CardType.SPELL or play.countered or
                record.target_id is not None and record.target_id not in state.entities or
                play.completed and not record.finished or
                record.interrupted and (state.status == 'playing' or not play.interrupted) or
                not record.finished and not record.interrupted and play.interrupted):
            raise ValueError('Invalid spell repeat provenance')
        for behavior in record.behavior_ids:
            registry.behavior(behavior)
        last_id = record.play_id


def validate_boundary(game):
    """Active repetitions must own exact, ordered queue markers and one deferral."""
    frame = game._frame
    queue = (*frame.prefix, *frame.continuation) if frame else ()
    pending = [r for r in game._state.spell_repeats if not r.finished and not r.interrupted]
    markers = [w for w in queue if isinstance(w, StartSpellIteration)]
    expected = []
    for record in reversed(pending):
        if record.casts > game.ruleset.max_resolution_steps:
            raise ValueError('Spell repeat count exceeds resolution budget')
        if record.running:
            expected.append(FinishSpellIteration(record.play_id))
        elif record.completed < record.casts:
            expected.append(StartSpellIteration(record.play_id))
        expected.append(FinishSpellRepeat(record.play_id))
    if markers != expected:
        raise ValueError('Spell repeat progress and continuations do not match')
    from .resolver import FinishPlay
    for record in pending:
        completion = next((i for i, work in enumerate(queue)
            if type(work) is FinishPlay and work.play_id == record.play_id), None)
        closer = queue.index(FinishSpellRepeat(record.play_id))
        if completion is None or completion < closer:
            raise ValueError('A repeated spell must finish its payloads before its play')
    if pending and frame is None:
        raise ValueError('Active spell repetition requires a suspended frame')


def register(mechanics):
    mechanics.register(GrantSpellRepeatAura, grant)
    mechanics.register(StartSpellIteration, start_iteration)
    mechanics.register(FinishSpellIteration, finish_iteration)
    mechanics.register(FinishSpellRepeat, finish_repeat)
