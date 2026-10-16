"""Native stored Deathrattles enter the existing interpreter from actual facts."""
from .model import CardType,Zone


def original_retirement(state,event):
    if event is None:
        raise ValueError('Stored Deathrattle requires its original retirement event')
    if event.kind=='card_discarded':
        from .discard_history import _validate_event
        rows=[x for x in state.discard_history if x.event_sequence==event.sequence]
        if len(rows)!=1:raise ValueError('Stored Deathrattle lost its original physical discard')
        row=rows[0];_validate_event(row,event)
        return(row.entity_id,row.player_id,row.card.owner,row.card_id,row.kind,
               row.card.zone_epoch+1,row.turn,row.action,row.source_id)
    if event.kind in('card_destroyed_in_hand','card_destroyed_in_deck','card_burned'):
        from .zones import destruction_result
        row=destruction_result(event)
        if row is None:raise ValueError('Stored Deathrattle lacks an actual supported destruction')
        return(row.card.entity_id,row.player_id,row.owner_id,row.card.card_id,row.kind,
               row.after_epoch,row.turn,row.action,row.source_id)
    raise ValueError('This event does not retire a stored Deathrattle card')


def validate_carrier(state,registry,event):
    eid,player,owner,cid,kind,epoch,turn,action,source=original_retirement(state,event)
    entity=state.entities.get(eid);definition=registry.card(cid)
    if not definition.stored_deathrattle or kind!=CardType.MINION:
        raise ValueError('Stored Deathrattle is not declared by this original card')
    if (entity is None or (entity.controller,entity.owner,entity.card_id,entity.kind,entity.zone,entity.zone_epoch)!=
            (player,owner,cid,kind,Zone.GRAVEYARD,epoch)or entity.components or
            (state.turn,state.action_number)!=(turn,action)):
        raise ValueError('Stored Deathrattle lost its original after-retirement carrier')
    if source is not None and source not in state.entities:
        raise ValueError('Stored Deathrattle lost its original disposing source')
    return entity,source


def validate_context(context,registry):
    entity,source=validate_carrier(context.state,registry,context.event)
    capture=context.deathrattle
    if (capture is None or capture.origin!='stored' or context.death is not None or
            (context.source_id,context.player_id,capture.card_id,capture.trigger_source_id)!=
            (entity.id,entity.controller,entity.card_id,source)or capture.trigger_index!=1):
        raise ValueError('Stored Deathrattle context differs from its original retirement')


def capture_group(r,event):
    entity,source=validate_carrier(r.state,r.registry,event)
    from .lifecycle import active_abilities
    from .deathrattles import schedule_group
    return tuple(schedule_group(r,entity.id,entity.controller,tuple(active_abilities(entity,'deathrattle')),
        event=event,trigger_source_id=source,origin='stored'))
