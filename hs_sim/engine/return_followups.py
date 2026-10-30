"""Guarded original-minion returns, using the existing return/death executor."""
from dataclasses import dataclass
from .effects import Effect, ReturnToHand, _source
from .errors import ResolutionError
from .model import CardType, CostSpec, Zone
from .sacrifice import MinionReference, live_minion, reference_value


@dataclass(frozen=True)
class ReturnCapturedMinion(Effect):
    minion: MinionReference
    source_id: int | None = None
    to_owner: bool = False
    cost: CostSpec | None = None
    on_success: tuple[Effect, ...] = ()
    expires_turn: int | None = None

    def __post_init__(self):
        reference_value(self.minion); _source(self.source_id)
        ReturnToHand(self.minion.entity_id, self.to_owner, self.cost, expires_turn=self.expires_turn).__post_init__()
        if type(self.on_success) is not tuple or any(not isinstance(x, Effect) for x in self.on_success):
            raise ValueError('Successful return requires immutable typed continuation effects')
        for effect in self.on_success:
            validate = getattr(effect, '__post_init__', None)
            if validate is not None: validate()


@dataclass(frozen=True)
class RandomReturnCapturedMinion(Effect):
    candidates: tuple[MinionReference, ...]
    source_id: int | None = None
    cost: CostSpec | None = None

    def __post_init__(self):
        _source(self.source_id)
        if type(self.candidates) is not tuple:
            raise ValueError('Random return requires an immutable original candidate list')
        for ref in self.candidates:
            reference_value(ref)
        if len({ref.entity_id for ref in self.candidates}) != len(self.candidates):
            raise ValueError('Random return cannot weight the same physical minion twice')
        if self.cost is not None:
            if type(self.cost) is not CostSpec: raise ValueError('Random return requires typed original cost')
            self.cost.__post_init__()


def validate_source(r, source_id):
    if source_id is not None and source_id not in r.state.entities:
        raise ResolutionError('Captured return source does not exist')


def eligible(r, ref):
    card = r.registry.card(ref.card_id)
    if card.kind != CardType.MINION:
        raise ResolutionError('Captured return requires an original registered minion face')
    entity = live_minion(r.state, ref)
    return entity if card.interactable is None else None


def return_captured(r, effect):
    from .resolver import return_to_hand
    effect.__post_init__(); validate_source(r, effect.source_id)
    entity = eligible(r, effect.minion)
    if entity is None:
        r.stale(effect, effect.minion.entity_id)
        return ()
    destination = entity.owner if effect.to_owner else entity.controller
    return_to_hand(r, ReturnToHand(entity.id, effect.to_owner, effect.cost, expires_turn=effect.expires_turn))
    # The original return handler either moves this physical minion successfully,
    # or leaves it on board for the ordinary full-hand death checkpoint.
    return effect.on_success if entity.zone == Zone.HAND and entity.controller == destination else ()


def random_return_captured(r, effect):
    effect.__post_init__(); validate_source(r, effect.source_id)
    candidates = tuple(sorted((ref for ref in effect.candidates if eligible(r, ref) is not None),
                              key=lambda ref: ref.entity_id))
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_candidates')
        return ()
    selected = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=effect.source_id, target_id=selected.entity_id,
           candidates=tuple(ref.entity_id for ref in candidates))
    return (ReturnCapturedMinion(selected, effect.source_id, cost=effect.cost),)


def register(mechanics):
    mechanics.register(ReturnCapturedMinion, return_captured)
    mechanics.register(RandomReturnCapturedMinion, random_return_captured)
