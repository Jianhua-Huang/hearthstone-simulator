"""Two actual ingredient choices, with curated inventories independent of adapters.

The source pool, printed budget, small-pool and discount windows are explicit.
An undeclared/incomplete pool is unsupported, never a reduced executable subset.
"""
from copy import deepcopy
from dataclasses import asdict,dataclass,fields,replace
from random import Random
import json

from .crafted_faces import CraftedMinionRecipe,native_domains,validate_blueprint,validate_part_shape
from .costs import quote_generated_cost
from .effects import AddToHand,ChoiceOption,Effect,RequestChoice,_player,_source
from .model import (CardType,ChoicePurpose,ChoiceResult,CostSpec,GameState,_int,_name,
    validate_end_turn_rng,validate_invariants)
from .pool_offers import preview
from .pools import GenerationContext,PoolCard,sample_candidates
from .registry import UnsupportedDefinitionError
from .serialization import canonical_hash,state_to_dict,end_turn_rng_to_json
from .tribes import has_any_tribe


@dataclass(frozen=True)
class CraftMinion(Effect):
    player_id:int
    template_card_id:str
    first_pool_id:str
    second_pool_id:str
    source_id:int
    max_total_cost:int=10
    discount_tribe:str|None=None
    discount_amount:int=0
    max_part_cost:int|None=None

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id)
        if self.source_id is None:raise ValueError('Crafting requires its original physical source')
        for key in('template_card_id','first_pool_id','second_pool_id'):_name(getattr(self,key),'craft '+key)
        _int(self.max_total_cost,'craft printed budget',1);_int(self.discount_amount,'craft discount',0)
        if self.discount_tribe is not None:_name(self.discount_tribe,'craft held tribe')
        if self.max_part_cost is not None:_int(self.max_part_cost,'craft printed ingredient budget',0)


@dataclass(frozen=True)
class CraftOffer:
    spec:CraftMinion
    before:GameState
    stage:int
    first_card_id:str|None
    candidates:tuple[str,...]
    offered:tuple[str,...]
    rng_before:tuple
    rng_after:tuple
    discount:int
    event_id:int
    parent:'CraftOffer|None'=None
    first_result:ChoiceResult|None=None

    def __post_init__(self):
        if type(self.spec)is not CraftMinion or type(self.before)is not GameState:raise ValueError('Crafting requires its typed original acceptance')
        self.spec.__post_init__();_int(self.stage,'craft stage',1);_int(self.event_id,'craft acceptance event',1)
        if self.stage not in(1,2):raise ValueError('Crafting requires exactly two stages')
        for key in('candidates','offered'):
            values=getattr(self,key)
            if type(values)is not tuple or not values or any(type(c)is not str or not c for c in values)or len(values)!=len(set(values)):
                raise ValueError('Craft inventories require complete ordered unique identities')
        if len(self.offered)>3 or not set(self.offered)<=set(self.candidates):raise ValueError('Craft offers lost their original candidate inventory')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        if type(self.discount)is not int or self.discount not in(0,self.spec.discount_amount):raise ValueError('Craft discount changed its accepted amount')
        if self.stage==1:
            if any(v is not None for v in(self.first_card_id,self.parent,self.first_result)):raise ValueError('First craft stage cannot borrow a prior choice')
        elif (type(self.parent)is not CraftOffer or self.parent.stage!=1 or self.parent.parent is not None or
                self.parent.spec!=self.spec or type(self.first_result)is not ChoiceResult or self.first_card_id not in self.parent.offered):
            raise ValueError('Second craft stage requires its actual first selection')


@dataclass(frozen=True)
class ResolveCraft(Effect):
    offer:CraftOffer
    card_id:str
    result:ChoiceResult|None=None

    def __post_init__(self):
        if type(self.offer)is not CraftOffer:raise ValueError('Craft branch requires its original typed offer')
        self.offer.__post_init__();_name(self.card_id,'selected craft ingredient')
        if self.card_id not in self.offer.offered:raise ValueError('Ingredient was not actually offered')
        if self.result is not None:
            if type(self.result)is not ChoiceResult:raise ValueError('Craft branch requires its real choice result')
            self.result.__post_init__()


