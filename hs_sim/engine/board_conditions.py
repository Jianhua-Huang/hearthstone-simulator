"""Finite board-capacity conditions evaluated against the actual rules."""
from dataclasses import dataclass

from .effects import Effect, _player, _source
from .zones import source_exists


@dataclass(frozen=True)
class IfBoardFull(Effect):
    player_id: int
    on_full: tuple[Effect, ...]
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if type(self.on_full) is not tuple or any(not isinstance(e,Effect) for e in self.on_full):
            raise ValueError('Board-full branch requires immutable public effects')


def evaluate(r,effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    # Board slots include inactive minions and locations. Do not replace the
    # real capacity with the usual printed value seven or a live-minion count.
    return effect.on_full if len(r.player(effect.player_id).board) >= r.rules.max_board else ()


def register(mechanics):
    mechanics.register(IfBoardFull,evaluate)
