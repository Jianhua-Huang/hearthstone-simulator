"""Native deckbuilding recipes compiled to ordinary immutable printed minions.

Blueprints, functional templates and cosmetic options are not physical cards.
Only requested, explicitly supported recipes are compiled before registry freeze.
No battle effects or saved entity fields are introduced here.
"""
from dataclasses import asdict, dataclass, fields, replace
import hashlib
import json

from .model import CardClass, CardDefinition, CardMetadata, CardType, Rarity

VERSION = 'modular-v1'
PREFIX = 'modular:'
MODULE_FIELDS = frozenset(('id', 'name', 'kind', 'cost', 'attack', 'health',
    'keywords', 'battlecry', 'deathrattle', 'triggers', 'auras', 'intrinsic_costs', 'board_minion_cost'))


@dataclass(frozen=True)
class ModularProfile:
    source_card_id: str
    name: str
    metadata: CardMetadata
    module_card_ids: tuple[str, ...]
    cosmetic_card_ids: tuple[str, ...]
    version: str = VERSION

    def __post_init__(self):
        from .construction import ids, name
        name(self.source_card_id, 'modular blueprint')
        name(self.name, 'modular printed name')
        if self.source_card_id.startswith(PREFIX):
            raise ValueError('Blueprint cannot occupy the compiled face namespace')
        if type(self.metadata) is not CardMetadata:
            raise ValueError('Modular blueprint requires reviewed CardMetadata')
        self.metadata.__post_init__()
        if (not self.metadata.collectible or self.metadata.rarity != Rarity.LEGENDARY or
                self.metadata.classes != (CardClass.NEUTRAL,) or
                self.metadata.deck_identity not in (None, self.source_card_id) or
                self.metadata.max_copies not in (None, 1)):
            raise ValueError('Native modular blueprint requires one neutral collectible Legendary identity')
        ids(self.module_card_ids, 'functional modules', unique=True)
        ids(self.cosmetic_card_ids, 'cosmetic options', unique=True)
        options = (*self.module_card_ids, *self.cosmetic_card_ids)
        if (len(self.module_card_ids) < 2 or not self.cosmetic_card_ids or
                len(set(options)) != len(options) or self.source_card_id in options or
                any(cid.startswith(PREFIX) for cid in options)):
            raise ValueError('Modular options require disjoint finite functional and cosmetic IDs')
        if type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported modular construction policy')


@dataclass(frozen=True)
class ModularSelection:
    source_card_id: str
    module_card_ids: tuple[str, str]
    cosmetic_card_id: str
    version: str = VERSION

    def __post_init__(self):
        from .construction import ids, name
        name(self.source_card_id, 'modular selected blueprint')
        name(self.cosmetic_card_id, 'modular selected cosmetic')
        ids(self.module_card_ids, 'selected functional modules', unique=True)
        if len(self.module_card_ids) != 2:
            raise ValueError('Native modular construction selects exactly two different functional modules')
        if type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported modular selection policy')
        # The two functional slots have no gameplay order. Canonicalize only
        # their order; retain both exact options and the cosmetic identity.
        object.__setattr__(self, 'module_card_ids', tuple(sorted(self.module_card_ids)))

    @property
    def card_id(self):
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return PREFIX + self.source_card_id + ':' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


def option_ids(registry):
    return {cid for profile in registry.modular_profiles.values() for cid in
        (profile.source_card_id, *profile.module_card_ids, *profile.cosmetic_card_ids)}


def validate_module(registry, card):
    if type(card) is not CardDefinition or card.kind != CardType.MINION:
        raise ValueError('Functional module requires an immutable minion template')
    default = CardDefinition(card.id, card.name, CardType.MINION)
    if any(getattr(card, field.name) != getattr(default, field.name)
           for field in fields(CardDefinition) if field.name not in MODULE_FIELDS):
        raise ValueError('Functional module has an unreviewed declaration field')
    registry._validate_card(card)


