"""Original player-owned sideboards, using the shared choice/hand pipeline.

Only registered finite policies are supported. Sideboard members are original
card definitions outside the main deck, not concealed live SETASIDE entities.
"""
from dataclasses import dataclass, replace

from .effects import AddToHand, ChoiceOption, Effect, RequestChoice
from .model import CardType, Rarity

VERSION = 'sideboard-v1'


@dataclass(frozen=True)
class SideboardSpec:
    source_card_id: str
    cards: tuple[str, ...]

    def __post_init__(self):
        from .construction import ids, name
        name(self.source_card_id, 'sideboard source')
        ids(self.cards, 'sideboard cards')


@dataclass(frozen=True)
class SideboardProfile:
    source_card_id: str
    max_cards: int = 3
    banned_card_ids: tuple[str, ...] = ()
    version: str = VERSION

    def __post_init__(self):
        from .construction import ids, integer, name
        name(self.source_card_id, 'sideboard source')
        integer(self.max_cards, 'maximum sideboard size')
        # This first policy is the independent E.T.C. band contract. Other
        # sideboard source types require their own reviewed future policy.
        if self.max_cards != 3 or type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported independent sideboard policy')
        ids(self.banned_card_ids, 'sideboard bans', unique=True)


@dataclass(frozen=True)
class DeckCopySideboardProfile:
    """One actual two-cost construction selection; copies are generated later."""
    source_card_id: str
    selected_cost: int = 2
    copies: int = 10
    version: str = 'deck-copy-sideboard-v1'

    @property
    def max_cards(self):
        return 1

    def __post_init__(self):
        from .construction import integer, name
        name(self.source_card_id, 'deck-copy source')
        integer(self.selected_cost, 'deck-copy selected cost')
        integer(self.copies, 'deck-copy quantity')
        if (self.selected_cost != 2 or self.copies != 10 or type(self.version) is not str
                or self.version != 'deck-copy-sideboard-v1'):
            raise ValueError('Unsupported native deck-copy selection policy')


def deck_copy_selection_error(profile, cards, registry):
    if len(cards) != 1:
        return 'A native deck-copy source needs exactly one selected minion'
    card = registry.cards.get(cards[0])
    if card is None:
        return 'The selected deck-copy minion needs an executable definition'
    if card.kind != CardType.MINION or card.cost != profile.selected_cost:
        return 'The selected deck-copy card must be a printed two-cost minion'
    return None


@dataclass(frozen=True)
class SideboardState:
    source_card_id: str
    cards: tuple[str, ...]
    taken_slots: tuple[int, ...] = ()

    def __post_init__(self):
        SideboardSpec(self.source_card_id, self.cards)
        if type(self.taken_slots) is not tuple:
            raise ValueError('Sideboard taken slots must be a unique tuple')
        if any(type(slot) is not int or not 0 <= slot < len(self.cards) for slot in self.taken_slots):
            raise ValueError('Sideboard taken slot is outside its original band')
        if len(set(self.taken_slots)) != len(self.taken_slots):
            raise ValueError('Sideboard taken slots must be a unique tuple')


def validate_profiles(registry):
    for cid, profile in registry.sideboards.items():
        if type(profile) not in (SideboardProfile, DeckCopySideboardProfile) or profile.source_card_id != cid:
            raise ValueError('Sideboard profile differs from its registered source')
        profile.__post_init__()
        card = registry.card(cid)
        meta = card.metadata
        if (card.kind != CardType.MINION or meta is None or
                not meta.collectible or meta.rarity != Rarity.LEGENDARY):
            raise ValueError('Sideboard source requires a collectible Legendary minion')
        if type(profile) is SideboardProfile:
            if card.battlecry is None:
                raise ValueError('A band sideboard requires its printed battlecry')
            for banned_id in profile.banned_card_ids:
                registry.card(banned_id)
        elif not any(h.phase == 'before_deal' for h in card.opening_hooks):
            raise ValueError('A deck-copy selection requires its native before-deal opening hook')