def pool_rows(registry,context,pool_id,tribe,budget):
    if type(context)is not GenerationContext:raise ValueError('Crafting requires an explicit generation context')
    pool=registry.pool(pool_id,context)
    if not pool.complete:raise UnsupportedDefinitionError('Crafting requires a complete declared curated pool: '+pool_id)
    result=[]
    for member in sorted(pool.members,key=lambda m:m.card_id):
        if member.card_id in pool.excluded_card_ids:continue
        row=registry.pool_card(member.card_id)
        if row.kind!=CardType.MINION or row.metadata.tribes is None or not any(t in row.metadata.tribes for t in(tribe,'all')):
            raise ValueError('Curated craft pool contains an unknown or wrong ingredient role: '+member.card_id)
        if row.cost>budget:continue
        card=registry.card(member.card_id)
        if member.card_id not in registry.crafted_minion_parts:
            raise UnsupportedDefinitionError('Eligible crafted ingredient lacks its reviewed native donation adapter: '+member.card_id)
        validate_part_shape(registry,card)
        if PoolCard.from_definition(card).filter_signature()!=row.filter_signature():raise ValueError('Curated ingredient metadata differs from its executable printed face')
        result.append(member)
    return tuple(result)


def part_budget(spec,remaining):
    return remaining if spec.max_part_cost is None else min(remaining,spec.max_part_cost)


def candidates(registry,context,spec,first=None):
    spec.__post_init__()
    blueprint=registry.crafted_minion_blueprints[spec.template_card_id];validate_blueprint(registry,blueprint)
    if first is not None:
        rows=pool_rows(registry,context,spec.second_pool_id,blueprint.second_tribe,part_budget(spec,spec.max_total_cost-registry.card(first).cost))
        for row in rows:native_domains((registry.card(first),registry.card(row.card_id)))
    else:
        rows=pool_rows(registry,context,spec.first_pool_id,blueprint.first_tribe,part_budget(spec,spec.max_total_cost))
        if not rows:raise ValueError('Curated first craft pool is empty')
        # Check every potentially reachable second ingredient before the first
        # RNG draw. This is capability validation, not a new eligibility filter.
        second=pool_rows(registry,context,spec.second_pool_id,blueprint.second_tribe,
            part_budget(spec,spec.max_total_cost-min(registry.card(row.card_id).cost for row in rows)))
        for row in rows:
            first_card=registry.card(row.card_id)
            partners=tuple(s for s in second if first_card.cost+registry.card(s.card_id).cost<=spec.max_total_cost)
            if not partners:raise ValueError('Curated first ingredient has no second ingredient under the printed budget')
            for partner in partners:native_domains((first_card,registry.card(partner.card_id)))
    if not rows:raise ValueError('Curated second craft pool is empty under the printed budget')
    return rows


def discount_for(registry,state,spec):
    if spec.discount_tribe is None:return spec.discount_amount
    return spec.discount_amount if any(registry.card(state.entities[i].card_id).kind==CardType.MINION and
        has_any_tribe(registry,state.entities[i],(spec.discount_tribe,)) for i in state.players[spec.player_id].hand)else 0


def cost_spec(offer):
    return CostSpec(delta=-offer.discount,card_types=(CardType.MINION,))if offer.discount else None


def prompt(registry,offer):
    blueprint=registry.crafted_minion_blueprints[offer.spec.template_card_id]
    tribe=blueprint.first_tribe if offer.stage==1 else blueprint.second_tribe
    label={'dragon':'龙','undead':'亡灵','beast':'野兽'}.get(tribe,tribe)
    return '选择一个'+label+('作为部件'if offer.stage==1 else '完成造物')


def options_for(registry,offer):
    result=[]
    for index,part_id in enumerate(offer.offered,1):
        cid=part_id if offer.stage==1 else CraftedMinionRecipe(offer.spec.template_card_id,offer.first_card_id,part_id).card_id
        card=registry.card(cid)
        amount=card.cost if offer.stage==1 else quote_generated_cost(offer.before,registry,offer.spec.player_id,cid,cost=cost_spec(offer)).amount
        result.append(ChoiceOption('component-'+str(index),registry.card(part_id).name,(ResolveCraft(offer,part_id),),
            card_id=cid,preview=preview(card,amount)))
    return tuple(result)


