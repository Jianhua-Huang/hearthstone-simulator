"""Physical first movement, immutable extras, and sequential zone selections.

Selection and actual entry have distinct original checkpoints. Private receipts
prove internal consistency; unsigned saves do not authenticate historical truth.
Quantity, ownership of extras and insertion policy await CN calibration.
"""
from __future__ import annotations
from .model import SummonStats
from dataclasses import asdict,dataclass,fields,is_dataclass,replace
import json
from random import Random
from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .copy_materials import CopyEntryMaterial
from .effects import Effect,_behavior,_integer,_player
from .errors import ResolutionError,ResolutionLimitExceeded
from .model import CardClass,CardType,GameState,Zone,validate_end_turn_rng
from .sacrifice import MinionReference,live_minion,reference_value


@dataclass(frozen=True)
class RecruitEntryMaterial:
    card_id:str
    reference:CardReference
    copy:CopyEntryMaterial
    on_summon:str|None=None
    swap_minion:MinionReference|None=None
    def __post_init__(self):
        from .zones import CardReference
        if type(self.reference)is not CardReference or type(self.copy)is not CopyEntryMaterial:raise ValueError('Typed physical first/extra recruit material required')
        if self.swap_minion is not None:
            reference_value(self.swap_minion)
            if self.reference.zone != Zone.HAND or self.on_summon is not None or self.copy.stats is not None:
                raise ValueError('Hand swap requires its plain physical hand material')
        if self.on_summon is not None:_behavior(self.on_summon)
        from .zones import CardReference
        if type(self.reference)is not CardReference or type(self.copy)is not CopyEntryMaterial:raise ValueError('Typed physical first/extra recruit material required')
        self.reference.__post_init__();self.copy.__post_init__();origin=self.copy.origin
        if self.card_id!=self.copy.card_id or self.copy.profile!='stored_copy'or self.copy.mode!='current':raise ValueError('Recruit extras require the original stored current recipe')
        if (self.reference.entity_id,self.reference.player_id,self.reference.zone,self.reference.card_id,self.reference.zone_epoch)!=(origin.entity_id,origin.controller,origin.zone,origin.card_id,origin.zone_epoch):
            raise ValueError('Physical first and immutable extra material identify different sources')


def validate_material(state,registry,material,*,closed=False):
    from .copy_materials import validate_scope
    material.__post_init__();validate_scope(state,registry,material.copy,closed=closed)
    from .minion_hand_swaps import validate_material as validate_swap_material
    validate_swap_material(state,registry,material)
    if material.on_summon is not None:registry.behavior(material.on_summon)


def first_body(r,material,player_id,position):
    from .zones import reference_entity
    entity=reference_entity(r,material.reference)
    if entity is None:raise ResolutionError('Accepted first recruit lost its physical source before delivery')
    if material.swap_minion is not None:
        from .minion_hand_swaps import return_partner
        position=return_partner(r,material,player_id)
    if entity.controller!=player_id:
        getattr(r.player(entity.controller),entity.zone.value).remove(entity.id)
        entity.controller=player_id;getattr(r.player(player_id),entity.zone.value).append(entity.id)
    r.move(entity,Zone.BOARD,position)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state,entity,material.copy.stats);r.refresh_auras()
    return entity


def validate_delivery(material,delivery,player_id):
    fact=delivery.entity;origin=material.copy.origin
    owner=origin.owner if delivery.index==0 else player_id
    if (fact.card_id,fact.owner,fact.controller,fact.kind,fact.zone)!=(material.card_id,owner,player_id,CardType.MINION,Zone.BOARD):raise ValueError('Recruit delivery differs from physical first/extra ownership recipe')
    if delivery.index==0 and (fact.entity_id,fact.zone_epoch,fact.entered_order)!=(origin.entity_id,origin.zone_epoch+1,origin.next_order):raise ValueError('First recruit must move its original allocated entity exactly once')
    if delivery.index>0 and fact.entity_id<origin.next_entity_id:raise ValueError('Extra recruit borrowed a preexisting physical entity')


def accept_entry(r,effect,source):
    from .summon_quantities import SummonByCard,DeliverCardSummon,FinishCardSummon,accept,deliver
    validate_effect(r.state,r.registry,effect)
    material=RecruitEntryMaterial(source.card_id,effect.card,CopyEntryMaterial.capture(r.state,source,'stored_copy','current',effect.stats,registry=r.registry,player_id=effect.player_id),effect.on_summon,effect.swap_minion)
    position=effect.position
    if effect.swap_minion is not None:
        body=live_minion(r.state,effect.swap_minion)
        if body is None:return ()
        position=r.player(effect.player_id).board.index(body.id)
    request=SummonByCard(effect.player_id,(material,),effect.cause,position=position,producer_link=effect.producer_link)
    accept(r,request);child=r.state.card_summon_history[-1]
    if effect.producer_link is not None:bind_entry(r,effect.producer_link,child.id)
    return (*deliver(r,DeliverCardSummon(child.id,0)),FinishCardSummon(child.id))


