"""Captured two-minion Health exchange through the ordinary stat setter."""
from dataclasses import dataclass

from .effects import Effect,SetStats,_source
from .model import CardType
from .sacrifice import MinionReference,live_minion,reference_value


@dataclass(frozen=True)
class SwapCapturedMinionHealth(Effect):
    first: MinionReference
    second: MinionReference
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.first);reference_value(self.second);_source(self.source_id)
        if self.first.entity_id==self.second.entity_id:
            raise ValueError('Health exchange requires two distinct original minions')

    def validate_in_state(self,state,registry=None):
        self.__post_init__()
        for ref in(self.first,self.second):
            entity=state.entities.get(ref.entity_id)
            if entity is None or ref.zone_epoch>entity.zone_epoch or ref.entered_order>=state.next_order:
                raise ValueError('Health exchange borrowed an unknown or future minion allocation')
            if registry is not None and registry.card(ref.card_id).kind!=CardType.MINION:
                raise ValueError('Health exchange requires original minion definitions')
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Health exchange has an unknown original source')


def swap(r,effect):
    effect.validate_in_state(r.state,r.registry)
    first=live_minion(r.state,effect.first);second=live_minion(r.state,effect.second)
    if first is None or second is None:
        r.stale(effect,effect.first.entity_id if first is None else effect.second.entity_id)
        return()
    values=(first.health,second.health);pending=[]
    from .resolver import _set_stats_on_entity
    _set_stats_on_entity(r,SetStats(first.id,health=values[1],source_id=effect.source_id),first,pending_events=pending)
    _set_stats_on_entity(r,SetStats(second.id,health=values[0],source_id=effect.source_id),second,pending_events=pending)
    # Both ordinary attachments exist before either public notification or any
    # reaction. The interpreter retains its normal death/choice checkpoints.
    for name,data in pending:r.emit(name,**data)
    return()


def register(mechanics):mechanics.register(SwapCapturedMinionHealth,swap)
