"""Original generated quote pairs and the continuation of an excess Discover discount."""
from dataclasses import dataclass,replace
import json

from .effects import _integer
from .model import CardClass,CardType,CostSpec,GeneratedCostQuoteFact

ACCEPTED='discovery_discount_accepted'
FINISHED='discovery_discount_finished'


@dataclass(frozen=True)
class DiscoveryDiscountStep:
    budget: int
    before: GeneratedCostQuoteFact
    after: GeneratedCostQuoteFact

    def __post_init__(self):
        _integer(self.budget,'original discovery discount budget',1)
        if type(self.before) is not GeneratedCostQuoteFact or type(self.after) is not GeneratedCostQuoteFact:
            raise ValueError('Discovery discount requires both complete original generated quotes')
        self.before.__post_init__();self.after.__post_init__()
        a,b=self.before.quote_input,self.after.quote_input
        if (a.kind!=CardType.SPELL or a.initial_cost is not None or a.minimum_cost!=0 or
                b.initial_cost!=CostSpec(delta=-self.budget) or replace(a,initial_cost=b.initial_cost)!=b or
                self.before.intrinsic!=self.after.intrinsic):
            raise ValueError('Discovery discount changed its original subject, budget or quote window')

    @property
    def remaining(self):
        return self.budget-min(self.budget,max(0,self.before.amount-self.after.amount))


def validate_spec(spec):
    from .pools import DiscoverFromPool,PoolQuery
    if (type(spec.source_id) is not int or spec.source_id<1 or type(spec.cost) is not CostSpec or
            spec.cost.delta>0 or spec.cost!=CostSpec(delta=spec.cost.delta)):
        raise ValueError('Excess discount requires its original source and plain nonpositive cost delta')
    plain=DiscoverFromPool(spec.player_id,spec.pool_id,PoolQuery(kinds=(CardType.SPELL,),
        collectible=True,class_mode='current',include_neutral=False),source_id=spec.source_id,
        prompt=spec.prompt,policy=spec.policy,cost=spec.cost)
    if replace(spec,excess_discount=False)!=plain:
        raise ValueError('Excess discount supports one ordinary current-class spell hand discovery')


def validate_progress(registry,batch,state=None):
    from .intrinsic_costs import validate_generated_quote_fact,validate_intrinsic_history_prefix
    previous=None
    for pick in batch.selections:
        step=pick.discount_step
        if type(step) is not DiscoveryDiscountStep or pick.result is None:
            raise ValueError('Discovery discount lost its complete committed original progress')
        step.__post_init__()
        if (previous is not None and step.budget!=previous or
                (step.before.quote_input.player_id,step.before.quote_input.card_id)!=(batch.spec.player_id,pick.card_id)):
            raise ValueError('Discovery discount reordered or borrowed another original budget')
        for quote in (step.before,step.after):
            validate_generated_quote_fact(registry,quote)
            if state is not None:validate_intrinsic_history_prefix(quote.intrinsic,state,registry)
        previous=step.remaining
    if previous is not None and previous!=-batch.spec.cost.delta:
        raise ValueError('Discovery continuation changed its exact remaining excess discount')


def accept(r,spec,pick):
    from .costs import capture_generated_quote_fact
    step=DiscoveryDiscountStep(-spec.cost.delta,
        capture_generated_quote_fact(r.state,r.registry,spec.player_id,pick.card_id),
        capture_generated_quote_fact(r.state,r.registry,spec.player_id,pick.card_id,cost=spec.cost))
    return replace(pick,discount_step=step),replace(spec,cost=CostSpec(delta=-step.remaining))


def encode(game,batch):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(game.mechanics,game.registry).encode(batch),ensure_ascii=False,
        sort_keys=True,separators=(',',':'))


def accepted(r,batch):
    last=batch.selections[-1];step=last.discount_step
    r.emit(ACCEPTED,source_id=batch.spec.source_id,player_id=batch.spec.player_id,
        choice_id=last.result.choice.id,batch=encode(r.game,batch),turn=r.state.turn,
        before_budget=step.budget,after_budget=step.remaining,_capture=False)


def finished(r,batch,reason):
    spec=batch.spec
    r.emit(FINISHED,source_id=spec.source_id,player_id=spec.player_id,
        choice_id=batch.selections[-1].result.choice.id if batch.selections else None,
        batch=encode(r.game,batch),reason=reason,hero_class=r.player(spec.player_id).hero_class,
        source_card_id=r.state.entities[spec.source_id].card_id,_capture=False)


