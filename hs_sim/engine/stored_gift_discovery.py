"""Physical own-deck minions paired with the ten constructed Dark Gifts."""
from dataclasses import dataclass
from types import SimpleNamespace

from .card_conditions import has_battlecry
from .dark_gifts import DARK_GIFTS, GrantDarkGift
from .discovery import sample_eligible_gifts
from .effects import ChoiceOption, Effect, RequestChoice, _integer, _player
from .errors import ResolutionLimitExceeded
from .model import CardPreview, CardType, ChoicePurpose, ChoiceResult, Zone
from .pools import PoolQuery
from .zones import CardReference, MoveCard, reference_entity, source_exists, zone_candidates

PROMPT = '从你的牌库中发现一张具有黑暗之赐的随从牌'


def gift_by_id(gift_id):
    if type(gift_id) is not str or gift_id not in {g.id for g in DARK_GIFTS}:
        raise ValueError('Unknown constructed stored Dark Gift')
    return next(g for g in DARK_GIFTS if g.id == gift_id)


def eligible_face(preview, battlecry):
    return SimpleNamespace(kind=CardType.MINION, attack=preview.attack, keywords=preview.keywords,
                           battlecry='captured-current-battlecry' if battlecry else None)


@dataclass(frozen=True)
class DiscoverDeckDarkGift(Effect):
    player_id: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'stored gift source', 1)


@dataclass(frozen=True)
class StoredGiftOffer:
    card: CardReference
    face: CardPreview
    battlecry: bool
    gift_id: str

    def __post_init__(self):
        if type(self.card) is not CardReference or self.card.zone != Zone.DECK:
            raise ValueError('Stored gift requires its original deck reference')
        self.card.__post_init__()
        if type(self.face) is not CardPreview or type(self.battlecry) is not bool:
            raise ValueError('Stored gift requires complete current visible material')
        self.face.__post_init__()
        if not gift_by_id(self.gift_id).eligible(eligible_face(self.face, self.battlecry)):
            raise ValueError('Captured stored minion is not eligible for its gift')


@dataclass(frozen=True)
class SelectGiftedDeckCard(Effect):
    request: DiscoverDeckDarkGift
    offered: tuple[StoredGiftOffer, ...]
    index: int
    result: ChoiceResult | None = None

    def __post_init__(self):
        if type(self.request) is not DiscoverDeckDarkGift:
            raise ValueError('Stored gift selection requires its original request')
        self.request.__post_init__()
        if (type(self.offered) is not tuple or not 1 <= len(self.offered) <= 3 or
                any(type(o) is not StoredGiftOffer for o in self.offered)):
            raise ValueError('Stored gift selection requires its complete ordered offers')
        for offer in self.offered:
            offer.__post_init__()
            if offer.card.player_id != self.request.player_id:
                raise ValueError('Stored gift borrowed another player deck')
        if (len({o.card.entity_id for o in self.offered}) != len(self.offered) or
                len({o.gift_id for o in self.offered}) != len(self.offered)):
            raise ValueError('Stored gift offers require distinct physical cards and gifts')
        _integer(self.index, 'stored gift selection index', 0)
        if self.index >= len(self.offered): raise ValueError('Stored gift index is outside its offers')
        if self.result is not None:
            if type(self.result) is not ChoiceResult:raise ValueError('Stored gift requires a complete actual result')
            self.result.__post_init__()


def preview(offer):
    gift = gift_by_id(offer.gift_id); face = offer.face; grant = gift.grant
    return CardPreview(max(0, face.cost + gift.cost_delta), max(0, face.attack + grant.attack),
        face.health + grant.health, face.max_health + grant.health, face.durability,
        tuple(sorted(set((*face.keywords, *grant.keywords)), key=lambda k: k.value)))


def options_for(registry, request, offered):
    return tuple(ChoiceOption(f'stored-gift-{n+1}', registry.card(o.card.card_id).name + ' · ' + gift_by_id(o.gift_id).label +
        ('（置于牌库顶）' if gift_by_id(o.gift_id).destination == 'deck_top' else ''),
        (SelectGiftedDeckCard(request, offered, n),), card_id=o.card.card_id, preview=preview(o))
        for n, o in enumerate(offered))


