"""Discover an original own-deck minion to summon or original spell to cast."""
from dataclasses import dataclass

from .effects import ChoiceOption, Effect, RequestChoice, _integer, _player
from .errors import ResolutionError
from .model import CardPreview, CardType, ChoicePurpose, ChoiceResult, Zone
from .summon_quantities import SummonCause, validate_cause
from .zones import (CardReference, ChooseFromZone, DeckTakeOffer, reference_entity,
    sample_zone_choices, source_exists)
from .pools import PoolQuery

PROMPT = '选择牌库中的一张牌直接执行'


@dataclass(frozen=True)
class DiscoverDeckCardAction(Effect):
    player_id: int
    kind: CardType
    cause: SummonCause

    @property
    def source_id(self): return self.cause.source.entity_id

    def __post_init__(self):
        _player(self.player_id)
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.SPELL):
            raise ValueError('Direct deck discovery requires an original minion or spell')
        if type(self.cause) is not SummonCause:
            raise ValueError('Direct deck discovery requires its original spell attribution')
        self.cause.__post_init__()
        if (self.cause.player_id != self.player_id or self.cause.origin != 'spell_cast' or
                self.cause.source.kind != CardType.SPELL):
            raise ValueError('Direct deck discovery borrowed another original spell actor')


@dataclass(frozen=True)
class SelectDeckCardAction(Effect):
    request: DiscoverDeckCardAction
    offered: tuple[DeckTakeOffer, ...]
    index: int
    result: ChoiceResult | None = None

    def __post_init__(self):
        if type(self.request) is not DiscoverDeckCardAction:
            raise ValueError('Direct deck selection requires its complete original request')
        self.request.__post_init__()
        if (type(self.offered) is not tuple or not 1 <= len(self.offered) <= 3 or
                any(type(o) is not DeckTakeOffer for o in self.offered)):
            raise ValueError('Direct deck selection requires its complete ordered offers')
        for offer in self.offered:
            offer.__post_init__()
            if offer.card.player_id != self.request.player_id:
                raise ValueError('Direct deck selection borrowed another player deck')
        if len({o.card.entity_id for o in self.offered}) != len(self.offered):
            raise ValueError('Direct deck selection repeated an original physical card')
        _integer(self.index, 'direct deck selection index', 0)
        if self.index >= len(self.offered):
            raise ValueError('Direct deck selection is outside its original offers')
        if self.result is not None:
            if type(self.result) is not ChoiceResult:
                raise ValueError('Direct deck selection requires its actual committed result')
            self.result.__post_init__()


def options_for(registry, request, offered):
    return tuple(ChoiceOption(f'deck-action-{index+1}',
        offer.face.display_name or registry.card(offer.card.card_id).name,
        (SelectDeckCardAction(request, offered, index),), card_id=offer.card.card_id,
        preview=offer.face) for index, offer in enumerate(offered))


def validate_request(state, registry, request):
    request.__post_init__()
    validate_cause(state, registry, request.cause)


def discover(r, request):
    validate_request(r.state, r.registry, request)
    query = ChooseFromZone(request.player_id, request.player_id, Zone.DECK,
        PoolQuery(kinds=(request.kind,)), operation='take', distinct='entity',
        source_id=request.source_id, discovery=True)
    cards = sample_zone_choices(r, query)
    if not cards: return ()
    offered = tuple(DeckTakeOffer(card, CardPreview.capture(r.state.entities[card.entity_id], r.registry))
        for card in cards)
    return (RequestChoice(request.player_id, options_for(r.registry, request, offered),
        request.source_id, prompt=PROMPT, purpose=ChoicePurpose.CARD_DISCOVERY),)


def select(r, work):
    work.__post_init__(); request = work.request
    validate_request(r.state, r.registry, request); source_exists(r, request.source_id)
    if work.result is None:
        raise ResolutionError('Direct deck selection requires its actual committed discovery')
    from .card_discoveries import require_original_result
    from .discovery_delivery import MaterializeDiscoveredCard, PublishDiscoveredSummon, queue
    original = require_original_result(r.state, work.result)
    from .offered_card_execution import original_offer
    accepted = original_offer(r.registry, original.original_offer)
    result = work.result; choice = result.choice
    if (choice.purpose != ChoicePurpose.CARD_DISCOVERY or
            (choice.player_id, choice.source_id, choice.prompt) != (request.player_id, request.source_id, PROMPT) or
            choice.options != tuple(o.item for o in options_for(r.registry, request, work.offered)) or
            accepted.options != options_for(r.registry, request, work.offered) or accepted.on_select is not None or
            result.selected_ids != (f'deck-action-{work.index+1}',)):
        raise ResolutionError('Direct deck selection changed its original complete offers or request')
    selected = work.offered[work.index].card
    entity = reference_entity(r, selected)
    if entity is None: return (MaterializeDiscoveredCard(result, None),)
    if entity.kind != request.kind:
        raise ResolutionError('Direct deck selection changed its original card kind')
    if request.kind == CardType.SPELL:
        from .spell_casts import CastStoredSpell
        return (MaterializeDiscoveredCard(result, CastStoredSpell(selected, request.player_id, request.source_id)),)
    from .colossal import SummonStoredCard, summon_stored
    from .summon_quantities import FinishCardSummon
    tail = tuple(summon_stored(r, SummonStoredCard(selected, request.player_id, cause=request.cause)) or ())
    roots = tuple(w.root_id for w in tail if type(w) is FinishCardSummon)
    if len(roots) != 1:
        raise ValueError('Discovered original minion lost its actual recruit root')
    return (*tail, queue(r, PublishDiscoveredSummon(result, roots[0])))


def validate_choice(game):
    frame = game._frame; choice = game._state.pending_choice
    if frame is None: return
    for work in (*frame.prefix, *frame.continuation):
        if type(work) is DiscoverDeckCardAction:
            validate_request(game._state, game.registry, work)
    if choice is None or not any(type(e) is SelectDeckCardAction for o in frame.options for e in o.effects):
        return
    branches = tuple(o.effects[0] for o in frame.options if len(o.effects) == 1 and type(o.effects[0]) is SelectDeckCardAction)
    if len(branches) != len(frame.options) or not branches:
        raise ValueError('Direct deck discovery lost an original physical branch')
    first = branches[0]; first.__post_init__(); validate_request(game._state, game.registry, first.request)
    if (choice.purpose != ChoicePurpose.CARD_DISCOVERY or choice.min_count != 1 or choice.max_count != 1 or
            choice.repeat_key is not None or frame.on_select is not None or
            (choice.player_id, choice.source_id, choice.prompt) != (first.request.player_id, first.request.source_id, PROMPT) or
            frame.options != options_for(game.registry, first.request, first.offered)):
        raise ValueError('Direct deck discovery disagrees with its original offered material')
    for offer in first.offered:
        entity = game._state.entities.get(offer.card.entity_id)
        if (entity is None or entity.kind != first.request.kind or CardReference.capture(entity) != offer.card or
                CardPreview.capture(entity, game.registry) != offer.face):
            raise ValueError('Direct deck discovery changed its original physical preview')


def register(mechanics):
    mechanics.register(DiscoverDeckCardAction, discover)
    mechanics.register(SelectDeckCardAction, select)
