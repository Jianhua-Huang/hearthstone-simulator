"""Secret assignment to an actual original/copy pair; ordinary trigger lifecycle."""
from dataclasses import dataclass
from .effects import Effect,GrantTrigger,_behavior,_integer
from .sacrifice import MinionReference,reference_value,live_minion


@dataclass(frozen=True)
class MarkHiddenDamagePair(Effect):
    original:MinionReference
    copy:MinionReference
    fragile_behavior_id:str
    real_behavior_id:str
    source_id:int
    def __post_init__(self):
        reference_value(self.original);reference_value(self.copy)
        _behavior(self.fragile_behavior_id);_behavior(self.real_behavior_id);_integer(self.source_id,'hidden pair source',1)
        if self.original.entity_id==self.copy.entity_id or self.original.player_id!=self.copy.player_id:
            raise ValueError('Hidden damage pair requires two distinct same-player original bodies')
        if self.fragile_behavior_id==self.real_behavior_id:raise ValueError('Hidden damage outcomes must differ')


def mark_pair(r,effect):
    effect.__post_init__()
    for behavior in(effect.fragile_behavior_id,effect.real_behavior_id):r.registry.behavior(behavior)
    if effect.source_id not in r.state.entities:raise ValueError('Hidden pair source missing')
    chosen=r.game._rng.randrange(2)
    from .resolver import grant_ability
    # Validate each original residence before mutation. Both grants happen in
    # this one checkpoint; no grant reaction can rebind the other member.
    live=[live_minion(r.state,ref)for ref in(effect.original,effect.copy)]
    for i,entity in enumerate(live):
        if entity is not None:
            grant_ability(r,GrantTrigger(entity.id,'damage_dealt',effect.fragile_behavior_id if i==chosen else effect.real_behavior_id,effect.source_id))
    r.emit('hidden_damage_pair_marked',source_id=effect.source_id,original=effect.original.entity_id,
        copy=effect.copy.entity_id,selected_index=chosen,_capture=False)


def register(mechanics):mechanics.register(MarkHiddenDamagePair,mark_pair)
