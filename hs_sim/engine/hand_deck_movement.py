"""Finite selectors and recipes over the existing physical zone writers."""
from dataclasses import dataclass

from .costs import quote_unselected_cost
from .deck_shuffles import ShuffleDeckCards
from .effects import Effect, _player, _source
from .model import Zone
from .zones import CardReference, MoveCard, source_exists


@dataclass(frozen=True)
class ShuffleLowestCostHandCard(Effect):
    player_id: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)


def shuffle_lowest(r, request):
    request.__post_init__(); source_exists(r, request.source_id)
    cards = tuple(CardReference.capture(r.state.entities[eid]) for eid in r.player(request.player_id).hand)
    if not cards:
        return ()
    prices = tuple(quote_unselected_cost(r.state, r.registry, r.state.entities[c.entity_id]).amount
        for c in cards)
    lowest = min(prices)
    tied = tuple(card for card, price in zip(cards, prices) if price == lowest)
    selected = tied[0] if len(tied) == 1 else r.game._rng.choice(tied)
    return (ShuffleDeckCards(request.player_id, request.player_id, (
        MoveCard(selected, request.player_id, Zone.DECK, 'random', source_id=request.source_id),),
        request.source_id),)


def exchange_bottom(context):
    """Reuse the original Finley recipe, including its per-move admission policy.

    Both groups are captured before movement. Current hand order determines
    bottom depth; this is not Draw, shuffle, or an atomic capacity exemption.
    """
    player = context.state.players[context.player_id]
    held = tuple(CardReference.capture(context.state.entities[eid]) for eid in player.hand)
    count = min(len(held), len(player.deck))
    selected = tuple(CardReference.capture(context.state.entities[eid])
        for eid in reversed(player.deck[-count:])) if count else ()
    return tuple(MoveCard(card, player.id, Zone.DECK, source_id=context.source_id)
        for card in reversed(held)) + tuple(MoveCard(card, player.id, Zone.HAND,
        source_id=context.source_id) for card in selected)


def register(mechanics):
    mechanics.register(ShuffleLowestCostHandCard, shuffle_lowest)
