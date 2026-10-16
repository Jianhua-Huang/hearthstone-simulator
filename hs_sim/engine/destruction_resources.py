"""Resource rewards joined to the original batch's physical destruction causes.

This delegates marking to DestroyBatch and all deaths, reactions, draw and mana
to the existing interpreter. There is no extra death checkpoint or death count.
"""
from dataclasses import dataclass

from .effects import DestroyBatch, Draw, Effect, RefreshMana, _integer, _player
from .model import CardType, DeathCause
from .sacrifice import MinionReference, live_minion, reference_value


@dataclass(frozen=True)
class DestroyMinionsForResources(Effect):
    player_id: int
    source_id: int
    victims: tuple[MinionReference, ...]

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'destruction-resource source', 1)
        if type(self.victims) is not tuple: raise ValueError('Destruction group requires immutable physical victims')
        for ref in self.victims:
            reference_value(ref)
            if ref.player_id != self.player_id or ref.entity_id == self.source_id: raise ValueError('Resource destruction requires original other friendly minions')
        if len({ref.entity_id for ref in self.victims}) != len(self.victims): raise ValueError('Destruction group duplicated a physical victim')


@dataclass(frozen=True)
class CompleteDestroyedResources(Effect):
    original: DestroyMinionsForResources
    first_death_id: int
    accepted: tuple[DeathCause, ...]

    def __post_init__(self):
        if type(self.original) is not DestroyMinionsForResources: raise ValueError('Destruction reward lost its original complete request')
        self.original.__post_init__(); _integer(self.first_death_id, 'original destruction death boundary', 1)
        if type(self.accepted) is not tuple or any(type(row) is not DeathCause for row in self.accepted): raise ValueError('Destruction reward requires original frozen causes')
        order = {ref.entity_id: index for index, ref in enumerate(self.original.victims)}
        previous = -1
        for cause in self.accepted:
            cause.__post_init__()
            if cause.target_id not in order or order[cause.target_id] <= previous: raise ValueError('Destruction reward changed its original ordered victim group')
            ref = self.original.victims[order[cause.target_id]]
            if not matches(cause, ref, self.original): raise ValueError('Destruction reward borrowed another source or incarnation')
            previous = order[cause.target_id]


def matches(cause, ref, original):
    return cause is not None and (
        cause.kind, cause.reason, cause.source_id, cause.target_id, cause.target_card_id,
        cause.target_controller, cause.target_zone_epoch, cause.target_entered_order) == (
        'destroy', 'Destroy', original.source_id, ref.entity_id, ref.card_id,
        ref.player_id, ref.zone_epoch, ref.entered_order)


def original_causes(state, request):
    result = []
    for ref in request.original.victims:
        candidates = [d.cause for d in state.death_history if d.id >= request.first_death_id and matches(d.cause, ref, request.original)]
        current = state.entities[ref.entity_id].death_cause
        if matches(current, ref, request.original) and current not in candidates: candidates.append(current)
        if len(candidates) > 1: raise ValueError('One original physical victim acquired multiple destruction causes')
        result.extend(candidates)
    return tuple(result)


def validate_material(state, registry, request):
    request.__post_init__()
    original = request.original if type(request) is CompleteDestroyedResources else request
    if original.source_id not in state.entities: raise ValueError('Destruction resource source does not exist')
    for ref in original.victims:
        entity = state.entities.get(ref.entity_id)
        if entity is None or registry.card(ref.card_id).kind != CardType.MINION or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
            raise ValueError('Destruction resource group borrowed an unknown or future victim')
    if type(request) is CompleteDestroyedResources:
        if request.first_death_id > state.next_death_id or original_causes(state, request) != request.accepted:
            raise ValueError('Destruction reward differs from its complete original accepted causes')


def begin(r, request):
    from .resolver import destroy_batch
    validate_material(r.state, r.registry, request)
    targets = tuple(ref.entity_id for ref in request.victims if live_minion(r.state, ref) is not None)
    boundary = r.state.next_death_id
    destroy_batch(r, DestroyBatch(targets, request.source_id))
    accepted = tuple(r.state.entities[eid].death_cause for eid in targets)
    result = CompleteDestroyedResources(request, boundary, accepted)
    validate_material(r.state, r.registry, result)
    return (result,)


def finish(r, request):
    validate_material(r.state, r.registry, request)
    count = 0
    for cause in request.accepted:
        dead = any(d.id >= request.first_death_id and d.cause == cause for d in r.state.death_history)
        entity = r.state.entities[cause.target_id]
        deferred = r.death_deferrals > 0 and entity.doomed and entity.death_cause == cause
        count += bool(dead or deferred)
    if not count: return ()
    original = request.original
    return (Draw(original.player_id, count, original.source_id), RefreshMana(original.player_id, count))


def register(mechanics):
    mechanics.register(DestroyMinionsForResources, begin)
    mechanics.register(CompleteDestroyedResources, finish)
