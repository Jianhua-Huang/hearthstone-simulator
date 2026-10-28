"""Original dead minion hand returns through the existing movement lifecycle."""
from dataclasses import dataclass
from .allocation_facts import SourceAllocationFact,validate_allocation
from .death_self_copies import validate_death_source
from .effects import Effect,_integer
from .errors import ResolutionError
from .hand_capacity import hand_capacity
from .lifecycle import reset_to_definition
from .model import CardType,CostSpec,Zone
from .summon_sources import death_record


def event_death(state,event,player_id,*,require_grave=True):
    """The original owner death notification, never a later same-name body."""
    if event is None or event.kind!='minion_died' or event.player_id!=player_id:return None
    data=dict(event.data);death=death_record(state,data['death_id'])
    if (event.source_id,event.player_id,data['batch'],data['position'])!=(
            death.entity_id,death.controller,death.batch,death.position):
        raise ValueError('Death return lost its original notification')
    if death.zone!=Zone.BOARD:return None
    if death.copy_source is None:raise ValueError('Original death return requires complete frozen minion facts')
    origin=death.copy_source.origin
    if origin.kind!=CardType.MINION:return None
    if type(require_grave)is not bool:raise ValueError('Original death residence policy requires bool')
    if not require_grave:return death
    e=state.entities.get(death.entity_id)
    if e is None or (e.owner,e.controller,e.card_id,e.kind,e.zone,e.zone_epoch,e.entered_order)!=(
            origin.owner,origin.controller,origin.card_id,CardType.MINION,Zone.GRAVEYARD,origin.zone_epoch+1,origin.entered_order):return None
    return death


@dataclass(frozen=True)
class ReturnDeadMinion(Effect):
    death_id: int
    card: SourceAllocationFact
    source: SourceAllocationFact
    cost_reduction: int = 0

    def __post_init__(self):
        _integer(self.death_id,'original returned death',1);_integer(self.cost_reduction,'dead return cost reduction',0)
        for value in (self.card,self.source):
            if type(value) is not SourceAllocationFact:raise ValueError('Dead return requires complete original physical facts')
            value.__post_init__()
        if (self.card.kind,self.card.zone)!=(CardType.MINION,Zone.GRAVEYARD) or self.source.controller!=self.card.controller:
            raise ValueError('Dead return requires its original friendly graveyard minion')

    def validate_in_state(self,state,registry):
        self.__post_init__()
        validate_allocation(state,registry,self.card);validate_allocation(state,registry,self.source)
        try:death=death_record(state,self.death_id)
        except ResolutionError as exc:raise ValueError('Dead hand return lost its original death identity') from exc
        validate_death_source(death,state,registry)
        if death.zone!=Zone.BOARD or death.copy_source is None:
            raise ValueError('Dead hand return needs its complete original minion death')
        origin=death.copy_source.origin
        if (self.card.entity_id,self.card.card_id,self.card.owner,self.card.controller,self.card.zone_epoch,self.card.entered_order)!=(
                death.entity_id,death.card_id,death.owner,death.controller,origin.zone_epoch+1,origin.entered_order) or origin.kind!=CardType.MINION:
            raise ValueError('Dead hand return borrowed another death or graveyard lifetime')
        if self.card.next_entity_id<origin.next_entity_id or self.card.next_order<origin.next_order:
            raise ValueError('Dead hand return predates its original death')


def return_minion(r,effect):
    effect.validate_in_state(r.state,r.registry)
    fact=effect.card;entity=r.state.entities[fact.entity_id]
    if (entity.owner,entity.controller,entity.card_id,entity.kind,entity.zone,entity.zone_epoch,entity.entered_order)!=(
            fact.owner,fact.controller,fact.card_id,fact.kind,fact.zone,fact.zone_epoch,fact.entered_order):
        r.emit('zone_target_skipped',target_id=fact.entity_id,reason='captured_death_departed');return ()
    player=r.player(fact.controller)
    if len(player.hand)>=hand_capacity(player,r.rules):
        original=SourceAllocationFact.capture(r.state,entity)
        r.move(entity,Zone.GRAVEYARD,hand_entry_reason=None);r.refresh_auras()
        from .zones import emit_burn
        emit_burn(r,entity,profile='graveyard_delivery_overflow',original=original,
            source_id=effect.source.entity_id,player_id=player.id,reason='return_hand_full')
        return ()
    # Match ordinary return's acquisition order; install the discount before listeners.
    r.move(entity,Zone.HAND,hand_entry_reason=None)
    from .hand_history import enter_hand,publish
    enter_hand(r.state,entity,Zone.GRAVEYARD,'return',source_id=effect.source.entity_id)
    reset_to_definition(r.state,entity,r.registry.card(entity.card_id),r.registry,preserve_jade=True,preserve_cthun=True)
    if effect.cost_reduction:
        from .zones import CardReference,ModifyStoredCost,modify_stored_cost
        modify_stored_cost(r,ModifyStoredCost(CardReference.capture(entity),CostSpec(delta=-effect.cost_reduction),effect.source.entity_id))
    r.refresh_auras()
    r.emit('card_returned',source_id=effect.source.entity_id,target_id=entity.id,player_id=player.id)
    publish(r,entity.hand_entry_id)
    return ()


def register(mechanics):mechanics.register(ReturnDeadMinion,return_minion)
