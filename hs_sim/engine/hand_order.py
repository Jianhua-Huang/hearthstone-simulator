"""Randomize one current physical hand through the ordinary reorder commit."""
from dataclasses import dataclass

from .effects import Effect, _player, _source
from .errors import ResolutionError
from .model import Zone
from .zones import ReorderZone, reorder_zone, source_exists


@dataclass(frozen=True)
class ShuffleHand(Effect):
    player_id: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _source(self.source_id)


def shuffle_hand(r, effect):
    effect.__post_init__()
    source_exists(r, effect.source_id)
    hand = tuple(r.player(effect.player_id).hand)
    if len(hand) != len(set(hand)):
        raise ResolutionError('Hand shuffle requires distinct original physical cards')
    for eid in hand:
        entity = r.state.entities[eid]
        if ((entity.zone, entity.controller) != (Zone.HAND, effect.player_id) or
                not r.registry.card(entity.card_id).hand_playable):
            raise ResolutionError('Hand shuffle lost its complete original allocation')
    order = list(hand)
    if len(order) > 1:
        # Identity permutations are valid. Retiring handles must not reveal
        # whether a hidden random permutation happened to leave a card in place.
        r.game._rng.shuffle(order)
        if r.game._information is not None:
            for eid in hand:
                r.game._information.conceal(eid)
    # Commit before capturing reactions. There is no intervening resolution
    # window in which another hand could replace the sampled physical members.
    return reorder_zone(r, ReorderZone(effect.player_id, Zone.HAND, tuple(order)), source_id=effect.source_id)


def register(mechanics):
    mechanics.register(ShuffleHand, shuffle_hand)
