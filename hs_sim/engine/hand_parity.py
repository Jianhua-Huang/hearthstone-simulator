"""Native one-way hand parity upgrades at actual own-hand change publications."""
from dataclasses import dataclass

from .model import CardType, Zone, _name


@dataclass(frozen=True)
class HandParityTransformProfile:
    card_id: str
    transformed_id: str

    def __post_init__(self):
        _name(self.card_id, 'native hand parity source')
        _name(self.transformed_id, 'native hand parity destination')
        if self.card_id == self.transformed_id:
            raise ValueError('Hand parity requires a different one-way destination')


def validate_profile(registry, profile):
    if type(profile) is not HandParityTransformProfile:
        raise ValueError('Native hand parity requires its typed declaration')
    profile.__post_init__()
    source, target = registry.card(profile.card_id), registry.card(profile.transformed_id)
    if (source.kind != CardType.MINION or target.kind != CardType.MINION or
            not source.hand_playable or not target.hand_playable or source.starship_for or target.starship_for or
            source.cost != target.cost):
        raise ValueError('Hand parity requires two ordinary same-cost native minion faces')


def hand_signature(state):
    return tuple(tuple((i, state.entities[i].card_id, state.entities[i].zone_epoch)
        for i in state.players[p].hand) for p in (1, 2))


def synchronize(r, *, initial=False):
    profiles = r.registry.hand_parity_profiles
    if not profiles or r.game._information is None or getattr(r, '_synchronizing_hand_parity', False):
        return
    current = hand_signature(r.state)
    before = r._hand_parity_signature
    r._hand_parity_signature = current
    players = tuple(p for p in (1, 2) if initial or before is None or before[p-1] != current[p-1])
    if not players:
        return
    from .costs import quote_unselected_cost
    from .hand_upgrades import upgrade_face
    from .cross_zone import announce_stored_transform
    accepted = []
    for p in players:
        hand = tuple(r.state.players[p].hand)
        candidates = tuple(r.state.entities[i] for i in hand if r.state.entities[i].card_id in profiles
            and r.state.entities[i].kind == CardType.MINION and not r.state.entities[i].silenced)
        if not candidates:
            continue
        # Quote the complete actual inventory once; source's own price is not
        # part of its condition. Unknown operands remain explicit quote errors.
        needed = {i for source in candidates for i in hand if i != source.id}
        prices = {i: quote_unselected_cost(r.state, r.registry, r.state.entities[i]).amount for i in hand if i in needed}
        for source in candidates:
            parities = {price % 2 for i, price in prices.items() if i != source.id}
            if len(parities) <= 1:
                accepted.append((source, source.card_id, profiles[source.card_id].transformed_id))
    r._synchronizing_hand_parity = True
    try:
        for source, old, target in accepted:
            if source.zone != Zone.HAND:
                raise ValueError('Accepted native hand parity source left its original hand window')
            upgrade_face(r, source, target)
        # Complete the accepted group before its first private notification.
        r._hand_parity_signature = hand_signature(r.state)
        for source, old, _ in accepted:
            announce_stored_transform(r, source, old, source_id=source.id)
    finally:
        r._synchronizing_hand_parity = False