@dataclass(frozen=True)
class RecruitCandidateFact:
    allocation:SourceAllocationFact
    current_battlecry:bool
    jade_size:int|None=None
    current_attack:int|None=None
    permanent_stats:SummonStats|None=None
    current_cost:int|None=None
    def __post_init__(self):
        from .permanent_minion_stats import validate_value
        validate_value(self.permanent_stats)
        if type(self.allocation)is not SourceAllocationFact or type(self.current_battlecry)is not bool:raise ValueError('Complete typed original physical zone candidate required')
        self.allocation.__post_init__()
        if self.current_attack is not None:_integer(self.current_attack,'original physical candidate Attack',0)
        if self.current_cost is not None:_integer(self.current_cost,'original physical candidate Cost',0)
        if self.jade_size is not None:
            from .jade import size_value
            size_value(self.jade_size)
    def reference(self):
        from .zones import CardReference
        a=self.allocation;return CardReference(a.entity_id,a.controller,a.zone,a.card_id,a.zone_epoch)


@dataclass(frozen=True)
class RecruitBasis:
    player_id:int
    owner_id:int
    zone:Zone
    query:PoolQuery
    source:SourceAllocationFact|None
    hero_class:CardClass|None
    inventory:tuple[RecruitCandidateFact,...]
    turn:int
    action:int
    next_entity_id:int
    next_order:int
    attack_basis:str='printed'
    cost_basis:str='printed'
    expansion_profile:str|None=None
    excluded_expansions:tuple[int,...]=()
    def __post_init__(self):
        from .pools import PoolQuery
        _player(self.player_id);_player(self.owner_id)
        if self.zone not in (Zone.HAND,Zone.DECK)or type(self.zone)is not Zone or type(self.query)is not PoolQuery:raise ValueError('Typed original physical zone/query required')
        self.query.__post_init__()
        for n in ('turn','next_entity_id','next_order'):_integer(getattr(self,n),'recruit basis '+n,1)
        _integer(self.action,'recruit basis action',0)
        if self.source is not None:self.source.__post_init__()
        if (self.query.class_mode in ('current','other'))!=(self.hero_class is not None):raise ValueError('Original recruit class basis differs from query')
        if self.hero_class is not None and(type(self.hero_class)is not CardClass or self.hero_class==CardClass.NEUTRAL):raise ValueError('Original recruit needs a playable class')
        if type(self.inventory)is not tuple or any(type(x)is not RecruitCandidateFact for x in self.inventory):raise ValueError('Complete ordered physical zone inventory required')
        if type(self.attack_basis)is not str or self.attack_basis not in('printed','current'):
            raise ValueError('Unknown original recruit Attack basis')
        if self.attack_basis=='current' and (self.query.attack_equals is None or self.query.attack_parity is not None):
            raise ValueError('Current physical Attack requires its exact numeric query')
        if type(self.cost_basis)is not str or self.cost_basis not in ('printed','local'):
            raise ValueError('Unknown original recruit Cost basis')
        if self.cost_basis=='local' and (self.zone!=Zone.DECK or self.owner_id!=self.player_id or
                self.attack_basis!='printed' or self.query.min_cost is None and self.query.max_cost is None):
            raise ValueError('Local physical Cost requires its bounded own-deck query')
        for row in self.inventory:
            row.__post_init__();a=row.allocation
            if (row.current_attack is not None)!=(self.attack_basis=='current'):
                raise ValueError('Physical Attack inventory differs from its original selector basis')
            if (row.current_cost is not None)!=(self.cost_basis=='local'):
                raise ValueError('Physical Cost inventory differs from its original selector basis')
            if (a.controller,a.zone,a.next_entity_id,a.next_order)!=(self.owner_id,self.zone,self.next_entity_id,self.next_order):raise ValueError('Original zone inventory borrowed another location/window')
        if len({x.allocation.entity_id for x in self.inventory})!=len(self.inventory):raise ValueError('Duplicate physical zone inventory identity')
        from .recruit_expansions import basis_value as expansion_basis_value
        expansion_basis_value(self)


def candidates(registry,basis):
    from .pools import matches_metadata
    excluded=set(basis.query.exclude_card_ids)
    if basis.query.exclude_source:
        if basis.source is None:raise ValueError('Recruit exclusion requires original query source')
        excluded.add(basis.source.card_id)
    query=replace(basis.query,attack_equals=None)if basis.attack_basis=='current'else basis.query
    result=[]
    for fact in basis.inventory:
        a=fact.allocation;card=registry.card(a.card_id)
        from .jade import family_for
        family=family_for(registry,a.card_id)
        if (family is None)!=(fact.jade_size is None) or family is not None and family.card_for(fact.jade_size)!=a.card_id:
            raise ValueError('Original recruit candidate lost its innate Jade size')
        cost=card.cost if fact.jade_size is None else min(10,fact.jade_size)
        if basis.cost_basis=='local':cost=fact.current_cost
        if basis.attack_basis=='current'and fact.current_attack!=basis.query.attack_equals:continue
        if a.card_id not in excluded and matches_metadata(query,card_id=a.card_id,kind=card.kind,cost=cost,
            meta=card.metadata,spell_school=card.spell_school,keywords=card.keywords,current_class=basis.hero_class,
            printed_battlecry=card.battlecry is not None,current_battlecry=fact.current_battlecry,
            printed_attack=fact.permanent_stats.attack if fact.permanent_stats is not None else card.attack if fact.jade_size is None else fact.jade_size):
            if basis.expansion_profile is not None:
                from .recruit_expansions import edition
                if edition(registry,basis.expansion_profile,a.card_id) in basis.excluded_expansions:continue
            result.append(fact.reference())
    return tuple(result)