def validate_result(registry,offer,card_id,result):
    if type(result)is not ChoiceResult:raise ValueError('Crafting requires an actual selected choice')
    result.__post_init__();choice=result.choice;spec=offer.spec;options=options_for(registry,offer)
    if ((choice.player_id,choice.source_id,choice.prompt,choice.min_count,choice.max_count,choice.purpose,choice.repeat_key)!=
            (spec.player_id,spec.source_id,prompt(registry,offer),1,1,ChoicePurpose.CRAFT,None)or choice.options!=tuple(o.item for o in options)):
        raise ValueError('Craft result changed its complete original choice contract')
    selected=next((o.id for o,p in zip(options,offer.offered)if p==card_id),None)
    if selected is None or result.selected_ids!=(selected,):raise ValueError('Craft result substituted the original selected ingredient')


def acceptance_data(offer):
    return dict(spec_json=json.dumps(asdict(offer.spec),sort_keys=True,separators=(',',':')),stage=offer.stage,
        first_card_id=offer.first_card_id,candidates=offer.candidates,offered=offer.offered,
        rng_before=end_turn_rng_to_json(offer.rng_before),rng_after=end_turn_rng_to_json(offer.rng_after),
        discount=offer.discount,before_hash=canonical_hash(state_to_dict(offer.before)),
        parent_event_id=offer.parent.event_id if offer.parent else None,
        first_result_hash=canonical_hash(asdict(offer.first_result))if offer.first_result else None)


def validate_offer(registry,context,offer,events):
    offer.__post_init__();validate_invariants(offer.before,registry)
    if offer.spec.source_id not in offer.before.entities:raise ValueError('Craft acceptance lost its original physical source')
    if offer.parent is not None:
        validate_offer(registry,context,offer.parent,events)
        validate_result(registry,offer.parent,offer.first_card_id,offer.first_result)
        if offer.discount!=offer.parent.discount or offer.parent.event_id>=offer.event_id:raise ValueError('Crafting changed its original discount or stage order')
        markers=[e for e in events if e.kind=='craft_ingredient_selected' and dict(e.data).get('acceptance_id')==offer.parent.event_id]
        if len(markers)!=1 or dict(markers[0].data)!=selection_data(offer.parent,offer.first_card_id,offer.first_result):
            raise ValueError('Second craft stage lost its actual first selection event')
    elif offer.discount!=discount_for(registry,offer.before,offer.spec):raise ValueError('Craft discount differs from the original held tribe')
    rows=candidates(registry,context,offer.spec,offer.first_card_id)
    rng=Random();rng.setstate(offer.rng_before);selected=sample_candidates(rng,rows,3,replacement=False)
    if (tuple(m.card_id for m in rows),selected,rng.getstate())!=(offer.candidates,offer.offered,offer.rng_after):
        raise ValueError('Craft offer changed its complete original candidates, selection or RNG')
    event=next((e for e in events if e.sequence==offer.event_id),None)
    if (event is None or event.kind!='craft_offer_accepted' or event.source_id!=offer.spec.source_id or
            event.player_id!=offer.spec.player_id or event.action!=offer.before.action_number or
            canonical_hash(dict(event.data))!=canonical_hash(acceptance_data(offer))):
        raise ValueError('Craft offer lost its original private acceptance event')


def validate_current(offer,state):
    for key in('turn','action_number','next_entity_id','next_order','next_attachment_id','next_choice_id'):
        if getattr(offer.before,key)>getattr(state,key):raise ValueError('Craft acceptance belongs to a future state')
    if offer.spec.source_id not in state.entities:raise ValueError('Crafting lost its original source')
    if any(offer.before.players[p].original_deck!=state.players[p].original_deck for p in(1,2)):
        raise ValueError('Craft acceptance changed original deck facts')


def make_offer(r,spec,parent=None,first=None,result=None):
    before=deepcopy(r.state);rows=candidates(r.registry,r.game._generation_context,spec,first)
    discount=parent.discount if parent else discount_for(r.registry,before,spec)
    rng_before=r.game._rng.getstate();offered=sample_candidates(r.game._rng,rows,3,replacement=False)
    offer=CraftOffer(spec,before,2 if parent else 1,first,tuple(m.card_id for m in rows),offered,
        rng_before,r.game._rng.getstate(),discount,len(r.game._events)+1,parent,result)
    event=r.emit('craft_offer_accepted',source_id=spec.source_id,player_id=spec.player_id,**acceptance_data(offer))
    if event.sequence!=offer.event_id:raise ValueError('Craft acceptance lost its original event sequence')
    return RequestChoice(spec.player_id,options_for(r.registry,offer),spec.source_id,prompt(r.registry,offer),purpose=ChoicePurpose.CRAFT)


