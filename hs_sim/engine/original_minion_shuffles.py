"""Original physical board/death transfers through one ordinary deck writer."""
from dataclasses import dataclass,replace

from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Effect,_player,_source
from .errors import ResolutionError
from .model import CardType,DeathRecord,Zone


@dataclass(frozen=True)
class ShuffleOriginalMinion(Effect):
    card:SourceAllocationFact
    player_id:int
    source_id:int|None=None
    death:DeathRecord|None=None
    keep_enchantments:bool=False

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id)
        if type(self.card)is not SourceAllocationFact or type(self.keep_enchantments)is not bool:
            raise ValueError('Original shuffle requires its complete allocation and material policy')
        self.card.__post_init__();fact=self.card
        if fact.kind!=CardType.MINION or fact.zone not in(Zone.BOARD,Zone.GRAVEYARD):
            raise ValueError('Original shuffle requires a board or original dead minion')
        if self.keep_enchantments and self.player_id!=fact.controller:
            raise ValueError('Retained-enchantment shuffle requires the original controller deck')
        if fact.zone==Zone.GRAVEYARD:
            from .dead_minion_shuffles import ShuffleDeadMinion
            ShuffleDeadMinion(fact,self.death,fact.controller,self.source_id).__post_init__()
        elif self.death is not None:
            raise ValueError('Live original shuffle cannot borrow a death record')

    def validate_in_state(self,state):
        self.__post_init__();fact=self.card;entity=state.entities.get(fact.entity_id)
        if (entity is None or fact.next_entity_id>state.next_entity_id or fact.next_order>state.next_order or
                fact.zone_epoch>entity.zone_epoch or fact.owner!=entity.owner):
            raise ValueError('Original shuffle has unknown or future physical allocation')
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Original shuffle has an unknown issuer')
        if self.death is not None and next((d for d in state.death_history if d.id==self.death.id),None)!=self.death:
            raise ValueError('Original shuffle changed its committed death')


def from_context(c,player_id,*,keep_enchantments=False):
    source=c.state.entities.get(c.source_id)
    if source is None:raise ResolutionError('Original shuffle lost its physical source')
    fact=SourceAllocationFact.capture(c.state,source);death=c.death
    if death is not None:
        if death.entity_id!=c.source_id:raise ResolutionError('Self shuffle borrowed another death source')
        fact=replace(fact,card_id=death.card_id,kind=CardType.MINION,owner=death.owner,
            controller=death.controller,zone=Zone.GRAVEYARD,zone_epoch=death.cause.target_zone_epoch+1,
            entered_order=death.cause.target_entered_order)
    else:
        fact=SourceAllocationFact.capture(c.state,c.source)
        if fact.kind!=CardType.MINION or fact.zone!=Zone.BOARD:return None
    return ShuffleOriginalMinion(fact,player_id,c.source_id,death,keep_enchantments)


def validate_request(state,registry,request):
    request.__post_init__();fact=request.card
    if fact.zone==Zone.GRAVEYARD:
        from .dead_minion_shuffles import ShuffleDeadMinion,validate_request as validate_dead
        validate_dead(state,registry,ShuffleDeadMinion(fact,request.death,fact.controller,request.source_id))
    else:
        validate_allocation(state,registry,fact)
        definition=registry.card(fact.card_id)
        if definition.kind!=CardType.MINION or not definition.hand_playable or definition.interactable:
            raise ValueError('Original shuffle requires its registered physical minion')
        if request.source_id is not None and request.source_id not in state.entities:
            raise ValueError('Original shuffle issuer is unknown')


def shuffle(r,request,*,reported_request=None):
    try:validate_request(r.state,r.registry,request)
    except ValueError as exc:raise ResolutionError(str(exc))from exc
    fact=request.card;entity=r.state.entities[fact.entity_id]
    if (entity.card_id,entity.kind,entity.owner,entity.controller,entity.zone,entity.zone_epoch,entity.entered_order)!=(
            fact.card_id,fact.kind,fact.owner,fact.controller,fact.zone,fact.zone_epoch,fact.entered_order):
        r.stale(request if reported_request is None else reported_request,entity.id);return
    if fact.zone==Zone.BOARD and(not entity.active or entity.health<=0 or entity.doomed):
        r.stale(request if reported_request is None else reported_request,entity.id);return
    from .deck_capacity import admits,failure
    if not admits(r.state,request.player_id,entity):
        if fact.zone==Zone.BOARD:
            from .death_causes import mark
            mark(r,entity,'destroy','ShuffleOriginalMinion_full');entity.doomed=True;r.refresh_auras()
        failure(r,request.player_id,entity.card_id,request.source_id,original=fact);return
    kept=replace(entity,enchantments=list(entity.enchantments),abilities=list(entity.abilities))if request.keep_enchantments else None
    from .lifecycle import reset_to_definition
    reset_to_definition(r.state,entity,r.registry.card(fact.card_id),r.registry,
        preserve_jade=True,preserve_cthun=fact.controller==request.player_id)
    if kept is not None:
        from .zones import copy_current_stored_state
        copy_current_stored_state(r.state,kept,entity,retain_ids=True)
        entity.damage=0
    player=r.player(request.player_id);position=r.game._rng.randrange(len(player.deck)+1)
    r.move(entity,Zone.DECK,position,controller_id=player.id)
    if fact.controller!=player.id:
        from .cthun import initialize_instance
        initialize_instance(r.state,r.registry,entity)
    r.refresh_auras()
    r.emit('card_shuffled',source_id=request.source_id,target_id=entity.id,
        player_id=player.id,position=position,_deck_insertion_mode='random')


def register(mechanics):mechanics.register(ShuffleOriginalMinion,shuffle)