def capture_basis(r,spec,excluded_expansions=()):
    from .summon_sources import minion_query
    from .card_conditions import has_battlecry
    from .permanent_minion_stats import value as permanent_value
    from .costs import local_cost
    inventory=tuple(RecruitCandidateFact(SourceAllocationFact.capture(r.state,r.state.entities[i]),has_battlecry(r.state.entities[i].abilities),r.state.entities[i].jade_size,
        r.state.entities[i].attack if spec.attack_basis=='current'else None,permanent_value(r.state.entities[i]),
        max(0,local_cost(r.state.entities[i])[0]) if spec.cost_basis=='local'else None)
        for i in getattr(r.player(spec.owner_id or spec.player_id),spec.zone.value))
    return RecruitBasis(spec.player_id,spec.owner_id or spec.player_id,spec.zone,minion_query(spec.query),
        None if spec.source_id is None else SourceAllocationFact.capture(r.state,r.state.entities[spec.source_id]),
        r.player(spec.player_id).hero_class if spec.query.class_mode in('current','other')else None,
        inventory,r.state.turn,r.state.action_number,r.state.next_entity_id,r.state.next_order,spec.attack_basis,spec.cost_basis,
        spec.expansion_profile,excluded_expansions)


def validate_basis(state,registry,basis,*,closed=False):
    basis.__post_init__()
    if basis.turn>state.turn or basis.action>state.action_number or basis.next_entity_id>state.next_entity_id or basis.next_order>state.next_order:raise ValueError('Future physical recruit query window')
    if basis.source is not None:validate_allocation(state,registry,basis.source,closed=closed)
    for row in basis.inventory:validate_allocation(state,registry,row.allocation,closed=closed)
    result=candidates(registry,basis)
    from .summon_quantities import SummonEntryMaterial,validate_material as validate_plain
    # Physical first/extra entries already delegate native Colossal expansion.
    for ref in result:validate_plain(registry,SummonEntryMaterial(ref.card_id),allow_colossal=True)
    return result


@dataclass(frozen=True)
class RecruitEntryLink:
    recruit_id:int
    index:int
    def __post_init__(self):_integer(self.recruit_id,'recruit producer identity',1);_integer(self.index,'original recruit selection index',0)


@dataclass(frozen=True)
class RecruitRound:
    index:int
    outcome:str
    board_size:int
    board_limit:int
    basis:RecruitBasis|None
    candidates:tuple[CardReference,...]
    selection:str
    selected:CardReference|None
    rng_before:tuple
    rng_after:tuple
    entry_status:str='unattempted'
    entry_root_id:int|None=None
    def __post_init__(self):
        from .zones import CardReference
        _integer(self.index,'recruit round index',0);_integer(self.board_size,'original recruit board size',0);_integer(self.board_limit,'original recruit board limit',1)
        if self.outcome not in('selected','empty','board_full')or self.selection not in('first','random'):raise ValueError('Unknown original recruit selection outcome')
        if (self.outcome=='board_full')!=(self.board_size>=self.board_limit)or(self.outcome=='board_full')!=(self.basis is None):raise ValueError('Capacity-aware recruit query window changed')
        if self.basis is not None:self.basis.__post_init__()
        if type(self.candidates)is not tuple or any(type(x)is not CardReference for x in self.candidates):raise ValueError('Complete ordered physical candidates required')
        for ref in self.candidates:ref.__post_init__()
        if (self.outcome=='selected')!=(self.selected is not None)or(self.outcome=='selected')!=bool(self.candidates):raise ValueError('Original recruit selection differs from candidate availability')
        if self.entry_status not in('unattempted','rooted','stale')or(self.entry_status=='rooted')!=(self.entry_root_id is not None):raise ValueError('Actual recruit entry identity/status changed')
        if self.outcome!='selected'and self.entry_status!='unattempted':raise ValueError('Unselected recruit cannot attempt an entry')
        if self.entry_root_id is not None:_integer(self.entry_root_id,'actual physical entry root',1)
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        local=Random();local.setstate(self.rng_before)
        chosen=(local.choice(self.candidates)if self.selection=='random'else self.candidates[0])if self.candidates else None
        if chosen!=self.selected or local.getstate()!=self.rng_after:raise ValueError('Physical recruit selection/RNG differs from original ordered inventory')