def printed_definition(registry, selection):
    from .registry import UnsupportedDefinitionError
    if type(selection) is not ModularSelection:
        raise ValueError('Expected ModularSelection')
    selection.__post_init__()
    profile = registry.modular_profiles.get(selection.source_card_id)
    if profile is None:
        raise UnsupportedDefinitionError('Unsupported modular blueprint: ' + selection.source_card_id)
    if (any(cid not in profile.module_card_ids for cid in selection.module_card_ids) or
            selection.cosmetic_card_id not in profile.cosmetic_card_ids):
        raise ValueError('Selection is outside the reviewed modular options')
    parts = []
    for cid in selection.module_card_ids:
        part = registry.modular_modules.get(cid)
        if part is None:
            raise UnsupportedDefinitionError('Functional module has no executable adapter: ' + cid)
        validate_module(registry, part)
        parts.append(part)
    bodies = {}
    for field in ('battlecry', 'deathrattle'):
        values = tuple(getattr(part, field) for part in parts if getattr(part, field) is not None)
        if len(values) > 1:
            raise UnsupportedDefinitionError('Multiple modular ' + field + ' bodies require a reviewed adapter')
        bodies[field] = values[0] if values else None
    board_costs = tuple(part.board_minion_cost for part in parts if part.board_minion_cost is not None)
    if len(board_costs) > 1:
        raise UnsupportedDefinitionError('Multiple modular board cost declarations require a reviewed adapter')
    return CardDefinition(selection.card_id, profile.name, CardType.MINION,
        cost=sum(part.cost for part in parts), attack=sum(part.attack for part in parts),
        health=sum(part.health for part in parts),
        keywords=tuple(sorted({keyword for part in parts for keyword in part.keywords})),
        board_minion_cost=board_costs[0] if board_costs else None,
        metadata=replace(profile.metadata, deck_identity=profile.source_card_id),
        **bodies, **{field: tuple(value for part in parts for value in getattr(part, field))
                    for field in ('triggers', 'auras', 'intrinsic_costs')})


def assemble_modular_card(registry, selection):
    """Register one complete printed face atomically, returning its physical ID.

The caller puts this ID in the complete DeckSpec.cards. A frozen match cannot
gain new recipes; rebuild the identical declarations for restore or replay.
"""
    registry._require_mutable()
    registry.validate()
    card = printed_definition(registry, selection)
    registry._validate_card(card)
    if card.id in registry.modular_faces:
        if registry.modular_faces[card.id] != selection or registry.card(card.id) != card:
            raise ValueError('Compiled modular face differs from its registered recipe')
        return card.id
    if card.id in registry.cards:
        raise ValueError('Compiled modular identity is already occupied')
    # All validation precedes either mutation. Templates have already passed
    # ordinary reference validation; assembly creates no callback or effect.
    registry._cards[card.id] = card
    registry._modular_faces[card.id] = selection
    return card.id


def validate_profiles(registry):
    reserved = set()
    for cid, profile in registry.modular_profiles.items():
        if type(profile) is not ModularProfile or cid != profile.source_card_id:
            raise ValueError('Modular profile differs from its registered blueprint')
        profile.__post_init__()
        members = {cid, *profile.module_card_ids, *profile.cosmetic_card_ids}
        if reserved & members or members & set(registry.cards):
            raise ValueError('Modular blueprints/options must be unique nonphysical declarations')
        reserved.update(members)
    functional = {cid for profile in registry.modular_profiles.values() for cid in profile.module_card_ids}
    for cid, card in registry.modular_modules.items():
        if cid not in functional or cid != card.id:
            raise ValueError('Module template differs from a registered functional option')
        validate_module(registry, card)
    for cid, selection in registry.modular_faces.items():
        expected = printed_definition(registry, selection)
        if cid != expected.id or registry.cards.get(cid) != expected:
            raise ValueError('Modular printed face differs from its complete original selection')
    if any(cid.startswith(PREFIX) and cid not in registry.modular_faces for cid in registry.cards):
        raise ValueError('Compiled modular face has no original selection')


def construction_identity(registry, card_id):
    """Only authenticated compiled recipes inherit their blueprint's format ID."""
    selection = registry.modular_faces.get(card_id)
    return selection.source_card_id if selection is not None else card_id


def validate_boundary(game):
    setup = game._match_setup
    if setup is None or not any(cid in game.registry.modular_faces for deck in setup.decks for cid in deck.cards):
        return
    for pid, deck in enumerate(setup.decks, 1):
        player = game._state.players[pid]
        if (player.deck_class, player.runes, player.original_deck) != (deck.card_class, deck.runes, deck.cards):
            raise ValueError('Modular original deck differs from its fixed physical construction')
