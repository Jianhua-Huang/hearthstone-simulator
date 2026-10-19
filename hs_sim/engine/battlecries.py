"""Explicit Battlecry identity and hand-play activation history (R-113).

Generic on_play payloads are deliberately separate. Repetition, suppression and
effect/history activations build on this entry point in subsequent contracts.
"""
from dataclasses import dataclass, replace
from copy import deepcopy
from .effects import Effect, _integer
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import BattlecryPayload, BattlecryRecord, CardType


def capture(entity):
    from .remaining_mana_numbers import battlecry_number
    return tuple(BattlecryPayload(a.id, a.behavior_id, a.battlecry_card_id,a.carved_spell_id,battlecry_number(entity,a))
                 for a in active_abilities(entity, 'battlecry'))


def battlecry_record(state, record_id):
    _integer(record_id, 'Battlecry record', 1)
    if record_id > len(state.battlecry_history):
        raise ValueError('Unknown Battlecry activation')
    return state.battlecry_history[record_id - 1]


def activated_battlecries(state, player_id, *, successful=None, turn=None, before_id=None):
    """Trusted query of actual activations, never inferred from plays or summons."""
    from .effects import _player
    _player(player_id)
    if successful is not None and type(successful) is not bool:
        raise ValueError('Battlecry success filter must be boolean')
    for value in (turn, before_id):
        if value is not None: _integer(value, 'Battlecry history bound', 1)
    return tuple(b for b in state.battlecry_history if b.player_id == player_id and
        (successful is None or (b.completed and b.failure is None) == successful) and
        (turn is None or b.turn == turn) and (before_id is None or b.id < before_id))


def active_battlecry(state, source_id, player_id):
    return next((b for b in reversed(state.battlecry_history) if
        b.source_id == source_id and b.player_id == player_id and not b.completed and not b.interrupted), None)


@dataclass(frozen=True)
class BeginBattlecry(Effect):
    play_id: int
    player_id: int
    payload: BattlecryPayload
    batch_id: int
    repeat_index: int = 1
    outcome_id: int | None = None
    iteration: int = 1

    def __post_init__(self):
        from .effects import _player
        _integer(self.play_id, 'Battlecry play', 1); _player(self.player_id)
        _integer(self.batch_id, 'Battlecry batch', 1); _integer(self.repeat_index, 'Battlecry repetition', 1)
        if type(self.payload) is not BattlecryPayload:
            raise ValueError('Battlecry requires a captured ability')
        self.payload.__post_init__()
        if self.outcome_id is not None: _integer(self.outcome_id, 'Battlecry outcome', 1)
        _integer(self.iteration, 'Battlecry iteration', 1)
        if self.outcome_id is None and self.iteration != 1:
            raise ValueError('Extra Battlecry iterations require an enclosing retained outcome')


@dataclass(frozen=True)
class FinishBattlecry(Effect):
    record_id: int

    def __post_init__(self):
        _integer(self.record_id, 'Battlecry completion', 1)