@dataclass(frozen=True)
class RecruitRecord:
    id:int
    event_cursor:int
    turn:int
    action:int
    spec:object
    rounds:tuple[RecruitRound,...]=()
    status:str='active'
    def __post_init__(self):
        from .summon_sources import SummonFromZone
        for n in ('id','turn'):_integer(getattr(self,n),'recruit producer '+n,1)
        for n in ('event_cursor','action'):_integer(getattr(self,n),'recruit producer '+n,0)
        if type(self.spec)is not SummonFromZone or self.spec.cause is None:raise ValueError('Complete original attributed recruit request required')
        self.spec.__post_init__()
        if type(self.rounds)is not tuple or any(type(x)is not RecruitRound for x in self.rounds):raise ValueError('Complete ordered recruit round prefix required')
        for row in self.rounds:row.__post_init__()
        if [x.index for x in self.rounds]!=list(range(len(self.rounds))):raise ValueError('Cropped/reordered original recruit rounds')
        if any(x.outcome!='selected'or x.entry_status=='unattempted'for x in self.rounds[:-1]):raise ValueError('Recruit advanced before previous physical attempt')
        selected=sum(x.outcome=='selected'for x in self.rounds)
        if selected>self.spec.count or len(self.rounds)>self.spec.count:raise ValueError('Recruit exceeded its original count')
        if self.status not in('active','completed','exhausted','board_full','interrupted'):raise ValueError('Unknown recruit producer status')
        if self.status=='completed'and(selected!=self.spec.count or any(x.entry_status=='unattempted'for x in self.rounds)):raise ValueError('Recruit completed before all original attempts')
        if self.status in('exhausted','board_full')and(not self.rounds or self.rounds[-1].outcome!=('empty'if self.status=='exhausted'else'board_full')):raise ValueError('Recruit closing outcome differs from original capacity/query')
        ids=[x.entry_root_id for x in self.rounds if x.entry_root_id is not None]
        if ids!=sorted(set(ids)):raise ValueError('Duplicated/reordered recruit child identity')


@dataclass(frozen=True)
class ContinueRecruit(Effect):
    recruit_id:int
    def __post_init__(self):_integer(self.recruit_id,'continue original recruit',1)


@dataclass(frozen=True)
class ContinueRecruitedMinion(Effect):
    root_id:int
    index:int
    beneficiary:MinionReference
    behavior_id:str
    def __post_init__(self):
        _integer(self.root_id,'original recruit child',1);_integer(self.index,'recruit delivery',0)
        reference_value(self.beneficiary);_behavior(self.behavior_id)


def followup_record(state,registry,effect):
    from .summon_quantities import record as child_record
    effect.__post_init__();registry.behavior(effect.behavior_id)
    child=child_record(state,effect.root_id)
    material=None if child.selected is None else child.request.materials[child.selected]
    if type(material)is not RecruitEntryMaterial or material.on_summon!=effect.behavior_id:
        raise ValueError('Recruit followup differs from its original selected material')
    if effect.index>=len(child.deliveries):raise ValueError('Recruit followup precedes its actual delivery')
    delivery=child.deliveries[effect.index];fact=delivery.entity;ref=effect.beneficiary
    if delivery.outcome!='delivered' or (ref.entity_id,ref.player_id,ref.card_id,ref.zone_epoch,ref.entered_order)!=(
            fact.entity_id,fact.controller,fact.card_id,fact.zone_epoch,fact.entered_order):
        raise ValueError('Recruit followup borrowed another actual body or lifetime')
    return child,delivery


def continue_recruited_minion(r,effect):
    from .summon_quantities import update as update_child
    child,delivery=followup_record(r.state,r.registry,effect)
    if child.status!='active' or delivery.followup_started:raise ResolutionError('Recruit followup already accepted or closed')
    rows=list(child.deliveries);rows[effect.index]=replace(delivery,followup_started=True)
    update_child(r.state,child,deliveries=tuple(rows))
    r.emit('recruit_followup_started',source_id=child.request.cause.source.entity_id,
        target_id=delivery.entity.entity_id,player_id=child.request.player_id,followup=encoded(effect),_capture=False)
    if live_minion(r.state,effect.beneficiary) is None:
        r.stale(effect,effect.beneficiary.entity_id);return ()
    return (r.call(effect.behavior_id,child.request.cause.source.entity_id,
                   child.request.player_id,target_id=delivery.entity.entity_id),)


def validate_followup_events(game):
    children=game._state.card_summon_history
    if not any(type(m)is RecruitEntryMaterial and m.on_summon is not None for x in children for m in x.request.materials):return
    seen=set()
    for event in game._events:
        if event.kind!='recruit_followup_started':continue
        row=json.loads(dict(event.data)['followup']);ref=MinionReference(**row.pop('beneficiary'))
        effect=ContinueRecruitedMinion(beneficiary=ref,**row)
        child,delivery=followup_record(game._state,game.registry,effect);key=(child.id,effect.index)
        if key in seen or not delivery.followup_started or (event.source_id,event.target_id,event.player_id)!=(
                child.request.cause.source.entity_id,delivery.entity.entity_id,child.request.player_id):
            raise ValueError('Missing, duplicated or foreign original recruit followup receipt')
        seen.add(key)
    expected={(x.id,d.index) for x in children if x.selected is not None and type(x.request.materials[x.selected])is RecruitEntryMaterial for d in x.deliveries if d.followup_started}
    if seen!=expected:raise ValueError('Recruit followup acceptance receipts disagree with original deliveries')


