"""Quota-preserving physical hand redistribution without a fictitious empty hand."""
from dataclasses import dataclass

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .hand_history import enter_hand
from .lifecycle import renew_hand_progress
from .model import Zone
from .zones import source_exists


@dataclass(frozen=True)
class ShuffleHandsTogether(Effect):
    player_id: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.source_id, 'joint hand shuffle source', 1)


def mixed_order(rng, left, right):
    """Uniform physical permutations conditional on the documented guarantees.

    The exact official sampling algorithm is not known. Rejection preserves
    uniformity among the permitted permutations, rather than forcing one swap
    after sampling and thereby biasing some allocations.
    """
    original = left + right
    if len(original) < 2:
        return original
    own = set(left)
    while True:
        mixed = list(original)
        rng.shuffle(mixed)
        if left and right and set(mixed[:len(left)]) == own:
            continue
        if tuple(mixed) != original:
            return tuple(mixed)


def shuffle_hands(r, effect):
    effect.__post_init__()
    source_exists(r, effect.source_id)
    players = (r.player(effect.player_id), r.player(3 - effect.player_id))
    before = tuple(tuple(player.hand) for player in players)
    original = before[0] + before[1]
    if len(set(original)) != len(original):
        raise ResolutionError('Joint hands require distinct original physical cards')
    for player, hand in zip(players, before):
        for eid in hand:
            entity = r.state.entities[eid]
            if (entity.zone, entity.controller) != (Zone.HAND, player.id):
                raise ResolutionError('Joint hand shuffle lost its original allocation')
            if not r.registry.card(entity.card_id).hand_playable:
                raise ResolutionError('Joint hands require complete playable card definitions')
    mixed = mixed_order(r.game._rng, *before)
    if mixed == original:
        return
    after = (mixed[:len(before[0])], mixed[len(before[0]):])
    transferred = []
    # Commit both complete allocations before publishing any ordinary event.
    # Quotas reserve the existing occupied slots: two full hands cannot burn
    # one another's incoming cards merely because one side is processed first.
    for player, hand in zip(players, after):
        player.hand[:] = hand
        for eid in hand:
            entity = r.state.entities[eid]
            if entity.controller == player.id:
                continue  # Retained cards neither leave nor acquire a new entry.
            entity.controller = player.id
            entity.zone_epoch += 1
            renew_hand_progress(r.state, entity, previous_zone=Zone.HAND, hand_transfer=True)
            enter_hand(r.state, entity, Zone.HAND, 'move', source_id=effect.source_id)
            transferred.append((player.id, eid))
    # Randomized hidden positions retire tracking for every participating card,
    # including those which happen to stay with their previous controller.
    if r.game._information is not None:
        for eid in original:
            r.game._information.conceal(eid)
    # A first acquisition notification invokes the existing continuous mirror
    # synchronization for the whole completed allocation before trigger capture.
    for player_id, eid in transferred:
        r.emit('card_moved_to_hand', source_id=effect.source_id, target_id=eid, player_id=player_id)
        from .hand_history import publish as publish_hand_entry
        publish_hand_entry(r, r.state.entities[eid].hand_entry_id)
    for player in players:
        r.emit('hand_reordered', source_id=effect.source_id, player_id=player.id)


def register(mechanics):
    mechanics.register(ShuffleHandsTogether, shuffle_hands)
