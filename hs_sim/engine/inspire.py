"""Shared after-use condition, backed by frozen activation history (R-111)."""
from .hero_powers import power_record
from .model import Event, _int


def completed_manual_power(state, event):
    """Return the completed manual activation, or None for unrelated events.

    This validates engine event/history consistency, not external authenticity.
    It never infers a use from the currently installed power or its counters.
    Malformed completion events raise rather than silently spending a trigger.
    """
    if event is None:
        return None
    if type(event) is not Event:
        raise ValueError('Power completion requires Event')
    if event.kind != 'hero_power_used':
        return None
    if (type(event.data) is not tuple or len(event.data) != 1 or
            type(event.data[0]) is not tuple or len(event.data[0]) != 2 or
            event.data[0][0] != 'power_id'):
        raise ValueError('Power completion requires exactly one activation reference')
    record = power_record(state, event.data[0][1])
    record.__post_init__()
    _int(event.sequence, 'completion sequence', 1)
    _int(event.action, 'completion action', 0)
    _int(event.source_id, 'completion source', 1)
    _int(event.player_id, 'completion player', 1)
    _int(event.amount, 'completion amount', 0)
    if event.target_id is not None:
        _int(event.target_id, 'completion target', 1)
    if (record.origin != 'manual' or not record.completed or record.interrupted or record.failure is not None or
            (event.source_id, event.target_id, event.player_id, event.amount) !=
            (record.source_id, record.target_id, record.player_id, 0) or
            not record.action <= event.action <= state.action_number):
        raise ValueError('Power completion event and activation disagree')
    return record


def is_inspire(state, event, player_id):
    """Owner's successful manual completion, usable by ordinary/limited triggers."""
    _int(player_id, 'Inspire controller', 1)
    if player_id not in (1, 2):
        raise ValueError('Invalid Inspire controller')
    record = completed_manual_power(state, event)
    return record is not None and record.player_id == player_id
