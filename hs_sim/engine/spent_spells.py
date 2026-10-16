"""Return an original captured spent spell through ordinary hand acquisition."""
from dataclasses import dataclass
from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Effect,_player
from .errors import ResolutionError
from .hand_capacity import hand_capacity
from .lifecycle import reset_to_definition
from .model import CardType,Zone


@dataclass(frozen=True)
class ReturnSpentSpell(Effect):
    card:SourceAllocationFact
    player_id:int
    def __post_init__(self):
        _player(self.player_id)
        if type(self.card)is not SourceAllocationFact:raise ValueError('Spent spell return requires its original allocation')
        self.card.__post_init__()
        if(self.card.kind,self.card.zone,self.card.controller)!=(CardType.SPELL,Zone.GRAVEYARD,self.player_id):
            raise ValueError('Spent spell return requires its original caster graveyard position')


def return_spell(r,request):
    request.__post_init__();validate_allocation(r.state,r.registry,request.card)
    fact=request.card;entity=r.state.entities[fact.entity_id];definition=r.registry.card(fact.card_id)
    if not definition.hand_playable or definition.kind!=CardType.SPELL:raise ResolutionError('Spent return requires a playable registered spell')
    if(entity.card_id,entity.kind,entity.owner,entity.controller,entity.zone,entity.zone_epoch,entity.entered_order)!=(
            fact.card_id,fact.kind,fact.owner,fact.controller,fact.zone,fact.zone_epoch,fact.entered_order):
        r.stale(request,entity.id);return ()
    reset_to_definition(r.state,entity,definition,r.registry)
    player=r.player(request.player_id)
    if len(player.hand)>=hand_capacity(player,r.rules):
        from .zones import emit_burn
        r.move(entity,Zone.GRAVEYARD,hand_entry_reason=None);r.refresh_auras()
        emit_burn(r,entity,profile='graveyard_delivery_overflow',original=fact,source_id=entity.id,player_id=player.id,reason='return_hand_full')
        return ()
    r.move(entity,Zone.HAND,hand_entry_reason='return');r.refresh_auras()
    r.emit('card_returned',source_id=entity.id,target_id=entity.id,player_id=player.id)
    return ()


def register(mechanics):mechanics.register(ReturnSpentSpell,return_spell)
