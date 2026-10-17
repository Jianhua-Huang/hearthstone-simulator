"""Genuine card-selection facts at the existing shared choice boundary.

The producer still owns delivery, overflow, copies and summoning. These facts
do not announce an after-Discover trigger or identify an acquired entity.
"""
from dataclasses import asdict

from .model import CardDiscoveryRecord, CardDiscoveredTurnMatch, ChoicePurpose, ChoiceResult, GameState, _int

PURPOSES = (ChoicePurpose.POOL_DISCOVERY, ChoicePurpose.CARD_DISCOVERY)
PURPOSE_VALUES = frozenset(p.value for p in PURPOSES)
SELECTION_EVENTS = frozenset(('choice_selected', 'spell_choice_automatic',
    'hero_power_choice_automatic', 'battlecry_choice_randomized', 'physical_choice_automatic'))
PUBLICATION = 'card_discovery_recorded'


def selection_matches(event, result):
    choice = result.choice
    data = dict(event.data)
    return (event.kind in SELECTION_EVENTS and
        (event.source_id, event.player_id, data.get('choice_id'), data.get('purpose'),
         data.get('option_ids')) ==
        (choice.source_id, choice.player_id, choice.id, choice.purpose.value, result.selected_ids))


def commit(r, result, selection_event):
    """No new work/checkpoint: all manual and automatic choices pass here."""
    if result.choice.purpose not in PURPOSES:
        return
    result.__post_init__()
    if (selection_event is None or not selection_matches(selection_event, result) or
            selection_event.sequence > len(r.game._events) or
            r.game._events[selection_event.sequence - 1] != selection_event or
            selection_event.action != r.state.action_number):
        raise ValueError('Card discovery lost its actual original selection event')
    if any(row.result.choice.id == result.choice.id for row in r.state.card_discovery_history):
        raise ValueError('A card discovery selection may be recorded only once')
    for option in result.choice.options:
        if not r.registry.card(option.card_id).hand_playable:
            raise ValueError('A card discovery offered an unplayable card face')
    from .owner_turns import current_owner_turn
    row = CardDiscoveryRecord(len(r.state.card_discovery_history) + 1, r.state.turn,
        r.state.action_number, current_owner_turn(r.state).id,
        selection_event.sequence, len(r.game._events) + 1, result)
    r.state.card_discovery_history.append(row)
    from .serialization import canonical_hash
    # This is a private consistency publication. Gameplay reads the typed state
    # receipt, never scans diagnostics; no new gameplay trigger is captured.
    r.emit(PUBLICATION, source_id=result.choice.source_id, player_id=result.choice.player_id,
        discovery_id=row.id, receipt=asdict(row), receipt_hash=canonical_hash(asdict(row)), _capture=False)


def discovered_cards(state, player_id, *, turn=None):
    if type(state) is not GameState or type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Card discovery query requires typed state and an actual player')
    if turn is not None:
        _int(turn, 'card discovery query turn', 1)
    return tuple(row for row in state.card_discovery_history
        if row.result.choice.player_id == player_id and (turn is None or row.turn == turn))


def discovered_this_turn(state, player_id):
    return bool(discovered_cards(state, player_id, turn=state.turn))


def require_original_result(state, result):
    """Bind producer work to its real immutable selection, never a later entity."""
    if type(state) is not GameState or type(result) is not ChoiceResult:
        raise ValueError('Discovery work requires its actual typed selection result')
    result.__post_init__()
    rows = [row for row in state.card_discovery_history if row.result.choice.id == result.choice.id]
    if len(rows) != 1 or rows[0].result != result:
        raise ValueError('Discovery work lost its complete original committed selection')
    return rows[0]


def capture_turn_match(state, player_id):
    return CardDiscoveredTurnMatch(player_id, state.turn, state.action_number,
        tuple(state.card_discovery_history), discovered_this_turn(state, player_id))


def validate_turn_match(match, registry):
    if type(match) is not CardDiscoveredTurnMatch:
        raise ValueError('Discovery price requires its complete typed selection prefix')
    match.__post_init__()
    for row in match.records:
        for option in row.result.choice.options:
            if not registry.card(option.card_id).hand_playable:
                raise ValueError('Discovery price changed an original offered card face')


def validate_turn_prefix(match, state, registry):
    validate_turn_match(match, registry)
    rows = tuple(state.card_discovery_history)
    if (match.turn > state.turn or match.action > state.action_number or
            rows[:len(match.records)] != match.records or
            any(row.action < match.action for row in rows[len(match.records):])):
        raise ValueError('Discovery price lost its complete original selection prefix')


