"""Attributed pool producers; original draw batches and entry plans stay distinct.

Batch draws precede the existing producer checkpoint. Each selected original
entry accepts its quantity at its old Summon execution window. These are local
policies awaiting CN calibration, not a completeness or authenticity claim.
"""
from dataclasses import asdict,dataclass,fields,is_dataclass,replace
import json
from random import Random

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .producer_amounts import AcceptedProducerAmount,ProducerAmountDecision,capture as capture_amount,validate_record as validate_amount_record,request_profile
from .effects import Effect,_integer,_player
from .errors import ResolutionError,ResolutionLimitExceeded
from .model import CardAbilityCondition,CardClass,CardType,GameState,Keyword,Rarity,SpellSchool,Zone,validate_end_turn_rng
from .pools import GenerationContext,GenerationPolicy,PoolMember,PoolQuery,resolve_candidates,sample_candidates,validate_pool_entry_keywords
from .summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial,accept as accept_entry,validate_cause,validate_material


@dataclass(frozen=True)
class PoolSummonBasis:
    player_id:int
    pool_id:str
    pool_version:str
    context:GenerationContext
    query:PoolQuery
    policy:GenerationPolicy
    source:SourceAllocationFact|None
    hero_class:CardClass|None
    candidates:tuple[PoolMember,...]
    entry_keywords:tuple[Keyword,...]=()
    entry_dormant_turns:int|None=None

    def __post_init__(self):
        if self.entry_dormant_turns is not None:
            _integer(self.entry_dormant_turns,'original pool dormant turns',1)
            if self.source is None or self.entry_keywords:
                raise ValueError('Dormant pool entry requires a source and plain printed material')
        validate_pool_entry_keywords(self.entry_keywords)
        if self.entry_keywords and self.source is None:
            raise ValueError('Original pool entry requires its finite typed declaration and source')
        _player(self.player_id)
        for name in ('pool_id','pool_version'):
            if type(getattr(self,name))is not str or not getattr(self,name):raise ValueError('Unknown pool summon identity')
        for value,kind in ((self.context,GenerationContext),(self.query,PoolQuery),(self.policy,GenerationPolicy)):
            if type(value)is not kind:raise ValueError('Typed original pool query/context/policy required')
            value.__post_init__()
        if self.source is not None:
            if type(self.source)is not SourceAllocationFact:raise ValueError('Typed original pool source required')
            self.source.__post_init__()
        if (self.query.class_mode in ('current','other'))!=(self.hero_class is not None):raise ValueError('Original pool class basis differs from query')
        if self.hero_class is not None and type(self.hero_class)is not CardClass:raise ValueError('Typed original pool class required')
        if type(self.candidates)is not tuple or any(type(x)is not PoolMember for x in self.candidates):raise ValueError('Complete ordered weighted pool inventory required')
        for row in self.candidates:row.__post_init__()
        if len({x.card_id for x in self.candidates})!=len(self.candidates):raise ValueError('Duplicate canonical pool entry')

    @classmethod
    def capture(cls,r,effect,candidates,*,entry_keywords=(),entry_dormant_turns=None):
        context=r.game._generation_context;pool=r.registry.pool(effect.pool_id,context)
        source=None if effect.source_id is None else SourceAllocationFact.capture(r.state,r.state.entities[effect.source_id])
        hero_class=r.player(effect.player_id).hero_class if effect.query.class_mode in ('current','other')else None
        return cls(effect.player_id,effect.pool_id,pool.version,context,effect.query,effect.policy,source,hero_class,candidates,entry_keywords,entry_dormant_turns)


def validate_basis(state,registry,basis,*,closed=False):
    basis.__post_init__()
    from .starting_generation import validate_context
    validate_context(basis.context, state)
    if basis.source is not None:validate_allocation(state,registry,basis.source,closed=closed)
    if registry.pool(basis.pool_id,basis.context).version!=basis.pool_version:raise ValueError('Original pool version differs from registered inventory')
    rows=resolve_candidates(registry,basis.context,basis.pool_id,basis.query,current_class=basis.hero_class,
        source_card_id=None if basis.source is None else basis.source.card_id,policy=basis.policy,player_id=basis.player_id,
        exclude_source_by_rule=True)
    if rows!=basis.candidates:raise ValueError('Pool summon lost/reordered/reweighted its complete original candidates')
    for row in rows:validate_material(registry,SummonEntryMaterial(row.card_id,keywords=basis.entry_keywords,dormant_turns=basis.entry_dormant_turns))


