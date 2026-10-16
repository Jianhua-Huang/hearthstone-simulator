"""Explicit bounded infinity health policy; ordinary health arithmetic is unchanged.

The int32 limit is an internal policy awaiting CN calibration, not the client's
one-million display threshold. All delivery still uses the shared health batch.
"""
from dataclasses import dataclass
from .effects import Damage, Effect, _integer
from .errors import ResolutionError
from .model import CardType, DamageKind
from .sacrifice import MinionReference, live_minion, reference_value

INFINITE_HEALTH_POLICY = 'saturated-positive-int32-v1'
INFINITE_HEALTH_VALUE = (1 << 31) - 1


@dataclass(frozen=True)
class InfiniteDamageMinion(Effect):
    minion: MinionReference
    source_id: int
    on_result: str | None = None

    def __post_init__(self):
        reference_value(self.minion)
        _integer(self.source_id, 'infinite SPELL source', 1)
        Damage(self.minion.entity_id, INFINITE_HEALTH_VALUE, self.source_id,
               DamageKind.SPELL, self.on_result).__post_init__()


@dataclass(frozen=True)
class RandomInfiniteDamageMinion(Effect):
    candidates: tuple[MinionReference, ...]
    source_id: int
    on_result: str | None = None

    def __post_init__(self):
        _integer(self.source_id, 'infinite SPELL source', 1)
        if type(self.candidates) is not tuple:
            raise ValueError('Infinite damage requires immutable original minion candidates')
        for ref in self.candidates:
            InfiniteDamageMinion(ref, self.source_id, self.on_result).__post_init__()
        if len({ref.entity_id for ref in self.candidates}) != len(self.candidates):
            raise ValueError('A physical infinite-damage candidate has one weight')
        Damage(1, INFINITE_HEALTH_VALUE, self.source_id, DamageKind.SPELL, self.on_result).__post_init__()


def validate_source(r, request):
    source = r.state.entities.get(request.source_id)
    if source is None or r.registry.card(source.card_id).kind != CardType.SPELL:
        raise ResolutionError('Infinite damage requires its actual allocated SPELL source')
    if request.on_result is not None: r.registry.behavior(request.on_result)


def eligible(r, ref):
    card = r.registry.card(ref.card_id)
    if card.kind != CardType.MINION or card.interactable is not None:
        raise ResolutionError('Infinite minion damage requires an original ordinary minion')
    return live_minion(r.state, ref)


def deliver(r, request):
    from .resolver import settle_health_batch
    request.__post_init__(); validate_source(r, request)
    target = eligible(r, request.minion)
    if target is None:
        r.stale(request, request.minion.entity_id); return ()
    instruction = Damage(target.id, INFINITE_HEALTH_VALUE, request.source_id, DamageKind.SPELL, request.on_result)
    return settle_health_batch(r, (instruction,), numeric_limit=INFINITE_HEALTH_VALUE)


def choose(r, request):
    request.__post_init__(); validate_source(r, request)
    candidates = tuple(sorted((ref for ref in request.candidates if eligible(r, ref) is not None),
                              key=lambda ref: ref.entity_id))
    if not candidates:
        r.emit('random_choice_skipped', source_id=request.source_id, reason='no_candidates'); return ()
    selected = candidates[0] if len(candidates) == 1 else r.game._rng.choice(candidates)
    if len(candidates) > 1:
        r.emit('random_choice', source_id=request.source_id, target_id=selected.entity_id,
               candidates=tuple(ref.entity_id for ref in candidates))
    return (InfiniteDamageMinion(selected, request.source_id, request.on_result),)


def register(mechanics):
    mechanics.register(InfiniteDamageMinion, deliver)
    mechanics.register(RandomInfiniteDamageMinion, choose)