def record(state,identity):
    root=next((x for x in state.recruit_summon_history if x.id==identity),None)
    if root is None:raise ValueError('Unknown original physical recruit producer')
    return root


def update(state,root,**changes):
    value=replace(root,**changes);state.recruit_summon_history[state.recruit_summon_history.index(root)]=value;return value


def encoded(value):return json.dumps(asdict(value),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def emit_root(r,kind,root):
    r.emit(kind,source_id=root.spec.cause.source.entity_id,player_id=root.spec.player_id,amount=root.spec.count,
        recruit_id=root.id,root=encoded(root),_capture=False)


def start(r,spec):
    validate_effect(r.state,r.registry,spec)
    if spec.count>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Physical recruit count exceeds engineering budget')
    root=RecruitRecord(r.state.next_recruit_summon_id,len(r.game._events),r.state.turn,r.state.action_number,spec)
    r.state.next_recruit_summon_id+=1;r.state.recruit_summon_history.append(root);emit_root(r,'recruit_summon_accepted',root)
    return continue_producer(r,ContinueRecruit(root.id))


def continue_producer(r,effect):
    root=record(r.state,effect.recruit_id)
    if root.status!='active':raise ResolutionError('Completed recruit cannot continue')
    if root.rounds:
        last=root.rounds[-1]
        if last.outcome!='selected'or last.entry_status=='unattempted':raise ResolutionError('Recruit continued before its original selected entry')
        if last.entry_root_id is not None:
            from .summon_quantities import record as child_record
            if child_record(r.state,last.entry_root_id).status=='active':raise ResolutionError('Recruit re-query preceded accepted extra copies')
    if len(root.rounds)==root.spec.count:
        emit_root(r,'recruit_summon_finished',update(r.state,root,status='completed'));return ()
    from .zones import source_exists
    source_exists(r,root.spec.source_id)
    full=len(r.player(root.spec.player_id).board)>=r.rules.max_board
    from .recruit_expansions import exclusions
    basis=None if full else capture_basis(r,root.spec,exclusions(r.registry,root.spec,root.rounds))
    available=()if full else validate_basis(r.state,r.registry,basis)
    before=r.game._rng.getstate()
    selected=(r.game._rng.choice(available)if root.spec.selection=='random'else available[0])if available else None
    round=RecruitRound(len(root.rounds),'board_full'if full else'selected'if selected else'empty',
        len(r.player(root.spec.player_id).board),r.rules.max_board,basis,available,root.spec.selection,selected,before,r.game._rng.getstate())
    root=update(r.state,root,rounds=(*root.rounds,round));r.emit('recruit_selection_accepted',recruit_id=root.id,round=encoded(round),_capture=False)
    if selected is None:
        emit_root(r,'recruit_summon_finished',update(r.state,root,status='board_full'if full else'exhausted'));return ()
    from .colossal import SummonStoredCard
    position=None if root.spec.position is None else root.spec.position+round.index
    return(SummonStoredCard(selected,root.spec.player_id,position,root.spec.stats,root.spec.cause,RecruitEntryLink(root.id,round.index),root.spec.on_summon),ContinueRecruit(root.id))


def bind_entry(r,link,child_id=None):
    root=record(r.state,link.recruit_id);round=root.rounds[link.index]
    if root.status!='active'or link.index!=len(root.rounds)-1 or round.entry_status!='unattempted':raise ResolutionError('Duplicate/stale original recruit entry attempt')
    bound=replace(round,entry_status='stale'if child_id is None else'rooted',entry_root_id=child_id)
    update(r.state,root,rounds=(*root.rounds[:-1],bound));r.emit('recruit_entry_bound',recruit_id=root.id,round=encoded(bound),_capture=False)


def validate_effect(state,registry,effect):
    from .summon_quantities import validate_cause
    from .summon_sources import SummonFromZone
    from .colossal import SummonStoredCard
    effect.__post_init__();validate_cause(state,registry,effect.cause)
    if effect.on_summon is not None:registry.behavior(effect.on_summon)
    if type(effect)is SummonFromZone:
        if effect.source_id is not None and effect.source_id not in state.entities:raise ValueError('Queued recruit has unknown original query source')
        if effect.expansion_profile is not None and effect.expansion_profile not in registry.recruit_expansion_profiles:
            from .registry import UnsupportedDefinitionError
            raise UnsupportedDefinitionError('Unknown queued recruit expansion inventory: '+effect.expansion_profile)
    elif type(effect)is SummonStoredCard:
        registry.card(effect.card.card_id)
        if effect.card.entity_id>=state.next_entity_id:raise ValueError('Queued physical recruit has future source')
        link=effect.producer_link
        if link is not None:
            root=record(state,link.recruit_id);round=root.rounds[link.index]if link.index<len(root.rounds)else None
            position=None if root.spec.position is None else root.spec.position+link.index
            if root.status!='active'or round is None or link.index!=len(root.rounds)-1 or round.entry_status!='unattempted'or(effect.card,effect.player_id,effect.position,effect.stats,effect.cause,effect.on_summon)!=(round.selected,root.spec.player_id,position,root.spec.stats,root.spec.cause,root.spec.on_summon):raise ValueError('Queued first recruit borrowed another original selection/window')


def validate_link(state,child,*,closed=False):
    link=child.request.producer_link
    if link.recruit_id>=state.next_recruit_summon_id:raise ValueError('Future recruit producer link')
    parent=next((x for x in state.recruit_summon_history if x.id==link.recruit_id),None)
    if parent is None:
        if closed:return
        raise ValueError('Unknown physical recruit parent')
    validate_child(parent,link.index,child)


def validate_child(parent,index,child):
    if index>=len(parent.rounds):raise ValueError('Recruit child index exceeds original selection prefix')
    round=parent.rounds[index];request=child.request
    position=None if parent.spec.position is None else parent.spec.position+index
    if round.entry_root_id!=child.id or request.producer_link!=RecruitEntryLink(parent.id,index)or request.player_id!=parent.spec.player_id or request.cause!=parent.spec.cause or request.position!=position or len(request.materials)!=1 or type(request.materials[0])is not RecruitEntryMaterial:raise ValueError('Physical child differs from original recruit selection/cause/position')
    material=request.materials[0]
    if material.reference!=round.selected or material.copy.stats!=parent.spec.stats or material.on_summon!=parent.spec.on_summon or child.event_cursor<=parent.event_cursor:raise ValueError('Physical material differs from original selected entity')
    fact=next(x.allocation for x in round.basis.inventory if x.reference()==round.selected)
    if (material.copy.origin.entity_id,material.copy.origin.card_id,material.copy.origin.owner,material.copy.origin.controller,material.copy.origin.zone,material.copy.origin.zone_epoch)!=(fact.entity_id,fact.card_id,fact.owner,fact.controller,fact.zone,fact.zone_epoch):raise ValueError('Recruit material borrowed another original allocation')


def validate_record(state,registry,root,*,closed=False,children=None):
    from .summon_quantities import validate_cause
    from .summon_sources import minion_query
    root.__post_init__();validate_cause(state,registry,root.spec.cause,closed=closed)
    if root.spec.expansion_profile is not None and root.spec.expansion_profile not in registry.recruit_expansion_profiles:
        raise ValueError('Original recruit lost its declared expansion inventory')
    if root.id>=state.next_recruit_summon_id or root.turn>state.turn or root.action>state.action_number or root.spec.cause.turn>root.turn or root.spec.cause.action>root.action:raise ValueError('Future physical recruit acceptance')
    if not closed and root.status=='interrupted'and state.status=='playing':raise ValueError('Playing recruit cannot be interrupted')
    children={x.id:x for x in state.card_summon_history}if children is None else children
    for row in root.rounds:
        if row.selection!=root.spec.selection:raise ValueError('Recruit selection mode differs from original request')
        if row.basis is not None:
            b=row.basis
            if (b.player_id,b.owner_id,b.zone,b.query,b.attack_basis,b.cost_basis)!=(root.spec.player_id,root.spec.owner_id or root.spec.player_id,root.spec.zone,minion_query(root.spec.query),root.spec.attack_basis,root.spec.cost_basis)or(None if b.source is None else b.source.entity_id)!=root.spec.source_id:raise ValueError('Recruit query basis differs from original request')
            from .recruit_expansions import exclusions
            if (b.expansion_profile,b.excluded_expansions)!=(root.spec.expansion_profile,exclusions(registry,root.spec,root.rounds[:row.index])):
                raise ValueError('Recruit expansion basis lost its original selected-set prefix')
            if b.turn<root.turn or b.action<root.action or validate_basis(state,registry,b,closed=closed)!=row.candidates:raise ValueError('Recruit lost its complete original ordered candidate query')
        if row.entry_root_id is not None:
            child=children.get(row.entry_root_id)
            if child is None:raise ValueError('Recruit lost its original physical entry root')
            validate_child(root,row.index,child)
            if (row is not root.rounds[-1]or root.status in('completed','exhausted','board_full'))and child.status=='active':raise ValueError('Recruit advances/closes before complete extra-copy delivery')


def validate_history(state,registry):
    _integer(state.next_recruit_summon_id,'next recruit producer',1)
    if type(state.recruit_summon_history)is not list:raise ValueError('Typed physical recruit history required')
    for root in state.recruit_summon_history:
        if type(root)is not RecruitRecord:raise ValueError('Typed original recruit producer required')
        validate_record(state,registry,root)
    ids=[x.id for x in state.recruit_summon_history]
    if ids!=sorted(set(ids)):raise ValueError('Reordered physical recruit identities')


def interrupt(r):
    for root in tuple(r.state.recruit_summon_history):
        if root.status=='active':emit_root(r,'recruit_summon_finished',update(r.state,root,status='interrupted'))


def validate_queue(state,registry,queue):
    from .colossal import SummonStoredCard
    from .summon_quantities import FinishCardSummon
    for work in queue:
        if type(work)is ContinueRecruit and record(state,work.recruit_id).status!='active':raise ValueError('Stale/orphan original recruit continuation')
        if type(work)is SummonStoredCard and work.producer_link is not None:validate_effect(state,registry,work)
    for root in state.recruit_summon_history:
        controls=[w for w in queue if type(w)is ContinueRecruit and w.recruit_id==root.id]
        entries=[w for w in queue if type(w)is SummonStoredCard and w.producer_link is not None and w.producer_link.recruit_id==root.id]
        if root.status!='active':
            if controls or entries:raise ValueError('Settled recruit retains work')
            continue
        if controls!=[ContinueRecruit(root.id)]or not root.rounds or root.rounds[-1].outcome!='selected':raise ValueError('Recruit lost its complete original owed continuation')
        last=root.rounds[-1]
        if len(entries)!=(1 if last.entry_status=='unattempted'else 0):raise ValueError('Recruit lost/duplicated original first movement')
        if entries and queue.index(entries[0])>queue.index(controls[0]):raise ValueError('Recruit re-query precedes its first movement')
        if last.entry_root_id is not None:
            child=next(x for x in state.card_summon_history if x.id==last.entry_root_id)
            if child.status=='active':
                tail=next((w for w in queue if type(w)is FinishCardSummon and w.root_id==child.id),None)
                if tail is None or queue.index(tail)>queue.index(controls[0]):raise ValueError('Recruit re-query precedes accepted child Finish')


def reject_choice_control(options):
    from .colossal import SummonStoredCard
    from .summon_quantities import walk_work
    if any(type(w)is ContinueRecruit or type(w)is SummonStoredCard and w.producer_link is not None for w in walk_work(options)):raise ValueError('Choice cannot inject physical recruit control')


def validate_frame_references(state,registry,value):
    from .colossal import SummonStoredCard
    from .summon_sources import SummonFromZone, SummonFromStoredCandidates, validate_stored_candidates
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item,scope,depth):
        if depth>FrameCodec.MAX_DEPTH:raise ValueError('Physical recruit frame depth exceeded')
        from .minion_hand_swaps import SwapWithOpponentHand
        if type(item)is SwapWithOpponentHand:item.validate_in_state(scope,registry);return
        if type(item)is SummonFromStoredCandidates:validate_stored_candidates(scope,registry,item);return
        if type(item)in(SummonStoredCard,SummonFromZone)and item.cause is not None:validate_effect(scope,registry,item);return
        if type(item)is ContinueRecruit:
            if record(scope,item.recruit_id).status!='active':raise ValueError('Stale original recruit continuation')
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
    validate_followup_events(game)
    frame=game._frame;queue=(*frame.prefix,*frame.continuation)if frame else()
    validate_queue(game._state,game.registry,queue)
    if frame:
        reject_choice_control(frame.options);validate_frame_references(game._state,game.registry,frame)
        if frame.paid_hand_choice_boundary.state.recruit_summon_history!=game._state.recruit_summon_history:raise ValueError('Recruit changed complete original choice boundary')
        controls=lambda q:tuple(w for w in q if type(w)is ContinueRecruit)
        if controls(queue)!=controls(frame.paid_hand_choice_boundary.work):raise ValueError('Recruit changed original owed continuation')