def discover(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    candidates = zone_candidates(r, effect.player_id, Zone.DECK, PoolQuery(kinds=(CardType.MINION,)), effect.player_id, effect.source_id)
    count = min(3, len(candidates))
    if count > r.rules.max_choice_options: raise ResolutionLimitExceeded('Stored gift discovery exceeds choice budget')
    if not count: return ()
    # Match the existing physical take policy: copies are separate physical
    # candidates. No generated pool or class filter is inferred from registration.
    cards = tuple(r.game._rng.sample(candidates, count))
    entities = tuple(r.state.entities[card.entity_id] for card in cards)
    faces = tuple(CardPreview.capture(e) for e in entities)
    cries = tuple(has_battlecry(e.abilities) for e in entities)
    gifts = sample_eligible_gifts(r, DARK_GIFTS, tuple(eligible_face(face, cry) for face, cry in zip(faces, cries)))
    offered = tuple(StoredGiftOffer(card, face, cry, gift.id) for card, face, cry, gift in zip(cards, faces, cries, gifts))
    return (RequestChoice(effect.player_id, options_for(r.registry, effect, offered),
                          source_id=effect.source_id, prompt=PROMPT,
                          purpose=ChoicePurpose.CARD_DISCOVERY),)


def select(r, effect):
    effect.__post_init__(); request = effect.request; source_exists(r, request.source_id)
    if effect.result is None:
        # Existing direct internal grant/move recipes are not a committed
        # discovery. Genuine choice execution always binds its actual result.
        offer=effect.offered[effect.index]
        if reference_entity(r,offer.card)is None:return ()
        gift=gift_by_id(offer.gift_id)
        return (GrantDarkGift(offer.card,gift.id,request.source_id),
            MoveCard(offer.card,request.player_id,Zone.DECK if gift.destination=='deck_top'else Zone.HAND,
                position='top'if gift.destination=='deck_top'else'bottom',source_id=request.source_id))
    from .card_discoveries import require_original_result
    from .discovery_delivery import MaterializeDiscoveredCard
    require_original_result(r.state,effect.result)
    result=effect.result;choice=result.choice
    if (choice.purpose!=ChoicePurpose.CARD_DISCOVERY or choice.options!=tuple(o.item for o in options_for(r.registry,request,effect.offered)) or
            (choice.player_id,choice.source_id,choice.prompt)!=(request.player_id,request.source_id,PROMPT) or
            result.selected_ids!=(f'stored-gift-{effect.index+1}',)):
        raise ValueError('Stored gift lost its original complete selected result')
    offer = effect.offered[effect.index]; entity = reference_entity(r, offer.card)
    if entity is None:return (MaterializeDiscoveredCard(result,None),)
    if entity.kind != CardType.MINION: raise ValueError('Stored Dark Gift selected a non-minion')
    gift = gift_by_id(offer.gift_id)
    return (GrantDarkGift(offer.card, gift.id, request.source_id),
            MaterializeDiscoveredCard(result,MoveCard(offer.card, request.player_id, Zone.DECK if gift.destination == 'deck_top' else Zone.HAND,
                     position='top' if gift.destination == 'deck_top' else 'bottom', source_id=request.source_id)))


def validate_choice(game):
    frame = game._frame; choice = game._state.pending_choice
    if choice is None or not any(type(e) is SelectGiftedDeckCard for o in frame.options for e in o.effects): return
    branches = [o.effects[0] for o in frame.options if len(o.effects) == 1 and type(o.effects[0]) is SelectGiftedDeckCard]
    if len(branches) != len(frame.options) or not branches: raise ValueError('Stored gift choice lost a physical branch')
    first = branches[0]; first.__post_init__()
    if (len(branches) != len(first.offered) or choice.min_count != 1 or choice.max_count != 1 or
            choice.purpose != ChoicePurpose.CARD_DISCOVERY or
            choice.repeat_key is not None or frame.on_select is not None or
            (choice.player_id, choice.source_id, choice.prompt) != (first.request.player_id, first.request.source_id, PROMPT)):
        raise ValueError('Stored gift choice disagrees with its original request')
    if tuple(frame.options) != options_for(game.registry, first.request, first.offered):
        raise ValueError('Stored gift branches, previews or pairings disagree')
    for offer in first.offered:
        entity = game._state.entities.get(offer.card.entity_id)
        if (entity is None or CardReference.capture(entity) != offer.card or entity.kind != CardType.MINION or
                CardPreview.capture(entity) != offer.face or has_battlecry(entity.abilities) != offer.battlecry):
            raise ValueError('Stored gift choice does not match its original physical material')


def register(mechanics):
    mechanics.register_payload_type(StoredGiftOffer)
    mechanics.register(DiscoverDeckDarkGift, discover)
    mechanics.register(SelectGiftedDeckCard, select)