def validate_boundary(game):
    from .card_discoveries import require_original_result
    from .continuations import FrameCodec
    from .discovery import ContinuePoolDiscovery,ResolvePoolDiscovery,validate_batch
    from .discovery_offers import ACCEPTED as OFFER,EXCESS_DISCOUNT,decode_offer
    from .effects import RequestChoice
    from .hero_health_history import effective_events
    from .pools import resolve_candidates
    events=effective_events(game._events)
    if not any(e.kind in (ACCEPTED,FINISHED) or
            e.kind==OFFER and dict(e.data).get(EXCESS_DISCOUNT) is True for e in events):return
    codec=FrameCodec(game.mechanics,game.registry);accepted_batches={};closed=set();children={};offers={}
    def original_batch(batch):
        if type(batch) is not ContinuePoolDiscovery or not batch.spec.excess_discount:
            raise ValueError('Discovery discount lost its original typed continuation')
        validate_batch(game.registry,game._generation_context,batch)
        validate_progress(game.registry,batch,game._state)
        for pick in batch.selections:require_original_result(game._state,pick.result)
    for event in events:
        data=dict(event.data)
        if event.kind==OFFER:
            offer=decode_offer(game,data['original_offer']);options=offer.options
            work=options[0].effects[0] if options and options[0].effects else None
            if type(work) is ResolvePoolDiscovery and work.batch.spec.excess_discount:
                original_batch(work.batch);offers[offer.choice.id]=offer
                if work.batch.selections:
                    parent=work.batch.selections[-1].result.choice.id
                    if parent not in accepted_batches or work.batch!=accepted_batches[parent] or parent in children or parent in closed:
                        raise ValueError('Discovery discount forked or changed its original owed next offer')
                    children[parent]=offer.choice.id
            continue
        if event.kind not in (ACCEPTED,FINISHED):continue
        batch=codec.decode(json.loads(data['batch']));original_batch(batch);spec=batch.spec
        if (event.source_id,event.player_id,event.target_id,event.amount)!=(spec.source_id,spec.player_id,None,0):
            raise ValueError('Discovery discount changed its original actor')
        key=batch.selections[-1].result.choice.id if batch.selections else None
        if (data['choice_id']!=key or key is not None and type(data['choice_id']) is not int):
            raise ValueError('Discovery discount borrowed another original selection')
        if event.kind==ACCEPTED:
            if set(data)!={'choice_id','batch','turn','before_budget','after_budget'} or not batch.selections or key in accepted_batches:
                raise ValueError('Discovery discount has no unique complete original acceptance')
            last=batch.selections[-1];step=last.discount_step;offer=offers.get(key)
            if any(type(data[k]) is not int for k in ('turn','before_budget','after_budget')):
                raise ValueError('Discovery discount requires exact original integer quote facts')
            if offer is None:raise ValueError('Discovery discount has no actual original offer')
            option=next(o for o in offer.options if o.id==last.result.selected_ids[0]);work=option.effects[0]
            prior=ContinuePoolDiscovery(replace(spec,cost=CostSpec(delta=-step.budget)),batch.selections[:-1])
            if (work.batch!=prior or work.selection!=replace(last,result=None,discount_step=None) or
                    (data['before_budget'],data['after_budget'])!=(step.budget,step.remaining) or
                    (step.before.intrinsic.boundary.turn,step.before.intrinsic.boundary.action)!=(data['turn'],event.action)):
                raise ValueError('Discovery discount changed its original selection or generated quote window')
            accepted_batches[key]=batch
        else:
            if set(data)!={'choice_id','batch','reason','hero_class','source_card_id'}:
                raise ValueError('Discovery discount lost its complete original finish')
            if key is not None and (accepted_batches.get(key)!=batch or key in closed or key in children):
                raise ValueError('Discovery discount closed another or already consumed continuation')
            if data['reason']=='spent':
                if key is None or spec.cost.delta!=0:raise ValueError('Discovery discount ended before exhausting its budget')
            elif data['reason']=='empty':
                candidates=resolve_candidates(game.registry,game._generation_context,spec.pool_id,spec.query,
                    current_class=None if data['hero_class'] is None else CardClass(data['hero_class']),
                    source_card_id=data['source_card_id'],policy=spec.policy,
                    player_id=spec.player_id,exclude_source_by_rule=True)
                if candidates:raise ValueError('Discovery discount discarded a nonempty original domain')
            else:raise ValueError('Unknown discovery discount finish')
            if key is not None:closed.add(key)
    queued=[]
    if game._frame:queued=[*game._frame.prefix,*game._frame.continuation]
    pending={}
    pending_acceptances={}
    for work in queued:
        batch=None
        if type(work) is ContinuePoolDiscovery and work.spec.excess_discount:batch=work
        elif type(work) is ResolvePoolDiscovery and work.batch.spec.excess_discount and work.choice_result is not None:
            key=work.choice_result.choice.id
            if key in pending_acceptances:raise ValueError('Discovery discount duplicated its original selected work')
            offer=offers.get(key)
            original=next((o.effects[0] for o in offer.options if o.id==work.choice_result.selected_ids[0]),None) if offer else None
            if original!=replace(work,choice_result=None):raise ValueError('Discovery discount changed its original pending selection')
            pending_acceptances[key]=work
        elif type(work) is RequestChoice and work.options:
            candidate=work.options[0].effects[0] if work.options[0].effects else None
            if type(candidate) is ResolvePoolDiscovery and candidate.batch.spec.excess_discount:batch=candidate.batch
        if batch is None or not batch.selections:continue
        key=batch.selections[-1].result.choice.id
        if (accepted_batches.get(key)!=batch or key in children or key in closed or key in pending):
            raise ValueError('Queued discovery discount changed or duplicated an original owed continuation')
        pending[key]=batch
    committed={row.result.choice.id for row in game._state.card_discovery_history}
    if (game._state.status=='playing' and
            (set(offers)&committed)-set(accepted_batches)!=set(pending_acceptances)):
        raise ValueError('Discovery discount lost its actual selected quote acceptance')
    if game._state.status=='playing' and set(accepted_batches)-set(children)-closed!=set(pending):
        raise ValueError('Discovery discount lost its owed original continuation')
