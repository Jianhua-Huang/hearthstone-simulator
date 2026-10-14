"""Dormancy lifecycle and serializable countdown work (provisional R-040/041)."""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _source
from .errors import ResolutionError
from .lifecycle import active_abilities, attachment_id
from .model import CardType, DormancyState, Zone


@dataclass(frozen=True)
class MakeDormant(Effect):
    target_id: int
    turns: int | None
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _source(self.source_id)
        if self.turns is not None:
            _integer(self.turns, 'turns', 1)


@dataclass(frozen=True)
class AwakenMinion(Effect):
    target_id: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _source(self.source_id)


@dataclass(frozen=True)
class AdvanceDormancy(Effect):
    target_id: int
    turns: int = 1
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.turns, 'turns', 1)
        _source(self.source_id)


@dataclass(frozen=True)
class TickDormancy(Effect):
    target_id: int
    dormancy_id: int
    player_id: int

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.dormancy_id, 'dormancy_id', 1)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid countdown player')


def _target(r, effect, *, dormant):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Dormancy effect source does not exist')
    entity = r.state.entities.get(effect.target_id)
    if (entity is None or entity.zone != Zone.BOARD or entity.starship_building or
            (entity.dormancy is not None) != dormant):
        r.stale(effect, effect.target_id)
        return None
    if entity.kind != CardType.MINION:
        raise ResolutionError('Dormancy requires a minion')
    if not dormant and (entity.doomed or entity.health <= 0):
        r.stale(effect, entity.id)
        return None
    return entity


def make_dormant(r, effect):
    entity = _target(r, effect, dormant=False)
    if entity is None:
        return
    entity.dormancy = DormancyState(attachment_id(r.state), effect.turns, r.state.turn)
    r.refresh_auras()
    r.emit('minion_dormant', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller, remaining_turns=effect.turns)


def awaken(r, effect):
    entity = _target(r, effect, dormant=True)
    if entity is None:
        return
    if entity.dormancy.permanent:
        r.stale(effect, entity.id)
        return
    entity.dormancy = None
    # Awakening grants no new entity, summon, battlecry, or attack allowance.
    entity.summoned_turn = r.state.turn
    r.refresh_auras()
    event = r.emit('minion_awakened', source_id=effect.source_id, target_id=entity.id,
                   player_id=entity.controller)
    return [r.call(a.behavior_id, entity.id, entity.controller, event=event)
            for a in active_abilities(entity, 'on_awaken')]


def advance(r, effect):
    entity = _target(r, effect, dormant=True)
    if entity is None:
        return
    remaining = entity.dormancy.remaining_turns
    if remaining is None:
        return
    if effect.turns >= remaining:
        # Transition now, so a countdown reaction cannot accidentally awaken a
        # newly installed dormancy instance using an old queued AwakenMinion.
        return awaken(r, AwakenMinion(entity.id, effect.source_id))
    entity.dormancy = replace(entity.dormancy, remaining_turns=remaining - effect.turns)
    r.emit('dormancy_progressed', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller, remaining_turns=entity.dormancy.remaining_turns)


def tick(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if (entity is None or entity.zone != Zone.BOARD or entity.controller != effect.player_id or
            entity.dormancy is None or entity.dormancy.id != effect.dormancy_id):
        return
    return advance(r, AdvanceDormancy(entity.id))


def turn_countdowns(r, player):
    # Freeze eligibility before turn-start callbacks. New or replaced dormancy
    # instances in those callbacks wait until a later controller turn.
    return [TickDormancy(i, r.state.entities[i].dormancy.id, player.id)
            for i in r.rules.entity_order(r.state, player.board)
            if r.state.entities[i].dormancy is not None and
            r.state.entities[i].dormancy.remaining_turns is not None]


def register_dormancy(mechanics):
    for kind, handler in ((MakeDormant, make_dormant), (AwakenMinion, awaken),
                          (AdvanceDormancy, advance), (TickDormancy, tick)):
        mechanics.register(kind, handler)