def from_dict(cls,value):
    from .zones import CardReference
    from .serialization import _row,end_turn_rng_from_json
    from .copy_materials import from_dict as copy_from_dict
    from .pool_summons import query_from_dict
    row=_row(value,cls)
    if cls is RecruitEntryMaterial:
        ref=_row(row['reference'],CardReference);ref['zone']=Zone(ref['zone']);row['reference']=CardReference(**ref)
        row['copy']=copy_from_dict(CopyEntryMaterial,row['copy'])
        row['swap_minion']=None if row['swap_minion']is None else MinionReference(**_row(row['swap_minion'],MinionReference))
    elif cls is RecruitCandidateFact:
        row['allocation']=allocation_from_dict(row['allocation'])
        row['permanent_stats']=None if row['permanent_stats']is None else SummonStats(**_row(row['permanent_stats'],SummonStats))
    elif cls is RecruitBasis:
        row['zone']=Zone(row['zone']);row['query']=query_from_dict(row['query']);row['source']=allocation_from_dict(row['source'])
        row['hero_class']=None if row['hero_class']is None else CardClass(row['hero_class']);row['inventory']=tuple(from_dict(RecruitCandidateFact,x)for x in row['inventory'])
        row['excluded_expansions']=tuple(row['excluded_expansions'])
    elif cls is RecruitRound:
        def ref(value):
            if value is None:return None
            r=_row(value,CardReference);r['zone']=Zone(r['zone']);return CardReference(**r)
        row['basis']=None if row['basis']is None else from_dict(RecruitBasis,row['basis'])
        row['candidates']=tuple(ref(x)for x in row['candidates']);row['selected']=ref(row['selected'])
        for n in('rng_before','rng_after'):row[n]=end_turn_rng_from_json(row[n])
    elif cls is RecruitRecord:
        from .summon_sources import SummonFromZone
        from .summon_quantities import SummonCause,from_dict as cause_from_dict
        spec=_row(row['spec'],SummonFromZone);spec['zone']=Zone(spec['zone']);spec['query']=query_from_dict(spec['query'])
        spec['cause']=cause_from_dict(SummonCause,spec['cause']);spec['stats']=None if spec['stats']is None else SummonStats(**_row(spec['stats'],SummonStats))
        row['spec']=SummonFromZone(**spec);row['rounds']=tuple(from_dict(RecruitRound,x)for x in row['rounds'])
    return cls(**row)


