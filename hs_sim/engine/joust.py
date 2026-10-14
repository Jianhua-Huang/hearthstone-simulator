"""Independent random deck reveal/comparison, with an accepted result callback.

Uses existing physical-zone queries, local stored costs and guarded draws. Deck
order preservation and complex cost layers remain explicit CN calibration policy.
"""
from dataclasses import dataclass

from .costs import local_cost
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .model import CardType, Zone
from .pools import PoolQuery
from .zones import CardReference, zone_candidates


def _kind(value):
    if type(value) is not CardType or value not in (CardType.MINION, CardType.SPELL):
        raise ValueError('Joust supports the actual minion or spell deck profiles')


@dataclass(frozen=True)
class JoustCard:
    card: CardReference
    cost: int

    def __post_init__(self):
        if type(self.card) is not CardReference:
            raise ValueError('Joust requires an exact physical card reference')
        self.card.__post_init__()
        if self.card.zone != Zone.DECK:
            raise ValueError('Joust reveals cards in their own deck')
        _integer(self.cost, 'revealed deck cost', 0)

    def payload(self):
        ref = self.card
        return ref.entity_id, ref.player_id, ref.zone.value, ref.card_id, ref.zone_epoch, self.cost


@dataclass(frozen=True)
class JoustResult:
    player_id: int
    kind: CardType
    own: JoustCard | None
    opponent: JoustCard | None

    def __post_init__(self):
        _player(self.player_id)
        _kind(self.kind)
        for value, player in ((self.own, self.player_id), (self.opponent, 3-self.player_id)):
            if value is not None:
                if type(value) is not JoustCard:
                    raise ValueError('Joust result contains an invalid revealed card')
                value.__post_init__()
                if value.card.player_id != player:
                    raise ValueError('Joust result changed a deck owner')

    @property
    def won(self):
        return self.own is not None and (self.opponent is None or self.own.cost > self.opponent.cost)

    def payload(self):
        return (1, self.player_id, self.kind.value, None if self.own is None else self.own.payload(),
                None if self.opponent is None else self.opponent.payload())


def joust_result(event):
    """Read immutable original operands; never re-query today's deck or cost."""
    if event is None or event.kind != 'joust_resolved':
        return None
    data = dict(event.data)
    if set(data) != {'result'}:
        raise ValueError('Joust event requires its exact result payload')
    payload = data['result']
    if type(payload) is not tuple or len(payload) != 5 or type(payload[0]) is not int or payload[0] != 1:
        raise ValueError('Invalid Joust result format')
    def card(row):
        if row is None:
            return None
        if type(row) is not tuple or len(row) != 6 or type(row[2]) is not str:
            raise ValueError('Invalid revealed Joust card payload')
        return JoustCard(CardReference(row[0], row[1], Zone(row[2]), row[3], row[4]), row[5])
    result = JoustResult(payload[1], CardType(payload[2]), card(payload[3]), card(payload[4]))
    if event.player_id != result.player_id or type(event.amount) is not int or event.amount != int(result.won):
        raise ValueError('Joust event disagrees with its original comparison')
    return result


@dataclass(frozen=True)
class Joust(Effect):
    player_id: int
    on_result: str | None = None
    source_id: int | None = None
    target_id: int | None = None
    kind: CardType = CardType.MINION

    def __post_init__(self):
        _player(self.player_id)
        _source(self.source_id)
        _source(self.target_id)
        _kind(self.kind)
        if self.on_result is not None:
            if type(self.on_result) is not str or not self.on_result.strip() or self.source_id is None:
                raise ValueError('Joust result callback requires a behavior and physical source')
        elif self.target_id is not None:
            raise ValueError('A Joust target is only used by its result callback')


def validate_request(state, registry, effect):
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in state.entities:
        raise ResolutionError('Joust source does not exist')
    if effect.target_id is not None and effect.target_id not in state.entities:
        raise ResolutionError('Joust callback target does not exist')
    if effect.on_result is not None:
        registry.behavior(effect.on_result)


def resolve(r, effect):
    validate_request(r.state, r.registry, effect)
    query = PoolQuery(kinds=(effect.kind,))
    # Validate both entire physical pools before any randomness. Duplicates are
    # distinct physical cards, each with one weight; no card-definition dedup.
    pools = []
    for player in (effect.player_id, 3-effect.player_id):
        rows = zone_candidates(r, player, Zone.DECK, query, effect.player_id, effect.source_id)
        pools.append(tuple(JoustCard(ref, local_cost(r.state.entities[ref.entity_id])[0]) for ref in rows))
    selected = [None if not rows else rows[r.game._rng.randrange(len(rows))] for rows in pools]
    result = JoustResult(effect.player_id, effect.kind, *selected)
    event = r.emit('joust_resolved', source_id=effect.source_id, player_id=effect.player_id,
                   amount=int(result.won), result=result.payload())
    return [] if effect.on_result is None else [r.call(effect.on_result, effect.source_id,
        effect.player_id, effect.target_id, event=event)]


def validate_result(state, registry, result, *, captured=False):
    result.__post_init__()
    for value in (result.own, result.opponent):
        if value is None:
            continue
        ref = value.card
        entity = state.entities.get(ref.entity_id)
        if entity is None or registry.card(ref.card_id).kind != result.kind or ref.zone_epoch > entity.zone_epoch:
            raise ValueError('Joust result refers to an unknown or future physical card')
        if captured and ((entity.controller, entity.zone, entity.card_id, entity.zone_epoch) !=
                (ref.player_id, ref.zone, ref.card_id, ref.zone_epoch) or
                ref.entity_id not in state.players[ref.player_id].deck or local_cost(entity)[0] != value.cost):
            raise ValueError('Captured Joust result differs from its original deck operands')


def validate_boundary(game):
    if game._frame is None:
        return
    from .resolver import BehaviorCall
    for work in (*game._frame.prefix, *game._frame.continuation):
        if type(work) is Joust:
            validate_request(game._state, game.registry, work)
        if type(work) is BehaviorCall and (result := joust_result(work.context.event)) is not None:
            event = work.context.event
            if event.sequence < 1 or event.sequence > len(game._events) or game._events[event.sequence-1] != event:
                raise ValueError('Joust callback lost its genuine original event')
            validate_result(work.context.state, game.registry, result, captured=True)


def validate_events(state, registry, events):
    for event in events:
        if (result := joust_result(event)) is not None:
            validate_result(state, registry, result)


def register(mechanics):
    mechanics.register(Joust, resolve)
