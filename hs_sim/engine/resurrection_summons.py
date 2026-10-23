"""Frozen death materials, original batch draws, and independent body followups.

Policies describe an internal ordinary-material profile pending CN calibration.
Private receipts prove consistency, not unsigned archive origin authenticity.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass,fields,is_dataclass,replace
import json
from random import Random
from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import Effect,_integer,_player,_source
from .errors import ResolutionError,ResolutionLimitExceeded
from .model import CardClass,CardType,DeathRecord,GameState,ResurrectionRecord,SummonStats,Zone,validate_end_turn_rng,validate_summon_stats


def encoded(value):return json.dumps(asdict(value),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def validate_death(state,registry,death,*,closed=False):
    death.__post_init__();registry.card(death.card_id)
    from .jade import validate_instance
    validate_instance(registry, death)
    if death.id>=state.next_death_id or death.entity_id>=state.next_entity_id or death.turn>state.turn:raise ValueError('Future original resurrection death')
    if not closed and death!=next((d for d in state.death_history if d.id==death.id),None):raise ValueError('Resurrection material differs from its immutable actual death')


@dataclass(frozen=True)
class ResurrectionEntryMaterial:
    card_id:str
    death:DeathRecord
    source:SourceAllocationFact|None
    captured_turn:int
    captured_action:int
    next_entity_id:int
    next_order:int
    next_attachment_id:int
    stats:SummonStats|None=None
    on_summon:str|None=None
    entry_herald_count:int|None=None
    def __post_init__(self):
        if type(self.death)is not DeathRecord:raise ValueError('Complete typed immutable death material required')
        self.death.__post_init__()
        if self.card_id!=self.death.card_id or self.death.zone!=Zone.BOARD:raise ValueError('Resurrection material requires its original board minion death')
        if self.source is not None:
            if type(self.source)is not SourceAllocationFact:raise ValueError('Typed original resurrection effect source required')
            self.source.__post_init__()
        for n in('captured_turn','next_entity_id','next_order','next_attachment_id'):_integer(getattr(self,n),'resurrection material '+n,1)
        _integer(self.captured_action,'resurrection material action',0);validate_summon_stats(self.stats)
        if self.on_summon is not None and(type(self.on_summon)is not str or not self.on_summon):raise ValueError('Registered resurrection followup required')
        if self.entry_herald_count is not None:_integer(self.entry_herald_count,'accepted resurrection Herald count',0)
        if self.death.entity_id>=self.next_entity_id:raise ValueError('Death material contains a future original body')


def validate_face(registry,material):
    material.__post_init__();card=registry.card(material.card_id)
    from .crafted_faces import composition_shape
    if card.kind!=CardType.MINION or card.choice_only or not composition_shape(card,material.death.components):
        raise ValueError('Resurrection requires a complete printed minion and its original composition')
    for card_id in material.death.components:
        component=registry.card(card_id)
        if component.kind!=CardType.MINION or component.starship_for:
            raise ValueError('Resurrection composition requires its original non-composite minion pieces')
    if material.on_summon is not None:registry.behavior(material.on_summon)
    if registry.card(material.card_id).herald_scaling!=(material.entry_herald_count is not None):raise ValueError('Resurrection lost original deferred entry-strength basis')


def validate_material(state,registry,material,*,closed=False):
    validate_face(registry,material);validate_death(state,registry,material.death,closed=closed)
    if material.source is not None:validate_allocation(state,registry,material.source,closed=closed)
    if any(getattr(material,n)>getattr(state,s)for n,s in(('captured_turn','turn'),('captured_action','action_number'),('next_entity_id','next_entity_id'),('next_order','next_order'),('next_attachment_id','next_attachment_id'))):raise ValueError('Future resurrection acceptance window')


def accept_entry(r,effect):
    from .summon_sources import death_record
    from .herald import herald_count
    from .summon_quantities import SummonByCard,DeliverCardSummon,FinishCardSummon,accept,deliver
    validate_effect(r.state,r.registry,effect);death=death_record(r.state,effect.death_id)
    material=ResurrectionEntryMaterial(death.card_id,death,None if effect.source_id is None else SourceAllocationFact.capture(r.state,r.state.entities[effect.source_id]),
        r.state.turn,r.state.action_number,r.state.next_entity_id,r.state.next_order,r.state.next_attachment_id,effect.stats,effect.on_summon,
        herald_count(r.state,effect.player_id)if r.registry.card(death.card_id).herald_scaling else None)
    request=SummonByCard(effect.player_id,(material,),effect.cause,position=effect.position,producer_link=effect.producer_link)
    accept(r,request);root=r.state.card_summon_history[-1]
    if effect.producer_link is not None:bind_entry(r,effect.producer_link,root.id)
    return(*deliver(r,DeliverCardSummon(root.id,0)),FinishCardSummon(root.id))


def failed(r,material,player_id):
    r.emit('resurrection_failed',player_id=player_id,source_id=None if material.source is None else material.source.entity_id,
        reason='board_full',death_id=material.death.id)


def create_body(r,material,player_id,position):
    entity = r.create_entity(player_id,material.card_id,Zone.BOARD,position,
        components=material.death.components,entry_herald_count=material.entry_herald_count)
    from .jade import inherit_printed
    inherit_printed(material.death, entity, state=r.state)
    return entity


def apply(r,material,entity,root_id,index):
    from .lifecycle import apply_summon_stats
    entity.origin_entity_id=material.death.entity_id
    from .native_stat_gains import seed
    seed(r,entity,replace_existing=True)
    apply_summon_stats(r.state,entity,material.stats)
    row=ResurrectionRecord(len(r.state.resurrection_history)+1,material.death.id,entity.id,entity.controller,r.state.turn,r.state.action_number,
        None if material.source is None else material.source.entity_id,material.stats,entity.entered_order,entity.zone_epoch)
    r.state.resurrection_history.append(row);r.refresh_auras()
    from .sacrifice import MinionReference
    binding=ResurrectionBodyBinding(root_id,index,row,MinionReference.capture(entity),material.on_summon,'pending'if material.on_summon is not None else'none')
    r.state.resurrection_quantity_bodies.append(binding)
    r.emit('resurrection_delivery_bound',root_id=root_id,index=index,binding=encoded(binding),_capture=False)


def enter(r,material,entity):
    from .colossal import enter_minion
    binding=next(x for x in r.state.resurrection_quantity_bodies if x.resurrection.entity_id==entity.id)
    tail=(ContinueQuantityResurrection(binding.root_id,binding.index),)if material.on_summon is not None else()
    return(*enter_minion(r,entity,'resurrect',origin_id=material.death.entity_id,death_id=material.death.id),*tail)


@dataclass(frozen=True)
class ResurrectionBodyBinding:
    root_id:int
    index:int
    resurrection:ResurrectionRecord
    beneficiary:object
    behavior_id:str|None
    status:str
    def __post_init__(self):
        from .sacrifice import MinionReference
        _integer(self.root_id,'body quantity root',1);_integer(self.index,'body quantity index',0)
        if type(self.resurrection)is not ResurrectionRecord or type(self.beneficiary)is not MinionReference:raise ValueError('Complete typed original body continuation binding required')
        self.resurrection.__post_init__();self.beneficiary.__post_init__()
        row=self.resurrection;ref=self.beneficiary
        if(ref.entity_id,ref.player_id,ref.zone_epoch,ref.entered_order)!=(row.entity_id,row.player_id,row.zone_epoch,row.entered_order):raise ValueError('Body continuation borrowed another original entry')
        if self.status not in('none','pending','attempted','skipped','interrupted')or(self.behavior_id is None)!=(self.status=='none'):raise ValueError('Unknown/incomplete body continuation status')


@dataclass(frozen=True)
class ContinueQuantityResurrection(Effect):
    root_id:int
    index:int
    def __post_init__(self):_integer(self.root_id,'body continuation quantity root',1);_integer(self.index,'body continuation quantity index',0)


def body_binding(state,root_id,index):
    row=next((x for x in state.resurrection_quantity_bodies if(x.root_id,x.index)==(root_id,index)),None)
    if row is None:raise ValueError('Unknown original quantity resurrection body')
    return row


def finish_body(r,binding,status):
    value=replace(binding,status=status);r.state.resurrection_quantity_bodies[r.state.resurrection_quantity_bodies.index(binding)]=value
    r.emit('resurrection_followup_finished',root_id=binding.root_id,index=binding.index,binding=encoded(value),_capture=False)


def continue_body(r,effect):
    from .summon_sources import ContinueResurrectedMinion,continue_resurrected_minion
    binding=body_binding(r.state,effect.root_id,effect.index)
    if binding.status!='pending':raise ResolutionError('Resurrection continuation was already attempted')
    work=continue_resurrected_minion(r,ContinueResurrectedMinion(binding.resurrection.id,binding.beneficiary,binding.behavior_id))
    finish_body(r,binding,'attempted'if work else'skipped');return work


def primary_resurrected_body(context):
    """Identify the original body of this attributed resurrection, before extras."""
    rows=[binding for binding in context.state.resurrection_quantity_bodies
          if binding.resurrection.entity_id==context.target_id]
    if len(rows)!=1 or context.death is None:
        raise ResolutionError('Primary resurrection query requires its original attributed body')
    binding=rows[0];row=binding.resurrection
    if (row.player_id,row.source_id,row.death_id)!=(context.player_id,context.source_id,context.death.id):
        raise ResolutionError('Primary resurrection query lost its original source or death')
    return binding.index==0


def validate_delivery(state,material,delivery,player_id,*,closed=False):
    fact=delivery.entity
    if (fact.card_id,fact.owner,fact.controller,fact.kind,fact.zone)!=(material.card_id,player_id,player_id,CardType.MINION,Zone.BOARD)or fact.entity_id<material.next_entity_id or fact.zone_epoch!=0:raise ValueError('Resurrection delivery borrowed another physical body or recipient')
    if delivery.index==0 and(fact.entity_id,fact.entered_order)!=(material.next_entity_id,material.next_order):raise ValueError('First resurrection differs from its actual original allocation window')
    if not closed:
        row=next((x for x in state.resurrection_history if x.entity_id==fact.entity_id),None)
        validate_body_row(material,fact,row)


def validate_body_row(material,fact,row):
    if row is None:raise ValueError('Successful quantity resurrection lost its own ResurrectionRecord')
    row.__post_init__()
    if (row.death_id,row.entity_id,row.player_id,row.source_id,row.stats,row.entered_order,row.zone_epoch)!=(material.death.id,fact.entity_id,fact.controller,
        None if material.source is None else material.source.entity_id,material.stats,fact.entered_order,fact.zone_epoch):raise ValueError('ResurrectionRecord differs from its actual accepted body')
    if row.turn<material.captured_turn or row.action<material.captured_action:raise ValueError('Resurrection record preceded original acceptance')


@dataclass(frozen=True)
class ResurrectionBasis:
    player_id:int
    query:object
    source:SourceAllocationFact|None
    hero_class:CardClass|None
    inventory:tuple[DeathRecord,...]
    turn:int
    action:int
    next_death_id:int
    next_entity_id:int
    def __post_init__(self):
        from .summon_sources import DeathQuery
        _player(self.player_id)
        if type(self.query)is not DeathQuery:raise ValueError('Typed original frozen death query required')
        self.query.__post_init__()
        if self.source is not None:self.source.__post_init__()
        if self.hero_class is not None and(type(self.hero_class)is not CardClass or self.hero_class==CardClass.NEUTRAL):raise ValueError('Invalid original resurrection hero class')
        if self.query.cards.class_mode in('current','other')and self.hero_class is None:raise ValueError('Original death query needs current class')
        for n in('turn','next_death_id','next_entity_id'):_integer(getattr(self,n),'resurrection query '+n,1)
        _integer(self.action,'resurrection query action',0)
        if type(self.inventory)is not tuple or any(type(x)is not DeathRecord for x in self.inventory):raise ValueError('Complete ordered original death inventory required')
        for x in self.inventory:x.__post_init__()
        if [x.id for x in self.inventory]!=sorted({x.id for x in self.inventory}):raise ValueError('Reordered/duplicated original death inventory')


def candidates(registry,basis):
    from .summon_sources import death_query_candidates
    return death_query_candidates(registry,basis.player_id,basis.query,basis.inventory,basis.hero_class,None if basis.source is None else basis.source.card_id)


def validate_basis(state,registry,basis,*,closed=False,death_ids=None):
    basis.__post_init__()
    if basis.turn>state.turn or basis.action>state.action_number or basis.next_death_id>state.next_death_id or basis.next_entity_id>state.next_entity_id:raise ValueError('Future original resurrection candidate window')
    if basis.source is not None:validate_allocation(state,registry,basis.source,closed=closed)
    for death in basis.inventory:
        validate_death(state,registry,death,closed=closed)
        if death.id>=basis.next_death_id or death.entity_id>=basis.next_entity_id:raise ValueError('Original death query included a future record')
    result=candidates(registry,basis)
    if death_ids is not None:
        # Exact native materials are checked by the existing entry profile when
        # selected. Unselected composite deaths must not veto this subset.
        ids=tuple(x.id for x in result)
        if set(death_ids)-set(ids):raise ValueError('Exact resurrection death is outside the complete original query')
        return tuple(i for i in ids if i in death_ids)
    from .summon_quantities import SummonEntryMaterial,validate_material as validate_plain
    for death in result:
        from .crafted_faces import PREFIX as crafted_prefix
        if death.components and not death.card_id.startswith(crafted_prefix):
            raise ValueError('Composite death quantity material is unsupported by ordinary profile')
        validate_plain(registry,SummonEntryMaterial(death.card_id))
    return tuple(x.id for x in result)


@dataclass(frozen=True)
class ResurrectionEntryLink:
    resurrection_batch_id:int
    index:int
    def __post_init__(self):_integer(self.resurrection_batch_id,'resurrection producer',1);_integer(self.index,'original resurrection iteration',0)


@dataclass(frozen=True)
class ResurrectionPick:
    index:int
    available:tuple[int,...]
    selected:int
    rng_before:tuple
    rng_after:tuple
    entry_root_id:int|None=None
    def __post_init__(self):
        _integer(self.index,'resurrection pick index',0);_integer(self.selected,'selected original death',1)
        if type(self.available)is not tuple or not self.available or len(set(self.available))!=len(self.available)or self.selected not in self.available:raise ValueError('Complete remaining frozen death candidates required')
        for x in self.available:_integer(x,'available original death',1)
        if self.entry_root_id is not None:_integer(self.entry_root_id,'actual resurrection entry root',1)
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)


@dataclass(frozen=True)
class ResurrectionBatch:
    id:int
    event_cursor:int
    turn:int
    action:int
    spec:object
    basis:ResurrectionBasis|None
    candidates:tuple[int,...]
    picks:tuple[ResurrectionPick,...]=()
    status:str='active'
    attacks:object=None
    def __post_init__(self):
        from .summon_sources import Resurrect
        for n in('id','turn'):_integer(getattr(self,n),'resurrection batch '+n,1)
        for n in('event_cursor','action'):_integer(getattr(self,n),'resurrection batch '+n,0)
        if type(self.spec)is not Resurrect or self.spec.cause is None:raise ValueError('Complete attributed original resurrection request required')
        self.spec.__post_init__()
        if self.basis is not None:self.basis.__post_init__()
        if type(self.candidates)is not tuple or len(set(self.candidates))!=len(self.candidates):raise ValueError('Complete original frozen death candidate IDs required')
        for x in self.candidates:_integer(x,'frozen death candidate',1)
        if self.basis is None and(self.candidates or self.picks):raise ValueError('Skipped death query cannot contain candidates or selections')
        if type(self.picks)is not tuple or any(type(x)is not ResurrectionPick for x in self.picks):raise ValueError('Complete original resurrection pick prefix required')
        for x in self.picks:x.__post_init__()
        if [x.index for x in self.picks]!=list(range(len(self.picks)))or len(self.picks)>self.spec.count:raise ValueError('Cropped/reordered original resurrection iterations')
        if any(x.entry_root_id is None for x in self.picks[:-1]):raise ValueError('Resurrection selected again before its original entry')
        ids=[x.entry_root_id for x in self.picks if x.entry_root_id is not None]
        if ids!=sorted(set(ids)):raise ValueError('Reordered/duplicated resurrection child identities')
        if self.status not in('active','completed','empty','board_full','interrupted'):raise ValueError('Unknown resurrection batch status')
        if self.status=='completed'and(len(self.picks)!=self.spec.count or any(x.entry_root_id is None for x in self.picks)):raise ValueError('Resurrection completed before original iterations finished')
        if self.attacks is not None:
            from .resurrection_attacks import ResurrectionAttacks
            if type(self.attacks)is not ResurrectionAttacks:raise ValueError('Typed original resurrection attacks required')
            self.attacks.__post_init__()


@dataclass(frozen=True)
class ContinueDeathResurrection(Effect):
    resurrection_batch_id:int
    def __post_init__(self):_integer(self.resurrection_batch_id,'original death batch continuation',1)


def record(state,identity):
    x=next((x for x in state.resurrection_summon_history if x.id==identity),None)
    if x is None:raise ValueError('Unknown original resurrection batch')
    return x


def update(state,root,**changes):
    value=replace(root,**changes);state.resurrection_summon_history[state.resurrection_summon_history.index(root)]=value;return value


def emit_root(r,kind,root):
    r.emit(kind,source_id=root.spec.cause.source.entity_id,player_id=root.spec.player_id,amount=root.spec.count,
        resurrection_batch_id=root.id,root=encoded(root),_capture=False)


def close(r,root,status):
    root=update(r.state,root,status=status)
    if root.spec.attack_after_all and status!='interrupted':
        from .resurrection_attacks import initial,ContinueResurrectionAttacks
        root=update(r.state,root,attacks=initial(root,{x.id:x for x in r.state.card_summon_history}))
    emit_root(r,'resurrection_batch_finished',root)
    return (ContinueResurrectionAttacks(root.id),)if root.attacks is not None and root.attacks.status=='active'else()


def start(r,spec):
    validate_effect(r.state,r.registry,spec)
    if spec.count>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Resurrection count exceeds engineering budget')
    full=len(r.player(spec.player_id).board)>=r.rules.max_board
    basis=None if full or not spec.count else ResurrectionBasis(spec.player_id,spec.query,None if spec.source_id is None else SourceAllocationFact.capture(r.state,r.state.entities[spec.source_id]),
        r.player(spec.player_id).hero_class,tuple(r.state.death_history),r.state.turn,r.state.action_number,r.state.next_death_id,r.state.next_entity_id)
    ids=()if basis is None else validate_basis(r.state,r.registry,basis,death_ids=spec.death_ids)
    root=ResurrectionBatch(r.state.next_resurrection_summon_id,len(r.game._events),r.state.turn,r.state.action_number,spec,basis,ids)
    r.state.next_resurrection_summon_id+=1;r.state.resurrection_summon_history.append(root);emit_root(r,'resurrection_batch_accepted',root)
    if not spec.count:return close(r,root,'completed')
    if full:return close(r,root,'board_full')
    # Original Resurrect always returned ContinueResurrection, including empty pools.
    return(ContinueDeathResurrection(root.id),)


def remaining(root):
    records={x.id:x for x in root.basis.inventory};available=list(root.candidates)
    for pick in root.picks:
        available=[i for i in available if i!=pick.selected]if root.spec.distinct=='death'else[i for i in available if records[i].card_id!=records[pick.selected].card_id]
    return tuple(available)


def choose(rng,root,available):
    records={x.id:x for x in root.basis.inventory}
    if root.spec.distinct=='card':
        groups={}
        for i in available:groups.setdefault(records[i].card_id,[]).append(i)
        group=rng.choice(tuple(groups.values()))if root.spec.selection=='random'else next(iter(groups.values()))
        return rng.choice(group)if root.spec.selection=='random'else group[0]
    return rng.choice(available)if root.spec.selection=='random'else available[0]


def continue_batch(r,effect):
    root=record(r.state,effect.resurrection_batch_id)
    if root.status!='active':raise ResolutionError('Completed resurrection cannot continue')
    if root.picks:
        child_id=root.picks[-1].entry_root_id
        if child_id is None:raise ResolutionError('Resurrection advanced before original entry')
        from .summon_quantities import record as child_record
        if child_record(r.state,child_id).status=='active':raise ResolutionError('Resurrection advanced before accepted extras and followups')
    available=remaining(root)
    if len(root.picks)==root.spec.count:return close(r,root,'completed')
    if not available:return close(r,root,'empty')
    if len(r.player(root.spec.player_id).board)>=r.rules.max_board:return close(r,root,'board_full')
    before=r.game._rng.getstate();selected=choose(r.game._rng,root,available)
    pick=ResurrectionPick(len(root.picks),available,selected,before,r.game._rng.getstate());root=update(r.state,root,picks=(*root.picks,pick))
    r.emit('resurrection_pick_accepted',resurrection_batch_id=root.id,pick=encoded(pick),_capture=False)
    from .summon_sources import ResurrectMinion
    position=None if root.spec.position is None else root.spec.position+pick.index
    return(ResurrectMinion(root.spec.player_id,pick.selected,position,root.spec.source_id,root.spec.stats,root.spec.on_summon,root.spec.cause,ResurrectionEntryLink(root.id,pick.index)),ContinueDeathResurrection(root.id))


def bind_entry(r,link,child_id):
    root=record(r.state,link.resurrection_batch_id);pick=root.picks[link.index]
    if root.status!='active'or link.index!=len(root.picks)-1 or pick.entry_root_id is not None:raise ResolutionError('Duplicate/stale original resurrection entry')
    bound=replace(pick,entry_root_id=child_id);update(r.state,root,picks=(*root.picks[:-1],bound))
    r.emit('resurrection_entry_bound',resurrection_batch_id=root.id,pick=encoded(bound),_capture=False)


def validate_effect(state,registry,effect):
    from .summon_sources import Resurrect,ResurrectMinion
    from .summon_quantities import validate_cause
    effect.__post_init__();validate_cause(state,registry,effect.cause)
    if effect.source_id is not None and effect.source_id not in state.entities:raise ValueError('Unknown original resurrection effect source')
    if effect.on_summon is not None:registry.behavior(effect.on_summon)
    if type(effect)is Resurrect and effect.death_ids is not None and set(effect.death_ids)-{x.id for x in state.death_history}:raise ValueError('Exact resurrection lost an original actual death')
    if type(effect)is ResurrectMinion:
        if effect.death_id>=state.next_death_id:raise ValueError('Queued resurrection has future death identity')
        if effect.producer_link is not None:
            link=effect.producer_link;root=record(state,link.resurrection_batch_id);pick=root.picks[link.index]if link.index<len(root.picks)else None
            position=None if root.spec.position is None else root.spec.position+link.index
            if root.status!='active'or pick is None or link.index!=len(root.picks)-1 or pick.entry_root_id is not None or(effect.death_id,effect.player_id,effect.position,effect.stats,effect.on_summon,effect.source_id,effect.cause)!=(pick.selected,root.spec.player_id,position,root.spec.stats,root.spec.on_summon,root.spec.source_id,root.spec.cause):raise ValueError('Queued resurrection borrowed another original selection')


def validate_child(parent,index,child):
    if index>=len(parent.picks):raise ValueError('Death child exceeds original selection prefix')
    pick=parent.picks[index];request=child.request;position=None if parent.spec.position is None else parent.spec.position+index
    if pick.entry_root_id!=child.id or request.producer_link!=ResurrectionEntryLink(parent.id,index)or(request.player_id,request.cause,request.position)!=(parent.spec.player_id,parent.spec.cause,position)or len(request.materials)!=1 or type(request.materials[0])is not ResurrectionEntryMaterial:raise ValueError('Death child differs from original request/selection')
    material=request.materials[0];death=next(x for x in parent.basis.inventory if x.id==pick.selected)
    if material.death!=death or(material.stats,material.on_summon,None if material.source is None else material.source.entity_id)!=(parent.spec.stats,parent.spec.on_summon,parent.spec.source_id)or child.event_cursor<=parent.event_cursor:raise ValueError('Death material differs from complete selected original death')


def validate_link(state,child,*,closed=False):
    link=child.request.producer_link
    if link.resurrection_batch_id>=state.next_resurrection_summon_id:raise ValueError('Future death batch link')
    parent=next((x for x in state.resurrection_summon_history if x.id==link.resurrection_batch_id),None)
    if parent is None:
        if closed:return
        raise ValueError('Death child lost original batch')
    validate_child(parent,link.index,child)


def validate_record(state,registry,root,*,closed=False,children=None):
    from .summon_quantities import validate_cause
    root.__post_init__();validate_cause(state,registry,root.spec.cause,closed=closed)
    if root.id>=state.next_resurrection_summon_id or root.turn>state.turn or root.action>state.action_number or root.spec.cause.turn>root.turn or root.spec.cause.action>root.action:raise ValueError('Future death batch acceptance')
    if root.basis is not None:
        b=root.basis
        if (b.player_id,b.query,b.turn,b.action)!=(root.spec.player_id,root.spec.query,root.turn,root.action)or(None if b.source is None else b.source.entity_id)!=root.spec.source_id or validate_basis(state,registry,b,closed=closed,death_ids=root.spec.death_ids)!=root.candidates:raise ValueError('Death batch lost complete original query basis')
    if root.status=='active'and root.basis is None and not closed:raise ValueError('Active death batch lost original query')
    if not closed and root.status=='interrupted'and state.status=='playing':raise ValueError('Playing death batch cannot be terminal interrupted')
    children={x.id:x for x in state.card_summon_history}if children is None else children
    prior=replace(root,picks=(),status='active',attacks=None)if root.basis is not None else None
    for pick in root.picks:
        available=remaining(prior);local=Random();local.setstate(pick.rng_before)
        if pick.available!=available or choose(local,root,available)!=pick.selected or local.getstate()!=pick.rng_after:raise ValueError('Death selection/RNG differs from original candidate and grouping policy')
        if pick.entry_root_id is not None:
            child=children.get(pick.entry_root_id)
            if child is None:raise ValueError('Death batch lost original entry root')
            validate_child(root,pick.index,child)
            if(pick is not root.picks[-1]or root.status in('completed','empty','board_full'))and child.status=='active':raise ValueError('Death batch advanced before full entry completion')
        prior=replace(prior,picks=(*prior.picks,pick))
    if root.status=='empty'and(root.basis is None or remaining(root)):raise ValueError('Death batch exhausted before frozen identities were used')
    from .resurrection_attacks import validate_plan
    validate_plan(state,registry,root,children,closed=closed)


def validate_history(state,registry):
    _integer(state.next_resurrection_summon_id,'next death batch',1)
    if type(state.resurrection_summon_history)is not list:raise ValueError('Typed death batch history required')
    for root in state.resurrection_summon_history:
        if type(root)is not ResurrectionBatch:raise ValueError('Typed original death batch required')
        validate_record(state,registry,root)
    ids=[x.id for x in state.resurrection_summon_history]
    if ids!=sorted(set(ids)):raise ValueError('Reordered death batch identities')
    if type(state.resurrection_quantity_bodies)is not list:raise ValueError('Complete actual resurrection body bindings required')
    identities=[]
    for binding in state.resurrection_quantity_bodies:
        binding.__post_init__();identities.append((binding.root_id,binding.index))
        child=next((x for x in state.card_summon_history if x.id==binding.root_id),None)
        if child is None or child.selected is None or binding.index>=len(child.deliveries)or type(child.request.materials[child.selected])is not ResurrectionEntryMaterial:raise ValueError('Body binding lost actual resurrection root')
        material=child.request.materials[child.selected];delivery=child.deliveries[binding.index]
        if delivery.entity is None or binding.beneficiary.card_id!=material.card_id or binding.behavior_id!=material.on_summon:raise ValueError('Body binding differs from original material/followup')
        if binding.behavior_id is not None:registry.behavior(binding.behavior_id)
        validate_body_row(material,delivery.entity,binding.resurrection)
        if binding.status=='interrupted'and state.status=='playing':raise ValueError('Playing body cannot have terminal canceled continuation')
    if len(set(identities))!=len(identities):raise ValueError('Duplicate resurrection body binding')
    for child in state.card_summon_history:
        if child.selected is not None and type(child.request.materials[child.selected])is ResurrectionEntryMaterial:
            for d in child.deliveries:
                if d.entity is not None and(child.id,d.index)not in identities:raise ValueError('Successful resurrection lost its complete body continuation binding')


def interrupt(r):
    for binding in tuple(r.state.resurrection_quantity_bodies):
        if binding.status=='pending':finish_body(r,binding,'interrupted')
    for root in tuple(r.state.resurrection_summon_history):
        if root.status=='active':close(r,root,'interrupted')
    from .resurrection_attacks import interrupt as interrupt_attacks
    interrupt_attacks(r)


def validate_queue(state,registry,queue):
    from .resurrection_attacks import validate_queue as validate_attacks_queue
    validate_attacks_queue(state,queue)
    from .summon_sources import ResurrectMinion
    from .summon_quantities import FinishCardSummon
    for work in queue:
        if type(work)is ContinueQuantityResurrection and body_binding(state,work.root_id,work.index).status!='pending':raise ValueError('Stale/orphan quantity resurrection followup')
        if type(work)is ContinueDeathResurrection and record(state,work.resurrection_batch_id).status!='active':raise ValueError('Stale/orphan death batch continuation')
        if type(work)is ResurrectMinion and work.producer_link is not None:validate_effect(state,registry,work)
    for root in state.resurrection_summon_history:
        controls=[w for w in queue if type(w)is ContinueDeathResurrection and w.resurrection_batch_id==root.id]
        entries=[w for w in queue if type(w)is ResurrectMinion and w.producer_link is not None and w.producer_link.resurrection_batch_id==root.id]
        if root.status!='active':
            if controls or entries:raise ValueError('Settled death batch retains work')
            continue
        if controls!=[ContinueDeathResurrection(root.id)]:raise ValueError('Death batch lost its complete owed continuation')
        last=root.picks[-1]if root.picks else None
        if len(entries)!=(1 if last is not None and last.entry_root_id is None else 0):raise ValueError('Death batch lost original selected entry')
        if entries and queue.index(entries[0])>queue.index(controls[0]):raise ValueError('Death batch advanced before original entry')
        if last is not None and last.entry_root_id is not None:
            child=next(x for x in state.card_summon_history if x.id==last.entry_root_id)
            if child.status=='active':
                tail=next((w for w in queue if type(w)is FinishCardSummon and w.root_id==child.id),None)
                if tail is None or queue.index(tail)>queue.index(controls[0]):raise ValueError('Death batch continuation preceded full accepted quantity tail')
    from .summon_quantities import DeliverCardSummon
    for binding in state.resurrection_quantity_bodies:
        owed=[x for x in queue if type(x)is ContinueQuantityResurrection and(x.root_id,x.index)==(binding.root_id,binding.index)]
        if owed!=([ContinueQuantityResurrection(binding.root_id,binding.index)]if binding.status=='pending'else[]):raise ValueError('Resurrection body lost/duplicated its original owed followup')
        if owed:
            tail=next((x for x in queue if type(x)in(DeliverCardSummon,FinishCardSummon)and x.root_id==binding.root_id),None)
            if tail is None or queue.index(owed[0])>queue.index(tail):raise ValueError('Later quantity delivery preceded body followup')


def reject_choice_control(options):
    from .summon_sources import ResurrectMinion,ContinueResurrection
    from .summon_quantities import walk_work
    from .resurrection_attacks import CONTROLS
    if any(type(w)in CONTROLS for w in walk_work(options)):raise ValueError('Choice cannot inject original resurrection attack controls')
    if any(type(w)in(ContinueDeathResurrection,ContinueQuantityResurrection)or type(w)is ResurrectMinion and w.producer_link is not None or type(w)is ContinueResurrection and w.spec.cause is not None for w in walk_work(options)):raise ValueError('Choice cannot inject death resurrection control')


def validate_frame_references(state,registry,value):
    from .summon_sources import Resurrect,ResurrectMinion
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item,scope,depth):
        if depth>FrameCodec.MAX_DEPTH:raise ValueError('Death resurrection frame depth exceeded')
        from .resurrection_attacks import CONTROLS,validate_control
        if type(item)in CONTROLS:validate_control(scope,item);return
        if type(item)in(Resurrect,ResurrectMinion)and item.cause is not None:validate_effect(scope,registry,item);return
        if type(item)is ContinueDeathResurrection:
            if record(scope,item.resurrection_batch_id).status!='active':raise ValueError('Stale death batch continuation')
            return
        if type(item)is ContinueQuantityResurrection:
            if body_binding(scope,item.root_id,item.index).status!='pending':raise ValueError('Stale quantity resurrection followup')
            return
        if type(item)is RuleContext:
            for f in fields(item):
                if f.name!='state':visit(getattr(item,f.name),item.state,depth+1)
            return
        if type(item)is PaidHandChoiceBoundaryProof:validate_queue(item.state,registry,item.work);visit(item.work,item.state,depth+1);return
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
        if frame.paid_hand_choice_boundary.state.resurrection_summon_history!=game._state.resurrection_summon_history or frame.paid_hand_choice_boundary.state.resurrection_quantity_bodies!=game._state.resurrection_quantity_bodies:raise ValueError('Death batch/body changed complete choice boundary')


def from_dict(cls,value):
    from .serialization import _row,_death_from_dict,end_turn_rng_from_json
    from .summon_sources import DeathQuery,Resurrect
    from .summon_quantities import SummonCause,from_dict as cause_from_dict
    from .pool_summons import query_from_dict
    row=_row(value,cls)
    if cls is ResurrectionEntryMaterial:
        row['death']=_death_from_dict(row['death']);row['source']=allocation_from_dict(row['source'])
        row['stats']=None if row['stats']is None else SummonStats(**_row(row['stats'],SummonStats))
    elif cls is ResurrectionBasis:
        q=_row(row['query'],DeathQuery);q['cards']=query_from_dict(q['cards']);q['exclude_entity_ids']=tuple(q['exclude_entity_ids']);row['query']=DeathQuery(**q)
        row['source']=allocation_from_dict(row['source']);row['hero_class']=None if row['hero_class']is None else CardClass(row['hero_class']);row['inventory']=tuple(_death_from_dict(x)for x in row['inventory'])
    elif cls is ResurrectionBodyBinding:
        from .sacrifice import MinionReference
        res=_row(row['resurrection'],ResurrectionRecord);res['stats']=None if res['stats']is None else SummonStats(**_row(res['stats'],SummonStats))
        row['resurrection']=ResurrectionRecord(**res);row['beneficiary']=MinionReference(**_row(row['beneficiary'],MinionReference))
    elif cls is ResurrectionPick:
        row['available']=tuple(row['available'])
        for n in('rng_before','rng_after'):row[n]=end_turn_rng_from_json(row[n])
    elif cls is ResurrectionBatch:
        spec=_row(row['spec'],Resurrect);q=_row(spec['query'],DeathQuery);q['cards']=query_from_dict(q['cards']);q['exclude_entity_ids']=tuple(q['exclude_entity_ids']);spec['query']=DeathQuery(**q)
        spec['stats']=None if spec['stats']is None else SummonStats(**_row(spec['stats'],SummonStats));spec['cause']=cause_from_dict(SummonCause,spec['cause']);spec['death_ids']=None if spec['death_ids']is None else tuple(spec['death_ids']);row['spec']=Resurrect(**spec)
        row['basis']=None if row['basis']is None else from_dict(ResurrectionBasis,row['basis']);row['candidates']=tuple(row['candidates']);row['picks']=tuple(from_dict(ResurrectionPick,x)for x in row['picks'])
        from .resurrection_attacks import from_dict as attacks_from_dict
        row['attacks']=None if row['attacks']is None else attacks_from_dict(row['attacks'])
    return cls(**row)


def validate_closed_events(game):
    from .summon_quantities import CardSummonRecord,from_dict as child_from_dict
    from .serialization import _row
    state,registry,events=game._state,game.registry,game._events;children={x.id:x for x in state.card_summon_history}
    for event in events:
        if event.kind in('card_summon_accepted','card_summon_finished'):
            child=child_from_dict(CardSummonRecord,json.loads(dict(event.data)['root']))
            if child.id not in children or event.kind=='card_summon_finished':children[child.id]=child
    current={x.id:x for x in state.resurrection_summon_history};accepted={};closed={};picked={};bound={};deliveries={};followups={}
    for event in events:
        data=dict(event.data)
        if event.kind in('resurrection_delivery_bound','resurrection_followup_finished'):
            if set(data)!={'root_id','index','binding'}:raise ValueError('Complete actual resurrection body binding required')
            child=children.get(data['root_id']);index=data['index'];binding=from_dict(ResurrectionBodyBinding,json.loads(data['binding']));row=binding.resurrection
            if child is None or child.selected is None or type(child.request.materials[child.selected])is not ResurrectionEntryMaterial or type(index)is not int or index<0 or index>=len(child.deliveries):raise ValueError('Body binding lost its original resurrection root')
            d=child.deliveries[index];identity=(child.id,index)
            if d.entity is None or child.event_cursor>=event.sequence or row.action>event.action or(binding.root_id,binding.index)!=identity:raise ValueError('Duplicated/reordered resurrection body binding')
            material=child.request.materials[child.selected]
            validate_body_row(material,d.entity,row)
            if binding.behavior_id!=material.on_summon or binding.beneficiary.card_id!=material.card_id:raise ValueError('Body binding changed accepted followup/material')
            if event.kind=='resurrection_delivery_bound':
                if identity in deliveries or binding.status!=('none'if material.on_summon is None else'pending'):raise ValueError('Duplicate/rewritten body acceptance')
                deliveries[identity]=binding
            else:
                original=deliveries.get(identity)
                if identity in followups or original is None or original.status!='pending'or binding.status not in('attempted','skipped','interrupted')or replace(binding,status='pending')!=original:raise ValueError('Body followup changed original complete acceptance')
                followups[identity]=binding
            continue
        if event.kind not in('resurrection_batch_accepted','resurrection_batch_finished','resurrection_pick_accepted','resurrection_entry_bound'):continue
        is_pick=event.kind in('resurrection_pick_accepted','resurrection_entry_bound')
        if set(data)!={'resurrection_batch_id','pick'if is_pick else'root'}:raise ValueError('Complete original death batch event required')
        if is_pick:
            row=from_dict(ResurrectionPick,json.loads(data['pick']));identity=(data['resurrection_batch_id'],row.index)
            if data['resurrection_batch_id']not in accepted:raise ValueError('Death selection preceded its batch acceptance')
            if event.kind=='resurrection_pick_accepted':
                if identity in picked or row.entry_root_id is not None or row.index and(data['resurrection_batch_id'],row.index-1)not in bound:raise ValueError('Duplicate/early death selection')
                picked[identity]=row
            else:
                if identity in bound or row.entry_root_id is None or replace(row,entry_root_id=None)!=picked.get(identity):raise ValueError('Death entry differs from original pick')
                bound[identity]=row
            continue
        root=from_dict(ResurrectionBatch,json.loads(data['root']));validate_record(state,registry,root,closed=True,children=children)
        if data['resurrection_batch_id']!=root.id or(event.source_id,event.player_id,event.amount)!=(root.spec.cause.source.entity_id,root.spec.player_id,root.spec.count)or root.action>event.action or root.event_cursor>=event.sequence:raise ValueError('Death batch event changed original chronology/domain')
        if event.kind=='resurrection_batch_accepted':
            if root.id in accepted or root.picks or root.attacks is not None or root.status!='active'or root.event_cursor!=event.sequence-1:raise ValueError('Duplicate/invalid death batch acceptance')
            accepted[root.id]=root
        else:
            if root.id in closed or root.status=='active'or replace(root,picks=(),status='active',attacks=None)!=accepted.get(root.id):raise ValueError('Death batch close changed original basis/request')
            closed[root.id]=root
        if root.id not in current and not any(e.kind=='timeline_rewound'and e.sequence>event.sequence and type(dict(e.data).get('event_start'))is int and dict(e.data)['event_start']<=root.event_cursor for e in events):raise ValueError('Death batch vanished without actual Retry')
    parents={**closed,**current}
    for root in parents.values():
        if replace(root,picks=(),status='active',attacks=None)!=accepted.get(root.id)or root.status!='active'and(root.id not in closed or replace(root,attacks=None)!=replace(closed[root.id],attacks=None)):raise ValueError('Death batch differs from original complete event receipts')
        for pick in root.picks:
            if pick!=(bound if pick.entry_root_id is not None else picked).get((root.id,pick.index)):raise ValueError('Death batch cropped/changed original pick or binding')
    for identity in picked:
        parent=parents.get(identity[0])
        if parent is None or identity[1]>=len(parent.picks):raise ValueError('Death selection lost complete original prefix')
    from .resurrection_attacks import validate_events
    validate_events(game,children,closed,current)
    current_bodies={x.entity_id:x for x in state.resurrection_history}
    for child in children.values():
        if type(child.request.producer_link)is ResurrectionEntryLink:
            link=child.request.producer_link;parent=parents.get(link.resurrection_batch_id)
            if parent is None:raise ValueError('Death child lost its complete original parent')
            validate_child(parent,link.index,child)
        if child.selected is not None and type(child.request.materials[child.selected])is ResurrectionEntryMaterial:
            for d in child.deliveries:
                if d.entity is not None:
                    identity=(child.id,d.index);binding=followups.get(identity,deliveries.get(identity))
                    validate_body_row(child.request.materials[child.selected],d.entity,None if binding is None else binding.resurrection)
                    if child.id in {x.id for x in state.card_summon_history}and(current_bodies.get(d.entity.entity_id)!=binding.resurrection or body_binding(state,*identity)!=binding):raise ValueError('Current resurrection history changed original body binding/followup')
                    if child.id not in {x.id for x in state.card_summon_history}and binding.status=='pending':raise ValueError('Retired resurrection body left its continuation unaccounted')


def rows_from_dict(value):
    if type(value['resurrection_summon_history'])is not list:raise ValueError('Typed original death batch history required')
    value['resurrection_summon_history']=[from_dict(ResurrectionBatch,x)for x in value['resurrection_summon_history']]
    if type(value['resurrection_quantity_bodies'])is not list:raise ValueError('Typed actual resurrection bodies required')
    value['resurrection_quantity_bodies']=[from_dict(ResurrectionBodyBinding,x)for x in value['resurrection_quantity_bodies']]


def register(mechanics):
    from .resurrection_attacks import register as register_attacks
    register_attacks(mechanics)
    for cls in(ResurrectionEntryMaterial,ResurrectionBasis,ResurrectionEntryLink,ResurrectionPick,ResurrectionBatch,ResurrectionBodyBinding):mechanics.register_payload_type(cls)
    mechanics.register(ContinueDeathResurrection,continue_batch)
    mechanics.register(ContinueQuantityResurrection,continue_body)