def choose_weighted(rng,materials,weights):
    rows=tuple(PoolMember(m.card_id,w)for m,w in zip(materials,weights))
    chosen=sample_candidates(rng,rows,1,replacement=True)[0]
    return next(i for i,m in enumerate(materials)if m.card_id==chosen)


def validate_weighted_request(state,registry,request,*,closed=False):
    if type(request.pool_basis)is not PoolSummonBasis:raise ValueError('Weighted summon requires its complete original pool basis')
    validate_basis(state,registry,request.pool_basis,closed=closed)
    if (request.player_id!=request.pool_basis.player_id or
        request.materials!=tuple(SummonEntryMaterial(m.card_id,keywords=request.pool_basis.entry_keywords,dormant_turns=request.pool_basis.entry_dormant_turns)for m in request.pool_basis.candidates)or
        request.weights!=tuple(m.weight for m in request.pool_basis.candidates)):
        raise ValueError('Weighted entry differs from original resolved pool')


@dataclass(frozen=True)
class PoolSummonEntryLink:
    batch_id:int
    index:int
    def __post_init__(self):
        _integer(self.batch_id,'pool entry batch',1);_integer(self.index,'pool entry index',0)


@dataclass(frozen=True)
class PoolFillCapacity:
    player_id:int
    limit:int
    occupants:tuple[SourceAllocationFact,...]

    def __post_init__(self):
        _player(self.player_id);_integer(self.limit,'original board limit',1)
        if (type(self.occupants)is not tuple or any(type(a)is not SourceAllocationFact for a in self.occupants)
                or len(self.occupants)>self.limit or len({a.entity_id for a in self.occupants})!=len(self.occupants)):
            raise ValueError('Fill capacity requires its complete original physical occupants')
        for a in self.occupants:
            a.__post_init__()
            if a.zone!=Zone.BOARD or a.controller!=self.player_id or a.kind not in(CardType.MINION,CardType.LOCATION):
                raise ValueError('Fill capacity borrowed a nonoccupant or another recipient')

    @property
    def remaining(self):return self.limit-len(self.occupants)

    def validate_in_state(self,state,registry,*,limit=None,closed=False):
        self.__post_init__()
        if limit is not None and self.limit!=limit:
            raise ValueError('Fill capacity changed the actual ruleset board limit')
        for a in self.occupants:validate_allocation(state,registry,a,closed=closed)

    @classmethod
    def capture(cls,r,player_id):
        return cls(player_id,r.rules.max_board,tuple(SourceAllocationFact.capture(r.state,r.state.entities[i])
            for i in r.player(player_id).board))


@dataclass(frozen=True)
class PoolSummonBatchSpec:
    cause:SummonCause
    basis:PoolSummonBasis
    count:int
    replacement:bool
    producer_profile_id:str|None=None
    position:int|None=None
    fill_capacity:PoolFillCapacity|None=None
    def __post_init__(self):
        if type(self.cause)is not SummonCause or type(self.basis)is not PoolSummonBasis:raise ValueError('Typed attributed batch producer required')
        self.cause.__post_init__();self.basis.__post_init__();_integer(self.count,'original batch count',0)
        if self.basis.entry_dormant_turns is not None:
            raise ValueError('Preselected batch producer does not declare forced dormant entries')
        if type(self.replacement)is not bool:raise ValueError('Typed batch replacement required')
        if self.producer_profile_id is not None and (type(self.producer_profile_id)is not str or not self.producer_profile_id):raise ValueError('Named logical batch profile required')
        if self.position is not None:_integer(self.position,'original pool batch board position',0)
        if self.fill_capacity is not None:
            if type(self.fill_capacity)is not PoolFillCapacity:
                raise ValueError('Fill producer requires its typed original capacity')
            self.fill_capacity.__post_init__()
            if (self.fill_capacity.player_id!=self.basis.player_id or self.count!=self.fill_capacity.remaining
                    or not self.replacement or self.producer_profile_id is not None or self.position is not None):
                raise ValueError('Fill producer changed its original free-slot count or profile')


