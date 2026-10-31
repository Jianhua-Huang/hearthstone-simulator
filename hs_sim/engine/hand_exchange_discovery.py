"""Two actual private discoveries and one atomic opposing hand exchange."""
from dataclasses import dataclass
from .effects import ChoiceOption,Effect,RequestChoice,_integer,_player
from .model import CardPreview,ChoicePurpose,Zone
from .pools import PoolQuery
from .zones import (CardReference,ChooseFromZone,reference_entity,reference_value,
    sample_zone_choices,source_exists,transfer_hand_cards)


def validate_reference(state,reference):
    reference_value(reference);entity=state.entities.get(reference.entity_id)
    if entity is None or reference.zone_epoch>entity.zone_epoch:
        raise ValueError('Hand exchange borrowed an unknown or future physical card')


@dataclass(frozen=True)
class DiscoverHandExchange(Effect):
    player_id:int
    source_id:int
    first:CardReference|None=None
    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'hand-exchange source',1)
        if self.first is not None:
            reference_value(self.first)
            if(self.first.zone,self.first.player_id)!=(Zone.HAND,self.player_id):
                raise ValueError('Second hand discovery lost its original own-hand selection')
    def validate_in_state(self,state):
        self.__post_init__()
        if self.source_id not in state.entities:raise ValueError('Hand exchange has an unknown original source')
        if self.first is not None:validate_reference(state,self.first)


@dataclass(frozen=True)
class SelectHandExchange(Effect):
    request:DiscoverHandExchange
    card:CardReference
    @property
    def player_id(self):return self.request.player_id
    @property
    def source_id(self):return self.request.source_id
    @property
    def card_id(self):return self.card.card_id
    def __post_init__(self):
        if type(self.request)is not DiscoverHandExchange:raise ValueError('Hand selection requires its typed original request')
        self.request.__post_init__();reference_value(self.card)
        owner=self.player_id if self.request.first is None else 3-self.player_id
        if(self.card.zone,self.card.player_id)!=(Zone.HAND,owner):raise ValueError('Hand exchange borrowed another hand or stage')
    def validate_in_state(self,state):
        self.__post_init__();self.request.validate_in_state(state);validate_reference(state,self.card)


def discover(r,request):
    request.validate_in_state(r.state);source_exists(r,request.source_id)
    if request.first is None:
        if not r.player(request.player_id).hand or not r.player(3-request.player_id).hand:return()
        owner=request.player_id
    else:
        if reference_entity(r,request.first)is None:return()
        owner=3-request.player_id
    sample=ChooseFromZone(request.player_id,owner,Zone.HAND,PoolQuery(),operation='take',distinct='entity',
        source_id=request.source_id,discovery=True)
    offered=sample_zone_choices(r,sample)
    if not offered:return()
    options=tuple(ChoiceOption('hand-exchange-'+str(i+1),r.registry.card(ref.card_id).name,
        (SelectHandExchange(request,ref),),card_id=ref.card_id,entity_id=ref.entity_id,
        preview=CardPreview.capture(r.state.entities[ref.entity_id],r.registry))for i,ref in enumerate(offered))
    return(RequestChoice(request.player_id,options,request.source_id,purpose=ChoicePurpose.CARD_DISCOVERY,
        prompt='发现要交换的本人手牌'if request.first is None else'发现要交换的对手手牌'),)


def validate_recipe(result,recipe):
    if type(recipe)is not SelectHandExchange:return
    recipe.__post_init__();selected=result.selected[0]
    if(selected.entity_id,selected.card_id)!=(recipe.card.entity_id,recipe.card.card_id):
        raise ValueError('Hand discovery changed its original physical selected face')


def materialize(r,recipe):
    recipe.validate_in_state(r.state)
    if recipe.request.first is None:return None,(DiscoverHandExchange(recipe.player_id,recipe.source_id,recipe.card),)
    own=reference_entity(r,recipe.request.first);other=reference_entity(r,recipe.card)
    if own is None or other is None:
        r.stale(recipe,recipe.request.first.entity_id if own is None else recipe.card.entity_id)
        return None,()
    transfer_hand_cards(r,((own,3-recipe.player_id),(other,recipe.player_id)),recipe.source_id)
    r.emit('hand_cards_exchanged',source_id=recipe.source_id,target_id=other.id,player_id=recipe.player_id,
        first_id=own.id,second_id=other.id,first_epoch=recipe.request.first.zone_epoch,second_epoch=recipe.card.zone_epoch,_capture=False)
    return other,()


def validate_completion(state,registry,completion):
    recipe=completion.recipe
    if type(recipe)is not SelectHandExchange:return
    recipe.validate_in_state(state);fact=completion.recipient
    if recipe.request.first is None:
        if fact is not None:raise ValueError('First hand selection cannot invent an acquisition')
        return
    if fact is not None and((fact.entity_id,fact.controller,fact.zone)!=(recipe.card.entity_id,recipe.player_id,Zone.HAND)or
            fact.zone_epoch<recipe.card.zone_epoch+1):raise ValueError('Hand discovery lost its actual transferred recipient')


def witnesses(recipe,window):
    if recipe.request.first is None:return[]
    result=[]
    for event in window:
        if(event.kind,event.source_id,event.player_id,event.target_id)!=('hand_cards_exchanged',recipe.source_id,recipe.player_id,recipe.card.entity_id):continue
        data=dict(event.data)
        if tuple(data.get(k)for k in('first_id','second_id','first_epoch','second_epoch'))!=(
                recipe.request.first.entity_id,recipe.card.entity_id,recipe.request.first.zone_epoch,recipe.card.zone_epoch):
            raise ValueError('Hand-exchange operation changed its original selected pair')
        result.append(event)
    return result


def direct_selection(r,effect):raise ValueError('Hand selection requires its original genuine discovery result')


def register(mechanics):
    mechanics.register(DiscoverHandExchange,discover)
    mechanics.register(SelectHandExchange,direct_selection)
