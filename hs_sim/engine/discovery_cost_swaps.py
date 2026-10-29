"""Original first discovery acquisition and the second spell's paired quote."""
from dataclasses import dataclass,replace
import json
from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Effect,_integer
from .model import CardType,CostQuoteFact,GeneratedCostQuoteFact,CostSpec,Event,Zone
from .pools import PoolQuery
from .zones import CardReference

QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',max_cost=3)


def validate_spec(spec):
    from .pools import DiscoverFromPool
    if type(spec.source_id)is not int or spec.source_id<1:raise ValueError('Cost swap requires its original discovery source')
    plain=DiscoverFromPool(spec.player_id,'constructed.cards',QUERY,source_id=spec.source_id,prompt=spec.prompt,discoveries=2)
    if replace(spec,swap_costs=False)!=plain:raise ValueError('Cost swap requires two ordinary low-cost spell discoveries')


@dataclass(frozen=True)
class DeliverCostSwappedSpell(Effect):
    batch:object
    first_event:Event
    first_entry_id:int|None
    first_ref:CardReference|None
    first_quote:CostQuoteFact|GeneratedCostQuoteFact
    second_quote:GeneratedCostQuoteFact

    @property
    def card_id(self):return self.batch.selections[1].card_id
    @property
    def source_id(self):return self.batch.spec.source_id
    @property
    def player_id(self):return self.batch.spec.player_id

    def __post_init__(self):
        from .discovery import ContinuePoolDiscovery
        if type(self.batch)is not ContinuePoolDiscovery:raise ValueError('Swapped discovery requires its complete original batch')
        self.batch.__post_init__();validate_spec(self.batch.spec)
        if not self.batch.spec.swap_costs or len(self.batch.selections)!=2 or any(v.result is None for v in self.batch.selections):
            raise ValueError('Swapped discovery requires both committed original choices')
        if type(self.first_event)is not Event or self.first_event.kind!='card_discovered':
            raise ValueError('Swapped discovery requires the original first completion event')
        if self.first_entry_id is not None:_integer(self.first_entry_id,'first discovered hand entry',1)
        if self.first_ref is not None:
            if type(self.first_ref)is not CardReference or self.first_ref.zone!=Zone.HAND or self.first_entry_id is None:
                raise ValueError('Swapped first recipient requires its original actual hand acquisition')
            self.first_ref.__post_init__()
        if type(self.first_quote)not in(CostQuoteFact,GeneratedCostQuoteFact)or type(self.second_quote)is not GeneratedCostQuoteFact:
            raise ValueError('Swapped discovery requires complete original physical/generated quotes')
        for q in(self.first_quote,self.second_quote):q.__post_init__()
        if (type(self.first_quote)is CostQuoteFact)!=(self.first_ref is not None):
            raise ValueError('Swapped first quote borrowed a different physical route')
        first,second=self.batch.selections;a=self.first_quote.quote_input;z=self.second_quote.quote_input
        expected_first=first.card_id if self.first_ref is None else self.first_ref.card_id
        if ((a.player_id,a.card_id,z.player_id,z.card_id)!=(self.player_id,expected_first,self.player_id,second.card_id)or
                z.initial_cost is not None or z.minimum_cost!=0 or first.result.choice.id>=second.result.choice.id or
                (self.first_event.source_id,self.first_event.player_id,dict(self.first_event.data).get('choice_id'))!=
                    (self.source_id,self.player_id,first.result.choice.id)):
            raise ValueError('Swapped discovery changed its original selections, subjects or completion')
        if type(self.first_quote)is GeneratedCostQuoteFact and(a.initial_cost is not None or a.minimum_cost!=0):
            raise ValueError('Unavailable first recipient cannot invent an original generated price change')
        if self.first_ref is not None and a.source_id!=self.first_ref.entity_id:
            raise ValueError('Swapped discovery quote lost its actual original first card')

    def validate_in_state(self,state,registry,events=None):
        from .card_discoveries import require_original_result
        from .discovery_delivery import original_recipient
        from .hand_history import hand_entry
        from .intrinsic_costs import validate_generated_quote_fact,validate_intrinsic_history_prefix
        self.__post_init__()
        for pick in self.batch.selections:
            require_original_result(state,pick.result)
            if (pick.result.choice.player_id,pick.result.choice.source_id,pick.result.choice.prompt)!=(self.player_id,self.source_id,self.batch.spec.prompt):
                raise ValueError('Swapped discovery borrowed another original source or menu')
        fact=original_recipient(state,self.first_event)
        if fact is not None:validate_allocation(state,registry,fact)
        if self.first_entry_id is not None:
            entry=hand_entry(state,self.first_entry_id)
            if fact is None or fact.zone!=Zone.HAND or(entry.entity_id,entry.player_id,entry.zone_epoch,entry.card_id,entry.source_id)!=(
                    fact.entity_id,self.player_id,fact.zone_epoch,fact.card_id,self.source_id):
                raise ValueError('Swapped discovery borrowed a later first-card acquisition')
        if self.first_ref is not None:
            e=state.entities.get(self.first_ref.entity_id)
            if fact is None or self.first_ref.entity_id!=fact.entity_id or self.first_ref.player_id!=self.player_id or e is None or self.first_ref.zone_epoch>e.zone_epoch:
                raise ValueError('Swapped discovery has an unknown or future first residence')
        for quote in(self.first_quote,self.second_quote):
            if type(quote)is GeneratedCostQuoteFact:validate_generated_quote_fact(registry,quote)
            validate_intrinsic_history_prefix(quote.intrinsic,state,registry)
        if events is not None:
            from .hero_health_history import effective_events
            if sum(e==self.first_event for e in effective_events(events))!=1:
                raise ValueError('Swapped discovery lost its actual first completion proof')


