"""Attributed board discoveries, independent offer receipts and entry windows.

Offer sampling, player selection and entry quantity are three different facts.
Local source/window policies await CN calibration. Receipts establish internal
consistency, not authenticity of an unsigned origin.
"""
from dataclasses import asdict,dataclass,fields,is_dataclass,replace
import json
from random import Random

from .effects import Effect,_integer
from .errors import ResolutionError
from .model import ChoicePurpose,ChoiceResult,GameState,PendingChoice,validate_end_turn_rng
from .pools import DiscoverFromPool,PoolMember,sample_candidates
from .pool_summons import PoolSummonBasis,validate_basis,from_dict as pool_from_dict
from .summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial,accept as accept_entry,validate_cause


@dataclass(frozen=True)
class DiscoverySummonEntryLink:
    producer_id:int
    index:int
    def __post_init__(self):
        _integer(self.producer_id,'discovery producer',1);_integer(self.index,'discovery entry index',0)


@dataclass(frozen=True)
class DiscoverySummonOffer:
    event_cursor:int
    turn:int
    action:int
    basis:PoolSummonBasis
    available:tuple[PoolMember,...]
    offered:tuple[str,...]
    rng_before:tuple
    rng_after:tuple
    choice:PendingChoice|None=None
    result:ChoiceResult|None=None

    def __post_init__(self):
        for n,floor in (('event_cursor',0),('turn',1),('action',0)):_integer(getattr(self,n),'discovery offer '+n,floor)
        if type(self.basis)is not PoolSummonBasis:raise ValueError('Complete original discovery basis required')
        self.basis.__post_init__()
        if type(self.available)is not tuple or any(type(m)is not PoolMember for m in self.available):raise ValueError('Complete available discovery inventory required')
        for m in self.available:m.__post_init__()
        if type(self.offered)is not tuple or any(type(c)is not str or not c for c in self.offered):raise ValueError('Ordered offered discovery cards required')
        if len(set(self.offered))!=len(self.offered):raise ValueError('Duplicate offered discovery identity')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        local=Random();local.setstate(self.rng_before)
        if sample_candidates(local,self.available,len(self.offered),replacement=False)!=self.offered or local.getstate()!=self.rng_after:
            raise ValueError('Discovery offer lost its original integer draw/RNG')
        if self.choice is not None:
            if type(self.choice)is not PendingChoice:raise ValueError('Typed actual discovery choice required')
            self.choice.__post_init__()
        if self.result is not None:
            if type(self.result)is not ChoiceResult or self.result.choice!=self.choice:raise ValueError('Discovery selection differs from its original choice')
            self.result.__post_init__()
            if len(self.result.selected_ids)!=1:raise ValueError('Discovery selects exactly one original option')
        if not self.offered and (self.choice is not None or self.result is not None):raise ValueError('Empty discovery cannot claim a choice')


def selected(offer):
    if offer.result is None:return None
    return next(x.card_id for x in offer.result.choice.options if x.id in offer.result.selected_ids)


