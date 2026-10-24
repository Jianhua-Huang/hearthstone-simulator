"""Independent extra/skip-turn scheduling; normal start and end stay in resolver.

Queued turns are accepted FIFO and preserve the ordinary successor that was
interrupted. A skipped slot is consumed without creating a real own interval.
Unverified mixed-source ordering remains an explicit prototype policy.
"""
from dataclasses import dataclass, replace

from .effects import Effect
from .errors import ResolutionError, ResolutionLimitExceeded


def _player(value):
    if type(value) is not int or value not in (1, 2):
        raise ValueError('Turn scheduling requires player 1 or 2')


def _source(value):
    if value is not None and (type(value) is not int or value < 1):
        raise ValueError('Turn scheduling source must be an entity ID')


@dataclass(frozen=True)
class QueueTurns(Effect):
    players: tuple[int, ...]
    source_id: int | None = None

    def __post_init__(self):
        if type(self.players) is not tuple or not self.players:
            raise ValueError('QueueTurns requires a nonempty immutable sequence')
        for player in self.players:
            _player(player)
        _source(self.source_id)


@dataclass(frozen=True)
class SkipTurns(Effect):
    player_id: int
    count: int = 1
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        if type(self.count) is not int or self.count < 1:
            raise ValueError('SkipTurns count must be a positive integer')
        _source(self.source_id)


def _admit(r, effect):
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Turn scheduling source does not exist')
    if not r.state.owner_turn_history or r.state.owner_turn_history[-1].closed:
        raise ResolutionError('Turn scheduling requires a genuinely started turn')


def queue_turns(r, effect):
    _admit(r, effect)
    schedule = r.state.turn_schedule
    if len(schedule.pending) + len(effect.players) > r.rules.max_turns:
        raise ResolutionLimitExceeded('Engineering queued-turn budget exhausted; action rolled back')
    r.state.turn_schedule = replace(schedule, pending=(*schedule.pending, *effect.players),
        resume_player_id=schedule.resume_player_id or 3 - r.state.active_player)
    r.emit('turns_scheduled', source_id=effect.source_id, players=effect.players)


def skip_turns(r, effect):
    _admit(r, effect)
    schedule = r.state.turn_schedule
    counts = list(schedule.skip_counts)
    counts[effect.player_id - 1] += effect.count
    if sum(counts) > r.rules.max_turns:
        raise ResolutionLimitExceeded('Engineering skipped-turn budget exhausted; action rolled back')
    r.state.turn_schedule = replace(schedule, skip_counts=tuple(counts))
    r.emit('skip_turns_scheduled', source_id=effect.source_id,
           player_id=effect.player_id, amount=effect.count)


def take_next_slot(state):
    """Consume exactly one slot, allowing its skip reactions to settle separately."""
    schedule = state.turn_schedule
    queued = bool(schedule.pending)
    player = schedule.pending[0] if queued else schedule.resume_player_id or 3 - state.active_player
    counts = list(schedule.skip_counts)
    skipped = counts[player - 1] > 0
    if skipped:
        counts[player - 1] -= 1
    state.turn_schedule = replace(schedule,
        pending=schedule.pending[1:] if queued else (),
        controlled_slots=tuple((index-1,identity) for index,identity in schedule.controlled_slots if index>0),
        resume_player_id=schedule.resume_player_id if queued else (3 - player if skipped else None),
        skip_counts=tuple(counts))
    return player, skipped


def validate_boundary(game):
    state, rules = game._state, game.ruleset
    schedule = state.turn_schedule
    if len(schedule.pending) > rules.max_turns or sum(schedule.skip_counts) > rules.max_turns:
        raise ValueError('Turn schedule exceeds its engineering budget')
    if not state.owner_turn_history and (schedule.pending or schedule.resume_player_id is not None or any(schedule.skip_counts)):
        raise ValueError('A turn schedule cannot precede the first actual turn')


def register(mechanics):
    mechanics.register(QueueTurns, queue_turns)
    mechanics.register(SkipTurns, skip_turns)
