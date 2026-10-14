"""Independent, opt-in Tourist construction eligibility.

A package pins a reviewed finite Perils destination pool. Permissions come from
one native Tourist in the original main deck, never from live entities. Printed
classes, ordinary format filters and battle/generation rules stay unchanged.
"""
from dataclasses import dataclass

from .model import CardClass, CardType, Rarity

VERSION = 'tourist-v1'


@dataclass(frozen=True)
class TouristSpec:
    card_id: str
    destination_class: CardClass
    pool_id: str
    eligible_card_ids: tuple[str, ...]
    version: str = VERSION

    def __post_init__(self):
        from .construction import ids, name
        name(self.card_id, 'Tourist source')
        name(self.pool_id, 'Tourist destination pool')
        if type(self.destination_class) is not CardClass or self.destination_class == CardClass.NEUTRAL:
            raise ValueError('Tourist needs a playable destination class')
        ids(self.eligible_card_ids, 'Tourist destination IDs', unique=True)
        if type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported Tourist policy version')


def validate_specs(registry):
    for card_id, spec in registry.tourists.items():
        if type(spec) is not TouristSpec or spec.card_id != card_id:
            raise ValueError('Tourist declaration differs from its registered key')
        spec.__post_init__()
        card = registry.card(card_id)
        meta = card.metadata
        if (card.kind != CardType.MINION or not card.hand_playable or meta is None or
                not meta.collectible or meta.rarity != Rarity.LEGENDARY or
                len(meta.classes) != 1 or meta.classes[0] in (CardClass.NEUTRAL, spec.destination_class)):
            raise ValueError('Tourist source needs a collectible native Legendary minion of another class')
        for candidate_id in spec.eligible_card_ids:
            candidate = registry.card(candidate_id)
            candidate_meta = candidate.metadata
            if (candidate_id in registry.tourists or not candidate.hand_playable or
                    candidate_meta is None or not candidate_meta.collectible or
                    candidate_meta.rarity is None or spec.destination_class not in candidate_meta.classes):
                raise ValueError('Tourist pool requires reviewed collectible destination cards, excluding Tourists')


def tourist_count(card_ids, registry):
    return sum(card_id in registry.tourists for card_id in card_ids)


def native_tourist(card_class, card_ids, registry, policy=None):
    """No chaining; a banned/rotated source cannot authorize foreign entries."""
    if tourist_count(card_ids, registry) != 1:
        return None
    card_id = next(card_id for card_id in card_ids if card_id in registry.tourists)
    card = registry.card(card_id)
    if card.metadata is None or card.metadata.classes != (card_class,):
        return None
    if policy is not None and (card_id not in policy.allowed_card_ids or card_id in policy.banned_card_ids):
        return None
    return registry.tourists[card_id]


def requires_runes(card_class, card_ids, registry, policy=None):
    if card_class == CardClass.DEATH_KNIGHT:
        return True
    spec = native_tourist(card_class, card_ids, registry, policy)
    return spec is not None and spec.destination_class == CardClass.DEATH_KNIGHT


def validate_boundary(game):
    """The existing saved setup binds original class/loadout, not current hero."""
    if not game.registry.tourists or game._match_setup is None:
        return
    for player_id, deck in enumerate(game._match_setup.decks, 1):
        player = game._state.players[player_id]
        if (player.deck_class, player.runes, player.original_deck) != (deck.card_class, deck.runes, deck.cards):
            raise ValueError('Tourist constructed origin differs from its original class, runes or main deck')