@dataclass(frozen=True)
class DiscoverySummonRecord:
    id:int
    event_cursor:int
    turn:int
    action:int
    spec:DiscoverFromPool
    offers:tuple[DiscoverySummonOffer,...]=()
    entry_root_ids:tuple[int,...]=()
    phase:str='discovering'
    exhausted:bool=False
    status:str='active'

    def __post_init__(self):
        for n,floor in (('id',1),('event_cursor',0),('turn',1),('action',0)):_integer(getattr(self,n),'discovery producer '+n,floor)
        if type(self.spec)is not DiscoverFromPool or self.spec.destination!='board' or type(self.spec.cause)is not SummonCause:
            raise ValueError('Typed attributed board discovery required')
        self.spec.__post_init__()
        if type(self.offers)is not tuple or any(type(o)is not DiscoverySummonOffer for o in self.offers):raise ValueError('Complete ordered discovery offers required')
        for offer in self.offers:offer.__post_init__()
        if len(self.offers)>self.spec.discoveries:raise ValueError('Discovery exceeded its original repetitions')
        unresolved=[i for i,o in enumerate(self.offers)if o.result is None]
        if unresolved and unresolved!=[len(self.offers)-1]:raise ValueError('Unselected discovery was skipped')
        if type(self.entry_root_ids)is not tuple:raise ValueError('Actual discovery entry prefix required')
        for i in self.entry_root_ids:_integer(i,'actual discovery child',1)
        if len(set(self.entry_root_ids))!=len(self.entry_root_ids):raise ValueError('Repeated physical discovery entry root')
        picks=sum(o.result is not None for o in self.offers)
        if len(self.entry_root_ids)>picks:raise ValueError('Discovery delivered an unselected entry')
        if self.phase not in ('discovering','delivering')or type(self.exhausted)is not bool or self.status not in ('active','completed','interrupted'):
            raise ValueError('Unknown discovery producer lifecycle')
        if self.exhausted!=(bool(self.offers)and not self.offers[-1].offered):raise ValueError('Discovery exhaustion differs from its complete final empty offer')
        if self.phase=='delivering'and not self.exhausted and picks!=self.spec.discoveries:raise ValueError('Discovery delivered before all original choices')
        if self.spec.delivery=='after_all'and self.phase=='discovering'and self.entry_root_ids:raise ValueError('after_all discovery delivered early')
        if self.spec.delivery=='after_each'and self.status=='active'and picks-len(self.entry_root_ids)>1:raise ValueError('after_each discovery skipped an original delivery')
        if self.status=='completed'and(self.phase!='delivering'or len(self.entry_root_ids)!=picks):raise ValueError('Incomplete original discovery close')


@dataclass(frozen=True)
class StartDiscoverySummonEntry(Effect):
    producer_id:int
    index:int
    def __post_init__(self):
        _integer(self.producer_id,'start discovery producer',1);_integer(self.index,'start discovery entry',0)


@dataclass(frozen=True)
class FinishDiscoverySummon(Effect):
    producer_id:int
    def __post_init__(self):_integer(self.producer_id,'finish discovery producer',1)


CONTROL=(StartDiscoverySummonEntry,FinishDiscoverySummon)


def record(state,producer_id):
    root=next((x for x in state.discovery_summon_history if x.id==producer_id),None)
    if root is None:raise ValueError('Unknown actual discovery producer')
    return root


def update(state,root,**changes):
    value=replace(root,**changes);state.discovery_summon_history[state.discovery_summon_history.index(root)]=value
    return value


def emit(r,kind,root):
    r.emit(kind,source_id=root.spec.cause.source.entity_id,player_id=root.spec.player_id,
        amount=len(root.entry_root_ids),producer_id=root.id,
        root=json.dumps(asdict(root),ensure_ascii=False,sort_keys=True,separators=(',',':')),_capture=False)


def picks(root):
    from .discovery import DiscoveryPick
    return tuple(DiscoveryPick(selected(o),o.basis.hero_class,None if o.basis.source is None else o.basis.source.card_id)
        for o in root.offers if o.result is not None)


def validate_progress(state,registry,batch):
    root=record(state,batch.producer_id)
    if root.status!='active'or batch.spec!=root.spec or batch.selections!=picks(root):raise ValueError('Discovery continuation lost its original producer/progress')
    validate_cause(state,registry,root.spec.cause)
    return root


def start(r,spec,candidates):
    from .discovery import ContinuePoolDiscovery
    validate_cause(r.state,r.registry,spec.cause)
    # Even zero discoveries validate every original candidate/material.
    validate_basis(r.state,r.registry,PoolSummonBasis.capture(r,spec,candidates))
    root=DiscoverySummonRecord(r.state.next_discovery_summon_id,len(r.game._events),r.state.turn,r.state.action_number,spec)
    r.state.next_discovery_summon_id+=1;r.state.discovery_summon_history.append(root)
    emit(r,'discovery_summon_accepted',root)
    if spec.discoveries:return (ContinuePoolDiscovery(spec,producer_id=root.id),FinishDiscoverySummon(root.id))
    emit(r,'discovery_summon_ready',update(r.state,root,phase='delivering'))
    return (FinishDiscoverySummon(root.id),)


