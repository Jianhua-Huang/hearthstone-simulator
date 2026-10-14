"""A single actual fatigue tick, shared by card effects and empty-deck draws."""
from dataclasses import dataclass

from .effects import Damage, Effect, _behavior, _integer, _player, _source
from .model import DamageKind
from .zones import source_exists


@dataclass(frozen=True)
class TakeFatigue(Effect):
    player_id: int
    source_id: int | None = None
    on_fatigue: str | None = None

    def __post_init__(self):
        _player(self.player_id)
        _source(self.source_id)
        if self.on_fatigue is not None:
            _behavior(self.on_fatigue)
            _integer(self.source_id, 'fatigue callback source', 1)


def advance(r, player_id, *, draw_id=None):
    """Capture the nominal number; prevention does not undo this account tick."""
    player = r.player(player_id)
    _integer(player.fatigue, 'fatigue counter', 0)
    if draw_id is not None:
        _integer(draw_id, 'fatigue draw ID', 1)
    player.fatigue += 1
    data = {} if draw_id is None else {'draw_id': draw_id}
    event = r.emit('fatigue', target_id=player.hero_id, player_id=player.id,
        amount=player.fatigue, **data)
    return Damage(player.hero_id, player.fatigue, kind=DamageKind.FATIGUE), event


def take(r, effect):
    effect.__post_init__()
    source_exists(r, effect.source_id)
    if effect.on_fatigue is not None:
        r.registry.behavior(effect.on_fatigue)
    packet, event = advance(r, effect.player_id)
    if effect.on_fatigue is None:
        return (packet,)
    source = r.state.entities[effect.source_id]
    callback = r.call(effect.on_fatigue, source.id, source.controller,
        target_id=packet.target_id, event=event)
    return (packet, callback)


def register(mechanics):
    mechanics.register(TakeFatigue, take)
