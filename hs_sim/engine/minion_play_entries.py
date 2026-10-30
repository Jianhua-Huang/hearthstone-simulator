"""One physical hand-play entry, frozen before entry reactions and Battlecry.

This compact fact is part of the original PlayRecord, not another play history.
Exact secret eligibility windows and dormant membership remain local policies.
"""
from .model import BoardPresenceReference, CardType, MinionPlayEntry


def other_minions(state, player_id):
    return tuple(BoardPresenceReference.capture(state, ident)
        for ident in state.players[player_id].board
        if (state.entities[ident].kind == CardType.MINION and state.entities[ident].active
            and state.entities[ident].health > 0 and not state.entities[ident].doomed))


def accept_entry(state, record, entity_id, original_others):
    from .play_history import update_play
    entry = MinionPlayEntry(BoardPresenceReference.capture(state, entity_id), original_others)
    update_play(state, record.id, minion_result='summoned', minion_entry=entry)
    return entry


def validate_entry(state, record):
    entry = record.minion_entry
    if entry is None:
        return
    entry.__post_init__()
    for ref in (entry.reference, *entry.other_minions):
        if ref.entity_id not in state.entities or ref.presence_id >= state.next_order:
            raise ValueError('Minion play entry borrowed an unknown or future board residence')


def event_data(entry):
    return dict(_entry_presence_id=entry.reference.presence_id,
        _entry_other_minions=tuple((ref.entity_id, ref.presence_id) for ref in entry.other_minions))


def validate_boundary(game):
    from .play_history import play_record
    from .hero_health_history import effective_events
    accepted = {}
    for event in effective_events(game.events):
        if event.kind != 'minion_play_accepted':
            continue
        data = dict(event.data)
        record = play_record(game._state, data.get('play_id'))
        # A committed hand play may enter after a choice resumes on a later
        # action. Keep its original play identity and reject pre-play entries.
        if (record.id in accepted or record.kind != CardType.MINION or
                (event.source_id, event.player_id) != (record.source_id, record.player_id) or
                event.action < record.action):
            raise ValueError('Minion entry event differs from its original physical hand play')
        accepted[record.id] = event
        if record.minion_entry is None:
            if record.minion_result != 'magnetized' or any(k.startswith('_entry_') for k in data):
                raise ValueError('Non-entry minion result borrowed an entry event')
        elif (event.target_id != record.source_id or
                any(data.get(key) != value for key, value in event_data(record.minion_entry).items())):
            raise ValueError('Minion entry event lost its original recipient or other minions')
    for record in game._state.play_history:
        if (record.minion_entry is not None) != (record.id in accepted and record.minion_result == 'summoned'):
            raise ValueError('Original minion play entry lost its unique acceptance event')
