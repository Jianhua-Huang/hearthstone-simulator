"""Atomic enemy character maximum-health theft to the player's current hero.

Ordinary minion debuffs use the existing Buff lifecycle; permanent hero changes
use the existing maximum-health projection. No damage/healing packet is made.
"""
from dataclasses import dataclass
from .effects import Buff, Effect, _integer, _player
from .errors import ResolutionError
from .health_loss import StealHeroHealth, adjust_max_health, current_living_hero, steal_hero_health
from .model import CardType, Zone
from .sacrifice import MinionReference, live_minion, reference_value


def reference_id(reference):
    if type(reference) is int:
        _integer(reference, 'physical hero donor', 1)
        return reference
    reference_value(reference)
    return reference.entity_id


@dataclass(frozen=True)
class StealHealthToHero(Effect):
    player_id: int
    donor: MinionReference | int
    amount: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        reference_id(self.donor)
        _integer(self.amount, 'stolen maximum health', 0)
        _integer(self.source_id, 'health theft source', 1)


@dataclass(frozen=True)
class RandomStealHealthToHero(Effect):
    player_id: int
    candidates: tuple[MinionReference | int, ...]
    amount: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'stolen maximum health', 0)
        _integer(self.source_id, 'health theft source', 1)
        if type(self.candidates) is not tuple:
            raise ValueError('Health theft requires immutable original candidates')
        ids = [reference_id(ref) for ref in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError('Each physical health donor has one random weight')


def eligible(r, player_id, reference):
    if type(reference) is MinionReference:
        card = r.registry.card(reference.card_id)
        if card.kind != CardType.MINION or card.interactable is not None:
            raise ResolutionError('Health donor must be an ordinary original minion')
        target = live_minion(r.state, reference)
    else:
        target = r.state.entities.get(reference)
        if target is not None and target.kind != CardType.HERO:
            raise ResolutionError('Integer health donor must be a physical hero')
        if target is not None and (target.zone != Zone.HERO or not target.active or target.health <= 0
                or target.doomed or r.player(target.controller).hero_id != target.id):
            target = None
    return target if target is not None and target.controller != player_id else None


def validate_source(r, request):
    from .resolver import validate_attachment_source
    request.__post_init__()
    validate_attachment_source(r, request.source_id, None)


def deliver(r, request):
    from .resolver import buff
    validate_source(r, request)
    donor = eligible(r, request.player_id, request.donor)
    recipient = current_living_hero(r, request.player_id)
    if donor is None or recipient is None:
        r.stale(request, reference_id(request.donor)); return ()
    if donor.kind == CardType.HERO:
        return steal_hero_health(r, StealHeroHealth(request.player_id, donor.controller,
                                                  request.amount, request.source_id))
    amount = min(request.amount, max(0, donor.max_health))
    if not amount:
        return ()
    # Commit recipient first without publishing. Buff then commits the donor;
    # its first emitted event already observes both final values. The shared
    # scheduler performs deaths/reactions after this complete effect returns.
    events = adjust_max_health(r, recipient, amount, request.source_id, 'preserve_missing')
    buff(r, Buff(donor.id, health=-amount, source_id=request.source_id))
    for kind, data in events:
        r.emit(kind, **data)
    return ()


def choose(r, request):
    validate_source(r, request)
    candidates = tuple(sorted((ref for ref in request.candidates
                               if eligible(r, request.player_id, ref) is not None), key=reference_id))
    if not candidates or not request.amount:
        r.emit('random_choice_skipped', source_id=request.source_id,
               reason='no_candidates' if not candidates else 'zero_amount')
        return ()
    selected = candidates[0] if len(candidates) == 1 else r.game._rng.choice(candidates)
    if len(candidates) > 1:
        r.emit('random_choice', source_id=request.source_id, target_id=reference_id(selected),
               candidates=tuple(reference_id(ref) for ref in candidates))
    return (StealHealthToHero(request.player_id, selected, request.amount, request.source_id),)


def register(mechanics):
    mechanics.register(StealHealthToHero, deliver)
    mechanics.register(RandomStealHealthToHero, choose)
