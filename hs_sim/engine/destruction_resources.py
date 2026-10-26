"""Resource rewards joined to the original batch's physical destruction causes.

This delegates marking to DestroyBatch and all deaths, reactions, draw and mana
to the existing interpreter. There is no extra death checkpoint or death count.
"""
from dataclasses import dataclass, replace

from .effects import DestroyBatch, Draw, Effect, RefreshMana, _integer, _player
from .model import BoardPresenceReference,CardType, DeathCause, Zone
from .sacrifice import MinionReference, live_minion, reference_value


def _request_fields(request, *, friendly_only):
    _player(request.player_id); _integer(request.source_id, 'destruction-resource source', 1)
    if type(request.victims) is not tuple: raise ValueError('Destruction group requires immutable physical victims')
    for ref in request.victims:
        reference_value(ref)
        if ref.entity_id == request.source_id or friendly_only and ref.player_id != request.player_id:
            raise ValueError('Resource destruction requires original other friendly minions' if friendly_only
                else 'Counted discard destruction requires original other minions')
    if len({ref.entity_id for ref in request.victims}) != len(request.victims):
        raise ValueError('Destruction group duplicated a physical victim')


@dataclass(frozen=True)
class DestroyMinionsForResources(Effect):
    player_id: int
    source_id: int
    victims: tuple[MinionReference, ...]

    def __post_init__(self):
        _request_fields(self, friendly_only=True)


@dataclass(frozen=True)
class DestroyMinionsForDiscard(Effect):
    """Capture both live boards at execution; retain the real Battlecry payer."""
    player_id: int
    source_id: int
    battlecry_id: int
    victims: tuple[MinionReference, ...] | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'counted destruction source', 1)
        _integer(self.battlecry_id, 'counted destruction Battlecry', 1)
        if self.victims is not None: _request_fields(self, friendly_only=False)


@dataclass(frozen=True)
class DestroyMinionsForStats(Effect):
    player_id:int
    source_id:int
    beneficiary:BoardPresenceReference|None
    victims:tuple[MinionReference,...]|None=None

    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'destruction-stat source',1)
        if self.beneficiary is not None:
            if type(self.beneficiary)is not BoardPresenceReference or self.beneficiary.entity_id!=self.source_id:
                raise ValueError('Destruction stat reward requires its original source residence')
            self.beneficiary.__post_init__()
        if self.victims is not None:_request_fields(self,friendly_only=False)


@dataclass(frozen=True)
class CompleteDestroyedResources(Effect):
    original: DestroyMinionsForResources | DestroyMinionsForDiscard | DestroyMinionsForStats
    first_death_id: int
    accepted: tuple[DeathCause, ...]

    def __post_init__(self):
        if type(self.original) not in (DestroyMinionsForResources, DestroyMinionsForDiscard,DestroyMinionsForStats): raise ValueError('Destruction reward lost its original complete request')
        self.original.__post_init__(); _integer(self.first_death_id, 'original destruction death boundary', 1)
        if self.original.victims is None: raise ValueError('Completed destruction lost its accepted original victim group')
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
    if type(original)is DestroyMinionsForStats:
        from .sacrifice import validate_reward_presence
        if original.beneficiary is not None:validate_reward_presence(state,original.beneficiary)
        if original.victims is None:return
    if type(original) is DestroyMinionsForDiscard:
        from .battlecries import battlecry_record
        battlecry = battlecry_record(state, original.battlecry_id)
        if ((battlecry.source_id, battlecry.player_id) != (original.source_id, original.player_id) or
                not battlecry.payload_started or battlecry.failure is not None):
            raise ValueError('Counted discard destruction changed its actual Battlecry source or recipient')
        if original.victims is None: return
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
    if type(request) in (DestroyMinionsForDiscard,DestroyMinionsForStats) and request.victims is None:
        from .cross_zone import MinionScope, minion_references
        scope = MinionScope((Zone.BOARD,), exclude_source=True)
        victims = tuple(ref for p in (1, 2)
            for ref in minion_references(r.state, r.registry, p, scope, request.source_id)
            if r.registry.card(ref.card_id).interactable is None)
        request = replace(request, victims=victims)
        validate_material(r.state, r.registry, request)
    targets = tuple(ref.entity_id for ref in request.victims if live_minion(r.state, ref) is not None)
    boundary = r.state.next_death_id
    destroy_batch(r, DestroyBatch(targets, request.source_id))
    accepted = tuple(r.state.entities[eid].death_cause for eid in targets)
    if type(request)is DestroyMinionsForStats:
        accepted=tuple(cause for ref,cause in zip((ref for ref in request.victims if ref.entity_id in targets),accepted)
            if matches(cause,ref,request))
    result = CompleteDestroyedResources(request, boundary, accepted)
    validate_material(r.state, r.registry, result)
    return (result,)


def finish(r, request):
    validate_material(r.state, r.registry, request)
    count = 0;attack=health=0
    for cause in request.accepted:
        deaths=tuple(d for d in r.state.death_history if d.id>=request.first_death_id and d.cause==cause)
        dead=bool(deaths)
        entity = r.state.entities[cause.target_id]
        deferred = r.death_deferrals > 0 and entity.doomed and entity.death_cause == cause
        count += bool(dead or deferred)
        if type(request.original)is DestroyMinionsForStats:
            if len(deaths)>1:raise ValueError('One original destroyed victim acquired multiple death records')
            if deaths:
                attack+=max(0,deaths[0].attack);health+=max(0,deaths[0].max_health-deaths[0].damage)
            elif deferred:
                attack+=max(0,entity.attack);health+=max(0,entity.health)
    if not count: return ()
    original = request.original
    if type(original)is DestroyMinionsForStats:
        from .sacrifice import BuffCapturedMinion
        return ()if original.beneficiary is None else(BuffCapturedMinion(original.beneficiary,attack,health,original.source_id),)
    if type(original) is DestroyMinionsForDiscard:
        from .zones import DiscardMatching
        return (DiscardMatching(original.player_id, count=count, source_id=original.source_id),)
    return (Draw(original.player_id, count, original.source_id), RefreshMana(original.player_id, count))


def register(mechanics):
    mechanics.register(DestroyMinionsForResources, begin)
    mechanics.register(DestroyMinionsForDiscard, begin)
    mechanics.register(DestroyMinionsForStats,begin)
    mechanics.register(CompleteDestroyedResources, finish)