def craft(r,spec):return(make_offer(r,spec),)


def selection_data(offer,card_id,result):
    return dict(acceptance_id=offer.event_id,stage=offer.stage,card_id=card_id,
        choice_id=result.choice.id,result_hash=canonical_hash(asdict(result)))


def resolve(r,effect):
    effect.__post_init__();offer=effect.offer;validate_offer(r.registry,r.game._generation_context,offer,r.game._events)
    validate_current(offer,r.state);validate_result(r.registry,offer,effect.card_id,effect.result)
    r.emit('craft_ingredient_selected',source_id=offer.spec.source_id,player_id=offer.spec.player_id,
        **selection_data(offer,effect.card_id,effect.result))
    if offer.stage==1:return(make_offer(r,offer.spec,offer,effect.card_id,effect.result),)
    cid=CraftedMinionRecipe(offer.spec.template_card_id,offer.first_card_id,effect.card_id).card_id
    return(AddToHand(offer.spec.player_id,cid,offer.spec.source_id,cost=cost_spec(offer)),)


def validate_boundary(game):
    from .hero_health_history import effective_events
    events=effective_events(game._events)
    accepted={e.sequence:e for e in events if e.kind=='craft_offer_accepted'}
    if not accepted:return
    closed=set()
    for event in events:
        if event.kind!='craft_ingredient_selected':continue
        data=dict(event.data);original=accepted.get(data.get('acceptance_id'))
        if (original is None or original.sequence in closed or original.sequence>=event.sequence or
                event.source_id!=original.source_id or event.player_id!=original.player_id or
                data.get('stage')!=dict(original.data).get('stage')or data.get('card_id')not in dict(original.data).get('offered',())):
            raise ValueError('Craft selection marker changed its actual acceptance')
        closed.add(original.sequence)
    frame=game._frame
    if game._state.status!='playing':return
    if frame is None:
        if set(accepted)-closed:raise ValueError('Craft acceptance lost all of its remaining selection work')
        return
    checked=set();accepted_work=set()
    def check(offer):
        if id(offer)not in checked:
            if offer.event_id not in accepted:raise ValueError('Craft work borrowed a retired acceptance')
            validate_offer(game.registry,game._generation_context,offer,events);validate_current(offer,game._state)
            checked.add(id(offer));accepted_work.add(offer.event_id)
    def request(options,on_select,purpose):
        branches=[e for o in options for e in o.effects if type(e)is ResolveCraft]
        if not branches and purpose!=ChoicePurpose.CRAFT:return None
        if not branches or on_select is not None:raise ValueError('Craft choice lost its typed original branches')
        offer=branches[0].offer;check(offer)
        if purpose!=ChoicePurpose.CRAFT or options!=options_for(game.registry,offer):raise ValueError('Craft choice cropped or substituted original branches')
        return offer
    choice=game._state.pending_choice
    offer=request(frame.options,frame.on_select,choice.purpose)
    if offer is not None:
        if ((choice.player_id,choice.source_id,choice.prompt,choice.min_count,choice.max_count,choice.repeat_key)!=
                (offer.spec.player_id,offer.spec.source_id,prompt(game.registry,offer),1,1,None)or
                choice.options!=tuple(o.item for o in frame.options)):
            raise ValueError('Pending craft choice changed its original actor or contract')
    def walk(value):
        if type(value)is ResolveCraft:
            check(value.offer)
            if value.result is not None:validate_result(game.registry,value.offer,value.card_id,value.result)
            return
        if type(value)is RequestChoice:
            offer=request(value.options,value.on_select,value.purpose)
            if offer is not None and (value.player_id,value.source_id,value.prompt,value.min_count,value.max_count,value.repeat_key)!=(
                    offer.spec.player_id,offer.spec.source_id,prompt(game.registry,offer),1,1,None):raise ValueError('Queued craft request changed its original contract')
        if isinstance(value,Effect):
            for field in fields(value):walk(getattr(value,field.name))
        elif type(value)is ChoiceOption:walk(value.effects)
        elif type(value)is tuple:
            for item in value:walk(item)
    walk(frame.prefix);walk(frame.continuation);walk(frame.options)
    if set(accepted)-closed!=accepted_work-closed:raise ValueError('Craft acceptance lost a queued original choice')


def register(mechanics):
    mechanics.register_payload_type(CraftOffer)
    mechanics.register(CraftMinion,craft);mechanics.register(ResolveCraft,resolve)
