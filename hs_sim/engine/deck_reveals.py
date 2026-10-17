"""One physical deck reveal, immutable original cost, no live tracking handle."""
from dataclasses import dataclass

from .costs import local_cost
from .effects import Effect, _player, _source
from .errors import ResolutionError
from .joust import JoustCard
from .model import CardType, Zone
from .pools import PoolQuery
from .zones import CardReference, zone_candidates

EVENT = 'deck_card_revealed'


@dataclass(frozen=True)
class RevealRandomDeckCard(Effect):
    player_id: int
    kind: CardType = CardType.SPELL
    source_id: int | None = None
    on_result: str | None = None
    target_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id); _source(self.target_id)
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.SPELL):
            raise ValueError('Deck revelation supports a real minion or spell range')
        if self.on_result is not None:
            if type(self.on_result) is not str or not self.on_result.strip() or self.source_id is None:
                raise ValueError('Deck reveal callback requires a behavior and original source')
        elif self.target_id is not None:
            raise ValueError('Deck reveal target requires its result callback')


@dataclass(frozen=True)
class DeckRevealResult:
    player_id: int
    kind: CardType
    card: JoustCard | None

    def __post_init__(self):
        _player(self.player_id)
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.SPELL):
            raise ValueError('Unknown deck reveal range')
        if self.card is not None:
            if type(self.card) is not JoustCard:
                raise ValueError('Deck reveal requires the original physical card/cost material')
            self.card.__post_init__()
            if self.card.card.player_id != self.player_id:
                raise ValueError('Deck reveal changed its original owner')

    def payload(self):
        return 1, self.player_id, self.kind.value, None if self.card is None else self.card.payload()


def deck_reveal_result(event):
    if event is None or event.kind != EVENT:
        return None
    data = dict(event.data)
    if set(data) != {'result'}:
        raise ValueError('Deck reveal requires its exact original result')
    value = data['result']
    if type(value) is not tuple or len(value) != 4 or type(value[0]) is not int or value[0] != 1:
        raise ValueError('Invalid deck reveal result format')
    row = value[3]
    if row is not None:
        if type(row) is not tuple or len(row) != 6 or type(row[2]) is not str:
            raise ValueError('Invalid physical deck reveal material')
        row = JoustCard(CardReference(row[0], row[1], Zone(row[2]), row[3], row[4]), row[5])
    result = DeckRevealResult(value[1], CardType(value[2]), row)
    result.__post_init__()
    if (event.player_id != result.player_id or type(event.amount) is not int or
            event.amount != (0 if row is None else row.cost) or event.target_id is not None):
        raise ValueError('Deck reveal changed its original domain, cost or hidden target')
    return result


def validate_request(state, registry, effect):
    effect.__post_init__()
    for value in (effect.source_id, effect.target_id):
        if value is not None and value not in state.entities:
            raise ResolutionError('Deck reveal uses an unknown source or callback target')
    if effect.on_result is not None:
        registry.behavior(effect.on_result)


def reveal(r, effect):
    validate_request(r.state, r.registry, effect)
    refs = zone_candidates(r, effect.player_id, Zone.DECK, PoolQuery(kinds=(effect.kind,)),
                           effect.player_id, effect.source_id)
    # Validate every physical operand before the one draw; duplicate faces keep
    # separate weights. No opponent pool, movement, draw, shuffle or hand quote.
    cards = tuple(JoustCard(ref, local_cost(r.state.entities[ref.entity_id])[0]) for ref in refs)
    chosen = None if not cards else cards[r.game._rng.randrange(len(cards))]
    result = DeckRevealResult(effect.player_id, effect.kind, chosen)
    event = r.emit(EVENT, source_id=effect.source_id, player_id=effect.player_id,
                   amount=0 if chosen is None else chosen.cost, result=result.payload())
    return () if effect.on_result is None else (r.call(effect.on_result, effect.source_id,
        effect.player_id, effect.target_id, event=event),)


def validate_result(state, registry, result, *, captured=False):
    result.__post_init__()
    if result.card is None:
        if captured and any(registry.card(state.entities[i].card_id).kind == result.kind
                            for i in state.players[result.player_id].deck):
            raise ValueError('Empty reveal omitted an original eligible physical card')
        return
    ref = result.card.card
    entity = state.entities.get(ref.entity_id)
    if entity is None or registry.card(ref.card_id).kind != result.kind or ref.zone_epoch > entity.zone_epoch:
        raise ValueError('Deck reveal refers to an unknown or future physical card')
    if captured and ((entity.controller, entity.zone, entity.card_id, entity.zone_epoch) !=
            (ref.player_id, ref.zone, ref.card_id, ref.zone_epoch) or
            ref.entity_id not in state.players[ref.player_id].deck or local_cost(entity)[0] != result.card.cost):
        raise ValueError('Captured deck reveal differs from its original physical operand/cost')


def validate_boundary(game):
    if game._frame is None:
        return
    from .resolver import BehaviorCall
    for work in (*game._frame.prefix, *game._frame.continuation):
        if type(work) is RevealRandomDeckCard:
            validate_request(game._state, game.registry, work)
        if type(work) is BehaviorCall:
            context = work.context
            result = deck_reveal_result(context.event)
            if result is None or context.source_id != context.event.source_id:
                continue
            event = context.event
            if event.sequence < 1 or event.sequence > len(game._events) or game._events[event.sequence-1] != event:
                raise ValueError('Deck reveal callback lost its genuine original event')
            if context.player_id != result.player_id:
                raise ValueError('Deck reveal callback changed its original player')
            validate_result(context.state, game.registry, result, captured=True)


def validate_events(state, registry, events):
    for event in events:
        result = deck_reveal_result(event)
        if result is not None:
            validate_result(state, registry, result)


def register(mechanics):
    mechanics.register(RevealRandomDeckCard, reveal)