def begin(r, effect):
    effect.__post_init__()
    from .play_history import play_record
    play = play_record(r.state, effect.play_id)
    if play.completed or play.interrupted or play.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
        raise ResolutionError('Battlecry requires an active character or weapon play')
    from .paid_body_targets import body_target
    from .held_opponent_copies import freeze_play
    record = BattlecryRecord(len(r.state.battlecry_history)+1, play.source_id,
        effect.player_id, play.card_id, r.state.turn, r.state.action_number, body_target(play, effect.payload, 'battlecry'),
        effect.play_id, effect.payload, effect.batch_id, effect.repeat_index, outcome_id=effect.outcome_id, iteration=effect.iteration,
        held_opponent_copy=freeze_play(r.state, r.registry, play, effect.payload))
    validate_record(r.state, r.registry, record)
    if any((b.play_id, b.payload.ability_id, b.outcome_id, b.iteration, b.repeat_index) ==
           (record.play_id, record.payload.ability_id, record.outcome_id, record.iteration, record.repeat_index)
           for b in r.state.battlecry_history):
        raise ResolutionError('Battlecry activation already recorded')
    from .paid_body_targets import available
    context = None
    if play.body_targets is not None and r.registry.target_visibility(r.registry.card(record.payload.card_id).target_rule) == 'player':
        from .player_target_inputs import live_factory
        source = deepcopy(r.state.entities[play.source_id]); source.controller = play.player_id
        context = live_factory(r, source)
    if not available(r.state, r.registry, play, record.payload, 'battlecry', context_factory=context):
        record = replace(record, failure='invalid_target', payload_started=False)
    r.state.battlecry_history.append(record)
    r.emit('battlecry_started', source_id=record.source_id, target_id=record.target_id,
           player_id=record.player_id, battlecry_id=record.id, play_id=record.play_id)
    if record.failure is not None:
        r.emit('body_target_skipped', source_id=record.source_id, target_id=record.target_id,
            player_id=record.player_id, family='battlecry', record_id=record.id, play_id=record.play_id)
        return [FinishBattlecry(record.id)]
    return [r.call(record.payload.behavior_id, record.source_id, record.player_id,
                   record.target_id, play=play, battlecry=record), FinishBattlecry(record.id)]


def finish(r, effect):
    record = battlecry_record(r.state, effect.record_id)
    if record.completed or record.interrupted:
        raise ResolutionError('Battlecry activation is already settled')
    r.state.battlecry_history[record.id-1] = replace(record, completed=True)
    r.emit('battlecry_finished', source_id=record.source_id, target_id=record.target_id,
           player_id=record.player_id, battlecry_id=record.id, play_id=record.play_id)


def validate_record(state, registry, record):
    if record.origin != 'hand':
        from .battlecry_sources import validate_indirect_record
        return validate_indirect_record(state, registry, record)
    from .held_opponent_copies import validate_battlecry
    validate_battlecry(state, registry, record)
    from .play_history import play_record
    play = play_record(state, record.play_id)
    from .paid_body_targets import body_target
    if record.failure is not None and (play.body_targets is None or record.failure != 'invalid_target' or record.payload_started or record.target_id is None):
        raise ValueError('Failed paid Battlecry requires its actual independent target receipt')
    from .battlecry_repeats import batch_record
    batch = batch_record(state, record.batch_id)
    if ((record.play_id,record.player_id,record.outcome_id,record.iteration) !=
            (batch.play_id,batch.player_id,batch.outcome_id,batch.iteration) or
            record.payload not in batch.payloads or record.repeat_index > batch.plan.repetitions):
        raise ValueError('Battlecry activation and repetition batch disagree')
    definition = registry.card(record.card_id)
    registry.behavior(record.payload.behavior_id)
    if (record.source_id not in state.entities or
            record.target_id is not None and record.target_id not in state.entities or
            record.payload.ability_id >= state.next_attachment_id or
            registry.card(record.payload.card_id).battlecry != record.payload.behavior_id or
            not definition.colossal and record.player_id != play.player_id or
            (record.source_id, record.card_id, record.target_id, record.turn) !=
            (play.source_id, play.card_id, body_target(play, record.payload, 'battlecry'), play.turn) or record.action < play.action or
            definition.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO) or
            record.interrupted and state.status == 'playing' or
            play.completed and not record.completed or play.interrupted and not(record.completed or record.interrupted)):
        raise ValueError('Invalid Battlecry provenance or enclosing play')
    if record.outcome_id is not None:
        from .rewind_outcomes import outcome
        retained = outcome(state, record.outcome_id)
        if (retained.play_id != record.play_id or retained.cast_id is not None or retained.power_id is not None or
                retained.player_id != record.player_id or record.payload not in retained.battlecries or
                record.iteration > retained.total or
                record.iteration > retained.completed + int(retained.running or retained.interrupted) or
                not(record.completed or record.interrupted) and not retained.running):
            raise ValueError('Battlecry and retained outcome disagree')