def construction_members(deck, registry, issue, *, policy=None):
    """Validate attachment/size/bans; ordinary deck filters validate all members."""
    validate_profiles(registry)
    seen, members = set(), []
    for band in deck.sideboards:
        cid = band.source_card_id
        if cid in seen:
            issue('sideboard_duplicate', f'Duplicate sideboard configuration for {cid}', cid)
        seen.add(cid)
        profile = registry.sideboards.get(cid)
        if profile is None:
            issue('unsupported_sideboard', f'No reviewed sideboard policy for {cid}', cid)
        if cid not in deck.cards:
            issue('sideboard_source', f'{cid} is not in the original main deck', cid)
        if profile is not None and len(band.cards) > profile.max_cards:
            issue('sideboard_size', f'{cid} permits at most {profile.max_cards} band members', cid)
        copy_selection = type(profile) is DeckCopySideboardProfile
        if copy_selection:
            error = deck_copy_selection_error(profile, band.cards, registry)
            if error is not None:
                issue('deck_copy_selection', error, cid)
            if policy is None:
                raise ValueError('Deck-copy selection needs its actual construction policy')
        for member in band.cards:
            card = registry.cards.get(member)
            if type(profile) is SideboardProfile and (member in profile.banned_card_ids or
                    card is not None and card.opening_hooks):
                issue('sideboard_banned', f'{member} is excluded by the sideboard policy', member)
            if copy_selection and card is not None and card.metadata is not None:
                # The selected card occupies its full ordinary copy allowance,
                # including other editions and other bands sharing that identity.
                from .construction import copy_limit
                members.extend((member,) * copy_limit(card.metadata, policy))
            else:
                members.append(member)
    for cid, profile in registry.sideboards.items():
        if type(profile) is DeckCopySideboardProfile and cid in deck.cards and cid not in seen:
            issue('deck_copy_selection', 'The original deck-copy source requires its construction selection', cid)
    return tuple(members)


@dataclass(frozen=True)
class DiscoverSideboard(Effect):
    player_id: int
    source_card_id: str
    source_id: int | None = None

    def __post_init__(self):
        from .construction import integer, name
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Sideboard owner must be player 1 or 2')
        name(self.source_card_id, 'sideboard source')
        if self.source_id is not None:
            integer(self.source_id, 'sideboard physical source')


@dataclass(frozen=True)
class _TakeSideboardCard(Effect):
    player_id: int
    source_card_id: str
    slot: int
    card_id: str
    source_id: int | None = None

    def __post_init__(self):
        from .construction import integer, name
        DiscoverSideboard(self.player_id, self.source_card_id, self.source_id)
        integer(self.slot, 'sideboard slot', 0)
        name(self.card_id, 'sideboard member')


def _band(player, source_card_id):
    return next((b for b in player.sideboards if b.source_card_id == source_card_id), None)


def _options(player_id, band, registry, source_id):
    return tuple(ChoiceOption(f'band:{slot}', registry.card(cid).name,
        (_TakeSideboardCard(player_id, band.source_card_id, slot, cid, source_id),), card_id=cid)
        for slot, cid in enumerate(band.cards) if slot not in band.taken_slots)


def discover(r, effect):
    effect.__post_init__()
    if type(r.registry.sideboards.get(effect.source_card_id)) is not SideboardProfile:
        raise ValueError('Unsupported sideboard source')
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ValueError('Sideboard physical source does not exist')
    band = _band(r.player(effect.player_id), effect.source_card_id)
    options = () if band is None else _options(effect.player_id, band, r.registry, effect.source_id)
    # Empty or exhausted bands have no choice and consume no RNG. Offer each
    # original physical slot once; equal card faces do not collapse two slots.
    return [RequestChoice(effect.player_id, options, effect.source_id,
        prompt='选择一张乐队成员牌')] if options else []


