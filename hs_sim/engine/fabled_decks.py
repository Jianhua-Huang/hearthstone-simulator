"""Finite Fabled construction bundles, distinct from battle-card behavior.

DeckSpec always contains the complete physical original deck. The optional
builder expands selected collectible roots; ordinary opening then handles all
members. This module adds no effects, entities, shuffle or saved-state fields.
"""
from collections import Counter
from dataclasses import dataclass

from .model import CardClass, CardType, Rarity

VERSION = 'fabled-v2'


@dataclass(frozen=True)
class FabledSpec:
    source_card_id: str
    companion_card_ids: tuple[str, ...]
    version: str = VERSION

    def __post_init__(self):
        from .construction import ids, name
        name(self.source_card_id, 'Fabled root')
        ids(self.companion_card_ids, 'Fabled companions', unique=True)
        if not self.companion_card_ids or self.source_card_id in self.companion_card_ids:
            raise ValueError('Fabled needs distinct companions outside its root')
        if type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported Fabled construction policy')


def validate_specs(registry):
    roots, members = set(registry.fabled), set()
    for cid, spec in registry.fabled.items():
        if type(spec) is not FabledSpec or cid != spec.source_card_id:
            raise ValueError('Fabled declaration differs from its registered root')
        spec.__post_init__()
        card = registry.card(cid)
        meta = card.metadata
        if (card.kind != CardType.MINION or not card.hand_playable or meta is None or
                not meta.collectible or meta.rarity != Rarity.LEGENDARY or
                len(meta.classes) != 1 or meta.classes[0] == CardClass.NEUTRAL):
            raise ValueError('Fabled root requires a collectible native Legendary minion')
        for companion_id in spec.companion_card_ids:
            companion = registry.card(companion_id)
            cm = companion.metadata
            if (companion_id in roots or companion_id in members or
                    not companion.hand_playable or cm is None or cm.collectible or
                    cm.classes != meta.classes):
                raise ValueError('Fabled companions need unique noncollectible native faces')
            members.add(companion_id)


def expand_fabled_cards(card_ids, registry):
    """Build a physical deck from selected collectible IDs, without RNG.

Already expanded lists belong directly in DeckSpec. Accepting a partly expanded
selection here would hide a malformed import, so direct companions are refused.
This does not validate format, class, rune, copy limits or the final deck size.
"""
    from .construction import ids
    ids(card_ids, 'selected deck cards')
    validate_specs(registry)
    companions = {cid for s in registry.fabled.values() for cid in s.companion_card_ids}
    result = []
    for cid in card_ids:
        registry.card(cid)
        if cid in companions:
            raise ValueError('Select the Fabled root; do not select a companion independently')
        result.append(cid)
        spec = registry.fabled.get(cid)
        if spec is not None:
            result.extend(spec.companion_card_ids)
    return tuple(result)


def construction_companions(deck, registry, policy, issue):
    """Only complete native original main-deck bundles grant an exemption."""
    validate_specs(registry)
    counts, permitted = Counter(deck.cards), set()
    for cid, spec in registry.fabled.items():
        if not counts[cid]:
            continue
        if counts[cid] != 1 or any(counts[member] != 1 for member in spec.companion_card_ids):
            issue('fabled_bundle', f'{cid} requires one root and every original companion exactly once', cid)
            continue
        if (cid in policy.allowed_card_ids and cid not in policy.banned_card_ids and
                registry.card(cid).metadata.classes == (deck.card_class,)):
            permitted.update(spec.companion_card_ids)
    # No companion permission is exported to sideboards or unrelated groups.
    for band in deck.sideboards:
        for cid in band.cards:
            if cid in registry.fabled:
                issue('fabled_scope', 'Fabled sideboard roots require a reviewed policy', cid)
    return frozenset(permitted)


def validate_boundary(game):
    if not game.registry.fabled or game._match_setup is None:
        return
    for pid, deck in enumerate(game._match_setup.decks, 1):
        player = game._state.players[pid]
        if (player.deck_class, player.runes, player.original_deck) != (deck.card_class, deck.runes, deck.cards):
            raise ValueError('Fabled origin differs from its original class, runes or complete main deck')