def validate_closed_events(game):
    from .summon_quantities import CardSummonRecord,from_dict as child_from_dict
    state,registry,events=game._state,game.registry,game._events
    children={x.id:x for x in state.card_summon_history}
    for event in events:
        if event.kind in('card_summon_accepted','card_summon_finished'):
            child=child_from_dict(CardSummonRecord,json.loads(dict(event.data)['root']))
            if child.id not in children or event.kind=='card_summon_finished':children[child.id]=child
    current={x.id:x for x in state.recruit_summon_history};accepted={};closed={};offers={};bound={}
    for event in events:
        if event.kind not in('recruit_summon_accepted','recruit_summon_finished','recruit_selection_accepted','recruit_entry_bound'):continue
        data=dict(event.data);is_round=event.kind in('recruit_selection_accepted','recruit_entry_bound')
        if set(data)!= {'recruit_id','round'if is_round else'root'}:raise ValueError('Complete physical recruit event receipt required')
        if is_round:
            row=from_dict(RecruitRound,json.loads(data['round']));identity=(data['recruit_id'],row.index)
            parent=accepted.get(data['recruit_id'])
            if parent is None:raise ValueError('Recruit selection preceded its producer acceptance')
            if row.board_limit!=game.ruleset.max_board:raise ValueError('Recruit selection borrowed another capacity policy')
            if row.basis is not None and validate_basis(state,registry,row.basis,closed=True)!=row.candidates:raise ValueError('Recruit receipt lost original physical inventory')
            if event.kind=='recruit_selection_accepted':
                if identity in offers or row.entry_status!='unattempted'or row.entry_root_id is not None:raise ValueError('Duplicate/rewritten original recruit selection')
                if row.index and(data['recruit_id'],row.index-1)not in bound:raise ValueError('Recruit selection advanced before original attempt binding')
                offers[identity]=row
            else:
                if identity in bound or row.entry_status=='unattempted'or replace(row,entry_status='unattempted',entry_root_id=None)!=offers.get(identity):raise ValueError('Recruit entry differs from original frozen selection')
                bound[identity]=row
            continue
        root=from_dict(RecruitRecord,json.loads(data['root']));validate_record(state,registry,root,closed=True,children=children)
        if data['recruit_id']!=root.id or(event.source_id,event.player_id,event.amount)!=(root.spec.cause.source.entity_id,root.spec.player_id,root.spec.count)or root.action>event.action or root.event_cursor>=event.sequence:raise ValueError('Recruit event changed producer/chronology domain')
        if event.kind=='recruit_summon_accepted':
            if root.id in accepted or root.rounds or root.status!='active'or root.event_cursor!=event.sequence-1:raise ValueError('Invalid/duplicate recruit acceptance')
            accepted[root.id]=root
        else:
            if root.id in closed or root.status=='active'or replace(root,rounds=(),status='active')!=accepted.get(root.id):raise ValueError('Recruit close differs from original request')
            closed[root.id]=root
        if root.id not in current and not any(e.kind=='timeline_rewound'and e.sequence>event.sequence and type(dict(e.data).get('event_start'))is int and dict(e.data)['event_start']<=root.event_cursor for e in events):raise ValueError('Recruit vanished without later actual Retry')
    parents={**closed,**current}
    for root in parents.values():
        if replace(root,rounds=(),status='active')!=accepted.get(root.id)or(root.status!='active'and closed.get(root.id)!=root):raise ValueError('Current recruit differs from original event receipts')
        for row in root.rounds:
            if row!=(bound if row.entry_status!='unattempted'else offers).get((root.id,row.index)):raise ValueError('Recruit cropped/changed an original selection or actual binding')
    for identity in offers:
        parent=parents.get(identity[0])
        if parent is None or identity[1]>=len(parent.rounds):raise ValueError('Original recruit selection lost its complete producer prefix')
    for child in children.values():
        link=child.request.producer_link
        if type(link)is RecruitEntryLink:
            parent=parents.get(link.recruit_id)
            if parent is None:raise ValueError('Physical child has no complete original producer')
            validate_child(parent,link.index,child)


def rows_from_dict(value):
    if type(value['recruit_summon_history'])is not list:raise ValueError('Typed original recruit history required')
    value['recruit_summon_history']=[from_dict(RecruitRecord,x)for x in value['recruit_summon_history']]


def register(mechanics):
    # Pool/zone types are resolved after their modules finish initialization.
    global CardReference,PoolQuery
    from .zones import CardReference
    from .pools import PoolQuery
    for cls in(RecruitEntryMaterial,RecruitCandidateFact,RecruitBasis,RecruitEntryLink,RecruitRound,RecruitRecord):mechanics.register_payload_type(cls)
    # Original repeated SummonFromZone was a real checkpoint; keep this one real.
    mechanics.register(ContinueRecruit,continue_producer)
    mechanics.register(ContinueRecruitedMinion,continue_recruited_minion)