def take(r, effect):
    effect.__post_init__()
    if type(r.registry.sideboards.get(effect.source_card_id)) is not SideboardProfile:
        raise ValueError('A construction-only selection is not a consumable band')
    player = r.player(effect.player_id)
    band = _band(player, effect.source_card_id)
    if (band is None or effect.slot >= len(band.cards) or
            effect.slot in band.taken_slots or band.cards[effect.slot] != effect.card_id):
        raise ValueError('Sideboard selection differs from an available original slot')
    changed = replace(band, taken_slots=band.taken_slots + (effect.slot,))
    player.sideboards = tuple(changed if b is band else b for b in player.sideboards)
    # Consume before the ordinary acquisition checkpoint. A full hand burns the
    # acquired card and cannot restore the sideboard member.
    r.emit('sideboard_card_taken', source_id=effect.source_id, player_id=effect.player_id,
        source_card_id=effect.source_card_id, slot=effect.slot, card_id=effect.card_id, _capture=False)
    return [AddToHand(effect.player_id, effect.card_id, effect.source_id)]


def validate_boundary(game):
    players = game._state.players
    if not game.registry.sideboards:
        if (any(type(p.sideboards) is not tuple or p.sideboards for p in players.values()) or
                any(e.kind == 'sideboard_card_taken' for e in game._events)):
            raise ValueError('Sideboard state requires registered original construction')
        return
    for player_id, player in players.items():
        if type(player.sideboards) is not tuple or any(type(b) is not SideboardState for b in player.sideboards):
            raise ValueError('Player sideboards require exact immutable records')
        for band in player.sideboards:
            band.__post_init__()
        expected = ()
        if game._match_setup is not None:
            deck = game._match_setup.decks[player_id-1]
            expected = deck.sideboards
            if (player.deck_class, player.runes, player.original_deck) != (deck.card_class, deck.runes, deck.cards):
                raise ValueError('Sideboard owner differs from its original deck class, runes or main deck')
        original = tuple(SideboardSpec(b.source_card_id, b.cards) for b in player.sideboards)
        if original != expected:
            raise ValueError('Sideboard origin differs from the original constructed band')
        taken = {b.source_card_id: [] for b in player.sideboards}
        for event in game._events:
            if event.kind != 'sideboard_card_taken' or event.player_id != player_id:
                continue
            data = dict(event.data)
            if len(event.data) != 3 or set(data) != {'source_card_id', 'slot', 'card_id'}:
                raise ValueError('Sideboard selection history has invalid fields')
            band = _band(player, data['source_card_id'])
            slot = data['slot']
            if (band is None or type(slot) is not int or not 0 <= slot < len(band.cards) or
                    data['card_id'] != band.cards[slot] or slot in taken[band.source_card_id]):
                raise ValueError('Sideboard history repeats or changes an original slot')
            taken[band.source_card_id].append(slot)
        if any(tuple(taken[b.source_card_id]) != b.taken_slots for b in player.sideboards):
            raise ValueError('Sideboard consumption differs from committed selection history')
    frame = game._frame
    if frame is not None and any(isinstance(e, _TakeSideboardCard) for o in frame.options for e in o.effects):
        first = next(e for o in frame.options for e in o.effects if isinstance(e, _TakeSideboardCard))
        band = _band(players[first.player_id], first.source_card_id)
        if (band is None or frame.options != _options(first.player_id, band, game.registry, first.source_id) or
                game._state.pending_choice.player_id != first.player_id):
            raise ValueError('Sideboard waiting options differ from all available original slots')


def register(mechanics):
    mechanics.register(DiscoverSideboard, discover)
    mechanics.register(_TakeSideboardCard, take)


def validate_player(player, registry):
    """Also validate historical rule-state captures, before their codec runs."""
    if type(player.sideboards) is not tuple or any(type(b) is not SideboardState for b in player.sideboards):
        raise ValueError('Player sideboards require exact immutable records')
    seen = set()
    for band in player.sideboards:
        band.__post_init__()
        profile = registry.sideboards.get(band.source_card_id)
        if (profile is None or band.source_card_id not in player.original_deck or
                band.source_card_id in seen or len(band.cards) > profile.max_cards):
            raise ValueError('Sideboard state requires a unique original supported source')
        if type(profile) is DeckCopySideboardProfile and (
                deck_copy_selection_error(profile, band.cards, registry) is not None or band.taken_slots):
            raise ValueError('Deck-copy selection changed its original member or was consumed as a band')
        seen.add(band.source_card_id)
        for cid in band.cards:
            registry.card(cid)
