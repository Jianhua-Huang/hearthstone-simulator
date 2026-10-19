"""Put an original deck Aura into play without inventing a spell cast."""
from dataclasses import dataclass

from .aura_duration import aura_spec
from .effects import Effect, _integer, _player
from .model import Zone
from .zones import CardReference, reference_entity, reference_value, source_exists


@dataclass(frozen=True)
class PutStoredAura(Effect):
    card: CardReference
    player_id: int
    source_id: int

    def __post_init__(self):
        reference_value(self.card); _player(self.player_id)
        _integer(self.source_id, 'original Aura entry source', 1)
        if self.card.zone != Zone.DECK or self.card.player_id != self.player_id:
            raise ValueError('Direct Aura entry requires its original beneficiary deck card')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        source = state.entities.get(self.source_id)
        target = state.entities.get(self.card.entity_id)
        if source is None or target is None or self.card.zone_epoch > target.zone_epoch:
            raise ValueError('Direct Aura entry lost its original source or physical residence')
        aura_spec(registry, self.card.card_id)


def put(r, effect):
    from .player_effects import AddPlayerEffect, add, timed_count
    from .secrets import area_count
    from .spell_auras import memory_id
    effect.validate_in_state(r.state, r.registry)
    source_exists(r, effect.source_id)
    entity = reference_entity(r, effect.card)
    if entity is None:
        return ()
    spec = aura_spec(r.registry, entity.card_id)
    player = r.player(effect.player_id)
    # A full area neither consumes nor reveals the hidden original card.
    if timed_count(player, r.registry) >= r.rules.max_ongoing_effects or area_count(player, r.registry) >= r.rules.max_secret_zone:
        return ()
    grants = tuple(a for a in entity.abilities if a.kind == 'aura_duration_bonus')
    original_memory = memory_id(entity)
    r.move(entity, Zone.GRAVEYARD)
    # Installation and publication are atomic; its ordinary reactions then run
    # before the next captured physical card in the caller's effect tuple.
    add(r, AddPlayerEffect(effect.player_id, spec.id, entity.id,
        spell_aura_id=original_memory, aura_duration_grants=grants))
    return ()


def register(mechanics):
    mechanics.register(PutStoredAura, put)