def make_offer(r,batch,candidates):
    root=validate_progress(r.state,r.registry,batch)
    if root.phase!='discovering'or len(root.offers)!=len(batch.selections):raise ResolutionError('Out-of-order discovery offer')
    basis=PoolSummonBasis.capture(r,batch.spec,candidates);validate_basis(r.state,r.registry,basis)
    used={r.registry.pool_card(x.card_id).generation_identity for x in batch.selections}
    available=candidates if batch.spec.replacement else tuple(x for x in candidates if r.registry.pool_card(x.card_id).generation_identity not in used)
    before=r.game._rng.getstate();offered=sample_candidates(r.game._rng,available,batch.spec.count,replacement=False)
    offer=DiscoverySummonOffer(len(r.game._events),r.state.turn,r.state.action_number,basis,available,offered,before,r.game._rng.getstate())
    root=update(r.state,root,offers=(*root.offers,offer),exhausted=not bool(offered))
    emit(r,'discovery_summon_offered',root)
    return offer


def validate_resolve(state,registry,effect,*,require_result=False):
    root=record(state,effect.batch.producer_id)
    prior=picks(root)
    if (root.status!='active'or effect.batch.spec!=root.spec or effect.batch.selections!=prior or not root.offers or
        root.offers[-1].result is not None):raise ValueError('Discovery branch lost its original producer/progress')
    offer=root.offers[-1];pick=effect.selection
    if (effect.offered_card_ids!=offer.offered or pick.card_id not in offer.offered or
        pick.hero_class!=offer.basis.hero_class or pick.source_card_id!=(None if offer.basis.source is None else offer.basis.source.card_id)):
        raise ValueError('Discovery branch differs from complete original offer basis')
    validate_basis(state,registry,offer.basis);validate_cause(state,registry,root.spec.cause)
    result=effect.choice_result
    if result is not None:
        result.__post_init__()
        expected=f'generated-{offer.offered.index(pick.card_id)+1}'
        if result.choice!=offer.choice or result.selected_ids!=(expected,):raise ValueError('Chosen branch differs from actual discovery selection')
    elif require_result:raise ValueError('Actual discovery branch requires its complete ChoiceResult')
    return root,offer


def bind_choice(r,choice,options):
    from .discovery import ResolvePoolDiscovery
    branches=[o.effects[0]for o in options if len(o.effects)==1 and type(o.effects[0])is ResolvePoolDiscovery and o.effects[0].batch.producer_id is not None]
    if not branches:return
    if len(branches)!=len(options):raise ValueError('Attributed discovery mixed selection branches')
    root,offer=validate_resolve(r.state,r.registry,branches[0])
    if offer.choice is not None:raise ValueError('Discovery offer bound to multiple actual choices')
    for b in branches:
        if b.batch!=branches[0].batch:raise ValueError('Discovery borrowed another original producer')
        validate_resolve(r.state,r.registry,b)
    value=replace(offer,choice=choice)
    validate_choice(root.spec,value,r.registry,r.state.next_choice_id)
    root=update(r.state,root,offers=(*root.offers[:-1],value));emit(r,'discovery_summon_bound',root)


def select_offer(r,effect):
    root,offer=validate_resolve(r.state,r.registry,effect,require_result=True)
    value=replace(offer,result=effect.choice_result)
    root=update(r.state,root,offers=(*root.offers[:-1],value));emit(r,'discovery_summon_picked',root)
    return (StartDiscoverySummonEntry(root.id,len(root.entry_root_ids)),)if root.spec.delivery=='after_each'else ()


def ready(r,batch):
    root=validate_progress(r.state,r.registry,batch)
    root=update(r.state,root,phase='delivering');emit(r,'discovery_summon_ready',root)
    return (StartDiscoverySummonEntry(root.id,len(root.entry_root_ids)),)if len(root.entry_root_ids)<len(picks(root))else ()