def prepare(r,batch):
    from .hero_health_history import effective_events
    from .discovery_delivery import original_recipient
    from .costs import capture_cost_input,quote_input,capture_generated_quote_fact
    first=batch.selections[0];events=[e for e in effective_events(r.game.events)if e.kind=='card_discovered'and
        dict(e.data).get('choice_id')==first.result.choice.id]
    if len(events)!=1:raise ValueError('Paired discovery requires the completed actual first delivery')
    event=events[0];fact=original_recipient(r.state,event);entry_id=None;reference=None
    if fact is not None and fact.zone==Zone.HAND:
        entries=[v for v in r.state.hand_entries if(v.entity_id,v.player_id,v.zone_epoch)==(fact.entity_id,fact.controller,fact.zone_epoch)]
        if len(entries)!=1:raise ValueError('First paired discovery lost its original successful hand entry')
        entry_id=entries[0].id;entity=r.state.entities[fact.entity_id]
        if(entity.zone,entity.controller,entity.hand_entry_id)==(Zone.HAND,batch.spec.player_id,entry_id):reference=CardReference.capture(entity)
    before=(capture_generated_quote_fact(r.state,r.registry,batch.spec.player_id,first.card_id)if reference is None else
        quote_input(r.state,r.registry,capture_cost_input(r.state.entities[reference.entity_id])))
    after=capture_generated_quote_fact(r.state,r.registry,batch.spec.player_id,batch.selections[1].card_id)
    value=DeliverCostSwappedSpell(batch,event,entry_id,reference,before,after);value.validate_in_state(r.state,r.registry,r.game.events);return value


def materialize(r,request):
    from .effects import AddToHand
    from .opening import create_hand_card
    from .zones import ModifyStoredCost,modify_stored_cost
    request.validate_in_state(r.state,r.registry,r.game.events)
    if request.first_ref is not None:
        current=r.state.entities[request.first_ref.entity_id]
        if current.hand_entry_id==request.first_entry_id:
            modify_stored_cost(r,ModifyStoredCost(request.first_ref,CostSpec(set_to=request.second_quote.local_amount),request.source_id))
    return create_hand_card(r,AddToHand(request.player_id,request.card_id,request.source_id,cost=CostSpec(set_to=request.first_quote.local_amount)))


def execute(r,request):materialize(r,request);return ()


def validate_completion(state,registry,completion):
    if type(completion.recipe)is not DeliverCostSwappedSpell:return
    request=completion.recipe;request.validate_in_state(state,registry)
    if completion.result!=request.batch.selections[1].result:
        raise ValueError('Swapped second delivery lost its actual selected result')
    if completion.recipient is not None and(completion.recipient.card_id,completion.recipient.controller)!=(request.card_id,request.player_id):
        raise ValueError('Swapped second delivery borrowed another actual generated card')


def validate_boundary(game):
    from .discovery_delivery import QUEUED,COMPLETED
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    name=__name__+'.DeliverCostSwappedSpell';values=[]
    for event in effective_events(game.events):
        key='work'if event.kind==QUEUED else'receipt'if event.kind==COMPLETED else None
        value=None if key is None else dict(event.data).get(key)
        if type(value)is str and name in value:values.append(value)
    if not values:return
    codec=FrameCodec(game.mechanics,game.registry,origin_state=game._state,origin_events=game.events)
    for value in values:codec.decode(json.loads(value))


def register(mechanics):mechanics.register(DeliverCostSwappedSpell,execute)
