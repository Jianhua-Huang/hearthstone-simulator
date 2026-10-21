"""Exact optional non-cost armor consumption; the Hero remains the account."""
from dataclasses import dataclass, fields
from .effects import Effect, _integer, _player
from .model import CardType, Event, _int
from .payment_projection import PaymentWrite, apply_resource_writes

EVENT = 'armor_consumption_resolved'
PUBLIC_EVENT = 'armor_consumed'


@dataclass(frozen=True)
class SpendArmor(Effect):
    player_id: int
    amount: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'exact armor consumption', 1)
        _integer(self.source_id, 'armor consumption issuer', 1)


@dataclass(frozen=True)
class ArmorConsumptionResult:
    event_sequence: int
    turn: int
    action: int
    root_action_number: int
    owner_turn_id: int
    player_id: int
    hero_id: int
    source_id: int
    requested: int
    before: int
    after: int
    actual: int

    def __post_init__(self):
        _player(self.player_id)
        for key in ('event_sequence', 'hero_id', 'source_id', 'requested'):
            _int(getattr(self, key), 'armor consumption '+key, 1)
        for key in ('turn', 'action', 'root_action_number', 'owner_turn_id', 'before', 'after', 'actual'):
            _int(getattr(self, key), 'armor consumption '+key, 0)
        if (self.root_action_number > self.action or self.actual != (self.requested if self.before >= self.requested else 0) or
                self.after != self.before-self.actual):
            raise ValueError('Armor consumption lost its exact all-or-nothing debit')

    def payload(self):
        return tuple((f.name, getattr(self, f.name)) for f in fields(self))


def consumption_result(event):
    if event is None or type(event) is Event and event.kind != EVENT:
        return None
    if type(event) is not Event or len(event.data) != 1 or set(dict(event.data)) != {'result'}:
        raise ValueError('Armor consumption requires its complete original event')
    raw = dict(event.data)['result']
    if type(raw) is not tuple or any(type(x) is not tuple or len(x) != 2 for x in raw):
        raise ValueError('Armor consumption result requires immutable fields')
    values = dict(raw)
    if len(values) != len(raw) or set(values) != {f.name for f in fields(ArmorConsumptionResult)}:
        raise ValueError('Armor consumption result lost or duplicated fields')
    row = ArmorConsumptionResult(**values)
    if (event.sequence, event.action, event.source_id, event.target_id, event.player_id, event.amount) != (
            row.event_sequence, row.action, row.source_id, row.hero_id, row.player_id, row.actual):
        raise ValueError('Armor consumption envelope changed its original account')
    return row


def consume(r, effect):
    from .zones import source_exists
    effect.__post_init__(); source_exists(r, effect.source_id)
    hero = r.state.entities[r.player(effect.player_id).hero_id]
    if hero.kind != CardType.HERO:
        raise ValueError('Armor consumption requires the actual installed Hero')
    owner = r.state.owner_turn_history[-1] if r.state.owner_turn_history else None
    actual = effect.amount if hero.armor >= effect.amount else 0
    row = ArmorConsumptionResult(len(r.game._events)+1, r.state.turn, r.state.action_number,
        r.root_action_number, owner.id if owner else 0, effect.player_id, hero.id, effect.source_id,
        effect.amount, hero.armor, hero.armor-actual, actual)
    apply_resource_writes(r.state, (PaymentWrite('entity', hero.id, 'armor', row.before, row.after),))
    r.emit(EVENT, source_id=effect.source_id, target_id=hero.id, player_id=effect.player_id,
        amount=actual, result=row.payload(), _capture=False)
    if actual:
        r.emit(PUBLIC_EVENT, source_id=effect.source_id, player_id=effect.player_id, amount=actual)
    return ()


def validate_result(state, registry, row):
    row.__post_init__()
    hero = state.entities.get(row.hero_id)
    if (row.turn > state.turn or row.action > state.action_number or row.source_id not in state.entities or
            hero is None or (hero.kind, hero.owner) != (CardType.HERO, row.player_id) or
            registry.card(hero.card_id).kind != CardType.HERO):
        raise ValueError('Armor consumption borrowed a future or different account')
    if row.owner_turn_id:
        if row.owner_turn_id > len(state.owner_turn_history):
            raise ValueError('Armor consumption borrowed an unknown owner interval')
        owner = state.owner_turn_history[row.owner_turn_id-1]
        if (owner.turn != row.turn or row.action < owner.start_action or row.event_sequence <= owner.start_event or
                owner.closed_action is not None and row.action > owner.closed_action or
                owner.closed_event is not None and row.event_sequence > owner.closed_event):
            raise ValueError('Armor consumption left its actual owner interval')
    elif row.turn != 1 or state.owner_turn_history and row.event_sequence > state.owner_turn_history[0].start_event:
        raise ValueError('Pre-first armor consumption borrowed a later turn')


def validate_events(state, registry, events):
    from .hero_health_history import effective_events
    timeline = tuple(effective_events(events))
    for index, event in enumerate(timeline):
        row = consumption_result(event)
        if row is None:
            continue
        validate_result(state, registry, row)
        if row.actual:
            following = timeline[index+1] if index+1 < len(timeline) else None
            if (following is None or following.kind != PUBLIC_EVENT or following.sequence != event.sequence+1 or
                    (following.source_id, following.player_id, following.amount, following.action, following.target_id) !=
                    (row.source_id, row.player_id, row.actual, row.action, None) or following.data):
                raise ValueError('Armor consumption lost its positive notification')
    for index, event in enumerate(timeline):
        if event.kind == PUBLIC_EVENT:
            row = None if not index else consumption_result(timeline[index-1])
            if row is None or not row.actual:
                raise ValueError('Armor consumption notification has no original positive debit')


def result_at(game, sequence):
    from .hero_health_history import effective_events
    event = next((e for e in effective_events(game._events) if e.sequence == sequence), None)
    row = consumption_result(event)
    if row is None:
        raise ValueError('Armor reward lost its original completed debit')
    validate_result(game._state, game.registry, row)
    return row


def register(mechanics):
    mechanics.register_payload_type(ArmorConsumptionResult)
    mechanics.register(SpendArmor, consume)
