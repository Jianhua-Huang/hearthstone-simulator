"""Join complete original fixed requests to their exact successful deliveries."""
from dataclasses import replace
from .owner_turns import validate_accepted_prefix
from .summon_quantities import SummonCause,SummonEntryMaterial


def root_prefix(before,after):
    if len(before.card_summon_history)>len(after.card_summon_history):raise ValueError('Original summon group lost its producer prefix')
    for old,new in zip(before.card_summon_history,after.card_summon_history):
        if replace(new,deliveries=old.deliveries,status=old.status)!=old or len(new.deliveries)<len(old.deliveries):
            raise ValueError('Original summon group changed an original producer')
        for a,b in zip(old.deliveries,new.deliveries):
            if replace(b,followup_started=a.followup_started)!=a or a.followup_started and not b.followup_started:
                raise ValueError('Original summon group rewrote an original delivery')


def recipients(original,accepted,registry,card_id,requests=2):
    if type(requests)is not int or requests<1:raise ValueError('Fixed summon group requires a positive original request count')
    validate_accepted_prefix(original.state,accepted.state,registry);root_prefix(original.state,accepted.state)
    cause=SummonCause.capture(original);material=(SummonEntryMaterial(card_id),)
    roots=[x for x in accepted.state.card_summon_history[len(original.state.card_summon_history):]
        if x.request.cause==cause and x.request.materials==material]
    if len(roots)!=requests or any(x.status not in('completed','skipped')for x in roots):
        raise ValueError('Original summon group requires every original completed fixed request')
    result=[]
    for root in roots:
        root.__post_init__()
        for delivery in root.deliveries:
            if delivery.entity is None:continue
            entity=delivery.entity
            matches=[x for x in accepted.state.successful_summon_history if(x.entity_id,x.minion.zone_epoch,x.minion.entered_order)==
                (entity.entity_id,entity.zone_epoch,entity.entered_order)]
            if len(matches)!=1 or matches[0].player_id!=original.player_id:raise ValueError('Original summon group lost its exact successful entry')
            result.append(matches[0].id)
    if len(result)!=len(set(result)):raise ValueError('Original summon group duplicated an original recipient')
    return tuple(result)
