"""Teach an original physical student through the ordinary memory discovery.

Past-set membership belongs to a complete versioned host pool. It is never
inferred from the already implemented spell adapters or a tiny test inventory.
"""
from dataclasses import asdict,dataclass,fields,is_dataclass
import json

from .allocation_facts import SourceAllocationFact,validate_allocation
from .carved_spells import install,profile_for,validate_spell
from .effects import AddToHand,Effect,_integer
from .model import CardType,GameState,Zone,_name
from .pools import DiscoverFromPool,GenerationContext,PoolQuery,resolve_candidates

QUERY=PoolQuery(kinds=(CardType.SPELL,),min_cost=7,collectible=True,class_mode='current')
PROMPT='发现一个来自过去的高费法术教给小学生'


@dataclass(frozen=True)
class StudentTeachingTarget:
    battlecry_id:int
    allocation:SourceAllocationFact
    event_id:int

    def __post_init__(self):
        _integer(self.battlecry_id,'original student creator Battlecry',1);_integer(self.event_id,'original student acceptance',1)
        if type(self.allocation)is not SourceAllocationFact:raise ValueError('Teaching requires its original physical allocation')
        self.allocation.__post_init__()
        if self.allocation.kind!=CardType.MINION or self.allocation.zone not in(Zone.HAND,Zone.GRAVEYARD):
            raise ValueError('Student must be the actual generated hand card or its ordinary overflow')


@dataclass(frozen=True)
class CreateStudentDiscovery(Effect):
    battlecry_id:int
    student_card_id:str
    pool_id:str

    def __post_init__(self):
        _integer(self.battlecry_id,'student creator Battlecry',1)
        _name(self.student_card_id,'original student face');_name(self.pool_id,'complete past spell pool')


def creator(state,registry,battlecry_id,student_card_id,*,active=True):
    from .battlecries import battlecry_record
    row=battlecry_record(state,battlecry_id);profile=profile_for(registry,student_card_id)
    if (not profile.teaching or row.payload.card_id!=profile.source_card_id or
            row.payload.behavior_id!=registry.card(profile.source_card_id).battlecry or
            not row.payload_started or row.failure is not None or active and(row.completed or row.interrupted)):
        raise ValueError('Teaching requires its actual accepted native creator Battlecry')
    return row


def validate_spec(spec):
    if type(spec)is not DiscoverFromPool or type(spec.memory_target)is not StudentTeachingTarget:
        raise ValueError('Teaching requires its typed original student discovery')
    spec.memory_target.__post_init__()
    plain=DiscoverFromPool(spec.player_id,spec.pool_id,QUERY,source_id=spec.source_id,prompt=PROMPT)
    if spec.destination!='memory' or spec.source_id is None or any(getattr(spec,f.name)!=getattr(plain,f.name)
            for f in fields(spec)if f.name not in('destination','memory_target')):
        raise ValueError('Student teaching supports one plain current-class past7+spell discovery')


def validate_target(state,registry,spec,*,active=True):
    validate_spec(spec);target=spec.memory_target;fact=target.allocation
    row=creator(state,registry,target.battlecry_id,fact.card_id,active=active)
    if (row.source_id,row.player_id)!=(spec.source_id,spec.player_id) or (fact.owner,fact.controller)!=(row.player_id,row.player_id):
        raise ValueError('Teaching borrowed another creator or original student recipient')
    validate_allocation(state,registry,fact)
    return row


def acceptance_data(target):
    return dict(battlecry_id=target.battlecry_id,allocation_json=json.dumps(asdict(target.allocation),sort_keys=True,separators=(',',':')))


def validate_acceptance(events,state,registry,spec):
    row=validate_target(state,registry,spec);target=spec.memory_target
    event=next((e for e in events if e.sequence==target.event_id),None)
    if (event is None or event.kind!='student_teaching_accepted' or
            (event.source_id,event.player_id)!=(row.source_id,row.player_id)or dict(event.data)!=acceptance_data(target)):
        raise ValueError('Teaching lost its original physical student acceptance')
    return row


