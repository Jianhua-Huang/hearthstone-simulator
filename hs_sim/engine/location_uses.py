"""Actual location activations and their original intrinsic-price operands.

The ordinary activation executor owns validation, durability, bodies and waits.
Only its accepted activation appends a fact; neither placing nor refreshing a
location invents a use. Pricing retains the whole original two-player prefix.
"""
from dataclasses import dataclass
from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .model import CardType, Zone, _int, _optional_id

CONDITION = 'own_location_use_count'
HISTORY_PROFILE = 'location.activations-game-v1'


@dataclass(frozen=True)
class LocationUseRecord:
    id: int
    player_id: int
    turn: int
    action: int
    event_sequence: int
    source: SourceAllocationFact
    target_id: int | None
    remaining_durability: int

    def __post_init__(self):
        for name in ('id','player_id','turn','event_sequence'):
            _int(getattr(self,name),'location activation '+name,1)
        _int(self.action,'location activation action',0)
        _int(self.remaining_durability,'location activation remaining durability',0)
        _optional_id(self.target_id,'location activation target')
        if self.player_id not in (1,2) or type(self.source) is not SourceAllocationFact:
            raise ValueError('Location use requires an original player and physical allocation')
        self.source.__post_init__()
        if (self.source.kind,self.source.zone,self.source.controller) != (CardType.LOCATION,Zone.BOARD,self.player_id):
            raise ValueError('Location activation lost its actual controller and board presence')
        if self.target_id is not None and self.target_id >= self.source.next_entity_id:
            raise ValueError('Location activation target exceeds its original allocation')


def validate_records(records, *, turn, action, next_entity_id):
    last_turn=last_action=last_event=0
    for index,row in enumerate(records,1):
        if type(row) is not LocationUseRecord:
            raise ValueError('Location uses require complete typed original occurrences')
        row.__post_init__()
        if (row.id != index or not last_turn <= row.turn <= turn or
                not last_action <= row.action <= action or row.event_sequence <= last_event or
                row.source.next_entity_id > next_entity_id):
            raise ValueError('Location use changed its complete original chronology or allocation')
        last_turn,last_action,last_event=row.turn,row.action,row.event_sequence


def validate_state(state, registry=None):
    if type(state.location_use_history) is not list:
        raise ValueError('Location use history requires ordered original occurrences')
    validate_records(state.location_use_history,turn=state.turn,action=state.action_number,
        next_entity_id=state.next_entity_id)
    if registry is not None:
        for row in state.location_use_history:
            validate_allocation(state,registry,row.source)
            if row.target_id is not None and row.target_id not in state.entities:
                raise ValueError('Location use names an unknown physical target')


def accept(r, source, player_id, target_id):
    """After actual durability debit, before the original body captures state."""
    validate_state(r.state,r.registry)
    row=LocationUseRecord(len(r.state.location_use_history)+1,player_id,r.state.turn,
        r.state.action_number,len(r.game._events)+1,SourceAllocationFact.capture(r.state,source),
        target_id,source.durability)
    r.state.location_use_history.append(row)


def validate_boundary(game):
    state=game._state
    validate_state(state,game.registry)
    events=[e for e in game._events if e.kind=='location_activated']
    if len(events) != len(state.location_use_history):
        raise ValueError('Location use history lost an actual activation or invented a use')
    for row,event in zip(state.location_use_history,events):
        data=dict(event.data)
        if ((row.event_sequence,row.action,row.source.entity_id,row.player_id,row.target_id) !=
                (event.sequence,event.action,event.source_id,event.player_id,event.target_id) or
                data.get('durability') != row.remaining_durability or data.get('cooldown') != 2):
            raise ValueError('Location use differs from its actual original activation event')


def capture_cost(state, player_id):
    from .model import LocationUseCostMatch
    validate_state(state)
    selected=tuple(row.id for row in state.location_use_history if row.player_id==player_id)
    return LocationUseCostMatch(player_id,state.turn,state.action_number,state.next_entity_id,
        tuple(state.location_use_history),selected,len(selected),bool(selected))


def validate_cost_match(value, registry=None):
    if type(value.player_id) is not int or value.player_id not in (1,2):
        raise ValueError('Location-use price requires the actual payer')
    _int(value.turn,'location-use price turn',1)
    _int(value.action,'location-use price action',0)
    _int(value.next_entity_id,'location-use price allocation',1)
    _int(value.quantity,'location-use price quantity',0)
    if (type(value.records) is not tuple or type(value.selected_ids) is not tuple or
            any(type(i) is not int for i in value.selected_ids) or type(value.matched) is not bool):
        raise ValueError('Location-use price requires its complete immutable original prefix')
    validate_records(value.records,turn=value.turn,action=value.action,next_entity_id=value.next_entity_id)
    if registry is not None:
        for row in value.records:
            if registry.card(row.source.card_id).kind != CardType.LOCATION:
                raise ValueError('Location-use price borrowed an unknown or non-location original face')
    expected=tuple(row.id for row in value.records if row.player_id==value.player_id)
    if (value.selected_ids,value.quantity,value.matched) != (expected,len(expected),bool(expected)):
        raise ValueError('Location-use price changed its original own activation selection')


def validate_cost_prefix(value, state, registry):
    value.__post_init__();validate_state(state,registry)
    if (value.turn > state.turn or value.action > state.action_number or value.next_entity_id > state.next_entity_id or
            tuple(state.location_use_history[:len(value.records)]) != value.records):
        raise ValueError('Location-use price lost its original accepted history prefix')


def row_from_dict(value):
    from .serialization import _row
    row=_row(value,LocationUseRecord)
    row['source']=allocation_from_dict(row['source'])
    return LocationUseRecord(**row)


def match_from_dict(value):
    from .model import LocationUseCostMatch
    from .serialization import _row, _list
    row=_row(value,LocationUseCostMatch)
    row['records']=tuple(row_from_dict(x)for x in _list(row['records'],'original location activation prefix'))
    row['selected_ids']=tuple(_list(row['selected_ids'],'original own location activations'))
    return LocationUseCostMatch(**row)


def register(mechanics):
    mechanics.register_payload_type(LocationUseRecord)