def validate_history(state, registry):
    from .historical_body_targets import validate_history as validate_historical_history
    validate_historical_history(state,registry)
    from .indirect_body_targets import validate_history as validate_bound_history
    validate_bound_history(state,registry)
    from .battlecry_repeats import validate_history as validate_batches
    validate_batches(state, registry)
    if type(state.battlecry_history) is not list:
        raise ValueError('Battlecry history must be a list')
    previous = (0, 0); keys = set()
    for index, record in enumerate(state.battlecry_history, 1):
        if type(record) is not BattlecryRecord: raise ValueError('Invalid Battlecry history record')
        record.__post_init__(); validate_record(state, registry, record)
        key = (record.play_id, record.payload.ability_id, record.outcome_id, record.iteration, record.repeat_index)
        if (record.id != index or record.origin == 'hand' and key in keys or
                not previous <= (record.turn, record.action) <= (state.turn, state.action_number)):
            raise ValueError('Invalid Battlecry chronology or duplicate activation')
        if record.origin == 'hand': keys.add(key)
        previous = (record.turn, record.action)


def validate_boundary(game):
    from .battlecry_sources import validate_boundary as validate_sources
    validate_sources(game)
    from .battlecry_repeats import validate_boundary as validate_batches
    validate_batches(game)
    from .resolver import FinishPlay
    from .rewind_outcomes import FinishRewindOutcome
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    pending = [b for b in game._state.battlecry_history if not b.completed and not b.interrupted]
    if [w.record_id for w in queue if type(w) is FinishBattlecry] != [b.id for b in reversed(pending)]:
        raise ValueError('Battlecry progress and completion markers differ')
    for record in pending:
        closer = FinishBattlecry(record.id)
        if record.origin != 'hand':
            continue
        play_end = next((i for i,w in enumerate(queue) if type(w) is FinishPlay and w.play_id == record.play_id), None)
        if play_end is None or queue.index(closer) >= play_end:
            raise ValueError('Battlecry must finish before its hand play')
        if record.outcome_id is not None:
            outcome_end = FinishRewindOutcome(record.outcome_id)
            if outcome_end not in queue or queue.index(closer) >= queue.index(outcome_end):
                raise ValueError('Battlecry must finish before its retained outcome')
    from .paid_body_targets import body_target
    starts = set()
    for index, work in enumerate(queue):
        if type(work) is not BeginBattlecry: continue
        work.__post_init__()
        from .play_history import play_record
        play = play_record(game._state, work.play_id)
        from .held_opponent_copies import freeze_play
        test = BattlecryRecord(len(game._state.battlecry_history)+1, play.source_id, work.player_id,
            play.card_id, game._state.turn, game._state.action_number, body_target(play, work.payload, 'battlecry'), play.id,
            work.payload, work.batch_id, work.repeat_index, outcome_id=work.outcome_id, iteration=work.iteration,
            held_opponent_copy=freeze_play(game._state, game.registry, play, work.payload))
        validate_record(game._state, game.registry, test)
        key = (work.play_id, work.payload.ability_id, work.outcome_id, work.iteration, work.repeat_index)
        if key in starts or any((b.play_id,b.payload.ability_id,b.outcome_id,b.iteration,b.repeat_index)==key for b in game._state.battlecry_history):
            raise ValueError('Duplicate queued Battlecry activation')
        starts.add(key)
        if not any(type(w) is FinishPlay and w.play_id == play.id for w in queue[index+1:]):
            raise ValueError('Queued Battlecry lost its enclosing play')


def register(mechanics):
    from .battlecry_sources import register as register_sources
    register_sources(mechanics)
    from .battlecry_repeats import register as register_repeats
    register_repeats(mechanics)
    mechanics.register(BeginBattlecry, begin)
    mechanics.register(FinishBattlecry, finish)