def validate_pool(r,pool_id,student_card_id,player_id):
    context=r.game._generation_context
    if type(context)is not GenerationContext:raise ValueError('Past spell discovery requires an explicit generation context')
    if not r.registry.pool(pool_id,context).complete:raise ValueError('Student teaching requires a complete declared past spell pool')
    rows=resolve_candidates(r.registry,context,pool_id,QUERY,current_class=r.player(player_id).hero_class,player_id=player_id)
    for row in rows:validate_spell(r.registry,student_card_id,row.card_id)
    return rows


def create_student(r,effect):
    effect.__post_init__();row=creator(r.state,r.registry,effect.battlecry_id,effect.student_card_id)
    validate_pool(r,effect.pool_id,effect.student_card_id,row.player_id)
    from .opening import create_hand_card,announce_hand_card
    request=AddToHand(row.player_id,effect.student_card_id,row.source_id)
    student=create_hand_card(r,request,defer_publication=True)
    target=StudentTeachingTarget(row.id,SourceAllocationFact.capture(r.state,student),len(r.game._events)+1)
    event=r.emit('student_teaching_accepted',source_id=row.source_id,player_id=row.player_id,**acceptance_data(target))
    if event.sequence!=target.event_id:raise ValueError('Student acceptance changed its original event cursor')
    announce_hand_card(r,request,student)
    return(DiscoverFromPool(row.player_id,effect.pool_id,QUERY,source_id=row.source_id,prompt=PROMPT,
        destination='memory',memory_target=target),)


def current_student(state,target):
    fact=target.allocation;entity=state.entities.get(fact.entity_id)
    if entity is None or fact.zone!=Zone.HAND:return None
    if (entity.controller,entity.zone,entity.card_id,entity.zone_epoch)!=(fact.controller,Zone.HAND,fact.card_id,fact.zone_epoch):return None
    return entity


def apply_selection(r,effect):
    spec=effect.batch.spec;validate_acceptance(r.game._events,r.state,r.registry,spec)
    from .card_discoveries import require_original_result
    from .discovery_delivery import DiscoveryCompletion,FinishCardDiscovery,queue
    discovery=require_original_result(r.state,effect.choice_result);target=spec.memory_target
    spell_id=effect.selection.card_id;validate_spell(r.registry,target.allocation.card_id,spell_id)
    entity=current_student(r.state,target)
    if entity is not None:install(r.registry,entity,spell_id)
    r.emit('student_spell_taught',source_id=spec.source_id,player_id=spec.player_id,
        target_id=None if entity is None else entity.id,battlecry_id=target.battlecry_id,
        acceptance_id=target.event_id,discovery_id=discovery.id,card_id=spell_id,taught=entity is not None)
    # The discovered spell is a genuine selection-only memory, not a newly
    # allocated hand spell. Shared completion owns card_discovered consumers.
    return(queue(r,FinishCardDiscovery(DiscoveryCompletion(effect.choice_result,None))),)


def validate_boundary(game):
    frame=game._frame
    if frame is None:return
    from .hero_health_history import effective_events
    events=effective_events(game._events);checked=set()
    def visit(value):
        if type(value)is GameState:return
        if type(value)is DiscoverFromPool:
            if type(value.memory_target)is StudentTeachingTarget:
                key=(value.memory_target.event_id,id(value))
                if key not in checked:
                    validate_acceptance(events,game._state,game.registry,value);checked.add(key)
            return
        if is_dataclass(value):
            for field in fields(value):visit(getattr(value,field.name))
        elif type(value)is tuple:
            for item in value:visit(item)
    visit(frame.prefix);visit(frame.continuation);visit(frame.options)


def register(mechanics):
    mechanics.register_payload_type(StudentTeachingTarget)
    mechanics.register(CreateStudentDiscovery,create_student)