@dataclass(frozen=True)
class PoolSummonBatchRecord:
    id:int
    event_cursor:int
    turn:int
    action:int
    spec:PoolSummonBatchSpec
    selected:tuple[str,...]
    rng_before:tuple
    rng_after:tuple
    entry_root_ids:tuple[int,...]=()
    status:str='active'
    producer_amount:AcceptedProducerAmount|None=None
    def __post_init__(self):
        for name in ('id','turn'):_integer(getattr(self,name),'pool batch '+name,1)
        for name in ('event_cursor','action'):_integer(getattr(self,name),'pool batch '+name,0)
        if type(self.spec)is not PoolSummonBatchSpec:raise ValueError('Typed original batch specification required')
        self.spec.__post_init__()
        if (self.spec.producer_profile_id is None)!=(self.producer_amount is None):raise ValueError('Logical batch lost or borrowed its amount fact')
        if self.producer_amount is not None:
            if type(self.producer_amount)is not AcceptedProducerAmount:raise ValueError('Typed original producer amount required')
            self.producer_amount.__post_init__()
            fact=self.producer_amount
            if (fact.profile.id!=self.spec.producer_profile_id or fact.base_count!=self.spec.count or fact.cause!=self.spec.cause or fact.recipient_id!=self.spec.basis.player_id or (fact.batch_id,fact.event_cursor,fact.turn,fact.action)!=(self.id,self.event_cursor,self.turn,self.action)):raise ValueError('Amount fact differs from original batch request/window')
        if type(self.selected)is not tuple or any(type(x)is not str for x in self.selected):raise ValueError('Complete original selected batch required')
        if type(self.entry_root_ids)is not tuple or len(self.entry_root_ids)>len(self.selected):raise ValueError('Typed original entry root prefix required')
        for root in self.entry_root_ids:_integer(root,'actual batch entry root',1)
        if list(self.entry_root_ids)!=sorted(set(self.entry_root_ids)):raise ValueError('Repeated/reordered batch entry identities')
        if self.status not in ('active','completed','interrupted'):raise ValueError('Unknown original batch status')
        if self.status=='completed'and len(self.entry_root_ids)!=len(self.selected):raise ValueError('Incomplete completed original batch')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        local=Random();local.setstate(self.rng_before)
        count=self.spec.count if self.producer_amount is None else self.producer_amount.total
        expected=sample_candidates(local,self.spec.basis.candidates,count,replacement=self.spec.replacement)
        if expected!=self.selected or local.getstate()!=self.rng_after:raise ValueError('Batch selection/RNG differs from complete original weighted draw')


@dataclass(frozen=True)
class StartPoolSummonEntry(Effect):
    batch_id:int
    index:int
    def __post_init__(self):_integer(self.batch_id,'start pool batch',1);_integer(self.index,'start original entry',0)


@dataclass(frozen=True)
class FinishPoolSummonBatch(Effect):
    batch_id:int
    def __post_init__(self):_integer(self.batch_id,'finish pool batch',1)


CONTROL=(StartPoolSummonEntry,FinishPoolSummonBatch)


def record(state,batch_id):
    root=next((r for r in state.pool_summon_history if r.id==batch_id),None)
    if root is None:raise ValueError('Unknown original pool summon batch')
    return root


def update(state,old,**changes):
    value=replace(old,**changes);state.pool_summon_history[state.pool_summon_history.index(old)]=value
    return value


