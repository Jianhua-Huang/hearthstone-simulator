"""Immutable successful hand acquisitions; opening hands predate turn one."""
from dataclasses import asdict
from .model import HandEntryRecord, Zone

EVENT = 'hand_card_entered'


def enter_hand(state, entity, from_zone=None, reason='move', *, source_id=None):
    if entity.zone != Zone.HAND:
        raise ValueError('Hand history requires a successful entry')
    if source_id is not None and (type(source_id) is not int or source_id not in state.entities):
        raise ValueError('Hand acquisition source must be an existing physical entity')
    turn = 0 if reason == 'scenario' or state.opening is not None and state.opening.stage != 'complete' else state.turn
    record = HandEntryRecord(len(state.hand_entries)+1, entity.id, entity.controller, entity.card_id,
                             turn, state.action_number, entity.zone_epoch, from_zone, reason, source_id)
    from .held_spells import reset_entry
    reset_entry(entity)
    from .held_mana import reset_entry as reset_mana_entry
    reset_mana_entry(entity)
    from .held_opponent_copies import reset_entry as reset_copy_entry
    reset_copy_entry(entity)
    from .held_higher_cost import reset_entry as reset_higher_cost_entry
    reset_higher_cost_entry(entity)
    state.hand_entries.append(record)
    entity.hand_entry_id = record.id
    return record


def hand_entry(state, entry_id):
    if type(entry_id) is not int or not 1 <= entry_id <= len(state.hand_entries):
        raise ValueError('Missing hand acquisition record')
    return state.hand_entries[entry_id-1]


def publication_data(record):
    from .serialization import canonical_hash
    return dict(hand_entry_id=record.id, hand_entry_hash=canonical_hash(asdict(record)))


def publish(r, entry_id):
    """Publish only from the original completed delivery, never from a callback."""
    record = hand_entry(r.state, entry_id)
    if record.reason == 'scenario':
        return None
    return r.emit(EVENT, source_id=record.source_id, target_id=record.entity_id,
        player_id=record.player_id, _hand_entry_record=record)


def prepare_publication(r, record, source_id, target_id, player_id, amount, capture):
    # Keep the acquisition immutable, including in previously captured states.
    # The original event binds the full row; the outer boundary requires a
    # bijection. Consult the actual log, so rewind cannot leave a stale cache.
    if type(record) is not HandEntryRecord:
        raise ValueError('Hand notification requires its original immutable acquisition')
    original = hand_entry(r.state, record.id)
    entity = r.state.entities[record.entity_id]
    from .hero_health_history import effective_events
    if (record != original or record.reason == 'scenario' or capture is not True or
            (source_id, target_id, player_id, amount, capture) !=
                (record.source_id, record.entity_id, record.player_id, 0, True) or
            (entity.zone, entity.controller, entity.hand_entry_id) != (Zone.HAND, record.player_id, record.id) or
            any(e.kind == EVENT and dict(e.data).get('hand_entry_id') == record.id for e in effective_events(r.game._events))):
        raise ValueError('Hand notification lost its original successful delivery window')
    return publication_data(record)


def from_event(state, event):
    from .model import Event
    if type(event) is not Event or event.kind != EVENT:
        raise ValueError('Expected original successful hand notification')
    data = dict(event.data)
    record = hand_entry(state, data.get('hand_entry_id'))
    if (record.reason == 'scenario' or
            (event.source_id, event.target_id, event.player_id, event.action, event.amount) !=
                (record.source_id, record.entity_id, record.player_id, record.action, 0) or
            data != publication_data(record)):
        raise ValueError('Hand notification changed its original acquisition or source')
    return record


def validate_context(context, origin_state=None, origin_events=None):
    if context.event is None or context.event.kind != EVENT:
        return
    record = from_event(context.state, context.event)
    if origin_state is not None and hand_entry(origin_state, record.id) != record:
        raise ValueError('Hand callback substituted its original physical acquisition')
    if origin_events is not None:
        from .hero_health_history import effective_events
        if (context.event.sequence > len(origin_events) or origin_events[context.event.sequence-1] != context.event or
                not any(e.sequence == context.event.sequence for e in effective_events(origin_events))):
            raise ValueError('Hand callback lost its actual current-timeline notification')


def validate_publications(game):
    from .hero_health_history import effective_events
    seen = set()
    for event in effective_events(game._events):
        if event.kind == EVENT:
            record = from_event(game._state, event)
            if record.id in seen:
                raise ValueError('Duplicate successful hand notification')
            seen.add(record.id)
    expected = {x.id for x in game._state.hand_entries if x.reason != 'scenario'}
    if seen != expected:
        raise ValueError('Successful hand acquisition lacks its original notification')


def validate_hand_history(state, registry):
    if type(state.hand_entries) is not list:
        raise ValueError('Hand history must be a list')
    latest={};last_turn=last_action=0
    for index,record in enumerate(state.hand_entries,1):
        if type(record) is not HandEntryRecord:
            raise ValueError('Expected immutable hand entry')
        record.__post_init__()
        entity=state.entities.get(record.entity_id)
        if (record.id != index or entity is None or not registry.card(record.card_id).hand_playable or
                not last_turn <= record.turn <= state.turn or not last_action <= record.action <= state.action_number or
                record.zone_epoch > entity.zone_epoch or
                record.source_id is not None and record.source_id not in state.entities):
            raise ValueError('Invalid hand acquisition chronology or provenance')
        latest[record.entity_id]=record
        last_turn,last_action=record.turn,record.action
    for entity in state.entities.values():
        record=latest.get(entity.id)
        if (entity.hand_entry_id != (record.id if record else None) or
                entity.zone == Zone.HAND and (record is None or record.player_id != entity.controller)):
            raise ValueError('Entity and latest hand acquisition disagree')
        if entity.hand_entry_id is not None and type(entity.hand_entry_id) is not int:
            raise ValueError('Invalid hand acquisition pointer')
