"""Reorder one complete physical deck by its original local costs."""
from dataclasses import dataclass
from .costs import local_cost
from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import Zone
from .zones import ReorderZone, reorder_zone, source_exists


@dataclass(frozen=True)
class OrderDeckByCost(Effect):
    player_id: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'deck order source', 1)


def order(r, request):
    request.__post_init__(); source_exists(r, request.source_id)
    original = tuple(r.player(request.player_id).deck)
    if len(set(original)) != len(original):
        raise ResolutionError('Deck order needs its complete unique physical inventory')
    tiers = {}
    for eid in original:
        entity = r.state.entities[eid]
        r.registry.card(entity.card_id)
        if (entity.zone, entity.controller) != (Zone.DECK, request.player_id):
            raise ResolutionError('Deck order lost an original own-deck residence')
        tiers.setdefault(max(0, local_cost(entity)[0]), []).append(eid)
    ordered = []
    for cost in sorted(tiers, reverse=True):
        entries = tiers[cost]
        if len(entries) > 1:
            r.game._rng.shuffle(entries)
        ordered.extend(entries)
    for eid in original:
        r.game._information.conceal(eid)
    reorder_zone(r, ReorderZone(request.player_id, Zone.DECK, tuple(ordered)), source_id=request.source_id)
    return ()


def register(mechanics):
    mechanics.register(OrderDeckByCost, order)
