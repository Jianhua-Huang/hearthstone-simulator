"""Freeze a successful minion discard at its original reactive event.

The later summon accepts its own quantity plan. Neither that acceptance nor
earlier listeners are permitted to recapture the live discarded entity.
"""
from .copy_materials import CopyEntryMaterial
from .discard_history import _validate_event, validate_base_copy
from .model import CardType, Zone


def capture(context, registry):
    """Return the original own minion material, or None for another event."""
    from .registry import RuleContext
    if type(context) is not RuleContext:
        raise ValueError('Discard summon requires its original RuleContext')
    event = context.event
    if event is None or event.kind != 'card_discarded' or event.player_id != context.player_id:
        return None
    rows = tuple(row for row in context.state.discard_history if row.event_sequence == event.sequence)
    if len(rows) != 1:
        raise ValueError('Discard summon lost its exact original successful occurrence')
    row = rows[0]
    _validate_event(row, event)
    if row.kind != CardType.MINION:
        return None
    validate_base_copy(context.state, registry, row)
    source = context.state.entities[row.entity_id]
    if (context.state.turn, context.state.action_number, source.zone, source.zone_epoch, source.components) != (
            row.turn, row.action, Zone.GRAVEYARD, row.card.zone_epoch + 1, row.components):
        raise ValueError('Discard summon must capture the original event state and material')
    return CopyEntryMaterial.capture(context.state, source, 'discard_summon_copy', 'current',
                                     registry=registry, player_id=row.player_id, discard=row)