def validate_history(state, registry):
    if type(state.card_discovery_history) is not list:
        raise ValueError('Card discovery history requires a list')
    last_turn = last_action = last_choice = last_publication = 0
    for index, row in enumerate(state.card_discovery_history, 1):
        if type(row) is not CardDiscoveryRecord:
            raise ValueError('Card discovery history requires immutable actual receipts')
        row.__post_init__()
        choice = row.result.choice
        if (row.id != index or not last_turn <= row.turn <= state.turn or
                not last_action <= row.action <= state.action_number or
                not last_choice < choice.id < state.next_choice_id or
                row.selection_event <= last_publication or
                row.owner_turn_id > len(state.owner_turn_history) or
                choice.source_id is not None and choice.source_id not in state.entities):
            raise ValueError('Card discovery chronology or original identity disagrees')
        owner = state.owner_turn_history[row.owner_turn_id - 1]
        if owner.turn != row.turn or row.action < owner.start_action:
            raise ValueError('Card discovery borrowed another actual turn interval')
        for option in choice.options:
            if (not registry.card(option.card_id).hand_playable or
                    option.entity_id is not None and option.entity_id not in state.entities):
                raise ValueError('Card discovery lost an original offered card')
        last_turn, last_action = row.turn, row.action
        last_choice, last_publication = choice.id, row.publication_event


def validate_boundary(game):
    from .serialization import canonical_hash
    from .hero_health_history import effective_events
    state, events = game._state, effective_events(game._events)
    originals = {event.sequence: event for event in events}
    publications = [event for event in events if event.kind == PUBLICATION]
    rows = state.card_discovery_history
    if len(publications) != len(rows):
        raise ValueError('Card discovery state and actual publications disagree')
    selected = set()
    requests = {dict(event.data)['choice_id']: event for event in events if event.kind == 'choice_requested'}
    for row, event in zip(rows, publications):
        origin = originals.get(row.selection_event)
        if (row.publication_event != event.sequence or origin is None or
                not selection_matches(origin, row.result) or
                origin.action != row.action or event.action != row.action or
                (event.source_id, event.player_id) != (row.result.choice.source_id, row.result.choice.player_id)):
            raise ValueError('Card discovery publication lost its actual original result')
        receipt = asdict(row)
        # Events arrive through JSON on restore. Canonical hashes compare the
        # complete typed receipt without relying on tuple/list representation.
        data = dict(event.data)
        if (set(data) != {'discovery_id', 'receipt', 'receipt_hash'} or data['discovery_id'] != row.id or
                data['receipt_hash'] != canonical_hash(receipt) or
                canonical_hash(data['receipt']) != canonical_hash(receipt)):
            raise ValueError('Card discovery publication changed its complete original receipt')
        if origin.kind == 'choice_selected':
            request = requests.get(row.result.choice.id)
            choice = row.result.choice
            expected = (choice.source_id, choice.player_id, choice.purpose.value,
                        tuple(o.id for o in choice.options), choice.min_count, choice.max_count)
            if request is None:
                raise ValueError('Manual card discovery lost its original request')
            requested = dict(request.data)
            if (request.sequence >= origin.sequence or
                    (request.source_id, request.player_id, requested.get('purpose'), requested.get('option_ids'),
                     requested.get('min_count'), requested.get('max_count')) != expected):
                raise ValueError('Card discovery disagrees with its actual requested choice')
        selected.add(row.selection_event)
    for event in events:
        if event.kind not in SELECTION_EVENTS:
            continue
        data = dict(event.data)
        requested = requests.get(data.get('choice_id')) if event.kind == 'choice_selected' else None
        actual_purpose = dict(requested.data).get('purpose') if requested is not None else data.get('purpose')
        if (actual_purpose in PURPOSE_VALUES
                and event.sequence not in selected):
            raise ValueError('Actual card discovery selection lost its receipt')


def record_from_dict(value):
    from .serialization import _row, _list, choice_from_dict
    row = _row(value, CardDiscoveryRecord)
    result = _row(row['result'], ChoiceResult)
    result['choice'] = choice_from_dict(result['choice'])
    result['selected_ids'] = tuple(_list(result['selected_ids'], 'discovered card selection'))
    row['result'] = ChoiceResult(**result)
    return CardDiscoveryRecord(**row)


def rows_from_dict(value):
    from .serialization import _list
    value['card_discovery_history'] = [record_from_dict(row)
        for row in _list(value['card_discovery_history'], 'card discovery history')]