def start_entry(r,effect):
    root=record(r.state,effect.producer_id);chosen=picks(root)
    if root.status!='active'or effect.index!=len(root.entry_root_ids)or effect.index>=len(chosen):raise ResolutionError('Out-of-order discovery entry')
    request=SummonByCard(root.spec.player_id,(SummonEntryMaterial(chosen[effect.index].card_id),),root.spec.cause,
        capacity='preselected_attempt',producer_link=DiscoverySummonEntryLink(root.id,effect.index))
    continuation=accept_entry(r,request);child_id=r.state.card_summon_history[-1].id
    root=update(r.state,root,entry_root_ids=(*root.entry_root_ids,child_id));emit(r,'discovery_summon_entry',root)
    if root.phase=='delivering'and len(root.entry_root_ids)<len(chosen):
        continuation=(*continuation,StartDiscoverySummonEntry(root.id,len(root.entry_root_ids)))
    return continuation


def finish(r,effect):
    root=record(r.state,effect.producer_id)
    if root.status!='active'or root.phase!='delivering'or len(root.entry_root_ids)!=len(picks(root)):raise ResolutionError('Incomplete discovery producer finish')
    if any(next(x for x in r.state.card_summon_history if x.id==i).status=='active'for i in root.entry_root_ids):
        raise ResolutionError('Discovery finish preceded actual entry finish')
    emit(r,'discovery_summon_finished',update(r.state,root,status='completed'))


def interrupt(r):
    for root in tuple(r.state.discovery_summon_history):
        if root.status=='active':emit(r,'discovery_summon_finished',update(r.state,root,status='interrupted'))


def validate_choice(spec,offer,registry,next_choice_id):
    choice=offer.choice
    if choice is None:return
    if (choice.id>=next_choice_id or (choice.player_id,choice.source_id,choice.prompt,choice.min_count,choice.max_count,choice.purpose,choice.repeat_key)!=
        (spec.player_id,spec.source_id,spec.prompt,1,1,ChoicePurpose.POOL_DISCOVERY,None)):
        raise ValueError('Discovery actual choice changed original metadata')
    expected=tuple((f'generated-{i}',registry.card(c).name,c,None,None)for i,c in enumerate(offer.offered,1))
    if tuple((o.id,o.label,o.card_id,o.entity_id,o.preview)for o in choice.options)!=expected:raise ValueError('Discovery actual choice lost complete offered order')


def validate_link(state,child,*,closed=False):
    link=child.request.producer_link
    if type(link)is not DiscoverySummonEntryLink:return
    link.__post_init__()
    if link.producer_id>=state.next_discovery_summon_id:raise ValueError('Future discovery entry parent')
    root=next((x for x in state.discovery_summon_history if x.id==link.producer_id),None)
    if root is None:
        if closed:return
        raise ValueError('Discovery entry lost actual producer')
    validate_child(root,link.index,child)


def validate_child(root,index,child):
    chosen=picks(root)
    if (index>=len(root.entry_root_ids)or root.entry_root_ids[index]!=child.id or
        child.request.producer_link!=DiscoverySummonEntryLink(root.id,index)or child.request.cause!=root.spec.cause or
        child.request.player_id!=root.spec.player_id or child.request.materials!=(SummonEntryMaterial(chosen[index].card_id),)or
        child.request.capacity!='preselected_attempt'or child.event_cursor<=root.event_cursor):
        raise ValueError('Discovery child borrowed another selected entry/cause/window')


