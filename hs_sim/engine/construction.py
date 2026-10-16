"""Versioned deck validation, separate from executable card coverage and setup."""
from collections import Counter
from dataclasses import asdict, dataclass, fields
import json

from .model import CardClass, CardType, Keyword, Rarity, Runes


def name(value, field):
    if type(value) is not str or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')


def integer(value, field, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{field} must be an integer >= {minimum}')


def ids(value, field, unique=False):
    if type(value) is not tuple:
        raise ValueError(f'{field} must be a tuple of IDs')
    for item in value:
        name(item, field)
    if unique and len(set(value)) != len(value):
        raise ValueError(f'{field} contains duplicates')


@dataclass(frozen=True)
class DeckPolicy:
    id: str
    target_id: str
    mode: str
    allowed_card_ids: tuple[str, ...]
    banned_card_ids: tuple[str, ...] = ()
    pool_complete: bool = False
    deck_size: int = 30
    max_copies: int = 2
    legendary_copies: int = 1
    rune_slots: int = 3

    def __post_init__(self):
        name(self.id, 'policy ID')
        name(self.target_id, 'target ID')
        if self.mode not in ('experimental', 'standard', 'wild'):
            raise ValueError('Unsupported constructed mode')
        if type(self.pool_complete) is not bool:
            raise ValueError('pool_complete must be boolean')
        if self.mode != 'experimental' and not self.pool_complete:
            raise ValueError('Standard/wild validation requires an explicit complete versioned legality pool')
        ids(self.allowed_card_ids, 'allowed_card_ids', unique=True)
        ids(self.banned_card_ids, 'banned_card_ids', unique=True)
        for field in ('deck_size', 'max_copies', 'legendary_copies', 'rune_slots'):
            integer(getattr(self, field), field)


@dataclass(frozen=True)
class DeckSpec:
    hero_card_id: str
    hero_power_card_id: str
    card_class: CardClass
    cards: tuple[str, ...]
    runes: Runes | None = None
    sideboards: tuple['SideboardSpec', ...] = ()

    def __post_init__(self):
        name(self.hero_card_id, 'hero_card_id')
        name(self.hero_power_card_id, 'hero_power_card_id')
        from .model import PLAYABLE_CARD_CLASSES
        if type(self.card_class)is not CardClass or self.card_class not in PLAYABLE_CARD_CLASSES:
            raise ValueError('A deck needs a playable hero class')
        ids(self.cards, 'deck cards')
        from .sideboards import SideboardSpec
        if type(self.sideboards) is not tuple or any(type(b) is not SideboardSpec for b in self.sideboards):
            raise ValueError('Deck sideboards require exact SideboardSpec entries')
        for band in self.sideboards:
            band.__post_init__()
        if self.runes is not None:
            if not isinstance(self.runes, Runes):
                raise ValueError('Deck runes require Runes')
            self.runes.__post_init__()


@dataclass(frozen=True)
class MatchSetup:
    decks: tuple[DeckSpec, DeckSpec]
    policy: DeckPolicy
    coin_card_id: str
    seed: int = 0
    first_player: int | None = None
    board_id: int | None = None

    def __post_init__(self):
        from .game_boards import validate_board_id
        validate_board_id(self.board_id)
        if type(self.decks) is not tuple or len(self.decks) != 2 or any(type(d) is not DeckSpec for d in self.decks):
            raise ValueError('A match requires two DeckSpec entries')
        for deck in self.decks:
            deck.__post_init__()
        if type(self.policy) is not DeckPolicy:
            raise ValueError('A match requires a DeckPolicy')
        self.policy.__post_init__()
        name(self.coin_card_id, 'coin_card_id')
        if type(self.seed) is not int:
            raise ValueError('seed must be an integer')
        if self.first_player is not None and (type(self.first_player) is not int or self.first_player not in (1, 2)):
            raise ValueError('first_player must be 1, 2 or None for random')

    def to_dict(self):
        return json.loads(json.dumps(asdict(self)))

    @classmethod
    def from_dict(cls, value):
        # Unversioned host setup JSON may omit the optional board. Current
        # snapshots additionally require its explicit field at Game decoding.
        row = strict_row({'board_id': None, **value} if type(value) is dict else value, cls)
        if type(row['decks']) is not list:
            raise ValueError('decks must be a JSON array')
        decks = []
        for item in row['decks']:
            # Host construction JSON can omit an empty optional sideboard.
            # Versioned snapshots require the explicit field at Game decoding.
            deck = strict_row({'sideboards': [], **item} if type(item) is dict else item, DeckSpec)
            deck['card_class'] = CardClass(deck['card_class'])
            deck['cards'] = array(deck['cards'], 'cards')
            from .sideboards import SideboardSpec
            bands = []
            for item in array(deck['sideboards'], 'sideboards'):
                band = strict_row(item, SideboardSpec)
                band['cards'] = array(band['cards'], 'sideboard cards')
                bands.append(SideboardSpec(**band))
            deck['sideboards'] = tuple(bands)
            if deck['runes'] is not None:
                deck['runes'] = Runes(**strict_row(deck['runes'], Runes))
            decks.append(DeckSpec(**deck))
        row['decks'] = tuple(decks)
        policy = strict_row(row['policy'], DeckPolicy)
        for field in ('allowed_card_ids', 'banned_card_ids'):
            policy[field] = array(policy[field], field)
        row['policy'] = DeckPolicy(**policy)
        return cls(**row)


def strict_row(value, kind):
    if type(value) is not dict or set(value) != {f.name for f in fields(kind)}:
        raise ValueError(f'{kind.__name__} must contain exactly its declared fields')
    return dict(value)


def array(value, field):
    if type(value) is not list:
        raise ValueError(f'{field} must be a JSON array')
    return tuple(value)


@dataclass(frozen=True)
class DeckIssue:
    code: str
    message: str
    card_id: str | None = None


@dataclass(frozen=True)
class DeckValidation:
    policy_id: str
    mode: str
    issues: tuple[DeckIssue, ...]

    @property
    def valid(self):
        return not self.issues

    def require_valid(self):
        if self.issues:
            raise DeckValidationError(self)


class DeckValidationError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('Invalid deck: ' + '; '.join(f'{i.code}: {i.message}' for i in report.issues))


def validate_deck(deck, registry, policy):
    if type(deck) is not DeckSpec or type(policy) is not DeckPolicy:
        raise ValueError('Expected DeckSpec and DeckPolicy')
    deck.__post_init__()
    policy.__post_init__()
    from .tourists import native_tourist, requires_runes, tourist_count, validate_specs
    validate_specs(registry)
    tourist = native_tourist(deck.card_class, deck.cards, registry, policy)
    from .deck_size_rules import expected_size, main_sources, validate_rules
    validate_rules(registry)
    issues = []
    def issue(code, message, card_id=None):
        issues.append(DeckIssue(code, message, card_id))
    if sum(Keyword.OLD_GOD in registry.card(card_id).keywords for card_id in deck.cards
           if card_id in registry.cards) > 1:
        issue('old_god_limit', 'A main deck can include at most one Old God')
    size = expected_size(deck, registry, policy)
    if len(main_sources(deck, registry)) > 1:
        issue('deck_rule_sources', 'Multiple original deck-size sources require a reviewed policy')
    if len(deck.cards) != size:
        issue('deck_size', f'Expected {size} cards, got {len(deck.cards)}')
    if tourist_count(deck.cards, registry) > 1:
        issue('tourist_limit', 'Only one Tourist can be included in the main deck')
    if requires_runes(deck.card_class, deck.cards, registry, policy):
        if deck.runes is None or deck.runes.total != policy.rune_slots:
            issue('rune_loadout', f'Death Knight access requires {policy.rune_slots} allocated runes')
    elif deck.runes is not None:
        issue('rune_loadout', 'Only Death Knight decks or a native Death Knight Tourist can allocate runes')
    for card_id, kind in ((deck.hero_card_id, CardType.HERO), (deck.hero_power_card_id, CardType.HERO_POWER)):
        card = registry.cards.get(card_id)
        if card is None:
            issue('unsupported_definition', f'Unknown starting {kind}: {card_id}', card_id)
        elif card.kind != kind or card.hero_card or card.metadata is None or card.metadata.classes != (deck.card_class,):
            issue('hero_identity', f'{card_id} is not a known {deck.card_class} {kind}', card_id)
        elif kind == CardType.HERO and card.initial_hero_power != deck.hero_power_card_id:
            issue('hero_power', f'{card_id} does not start with {deck.hero_power_card_id}', card_id)
    groups, limits = Counter(), {}
    allowed, banned = set(policy.allowed_card_ids), set(policy.banned_card_ids)
    from .fabled_decks import construction_companions
    fabled_companions = construction_companions(deck, registry, policy, issue)
    from .sideboards import construction_members
    sideboard_cards = construction_members(deck, registry, issue)
    from .modular_decks import construction_identity, validate_profiles as validate_modular_profiles
    validate_modular_profiles(registry)
    # Sideboard members do not add to main deck size, but share its reviewed
    # legality, class, rune and aggregate copy limits.
    for card_id, count in Counter(deck.cards + sideboard_cards).items():
        format_id = construction_identity(registry, card_id)
        if format_id not in allowed or format_id in banned or card_id in banned:
            issue('format_legality', f'{card_id} is excluded by policy {policy.id}', card_id)
        card = registry.cards.get(card_id)
        if card is None:
            issue('unsupported_definition', f'No executable definition for {card_id}', card_id)
            continue
        if not card.hand_playable:
            issue('unsupported_deck_type', f'{card.kind} cards are not supported as deck entries', card_id)
        meta = card.metadata
        if meta is None:
            issue('unknown_metadata', f'Missing reviewed construction metadata for {card_id}', card_id)
            continue
        if not meta.collectible and (card_id not in fabled_companions or card_id in sideboard_cards):
            issue('uncollectible', f'{card_id} cannot be added to a constructed deck', card_id)
        elif meta.rarity is None and card_id not in fabled_companions:
            issue('unknown_metadata', f'Missing rarity for {card_id}', card_id)
        if CardClass.NEUTRAL not in meta.classes and deck.card_class not in meta.classes:
            if tourist is None or card_id not in tourist.eligible_card_ids or card_id in registry.tourists:
                issue('class', f'{card_id} does not belong to {deck.card_class} or its reviewed Tourist pool', card_id)
        if CardClass.DEATH_KNIGHT in meta.classes and meta.runes is None:
            issue('unknown_runes', f'Missing rune requirements for {card_id}', card_id)
        if meta.runes is not None and meta.runes.total:
            if deck.runes is None or any(getattr(meta.runes, rune) > getattr(deck.runes, rune)
                                         for rune in ('blood', 'frost', 'unholy')):
                issue('rune_requirements', f'Rune loadout cannot include {card_id}', card_id)
        group = meta.deck_identity or card_id
        limit = meta.max_copies or (policy.legendary_copies if meta.rarity == Rarity.LEGENDARY else policy.max_copies)
        if card_id in fabled_companions:
            # Bundle membership enforces one copy, including tokens without rarity.
            limit = min(limit, 1)
        groups[group] += count
        limits[group] = min(limits.get(group, limit), limit)
    for group, count in groups.items():
        if count > limits[group]:
            issue('copy_limit', f'{group} has {count} copies; maximum is {limits[group]}', group)
    return DeckValidation(policy.id, policy.mode, tuple(issues))


def validate_setup(setup, registry, ruleset):
    if type(setup) is not MatchSetup:
        raise ValueError('Expected MatchSetup')
    setup.__post_init__()
    for deck in setup.decks:
        validate_deck(deck, registry, setup.policy).require_valid()
    if ruleset.max_hand < 5:
        raise ValueError('Normal opening requires room for four cards and The Coin')
    if any(len(deck.cards) < 8 for deck in setup.decks):
        raise ValueError('Normal opening requires at least eight cards for a full mulligan')
    coin = registry.card(setup.coin_card_id)
    if coin.kind != CardType.SPELL or coin.on_play is None:
        raise ValueError('Coin must be an explicitly implemented spell')