def json_record(root):return json.dumps(asdict(root),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def emit(r,kind,root):
    r.emit(kind,source_id=root.spec.cause.source.entity_id,player_id=root.spec.basis.player_id,
        amount=len(root.selected)if kind=='pool_summon_accepted'else len(root.entry_root_ids),batch_id=root.id,root=json_record(root),_capture=False)


def accept_batch(r,effect,candidates,*,fill_board=False):
    if type(fill_board)is not bool:raise ValueError('Fill policy requires a boolean')
    validate_cause(r.state,r.registry,effect.cause)
    if effect.count>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Pool summon batch exceeds engineering budget')
    basis=PoolSummonBasis.capture(r,effect,candidates);validate_basis(r.state,r.registry,basis)
    capacity=PoolFillCapacity.capture(r,effect.player_id)if fill_board else None
    if capacity is not None:
        capacity.validate_in_state(r.state,r.registry,limit=r.rules.max_board)
        if effect.producer_profile_id is not None:raise ValueError('Fill cannot borrow a logical amount profile')
    amount=capture_amount(r,effect)
    base_count=effect.count if capacity is None else capacity.remaining
    count=base_count if amount is None else amount.total
    if count>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Derived producer amount exceeds engineering budget')
    spec=PoolSummonBatchSpec(effect.cause,basis,base_count,effect.replacement,effect.producer_profile_id,effect.board_position,capacity)
    before=r.game._rng.getstate()
    selected=sample_candidates(r.game._rng,candidates,count,replacement=effect.replacement)
    root=PoolSummonBatchRecord(r.state.next_pool_summon_id,len(r.game._events),r.state.turn,r.state.action_number,
        spec,selected,before,r.game._rng.getstate(),producer_amount=amount)
    r.state.next_pool_summon_id+=1;r.state.pool_summon_history.append(root);emit(r,'pool_summon_accepted',root)
    return ((StartPoolSummonEntry(root.id,0),)if selected else ())+ (FinishPoolSummonBatch(root.id),)


def entry_position(batch,index,children):
    if batch.spec.position is None:return None
    return batch.spec.position+sum(d.outcome=='delivered'for child_id in batch.entry_root_ids[:index]
        for d in children[child_id].deliveries)


def start_entry(r,effect):
    root=record(r.state,effect.batch_id)
    if root.status!='active'or effect.index!=len(root.entry_root_ids)or effect.index>=len(root.selected):raise ResolutionError('Out-of-order original pool entry')
    if root.entry_root_ids and next(x for x in r.state.card_summon_history if x.id==root.entry_root_ids[-1]).status=='active':raise ResolutionError('Pool entry preceded completion of previous entry')
    request=SummonByCard(root.spec.basis.player_id,(SummonEntryMaterial(root.selected[effect.index]),),root.spec.cause,
        position=entry_position(root,effect.index,{x.id:x for x in r.state.card_summon_history}),
        capacity='preselected_attempt',producer_link=PoolSummonEntryLink(root.id,effect.index))
    continuation=accept_entry(r,request);child_id=r.state.card_summon_history[-1].id
    update(r.state,root,entry_root_ids=(*root.entry_root_ids,child_id))
    if effect.index+1<len(root.selected):continuation=(*continuation,StartPoolSummonEntry(root.id,effect.index+1))
    return continuation


def finish(r,effect):
    root=record(r.state,effect.batch_id)
    if root.status!='active'or len(root.entry_root_ids)!=len(root.selected):raise ResolutionError('Incomplete original pool batch finish')
    if any(next(x for x in r.state.card_summon_history if x.id==i).status=='active'for i in root.entry_root_ids):raise ResolutionError('Pool batch finish preceded child entry finish')
    emit(r,'pool_summon_finished',update(r.state,root,status='completed'))


def interrupt(r):
    for root in tuple(r.state.pool_summon_history):
        if root.status=='active':emit(r,'pool_summon_finished',update(r.state,root,status='interrupted'))


def validate_link(state,root,*,closed=False):
    link=root.request.producer_link
    if link is None:return
    link.__post_init__()
    if link.batch_id>=state.next_pool_summon_id:raise ValueError('Future original batch entry link')
    batch=next((r for r in state.pool_summon_history if r.id==link.batch_id),None)
    if batch is None:
        if closed:return
        raise ValueError('Unknown pool entry producer')
    if (link.index>=len(batch.entry_root_ids)or batch.entry_root_ids[link.index]!=root.id or
        root.request.cause!=batch.spec.cause or root.request.player_id!=batch.spec.basis.player_id or
        root.request.materials!=(SummonEntryMaterial(batch.selected[link.index]),)or root.request.capacity!='preselected_attempt'or
        root.request.position!=entry_position(batch,link.index,{x.id:x for x in state.card_summon_history})):
        raise ValueError('Entry borrowed another original batch/index/cause/material')


def validate_record(state,registry,root,*,closed=False,children=None):
    validate_amount_record(registry,root)
    root.__post_init__();validate_cause(state,registry,root.spec.cause,closed=closed);validate_basis(state,registry,root.spec.basis,closed=closed)
    if root.spec.fill_capacity is not None:root.spec.fill_capacity.validate_in_state(state,registry,closed=closed)
    fact=root.producer_amount
    if fact is not None and (fact.next_entity_id>state.next_entity_id or fact.next_attachment_id>state.next_attachment_id or fact.next_order>state.next_order):
        raise ValueError('Producer amount carries future original allocation counters')
    if root.id>=state.next_pool_summon_id or root.turn>state.turn or root.action>state.action_number:raise ValueError('Future pool batch acceptance')
    if root.spec.cause.turn>root.turn or root.spec.cause.action>root.action:raise ValueError('Batch cause is newer than its original acceptance')
    if not closed and root.status=='interrupted'and state.status=='playing':raise ValueError('Playing batch cannot be terminal interrupted')
    if children is None:children={r.id:r for r in state.card_summon_history}
    for index,child_id in enumerate(root.entry_root_ids):
        child=children.get(child_id)
        if child is None:raise ValueError('Batch lost an actual original child entry')
        req=child.request
        if (req.producer_link!=PoolSummonEntryLink(root.id,index)or req.cause!=root.spec.cause or
            req.player_id!=root.spec.basis.player_id or req.materials!=(SummonEntryMaterial(root.selected[index]),)or
            req.capacity!='preselected_attempt' or req.position!=entry_position(root,index,children)or
            child.event_cursor<=root.event_cursor):raise ValueError('Batch entry differs from original selected item/cause/window')


def validate_history(state,registry):
    _integer(state.next_pool_summon_id,'next pool summon id',1)
    if type(state.pool_summon_history)is not list:raise ValueError('Typed pool summon history required')
    for root in state.pool_summon_history:
        if type(root)is not PoolSummonBatchRecord:raise ValueError('Typed original pool batch required')
        validate_record(state,registry,root)
    ids=[r.id for r in state.pool_summon_history]
    if ids!=sorted(set(ids)):raise ValueError('Reordered pool producer identities')


def reject_choice_control(options):
    from .summon_quantities import walk_work
    if any(type(w)in CONTROL for w in walk_work(options)):raise ValueError('Choice cannot inject pool summon control')


def validate_queue(state,registry,queue):
    from .summon_quantities import FinishCardSummon
    for work in queue:
        if type(work)in CONTROL and record(state,work.batch_id).status!='active':raise ValueError('Orphan/settled pool summon control')
    for root in state.pool_summon_history:
        controls=[w for w in queue if type(w)in CONTROL and w.batch_id==root.id]
        if root.status!='active':
            if controls:raise ValueError('Completed pool batch retains control')
            continue
        expected=((StartPoolSummonEntry(root.id,len(root.entry_root_ids)),)if len(root.entry_root_ids)<len(root.selected)else())+(FinishPoolSummonBatch(root.id),)
        if tuple(controls)!=expected:raise ValueError('Pool batch lost complete original owed continuation')
        if root.entry_root_ids:
            child=next(r for r in state.card_summon_history if r.id==root.entry_root_ids[-1])
            if child.status=='active':
                tail=next((w for w in queue if type(w)is FinishCardSummon and w.root_id==child.id),None)
                if tail is None or queue.index(tail)>queue.index(controls[0]):raise ValueError('Batch advances before current child completion')


def validate_frame_references(state,registry,value):
    from .pools import GenerateFromPool,SummonFromCandidates,SummonFromPool,FillBoardFromPool
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item,scope,depth):
        if depth>FrameCodec.MAX_DEPTH:raise ValueError('Pool summon frame depth exceeded')
        if type(item)in(GenerateFromPool,SummonFromCandidates,SummonFromPool,FillBoardFromPool)and item.cause is not None:
            item.__post_init__()
            if type(item)is GenerateFromPool:request_profile(registry,item)
            validate_cause(scope,registry,item.cause)
            if item.source_id is not None and item.source_id not in scope.entities:raise ValueError('Queued attributed producer has an unknown original query source')
            if type(item)is SummonFromCandidates:
                for card_id in item.card_ids:validate_material(registry,SummonEntryMaterial(card_id))
            return
        if type(item)is SummonCause:validate_cause(scope,registry,item);return
        if type(item)is PoolSummonBasis:validate_basis(scope,registry,item);return
        if type(item)in CONTROL:
            if record(scope,item.batch_id).status!='active':raise ValueError('Stale pool summon control')
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
    for root in game._state.pool_summon_history:
        if root.spec.fill_capacity is not None:
            root.spec.fill_capacity.validate_in_state(game._state,game.registry,limit=game.ruleset.max_board)
    frame=game._frame;queue=(*frame.prefix,*frame.continuation)if frame else()
    validate_queue(game._state,game.registry,queue)
    if frame:
        reject_choice_control(frame.options);validate_frame_references(game._state,game.registry,frame)
        proof=frame.paid_hand_choice_boundary
        if proof.state.pool_summon_history!=game._state.pool_summon_history:raise ValueError('Batch history differs from complete original choice boundary')
        controls=lambda q:tuple(w for w in q if type(w)in CONTROL)
        if controls(queue)!=controls(proof.work):raise ValueError('Batch changed original pending continuation')