def validate_record(state,registry,root,*,closed=False,children=None):
    root.__post_init__();validate_cause(state,registry,root.spec.cause,closed=closed)
    if root.id>=state.next_discovery_summon_id or root.turn>state.turn or root.action>state.action_number:raise ValueError('Future discovery producer')
    if root.spec.cause.turn>root.turn or root.spec.cause.action>root.action:raise ValueError('Discovery cause is newer than acceptance')
    used=set();cursor=root.event_cursor
    for offer in root.offers:
        validate_basis(state,registry,offer.basis,closed=closed)
        b=offer.basis
        if (b.player_id,b.pool_id,b.query,b.policy)!=(root.spec.player_id,root.spec.pool_id,root.spec.query,root.spec.policy):
            raise ValueError('Discovery offer borrowed another query/policy/recipient')
        if (root.spec.source_id is None)!=(b.source is None)or b.source is not None and b.source.entity_id!=root.spec.source_id:
            raise ValueError('Discovery offer changed its original query source')
        expected=b.candidates if root.spec.replacement else tuple(m for m in b.candidates if registry.pool_card(m.card_id).generation_identity not in used)
        if offer.available!=expected or len(offer.offered)!=min(root.spec.count,len(expected)):raise ValueError('Discovery lost complete original remaining inventory')
        if offer.event_cursor<=cursor or offer.turn>state.turn or offer.action>state.action_number:raise ValueError('Reordered/future original discovery offer')
        cursor=offer.event_cursor
        validate_choice(root.spec,offer,registry,state.next_choice_id)
        if offer.result is not None:used.add(registry.pool_card(selected(offer)).generation_identity)
    if not closed and root.status=='interrupted'and state.status=='playing':raise ValueError('Playing discovery cannot be terminal interrupted')
    if children is None:children={x.id:x for x in state.card_summon_history}
    for index,i in enumerate(root.entry_root_ids):
        if i not in children:raise ValueError('Discovery lost an actual child entry')
        validate_child(root,index,children[i])


def validate_history(state,registry):
    _integer(state.next_discovery_summon_id,'next discovery producer',1)
    if type(state.discovery_summon_history)is not list:raise ValueError('Typed discovery producer history required')
    for root in state.discovery_summon_history:
        if type(root)is not DiscoverySummonRecord:raise ValueError('Typed original discovery producer required')
        validate_record(state,registry,root)
    ids=[x.id for x in state.discovery_summon_history]
    if ids!=sorted(set(ids)):raise ValueError('Reordered discovery producer identities')


def reject_choice_control(options):
    from .summon_quantities import walk_work
    if any(type(w)in CONTROL for w in walk_work(options)):raise ValueError('Choice cannot inject discovery delivery control')


def validate_queue(state,registry,queue):
    from .discovery import ContinuePoolDiscovery,ResolvePoolDiscovery
    from .summon_quantities import FinishCardSummon
    for work in queue:
        if type(work)in CONTROL and record(state,work.producer_id).status!='active':raise ValueError('Orphan/closed discovery control')
    for root in state.discovery_summon_history:
        controls=[w for w in queue if type(w)in CONTROL and w.producer_id==root.id]
        advances=[w for w in queue if type(w)is ContinuePoolDiscovery and w.producer_id==root.id]
        if root.status!='active':
            if controls or advances:raise ValueError('Closed discovery retains pending work')
            continue
        chosen=picks(root);need_entry=len(root.entry_root_ids)<len(chosen)and(root.spec.delivery=='after_each'or root.phase=='delivering')
        expected=((StartDiscoverySummonEntry(root.id,len(root.entry_root_ids)),)if need_entry else())+(FinishDiscoverySummon(root.id),)
        if tuple(controls)!=expected:raise ValueError('Discovery lost original owed entry/finish tail')
        pending=bool(root.offers and root.offers[-1].offered and root.offers[-1].result is None)
        if len(advances)!=(int(root.phase=='discovering'and not pending)):raise ValueError('Discovery lost original next offer continuation')
        for work in advances:validate_progress(state,registry,work)
        if root.entry_root_ids:
            child=next(x for x in state.card_summon_history if x.id==root.entry_root_ids[-1])
            if child.status=='active':
                tail=next((w for w in queue if type(w)is FinishCardSummon and w.root_id==child.id),None)
                next_work=next((w for w in queue if w in controls or w in advances),None)
                if tail is None or next_work is None or queue.index(tail)>queue.index(next_work):raise ValueError('Discovery advances before its current entry finishes')
        if pending:
            offer=root.offers[-1]
            has_pending=state.pending_choice is not None and state.pending_choice==offer.choice
            has_branch=any(type(w)is ResolvePoolDiscovery and w.batch.producer_id==root.id for w in queue)
            from .effects import RequestChoice
            has_request=any(type(w)is RequestChoice and any(type(e)is ResolvePoolDiscovery and e.batch.producer_id==root.id for o in w.options for e in o.effects)for w in queue)
            if not(has_pending or has_branch or has_request):raise ValueError('Discovery lost its actual original offered choice')


