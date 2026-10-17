"""Actual positive Overload occurrences, anchored to the existing event pair."""
from .model import Event, OverloadRecord, OwnerTurnRecord, _int


def validate_state(state):
    _int(state.next_overload_id, 'next_overload_id', 1)
    if type(state.overload_history) is not list or any(type(row) is not OverloadRecord for row in state.overload_history):
        raise ValueError('Overload history requires immutable actual occurrences')
    if state.next_overload_id != len(state.overload_history) + 1:
        raise ValueError('Overload history lost its complete allocation cursor')
    last_turn = last_action = last_owner = last_event = 0
    for index, row in enumerate(state.overload_history, 1):
        row.__post_init__()
        if (row.id != index or row.player_id not in state.players or
                not last_turn <= row.turn <= state.turn or not last_action <= row.action <= state.action_number or
                row.owner_turn_id < last_owner or row.owner_turn_id > len(state.owner_turn_history) or
                row.mana_event_sequence <= last_event):
            raise ValueError('Overload history changed its original chronology or allocation')
        if row.owner_turn_id:
            owner = state.owner_turn_history[row.owner_turn_id - 1]
            if type(owner) is not OwnerTurnRecord:
                raise ValueError('Overload history lost an original owner interval')
            owner.__post_init__()
            if (owner.turn != row.turn or owner.start_action > row.action or owner.start_event >= row.mana_event_sequence or
                    owner.closed_action is not None and row.action > owner.closed_action or
                    owner.closed_event is not None and row.event_sequence > owner.closed_event):
                raise ValueError('Overload occurrence is outside its actual owner interval')
        elif (row.turn != 1 or state.owner_turn_history and
                (row.event_sequence > state.owner_turn_history[0].start_event or
                 row.action > state.owner_turn_history[0].start_action)):
            raise ValueError('Pre-first overload borrowed a later genuine turn')
        last_turn, last_action, last_owner, last_event = row.turn, row.action, row.owner_turn_id, row.event_sequence


def overloaded_crystals(state, player_id):
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Overload quantity requires a real affected player')
    validate_state(state)
    return sum(row.amount for row in state.overload_history if row.player_id == player_id)


def _validate_pair(row, event, mana):
    row.__post_init__()
    if type(event) is not Event or type(mana) is not Event:
        raise ValueError('Overload requires its complete original event pair')
    if (event.kind != 'overload_added' or len(event.data) != 2 or
            set(dict(event.data)) != {'pending_before', 'pending_after'} or
            (event.sequence, event.action, event.player_id, event.amount, event.source_id, event.target_id) !=
            (row.event_sequence, row.action, row.player_id, row.amount, None, None) or
            dict(event.data) != {'pending_before': row.pending_before, 'pending_after': row.pending_after}):
        raise ValueError('Overload history differs from its original increment event')
    _int(event.player_id, 'overload original increment player', 1)
    _int(dict(event.data)['pending_before'], 'overload original pending before', 0)
    _int(dict(event.data)['pending_after'], 'overload original pending after', 1)
    data = dict(mana.data)
    if (mana.kind != 'mana_changed' or len(mana.data) != 6 or
            set(data) != {'operation', 'available', 'maximum', 'temporary', 'locked', 'owed'} or
            data['operation'] != 'Overload' or data['owed'] != row.pending_after or
            (mana.sequence, mana.action, mana.player_id, mana.amount, mana.source_id, mana.target_id) !=
            (row.mana_event_sequence, row.action, row.player_id, 0, None, None)):
        raise ValueError('Overload history lost its actual earlier mana account event')
    _int(mana.player_id, 'overload original mana player', 1)
    for name in ('available', 'maximum', 'temporary', 'locked', 'owed'):
        _int(data[name], 'overload original mana ' + name, 0)


def commit(resolution, event, mana):
    """Resolver-only publication, before original overload listeners capture."""
    state = resolution.state
    if type(event) is not Event or type(mana) is not Event:
        raise ValueError('Overload requires its actual original event pair')
    validate_state(state)
    data = dict(event.data)
    row = OverloadRecord(state.next_overload_id, event.player_id, state.turn, state.action_number,
        len(state.owner_turn_history), mana.sequence, event.sequence, event.amount,
        data['pending_before'], data['pending_after'])
    _validate_pair(row, event, mana)
    if (event.sequence != len(resolution.game._events) + 1 or
            mana.sequence > len(resolution.game._events) or resolution.game._events[mana.sequence - 1] is not mana or
            state.players[row.player_id].overload_owed != row.pending_after):
        raise ValueError('Overload publication lost its actual committed mana operation')
    state.overload_history.append(row)
    state.next_overload_id += 1


def validate_boundary(game):
    state = game._state
    validate_state(state)
    from .hero_health_history import effective_events
    if tuple(event.sequence for event in effective_events(game._events) if event.kind == 'overload_added') != tuple(
            row.event_sequence for row in state.overload_history):
        raise ValueError('Overload history lost its complete committed increment inventory')
    for row in state.overload_history:
        if row.event_sequence > len(game._events):
            raise ValueError('Overload history borrowed an unknown or future event')
        _validate_pair(row, game._events[row.event_sequence - 1], game._events[row.mana_event_sequence - 1])