def validate_closed_events(game):
    from .summon_quantities import CardSummonRecord,from_dict as entry_from_dict
    state,registry,events=game._state,game.registry,game._events
    children={r.id:r for r in state.card_summon_history}
    for event in events:
        if event.kind=='card_summon_accepted':
            child=entry_from_dict(CardSummonRecord,json.loads(dict(event.data)['root']));children.setdefault(child.id,child)
    current={r.id:r for r in state.pool_summon_history};accepted={};closed={}
    for event in events:
        if event.kind not in ('pool_summon_accepted','pool_summon_finished'):continue
        data=dict(event.data)
        if set(data)!= {'batch_id','root'}or type(data['root'])is not str:raise ValueError('Complete original pool producer event required')
        root=from_dict(PoolSummonBatchRecord,json.loads(data['root']));validate_record(state,registry,root,closed=True,children=children)
        if root.spec.fill_capacity is not None:
            root.spec.fill_capacity.validate_in_state(state,registry,limit=game.ruleset.max_board,closed=True)
        if (data['batch_id']!=root.id or root.action>event.action or root.event_cursor>=event.sequence or
            (event.source_id,event.player_id)!=(root.spec.cause.source.entity_id,root.spec.basis.player_id)):
            raise ValueError('Pool event changed original producer/event domain')
        if event.kind=='pool_summon_accepted':
            if root.id in accepted or root.status!='active'or root.entry_root_ids or root.event_cursor!=event.sequence-1 or event.amount!=len(root.selected):raise ValueError('Invalid/duplicate original pool acceptance')
            accepted[root.id]=root
        else:
            if (root.id in closed or root.status=='active'or event.amount!=len(root.entry_root_ids)or
                replace(root,entry_root_ids=(),status='active')!=accepted.get(root.id)):raise ValueError('Pool close differs from complete original draw')
            closed[root.id]=root
        if root.id not in current and not any(e.kind=='timeline_rewound'and e.sequence>event.sequence and
            type(dict(e.data).get('event_start'))is int and dict(e.data)['event_start']<=root.event_cursor for e in events):raise ValueError('Pool producer vanished without later actual Retry')
    for root in current.values():
        if replace(root,entry_root_ids=(),status='active')!=accepted.get(root.id)or(root.status!='active'and closed.get(root.id)!=root):raise ValueError('Current producer differs from original event receipts')
    parents={**closed,**current}
    for child in children.values():
        link=child.request.producer_link
        if type(link)is not PoolSummonEntryLink:continue
        parent=parents.get(link.batch_id)
        if (parent is None or link.index>=len(parent.entry_root_ids)or
            parent.entry_root_ids[link.index]!=child.id):raise ValueError('Actual child entry has no complete original producer ownership')