def validate_frame_references(state,registry,value):
    from .discovery import ContinuePoolDiscovery,ResolvePoolDiscovery
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item,scope,depth):
        if depth>FrameCodec.MAX_DEPTH:raise ValueError('Discovery summon frame depth exceeded')
        if type(item)is DiscoverFromPool and item.cause is not None:
            validate_cause(scope,registry,item.cause)
            if item.source_id is not None and item.source_id not in scope.entities:raise ValueError('Queued attributed discovery has an unknown query source')
            return
        if type(item)is ContinuePoolDiscovery and item.producer_id is not None:
            validate_progress(scope,registry,item);return
        if type(item)is ResolvePoolDiscovery and item.batch.producer_id is not None:
            validate_resolve(scope,registry,item);return
        if type(item)in CONTROL:
            if record(scope,item.producer_id).status!='active':raise ValueError('Stale discovery delivery control')
            return
        if type(item)is RuleContext:
            for f in fields(item):
                if f.name!='state':visit(getattr(item,f.name),item.state,depth+1)
            return
        if type(item)is PaidHandChoiceBoundaryProof:
            validate_queue(item.state,registry,item.work);visit(item.work,item.state,depth+1);return
        if type(item)is GameState:return
        if type(item)in(tuple,list):
            for child in item:visit(child,scope,depth+1)
        elif is_dataclass(item):
            for f in fields(item):visit(getattr(item,f.name),scope,depth+1)
    visit(value,state,0)


def validate_boundary(game):
    frame=game._frame;queue=(*frame.prefix,*frame.continuation)if frame else()
    validate_queue(game._state,game.registry,queue)
    if frame:
        reject_choice_control(frame.options);validate_frame_references(game._state,game.registry,frame)
        proof=frame.paid_hand_choice_boundary
        if proof.state.discovery_summon_history!=game._state.discovery_summon_history:raise ValueError('Discovery history differs from complete original choice boundary')
        owned=lambda q:tuple(w for w in q if type(w)in CONTROL)
        if owned(queue)!=owned(proof.work):raise ValueError('Discovery changed original owed delivery work')


def validate_closed_events(game):
    from .summon_quantities import CardSummonRecord,from_dict as entry_from_dict
    state,registry,events=game._state,game.registry,game._events
    children={x.id:x for x in state.card_summon_history}
    for event in events:
        if event.kind=='card_summon_accepted':
            child=entry_from_dict(CardSummonRecord,json.loads(dict(event.data)['root']));children.setdefault(child.id,child)
    current={x.id:x for x in state.discovery_summon_history};latest={}
    kinds=('discovery_summon_accepted','discovery_summon_offered','discovery_summon_bound','discovery_summon_picked','discovery_summon_ready','discovery_summon_entry','discovery_summon_finished')
    for event in events:
        if event.kind not in kinds:continue
        data=dict(event.data)
        if set(data)!={'producer_id','root'}or type(data['root'])is not str:raise ValueError('Complete original discovery event required')
        root=from_dict(DiscoverySummonRecord,json.loads(data['root']));validate_record(state,registry,root,closed=True,children=children)
        if (data['producer_id']!=root.id or event.amount!=len(root.entry_root_ids)or root.event_cursor>=event.sequence or
            root.action>event.action or(event.source_id,event.player_id)!=(root.spec.cause.source.entity_id,root.spec.player_id)):
            raise ValueError('Discovery event changed original identity/domain')
        previous=latest.get(root.id)
        if event.kind=='discovery_summon_accepted':
            if previous is not None or root.offers or root.entry_root_ids or root.phase!='discovering'or root.status!='active'or root.event_cursor!=event.sequence-1:
                raise ValueError('Invalid/duplicate original discovery acceptance')
        else:
            if previous is None or previous.status!='active':raise ValueError('Discovery transition has no original active producer')
            expected=previous
            if event.kind=='discovery_summon_offered':
                if len(root.offers)!=len(previous.offers)+1 or root.offers[-1].choice is not None or root.offers[-1].result is not None or root.offers[-1].event_cursor!=event.sequence-1:
                    raise ValueError('Discovery changed original offer append')
                expected=replace(previous,offers=root.offers,exhausted=root.exhausted)
            elif event.kind in ('discovery_summon_bound','discovery_summon_picked'):
                if not previous.offers or len(root.offers)!=len(previous.offers):raise ValueError('Discovery transition lost original offer')
                old,new=previous.offers[-1],root.offers[-1]
                if event.kind=='discovery_summon_bound':
                    if old.choice is not None or new.choice is None or replace(new,choice=None)!=old:raise ValueError('Discovery changed original actual choice binding')
                else:
                    if old.result is not None or new.result is None or replace(new,result=None)!=old:raise ValueError('Discovery changed original selection')
                expected=replace(previous,offers=(*previous.offers[:-1],new))
            elif event.kind=='discovery_summon_ready':
                expected=replace(previous,phase='delivering')
            elif event.kind=='discovery_summon_entry':
                if len(root.entry_root_ids)!=len(previous.entry_root_ids)+1:raise ValueError('Discovery changed actual child prefix')
                expected=replace(previous,entry_root_ids=root.entry_root_ids)
            elif event.kind=='discovery_summon_finished':
                if root.status=='active':raise ValueError('Discovery has no final status')
                expected=replace(previous,status=root.status)
            if root!=expected:raise ValueError('Discovery transition changed original facts')
        latest[root.id]=root
        if root.id not in current and not any(e.kind=='timeline_rewound'and e.sequence>event.sequence and type(dict(e.data).get('event_start'))is int and dict(e.data)['event_start']<=root.event_cursor for e in events):
            raise ValueError('Discovery producer vanished without actual later Retry')
    for root in current.values():
        if latest.get(root.id)!=root:raise ValueError('Current discovery differs from original private event chain')
    for child in children.values():
        link=child.request.producer_link
        if type(link)is DiscoverySummonEntryLink:
            parent=latest.get(link.producer_id)
            if parent is None:raise ValueError('Actual discovery child has no original parent')
            validate_child(parent,link.index,child)


