"""Finite native minion pairs, settled by the existing hand lifecycle driver."""
from dataclasses import dataclass

from .construction import ids, name
from .model import CardType, Zone


@dataclass(frozen=True)
class HandCombinationProfile:
    result_card_id: str
    left_card_id: str
    right_card_id: str
    version: str = 'hand-combination-v1'

    def __post_init__(self):
        ids((self.result_card_id, self.left_card_id, self.right_card_id), 'hand combination faces', unique=True)
        name(self.version, 'hand combination policy')
        if self.version != 'hand-combination-v1':
            raise ValueError('Unsupported native hand combination policy')


def validate_profiles(registry):
    seen = set()
    for key, profile in registry.hand_combinations.items():
        if type(profile) is not HandCombinationProfile or profile.result_card_id != key:
            raise ValueError('Hand combination profile differs from its registered result')
        profile.__post_init__()
        for cid in (profile.result_card_id, profile.left_card_id, profile.right_card_id):
            card = registry.card(cid)
            if cid in seen or card.kind != CardType.MINION or not card.hand_playable or card.shatter is not None:
                raise ValueError('Native hand combinations require disjoint ordinary minion faces')
            seen.add(cid)


def next_pair(state, registry):
    for player in state.players.values():
        for key in sorted(registry.hand_combinations):
            profile = registry.hand_combinations[key]
            left = [state.entities[i] for i in player.hand if state.entities[i].card_id == profile.left_card_id]
            right = [state.entities[i] for i in player.hand if state.entities[i].card_id == profile.right_card_id]
            for a in left:
                for b in right:
                    # Either unsilenced half still has its printed combination
                    # text. No invented keyword or counter is attached to it.
                    if not (a.silenced and b.silenced):
                        return player, profile, a, b
    return None


def settle_hands(r, *, initial=False):
    from .shatter import inherit
    while pair := next_pair(r.state, r.registry):
        r.charge()
        player, profile, left, right = pair
        position = min(player.hand.index(left.id), player.hand.index(right.id))
        ordered = tuple(i for i in player.hand if i in (left.id, right.id))
        r.move(left, Zone.GRAVEYARD)
        r.move(right, Zone.GRAVEYARD)
        combined = r.create_entity(player.id, profile.result_card_id, Zone.HAND, position,
            hand_entry_reason='scenario' if initial else 'recombine')
        # Reuse the existing canonical-left attachment/material policy. Its
        # application to the native minion pair remains explicitly CN-pending.
        inherit(r, left, combined)
        r.emit('cards_recombined', source_id=ordered[0], target_id=combined.id,
            player_id=player.id, fragment_ids=ordered)