def query_from_dict(value):
    from .serialization import _row
    row=_row(value,PoolQuery)
    for name,kind in (('kinds',CardType),('classes',CardClass),('rarities',Rarity),('spell_schools',SpellSchool),('keywords_all',Keyword)):
        row[name]=tuple(kind(v)for v in row[name])
    if type(row['subtypes_any']) not in (list,tuple):
        raise ValueError('Pool subtype filter requires an array or tuple')
    for name in ('tribes_any','exclude_card_ids','factions_any','subtypes_any'):row[name]=tuple(row[name])
    row['ability']=None if row['ability']is None else CardAbilityCondition(**_row(row['ability'],CardAbilityCondition))
    alternatives=row['any_of']
    if type(alternatives) not in (list,tuple):
        raise ValueError('Pool query alternatives require an array or tuple')
    # Reject nested input before recursion, including forged JSON with arbitrary
    # depth. The shared query contract permits only one flat alternative layer.
    for clause in alternatives:
        fields=_row(clause,PoolQuery)
        if type(fields['any_of']) not in (list,tuple) or fields['any_of']:
            raise ValueError('Pool query alternatives must be flat')
    row['any_of']=tuple(query_from_dict(clause) for clause in alternatives)
    return PoolQuery(**row)


def from_dict(cls,value):
    from .serialization import _row,end_turn_rng_from_json
    from .summon_quantities import from_dict as entry_from_dict
    row=_row(value,cls)
    if cls is PoolSummonBasis:
        row['context']=GenerationContext.from_dict(_row(row['context'],GenerationContext));row['query']=query_from_dict(row['query'])
        policy=_row(row['policy'],GenerationPolicy);policy['allowed_special']=tuple(Keyword(k)for k in policy['allowed_special']);row['policy']=GenerationPolicy(**policy)
        row['source']=allocation_from_dict(row['source']);row['hero_class']=None if row['hero_class']is None else CardClass(row['hero_class'])
        row['candidates']=tuple(PoolMember(**_row(x,PoolMember))for x in row['candidates'])
        row['entry_keywords']=tuple(Keyword(k)for k in row['entry_keywords'])
    elif cls is PoolSummonBatchSpec:
        row['cause']=entry_from_dict(SummonCause,row['cause']);row['basis']=from_dict(PoolSummonBasis,row['basis'])
        if row['fill_capacity']is not None:
            cap=_row(row['fill_capacity'],PoolFillCapacity)
            cap['occupants']=tuple(allocation_from_dict(a)for a in cap['occupants'])
            row['fill_capacity']=PoolFillCapacity(**cap)
    elif cls is PoolSummonBatchRecord:
        row['spec']=from_dict(PoolSummonBatchSpec,row['spec']);row['selected']=tuple(row['selected']);row['entry_root_ids']=tuple(row['entry_root_ids'])
        from .producer_amounts import from_dict as amount_from_dict
        row['producer_amount']=None if row['producer_amount']is None else amount_from_dict(row['producer_amount'])
        for name in ('rng_before','rng_after'):row[name]=end_turn_rng_from_json(row[name])
    return cls(**row)


def rows_from_dict(value):
    if type(value['pool_summon_history'])is not list:raise ValueError('Typed original pool producer history required')
    value['pool_summon_history']=[from_dict(PoolSummonBatchRecord,x)for x in value['pool_summon_history']]


def register(mechanics):
    for cls in (PoolSummonBasis,PoolFillCapacity,PoolSummonEntryLink,PoolSummonBatchSpec,PoolSummonBatchRecord,GenerationContext,AcceptedProducerAmount,ProducerAmountDecision):mechanics.register_payload_type(cls)
    mechanics.register(StartPoolSummonEntry,start_entry);mechanics.register(FinishPoolSummonBatch,finish)