def spec_from_dict(value):
    from .serialization import _row
    from .model import Keyword
    from .pools import GenerationPolicy
    from .pool_summons import query_from_dict
    from .summon_quantities import from_dict as entry_from_dict
    row=_row(value,DiscoverFromPool);row['query']=query_from_dict(row['query'])
    policy=_row(row['policy'],GenerationPolicy);policy['allowed_special']=tuple(Keyword(k)for k in policy['allowed_special'])
    row['policy']=GenerationPolicy(**policy);row['cause']=entry_from_dict(SummonCause,row['cause'])
    return DiscoverFromPool(**row)


def from_dict(cls,value):
    from .serialization import _row,choice_from_dict,end_turn_rng_from_json
    row=_row(value,cls)
    if cls is DiscoverySummonOffer:
        row['basis']=pool_from_dict(PoolSummonBasis,row['basis'])
        row['available']=tuple(PoolMember(**_row(x,PoolMember))for x in row['available']);row['offered']=tuple(row['offered'])
        for n in ('rng_before','rng_after'):row[n]=end_turn_rng_from_json(row[n])
        row['choice']=None if row['choice']is None else choice_from_dict(row['choice'])
        if row['result']is not None:
            result=_row(row['result'],ChoiceResult);row['result']=ChoiceResult(choice_from_dict(result['choice']),tuple(result['selected_ids']))
    elif cls is DiscoverySummonRecord:
        row['spec']=spec_from_dict(row['spec']);row['offers']=tuple(from_dict(DiscoverySummonOffer,x)for x in row['offers'])
        row['entry_root_ids']=tuple(row['entry_root_ids'])
    return cls(**row)


def rows_from_dict(value):
    if type(value['discovery_summon_history'])is not list:raise ValueError('Typed discovery producer history required')
    value['discovery_summon_history']=[from_dict(DiscoverySummonRecord,x)for x in value['discovery_summon_history']]


def register(mechanics):
    for cls in (DiscoverySummonEntryLink,DiscoverySummonOffer,DiscoverySummonRecord):mechanics.register_payload_type(cls)
    mechanics.register(StartDiscoverySummonEntry,start_entry);mechanics.register(FinishDiscoverySummon,finish)
