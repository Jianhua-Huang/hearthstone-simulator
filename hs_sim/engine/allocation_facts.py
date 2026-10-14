"""Minimal original physical allocation facts; never external authentication.

The closed boundary follows v142's exact field/bound policy. Live/captured states
still require their own physical entity; only the outer committed log may retain
a proved old identity removed by Retry. No later log is consulted by this module.
"""
from dataclasses import dataclass,fields
from .effects import _integer,_player
from .model import CardType,Zone,_name

@dataclass(frozen=True)
class SourceAllocationFact:
    entity_id:int
    card_id:str
    kind:CardType
    owner:int
    controller:int
    zone:Zone
    zone_epoch:int
    entered_order:int
    next_entity_id:int
    next_order:int

    def __post_init__(self):
        for n in ('entity_id','next_entity_id','next_order'):_integer(getattr(self,n),'original '+n,1)
        for n in ('zone_epoch','entered_order'):_integer(getattr(self,n),'original '+n,0)
        _name(self.card_id,'original allocated card');_player(self.owner);_player(self.controller)
        if type(self.kind) is not CardType or type(self.zone) is not Zone:raise ValueError('Unknown original allocation kind/zone')
        if self.entity_id>=self.next_entity_id or self.entered_order>=self.next_order:raise ValueError('Original identity exceeds its allocation bounds')

    @classmethod
    def capture(cls,state,entity):
        if entity is None:return None
        return cls(entity.id,entity.card_id,entity.kind,entity.owner,entity.controller,entity.zone,entity.zone_epoch,entity.entered_order,state.next_entity_id,state.next_order)

    def payload(self):return tuple((f.name,getattr(self,f.name)) for f in fields(self))

def allocation_from_payload(raw):
    if raw is None:return None
    if type(raw) is not tuple or any(type(r) is not tuple or len(r)!=2 or type(r[0]) is not str for r in raw):raise ValueError('Original allocation requires immutable fields')
    values=dict(raw)
    if len(values)!=len(raw) or set(values)!={f.name for f in fields(SourceAllocationFact)}:raise ValueError('Original allocation requires its complete declared fields')
    return allocation_from_dict(values)

def allocation_from_dict(values):
    if values is None:return None
    if type(values) is not dict or set(values)!={f.name for f in fields(SourceAllocationFact)}:raise ValueError('Original allocation requires exact fields')
    values=dict(values);values['kind']=CardType(values['kind']);values['zone']=Zone(values['zone'])
    return SourceAllocationFact(**values)

def validate_allocation(state,registry,value,*,closed=False):
    if type(value) is not SourceAllocationFact:raise ValueError('Expected complete original allocation fact')
    value.__post_init__()
    if registry.card(value.card_id).kind!=value.kind or value.next_entity_id>state.next_entity_id or value.next_order>state.next_order:
        raise ValueError('Original allocation has unregistered kind/future allocator bounds')
    entity=state.entities.get(value.entity_id)
    if entity is not None and entity.owner!=value.owner:raise ValueError('Original allocation has another physical owner')
    if not closed and (entity is None or value.zone_epoch>entity.zone_epoch):raise ValueError('Unknown/future physical allocation in its captured state')
