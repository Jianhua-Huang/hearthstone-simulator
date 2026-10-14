"""Finite original main-deck size rules, separate from battle effects.

Starting-health bodies use the existing opening hooks and stat effects. This
module neither replaces the submitted deck nor executes a second opening.
"""
from dataclasses import dataclass

from .model import CardClass, CardType, Rarity

VERSION = 'deck-size-v1'


@dataclass(frozen=True)
class DeckSizeRule:
    source_card_id: str
    deck_size: int
    version: str = VERSION

    def __post_init__(self):
        from .construction import integer, name
        name(self.source_card_id, 'deck-size source')
        integer(self.deck_size, 'original main-deck size', 8)
        if type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported original deck-size policy')


def validate_rules(registry):
    for cid, rule in registry.deck_size_rules.items():
        if type(rule) is not DeckSizeRule or rule.source_card_id != cid:
            raise ValueError('Deck-size rule differs from its registered source')
        rule.__post_init__()
        card = registry.card(cid)
        meta = card.metadata
        if (card.kind != CardType.MINION or meta is None or not meta.collectible or
                meta.rarity != Rarity.LEGENDARY):
            raise ValueError('Deck-size source requires a reviewed collectible Legendary minion')


def main_sources(deck, registry):
    """Only physical slots of the submitted original main deck are sources."""
    return tuple(registry.deck_size_rules[cid] for cid in deck.cards if cid in registry.deck_size_rules)


def active_rule(deck, registry, policy):
    sources = main_sources(deck, registry)
    if len(sources) != 1:
        return None
    rule = sources[0]
    if rule.source_card_id not in policy.allowed_card_ids or rule.source_card_id in policy.banned_card_ids:
        return None
    meta = registry.card(rule.source_card_id).metadata
    if CardClass.NEUTRAL not in meta.classes and deck.card_class not in meta.classes:
        return None
    return rule


def expected_size(deck, registry, policy):
    rule = active_rule(deck, registry, policy)
    return policy.deck_size if rule is None else rule.deck_size


def validate_boundary(game):
    # Original setup remains the qualification even after drawing, playing or
    # losing the source. Never derive construction from the current zones.
    if not game.registry.deck_size_rules or game._match_setup is None:
        return
    for player_id, deck in enumerate(game._match_setup.decks, 1):
        player = game._state.players[player_id]
        if (player.deck_class, player.runes, player.original_deck) != (deck.card_class, deck.runes, deck.cards):
            raise ValueError('Deck-size origin differs from its original class, runes or main deck')
