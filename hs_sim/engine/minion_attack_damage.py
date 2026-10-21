"""Original friendly minion residences each deliver ordinary ability damage.

The finite board-order inventory is accepted once. Each surviving original
friendly participant reads its current Attack and current enemy domain at its
own leg; ordinary random damage and reactions finish before the next leg.
These timing/control policies remain explicit local choices pending CN checks.
"""
from dataclasses import dataclass, replace

from .board_presence import resolve_board_presence
from .effects import Effect, RandomDamage, _integer, _player
from .model import BoardPresenceReference, CardType, DamageKind, Zone


@dataclass(frozen=True)
class EachMinionDealsAttackDamage(Effect):
    player_id: int
    source_id: int
    remaining: tuple[BoardPresenceReference, ...] | None = None

    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'minion damage sequence source',1)
        if self.remaining is not None:
            if (type(self.remaining) is not tuple or
                    any(type(ref) is not BoardPresenceReference for ref in self.remaining) or
                    len({ref.entity_id for ref in self.remaining}) != len(self.remaining)):
                raise ValueError('Minion damage needs distinct original board residences')
            for ref in self.remaining:ref.__post_init__()

    def validate_in_state(self,state):
        self.__post_init__()
        if self.source_id not in state.entities:
            raise ValueError('Minion damage sequence lost its original source')
        if self.remaining is not None and any(ref.entity_id not in state.entities or
                ref.presence_id >= state.next_order for ref in self.remaining):
            raise ValueError('Minion damage borrowed an unknown or future residence')


def active_minion(r,entity):
    return (entity is not None and entity.kind == CardType.MINION and entity.zone == Zone.BOARD
        and entity.active and entity.health > 0 and not entity.doomed
        and r.registry.card(entity.card_id).interactable is None)


def execute(r,effect):
    effect.validate_in_state(r.state)
    remaining=effect.remaining
    if remaining is None:
        remaining=tuple(BoardPresenceReference.capture(r.state,eid)
            for eid in r.player(effect.player_id).board if active_minion(r,r.state.entities[eid]))
    if not remaining:return()
    ref,*tail=remaining
    continuation=replace(effect,remaining=tuple(tail))
    entity=resolve_board_presence(r.state,ref)
    if not active_minion(r,entity) or entity.controller != effect.player_id:
        r.stale(effect,ref.entity_id)
        return(continuation,)
    enemy=r.player(3-effect.player_id)
    candidates=tuple(eid for eid in (enemy.hero_id,*enemy.board)
        if (candidate:=r.live_character(eid)) is not None and candidate.health > 0 and not candidate.doomed
        and (candidate.kind == CardType.HERO or active_minion(r,candidate)))
    # Zero Attack keeps RandomDamage's ordinary choice/no-damage semantics.
    # The physical participant is the damage source, not the battlecry carrier.
    return(RandomDamage(candidates,entity.attack,entity.id,DamageKind.MINION_ABILITY),continuation)


def register(mechanics):
    mechanics.register(EachMinionDealsAttackDamage,execute)
