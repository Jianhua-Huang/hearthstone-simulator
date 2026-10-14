"""Shared storage plumbing for the two original settled health flows.

Numbers, packet identities, conversion and checkpoints belong to the existing
resolver. These facts only retain its complete immutable results.
"""
from .health_outcomes import health_result, result_from_payload
from .model import CardType, DamageKind, DamageRecord, GameState, HealingRecord, HealthFlow, _int


def _settings(flow):
    if type(flow) is not HealthFlow:
        raise ValueError('Health history requires an exact original flow')
    if flow is HealthFlow.DAMAGE:
        return DamageRecord, 'damage_history', 'next_damage_id', 'damage_dealt', 'Damage'
    if flow is HealthFlow.HEALING:
        return HealingRecord, 'healing_history', 'next_healing_id', 'healed', 'Healing'
    raise ValueError('Unsupported health history flow')


def related(result, flow):
    _settings(flow)
    return result.original_flow == flow.value or result.flow == flow.value


def validate_record(record, flow):
    record_type, _history, _cursor, _units, label = _settings(flow)
    if type(record) is not record_type:
        raise ValueError(label + ' history requires immutable original results')
    _int(record.id, label.lower() + ' occurrence identity', 1)
    _int(record.action, label.lower() + ' occurrence action', 0)
    result = result_from_payload(record.result)
    if not related(result, flow) or record.result != result.payload():
        raise ValueError(label + ' history lost its complete ordered original result')
    return result


def checked_rows(state, flow, registry=None):
    _record_type, history, cursor, _units, label = _settings(flow)
    if type(state) is not GameState:
        raise ValueError(label + ' history requires typed State')
    rows = getattr(state, history); next_id = getattr(state, cursor)
    _int(next_id, 'next ' + label.lower() + ' identity', 1)
    if type(rows) is not list or next_id != len(rows) + 1:
        raise ValueError(label + ' history lost its complete allocation cursor')
    last_turn = last_action = 0; last_packet = (0, 0); checked = []
    for index, row in enumerate(rows, 1):
        result = validate_record(row, flow)
        packet = (result.batch_id, result.packet_index)
        if (row.id != index or not last_turn <= result.turn <= state.turn or
                not last_action <= row.action <= state.action_number or packet <= last_packet):
            raise ValueError(label + ' history changed its original packet order or clock')
        identities = ((result.target_id, result.target_card_id, result.target_zone_epoch, result.target_entered_order),)
        if result.source_id is not None:
            identities += ((result.source_id, result.source_card_id, result.source_zone_epoch, result.source_entered_order),)
        if result.weapon_id is not None:
            identities += ((result.weapon_id, None, result.weapon_zone_epoch, result.weapon_entered_order),)
        for identity, card, epoch, order in identities:
            entity = state.entities.get(identity)
            if (entity is None or identity >= state.next_entity_id or epoch > entity.zone_epoch or
                    order >= state.next_order):
                raise ValueError(label + ' history borrowed an unknown or future physical identity')
            if registry is not None and card is not None: registry.card(card)
        if result.original_target_id not in state.entities or any(identity not in state.entities for identity in result.redirect_path):
            raise ValueError(label + ' history lost its original target routing')
        if registry is not None and registry.card(result.target_card_id).kind.value != result.target_kind:
            raise ValueError(label + ' history changed its original target kind')
        checked.append((row, result))
        last_turn, last_action, last_packet = result.turn, row.action, packet
    return tuple(checked)


def select_records(state, flow, *, source_player=None, target_player=None, target_kind=None,
                   turn=None, before_id=None, target_own_turn=False):
    _record_type, _history, _cursor, units, label = _settings(flow)
    for name, value in (('source player', source_player), ('target player', target_player)):
        if value is not None and (type(value) is not int or value not in (1, 2)):
            raise ValueError('Invalid ' + label.lower() + ' query ' + name)
    if target_kind is not None and (type(target_kind) is not CardType or target_kind not in (CardType.HERO, CardType.MINION)):
        raise ValueError(label + ' query target kind must be a character')
    for name, value in (('turn', turn), ('before identity', before_id)):
        if value is not None: _int(value, label.lower() + ' query ' + name, 1)
    if type(target_own_turn) is not bool or target_own_turn and target_player is None:
        raise ValueError('Own-turn query requires a boolean and an actual target player')
    selected = []
    for row, result in checked_rows(state, flow):
        if (turn is not None and result.turn != turn or before_id is not None and row.id >= before_id or
                target_player is not None and result.target_controller != target_player or
                target_kind is not None and result.target_kind != target_kind.value or
                target_own_turn and result.active_player != target_player):
            continue
        if source_player is not None:
            if result.source_controller is None and getattr(result, units) > 0:
                # FATIGUE is an explicit systemic packet, with no card source.
                if flow is HealthFlow.DAMAGE and result.damage_kind == DamageKind.FATIGUE.value:
                    continue
                from .registry import UnsupportedDefinitionError
                raise UnsupportedDefinitionError('Actual ' + label.lower() + ' has unknown original source controller')
            if result.source_controller != source_player: continue
        selected.append(row)
    return tuple(selected)


def commit_batch(state, pending_events, flows=(HealthFlow.DAMAGE, HealthFlow.HEALING)):
    """Commit original results once, before the batch's first event capture."""
    for flow in flows:
        _record_type, history, cursor, _units, label = _settings(flow)
        if getattr(state, cursor) != len(getattr(state, history)) + 1:
            raise ValueError(label + ' batch lost its original allocation cursor')
    for kind, payload in pending_events:
        if kind != 'health_resolved': continue
        result = result_from_payload(payload['result'])
        for flow in flows:
            if not related(result, flow): continue
            record_type, history, cursor, _units, label = _settings(flow)
            rows = getattr(state, history); next_id = getattr(state, cursor)
            row = record_type(next_id, state.action_number, result.payload())
            if rows:
                old = rows[-1].health_result
                if (result.batch_id, result.packet_index) <= (old.batch_id, old.packet_index):
                    raise ValueError('A ' + label.lower() + ' packet cannot commit twice or out of order')
            rows.append(row); setattr(state, cursor, next_id + 1)


def validate_boundary(game, flows=(HealthFlow.DAMAGE, HealthFlow.HEALING)):
    """Bind both histories to the effective event inventory in one traversal."""
    expected = {flow: tuple((row.action, row.result) for row, _result in
        checked_rows(game._state, flow, game.registry)) for flow in flows}
    actual = {flow: [] for flow in flows}
    from .hero_health_history import effective_events
    for event in effective_events(game._events):
        if event.kind != 'health_resolved': continue
        result = health_result(event)
        for flow in flows:
            if related(result, flow): actual[flow].append((event.action, result.payload()))
    for flow in flows:
        if expected[flow] != tuple(actual[flow]):
            raise ValueError(_settings(flow)[4] + ' history lost its complete original settled event inventory')


def record_from_dict(value, flow):
    from .serialization import _row, _list
    record_type, _history, _cursor, _units, label = _settings(flow)
    row = _row(value, record_type)
    def freeze(item):
        return tuple(freeze(value) for value in item) if type(item) is list else item
    row['result'] = freeze(_list(row['result'], 'complete original ' + label.lower() + ' result'))
    return record_type(**row)


def rows_from_dict(value, flow):
    from .serialization import _integer, _list
    _record_type, history, cursor, _units, label = _settings(flow)
    _integer(value[cursor], 'next ' + label.lower() + ' identity', 1)
    value[history] = [record_from_dict(row, flow) for row in _list(value[history], label.lower() + ' history')]
