"""Immutable successful hand acquisitions; opening hands predate turn one."""
from .model import HandEntryRecord, Zone


def enter_hand(state, entity, from_zone=None, reason='move'):
    if entity.zone != Zone.HAND:
        raise ValueError('Hand history requires a successful entry')
    turn = 0 if reason == 'scenario' or state.opening is not None and state.opening.stage != 'complete' else state.turn
    from .held_spells import reset_entry
    reset_entry(entity)
    from .held_mana import reset_entry as reset_mana_entry
    reset_mana_entry(entity)
    from .held_opponent_copies import reset_entry as reset_copy_entry
    reset_copy_entry(entity)
    from .held_higher_cost import reset_entry as reset_higher_cost_entry
    reset_higher_cost_entry(entity)
    record = HandEntryRecord(len(state.hand_entries)+1, entity.id, entity.controller, entity.card_id,
                             turn, state.action_number, entity.zone_epoch, from_zone, reason)
    state.hand_entries.append(record)
    entity.hand_entry_id = record.id
    return record


def hand_entry(state, entry_id):
    if type(entry_id) is not int or not 1 <= entry_id <= len(state.hand_entries):
        raise ValueError('Missing hand acquisition record')
    return state.hand_entries[entry_id-1]


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
                record.zone_epoch > entity.zone_epoch):
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
