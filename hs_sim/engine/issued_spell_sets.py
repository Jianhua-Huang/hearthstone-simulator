"""Three actual generated spells and one source-independent return program.

The original physical members are the local policy; copy inheritance and exact
CN reward timing remain separate calibration questions. Printed spell kinds at
play, rather than the generated card name or raw CAST count, determine progress.
"""
from dataclasses import asdict,dataclass,fields,is_dataclass,replace
from random import Random
import json

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import AddToHand,Effect,_integer,_player,_source
from .model import (CardClass,CardType,Event,GameState,PlayerEffect,PlayerEffectSpec,TriggerSpec,Zone,
    _name,validate_end_turn_rng)
from .pools import GenerationContext,PoolQuery,resolve_candidates,sample_candidates
from .serialization import end_turn_rng_from_json,end_turn_rng_to_json

PROGRESS='engine.issued_spell_set.progress'
QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')


def is_program_spec(spec):
    if(type(spec)is not PlayerEffectSpec or len(spec.triggers)!=1 or
            spec.triggers[0].event!='card_played' or spec.triggers[0].behavior_id!=PROGRESS):return False
    return spec==PlayerEffectSpec(spec.id,spec.card_id,triggers=(TriggerSpec('card_played',PROGRESS),))


@dataclass(frozen=True)
class IssuedSpellSet:
    battlecry_id:int
    pool_id:str
    player_id:int
    source_id:int
    source_card_id:str
    hero_class:CardClass
    candidates:tuple[str,...]
    selected:tuple[str,...]
    rng_before:tuple
    rng_after:tuple
    acceptance_event:int
    allocations:tuple[SourceAllocationFact,...]=()
    reward_play_ids:tuple[int,...]=()

    def __post_init__(self):
        _integer(self.battlecry_id,'issued original Battlecry',1);_player(self.player_id);_source(self.source_id)
        if self.source_id is None:raise ValueError('Issued spell sets require their original physical creator')
        _name(self.pool_id,'past spell pool');_name(self.source_card_id,'original return card')
        if type(self.hero_class)is not CardClass or self.hero_class==CardClass.NEUTRAL:raise ValueError('Issued spell set requires original current hero class')
        for key in('candidates','selected'):
            values=getattr(self,key)
            if type(values)is not tuple or any(type(x)is not str or not x for x in values):raise ValueError('Issued set requires complete immutable card inventories')
        if len(self.candidates)!=len(set(self.candidates))or len(self.selected)!=(3 if self.candidates else 0)or not set(self.selected)<=set(self.candidates):
            raise ValueError('Issued set lost its three physical selections')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        _integer(self.acceptance_event,'issued original acceptance event',1)
        if type(self.allocations)is not tuple or len(self.allocations)>len(self.selected)or any(type(a)is not SourceAllocationFact for a in self.allocations):
            raise ValueError('Issued set requires its actual ordered physical deliveries')
        for allocation in self.allocations:allocation.__post_init__()
        if len({a.entity_id for a in self.allocations})!=len(self.allocations):raise ValueError('Issued physical members must be distinct even for duplicate card names')
        if type(self.reward_play_ids)is not tuple or len(self.reward_play_ids)not in(0,3)or len(set(self.reward_play_ids))!=len(self.reward_play_ids):
            raise ValueError('Issued completion requires three distinct original plays')
        for pid in self.reward_play_ids:_integer(pid,'issued original completed play',1)


def from_dict(value):
    if type(value)is not dict or set(value)!={f.name for f in fields(IssuedSpellSet)}:raise ValueError('Issued set requires its complete saved fields')
    row=dict(value);row['hero_class']=CardClass(row['hero_class'])
    for name in('candidates','selected','reward_play_ids'):
        if type(row[name])is not list:raise ValueError('Issued set JSON inventories require arrays')
        row[name]=tuple(row[name])
    for name in('rng_before','rng_after'):row[name]=end_turn_rng_from_json(row[name])
    if type(row['allocations'])is not list:raise ValueError('Issued allocations require an array')
    row['allocations']=tuple(allocation_from_dict(a)for a in row['allocations'])
    return IssuedSpellSet(**row)


def matching_plays(state,plan,through):
    if len(plan.allocations)!=3:return ()
    result=[]
    for fact in plan.allocations:
        play=next((p for p in state.play_history if p.id<=through and p.player_id==plan.player_id and
            p.source_id==fact.entity_id and p.kind==CardType.SPELL and p.completed),None)
        if play is None:return ()
        result.append(play.id)
    return tuple(result)


def validate_plan(state,registry,plan):
    if type(plan)is not IssuedSpellSet:raise ValueError('Expected a typed issued spell plan')
    plan.__post_init__()
    from .battlecries import battlecry_record
    row=battlecry_record(state,plan.battlecry_id)
    if((row.source_id,row.player_id,row.payload.card_id)!=(plan.source_id,plan.player_id,plan.source_card_id)or
            not row.payload_started or row.failure is not None or registry.card(plan.source_card_id).kind!=CardType.MINION):
        raise ValueError('Issued program lost its actual original native Battlecry')
    for index,fact in enumerate(plan.allocations):
        validate_allocation(state,registry,fact)
        if(fact.card_id!=plan.selected[index]or fact.kind!=CardType.SPELL or fact.owner!=plan.player_id or
                fact.controller!=plan.player_id or fact.zone not in(Zone.HAND,Zone.GRAVEYARD)):
            raise ValueError('Issued set borrowed another actual delivery or recipient')
    if plan.reward_play_ids and matching_plays(state,plan,max(plan.reward_play_ids))!=plan.reward_play_ids:
        raise ValueError('Issued set changed its original three completed spell plays')


def validate_instance(state,registry,player_id,instance):
    spec=registry.player_effect(instance.spec_id);plan=instance.issued_spell_set
    if is_program_spec(spec)!=(plan is not None):raise ValueError('Issued source program differs from its explicit native trigger declaration')
    if plan is None:return
    validate_plan(state,registry,plan)
    if((player_id,instance.source_id,instance.source_card_id,spec.card_id)!=(plan.player_id,plan.source_id,plan.source_card_id,plan.source_card_id)or
            any(getattr(instance,k)is not None for k in('remaining_turns','source_allocation','source_player_id','cost_modifier_id',
                'aura_duration_cast_id','spell_aura_id','spell_aura_card_id','spell_aura_player_id','investigation'))or
            instance.adaptations or instance.aura_duration_grants):
        raise ValueError('Issued program cannot borrow another source or other player-effect material')


def validate_install(state,registry,effect):
    spec=registry.player_effect(effect.spec_id);plan=effect.issued_spell_set
    if is_program_spec(spec)!=(plan is not None):raise ValueError('Issued installation needs its complete original plan')
    if plan is None:return
    validate_plan(state,registry,plan)
    if((effect.player_id,effect.source_id,spec.card_id)!=(plan.player_id,plan.source_id,plan.source_card_id)or
            plan.allocations or plan.reward_play_ids or effect.capture_health_source or effect.aura_duration_cast_id is not None or
            effect.spell_aura_id is not None or effect.aura_duration_grants or effect.investigation is not None):
        raise ValueError('Issued program must install its original unstarted independent set')
    if any(e.issued_spell_set is not None and e.issued_spell_set.battlecry_id==plan.battlecry_id for p in state.players.values()for e in p.player_effects):
        raise ValueError('Original Battlecry already has its issued set')


def rows_for(registry,context,pool_id,hero_class,source_card_id,player_id):
    if type(context)is not GenerationContext:raise ValueError('Issued past spells require their explicit generation context')
    if not registry.pool(pool_id,context).complete:raise ValueError('Issued past spells require a complete declared historical pool')
    return resolve_candidates(registry,context,pool_id,QUERY,current_class=hero_class,
        source_card_id=source_card_id,player_id=player_id,exclude_source_by_rule=True)


def accepted_data(plan):
    return dict(battlecry_id=plan.battlecry_id,pool_id=plan.pool_id,source_card_id=plan.source_card_id,
        hero_class=plan.hero_class.value,candidates=plan.candidates,selected=plan.selected,
        rng_before=json.dumps(end_turn_rng_to_json(plan.rng_before),separators=(',',':')),
        rng_after=json.dumps(end_turn_rng_to_json(plan.rng_after),separators=(',',':')))


def validate_original(game,plan,instance=None):
    validate_plan(game._state,game.registry,plan)
    rows=rows_for(game.registry,game._generation_context,plan.pool_id,plan.hero_class,plan.source_card_id,plan.player_id)
    rng=Random();rng.setstate(plan.rng_before);selected=sample_candidates(rng,rows,3,replacement=True)
    if(tuple(r.card_id for r in rows),selected,rng.getstate())!=(plan.candidates,plan.selected,plan.rng_after):
        raise ValueError('Issued set changed its original candidates, selections or RNG')
    from .hero_health_history import effective_events
    events=effective_events(game._events);event=next((e for e in events if e.sequence==plan.acceptance_event),None)
    if(event is None or event.kind!='issued_spell_set_accepted' or
            (event.source_id,event.player_id)!=(plan.source_id,plan.player_id)or
            json.dumps(dict(event.data),sort_keys=True)!=json.dumps(accepted_data(plan),sort_keys=True)):
        raise ValueError('Issued set lost its original private acceptance')
    for index,fact in enumerate(plan.allocations):
        candidates=[e for e in events if e.kind=='issued_spell_member_created' and dict(e.data).get('acceptance_id')==plan.acceptance_event and dict(e.data).get('index')==index]
        if len(candidates)!=1 or dict(candidates[0].data).get('allocation_json')!=json.dumps(asdict(fact),sort_keys=True,separators=(',',':')):
            raise ValueError('Issued physical member lost its original creation')


@dataclass(frozen=True)
class CreateIssuedSpellSet(Effect):
    battlecry_id:int
    pool_id:str
    spec_id:str
    def __post_init__(self):
        _integer(self.battlecry_id,'issued Battlecry',1);_name(self.pool_id,'issued pool');_name(self.spec_id,'issued program')


@dataclass(frozen=True)
class DeliverIssuedMember(Effect):
    player_id:int
    battlecry_id:int
    index:int
    def __post_init__(self):
        _player(self.player_id);_integer(self.battlecry_id,'issued Battlecry',1);_integer(self.index,'issued member index',0)
        if self.index>=3:raise ValueError('Issued set has exactly three members')


@dataclass(frozen=True)
class CheckIssuedPlay(Effect):
    instance_id:int
    event:Event
    def __post_init__(self):
        _integer(self.instance_id,'issued original instance',1)
        if type(self.event)is not Event or self.event.kind!='card_played':raise ValueError('Issued progress requires an actual completed play event')


@dataclass(frozen=True)
class DeliverIssuedReward(Effect):
    player_id:int
    instance:PlayerEffect
    def __post_init__(self):
        _player(self.player_id)
        if type(self.instance)is not PlayerEffect or self.instance.issued_spell_set is None:raise ValueError('Issued reward needs its consumed original program')
        self.instance.__post_init__()
        if not self.instance.issued_spell_set.reward_play_ids:raise ValueError('Issued reward lost its accepted completion')


def progress(c):
    if c.player_effect is None or c.event is None or c.event.player_id!=c.player_id:return ()
    return(CheckIssuedPlay(c.player_effect.id,c.event),)


def start(r,effect):
    effect.__post_init__()
    from .battlecries import battlecry_record
    from .player_effects import AddPlayerEffect
    row=battlecry_record(r.state,effect.battlecry_id);spec=r.registry.player_effect(effect.spec_id)
    if(not row.payload_started or row.completed or row.interrupted or row.failure is not None or
            not is_program_spec(spec)or spec.card_id!=row.payload.card_id):raise ValueError('Issued source requires its active native Battlecry and explicit program')
    hero=r.player(row.player_id).hero_class;rows=rows_for(r.registry,r.game._generation_context,effect.pool_id,hero,row.payload.card_id,row.player_id)
    before=r.game._rng.getstate();chosen=sample_candidates(r.game._rng,rows,3,replacement=True)
    plan=IssuedSpellSet(row.id,effect.pool_id,row.player_id,row.source_id,row.payload.card_id,hero,
        tuple(m.card_id for m in rows),chosen,before,r.game._rng.getstate(),len(r.game._events)+1)
    event=r.emit('issued_spell_set_accepted',source_id=row.source_id,player_id=row.player_id,**accepted_data(plan),_capture=False)
    if event.sequence!=plan.acceptance_event:raise ValueError('Issued set changed its original acceptance cursor')
    if not chosen:return ()
    return(AddPlayerEffect(row.player_id,effect.spec_id,row.source_id,issued_spell_set=plan),DeliverIssuedMember(row.player_id,row.id,0))


def find_program(state,player_id,battlecry_id):
    found=[e for e in state.players[player_id].player_effects if e.issued_spell_set is not None and e.issued_spell_set.battlecry_id==battlecry_id]
    if len(found)!=1:raise ValueError('Issued delivery lost its unique original program')
    return found[0]


def deliver_member(r,effect):
    effect.__post_init__();instance=find_program(r.state,effect.player_id,effect.battlecry_id);plan=instance.issued_spell_set
    validate_instance(r.state,r.registry,effect.player_id,instance);validate_original(r.game,plan)
    if effect.index!=len(plan.allocations)or plan.reward_play_ids:raise ValueError('Issued delivery changed original member order')
    from .opening import create_hand_card,announce_hand_card
    request=AddToHand(plan.player_id,plan.selected[effect.index],plan.source_id)
    entity=create_hand_card(r,request,defer_publication=True);fact=SourceAllocationFact.capture(r.state,entity)
    updated=replace(instance,issued_spell_set=replace(plan,allocations=(*plan.allocations,fact)))
    player=r.player(plan.player_id);player.player_effects[player.player_effects.index(instance)]=updated
    r.emit('issued_spell_member_created',source_id=plan.source_id,player_id=plan.player_id,
        acceptance_id=plan.acceptance_event,index=effect.index,allocation_json=json.dumps(asdict(fact),sort_keys=True,separators=(',',':')),_capture=False)
    announce_hand_card(r,request,entity)
    return(DeliverIssuedMember(plan.player_id,plan.battlecry_id,effect.index+1),)if effect.index<2 else()


def encode_instance(game,instance):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(game.mechanics,game.registry).encode(instance),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def note_program(r,instance,phase):
    plan=instance.issued_spell_set
    r.emit('issued_spell_program_'+phase,source_id=plan.source_id,player_id=plan.player_id,
        instance_id=instance.id,acceptance_id=plan.acceptance_event,instance_json=encode_instance(r.game,instance),_capture=False)


def check_play(r,effect):
    effect.__post_init__();event=next((e for e in r.game._events if e.sequence==effect.event.sequence),None)
    if event!=effect.event:raise ValueError('Issued progress lost its original committed event')
    player=r.player(event.player_id);instance=next((e for e in player.player_effects if e.id==effect.instance_id),None)
    if instance is None:return ()
    validate_instance(r.state,r.registry,player.id,instance);plan=instance.issued_spell_set;validate_original(r.game,plan)
    from .play_history import play_record
    play=play_record(r.state,dict(event.data)['play_id'])
    if not play.completed or (play.player_id,play.source_id)!=(event.player_id,event.source_id):raise ValueError('Issued progress requires its actual completed physical play')
    matches=matching_plays(r.state,plan,play.id)
    if not matches:return ()
    updated=replace(instance,issued_spell_set=replace(plan,reward_play_ids=matches))
    player.player_effects[player.player_effects.index(instance)]=updated
    from .player_effects import ConsumePlayerEffect,consume
    work=consume(r,ConsumePlayerEffect(player.id,updated,(DeliverIssuedReward(player.id,updated),)))
    if work:r.emit('issued_spell_set_consumed',source_id=plan.source_id,player_id=player.id,
        instance_id=instance.id,instance_json=encode_instance(r.game,updated),_capture=False)
    return work


def reward(r,effect):
    effect.__post_init__();instance=effect.instance;plan=instance.issued_spell_set
    validate_instance(r.state,r.registry,effect.player_id,instance);validate_original(r.game,plan)
    if any(e.id==instance.id for p in r.state.players.values()for e in p.player_effects):raise ValueError('Issued reward requires actual original consumption')
    marks=[e for e in r.game._events if e.kind=='issued_spell_set_consumed' and dict(e.data).get('instance_id')==instance.id]
    if len(marks)!=1 or dict(marks[0].data).get('instance_json')!=encode_instance(r.game,instance):raise ValueError('Issued reward lost its original consumed instance')
    if any(e.kind=='issued_spell_set_reward_delivered' and dict(e.data).get('instance_id')==instance.id for e in r.game._events):raise ValueError('Issued reward has already been delivered')
    from .opening import create_hand_card,announce_hand_card
    request=AddToHand(plan.player_id,plan.source_card_id,plan.source_id);entity=create_hand_card(r,request,defer_publication=True)
    r.emit('issued_spell_set_reward_delivered',source_id=plan.source_id,player_id=plan.player_id,
        instance_id=instance.id,allocation_json=json.dumps(asdict(SourceAllocationFact.capture(r.state,entity)),sort_keys=True,separators=(',',':')),_capture=False)
    announce_hand_card(r,request,entity)
    return ()


def validate_boundary(game):
    programs=[(p.id,e)for p in game._state.players.values()for e in p.player_effects if e.issued_spell_set is not None]
    if not programs and not any(e.kind=='issued_spell_set_accepted' for e in game._events):return
    for pid,instance in programs:
        validate_instance(game._state,game.registry,pid,instance);validate_original(game,instance.issued_spell_set)
    frame=game._frame;members=[];rewards=[];installing=[]
    from .player_effects import AddPlayerEffect
    def visit(value):
        if type(value)is GameState:return
        if type(value)is IssuedSpellSet:return
        if type(value)is DeliverIssuedMember:members.append(value);return
        if type(value)is DeliverIssuedReward:
            value.__post_init__();validate_original(game,value.instance.issued_spell_set);rewards.append(value);return
        if type(value)is AddPlayerEffect and value.issued_spell_set is not None:
            validate_install(game._state,game.registry,value);validate_original(game,value.issued_spell_set);installing.append(value);return
        if is_dataclass(value):
            for field in fields(value):visit(getattr(value,field.name))
        elif type(value)is tuple:
            for item in value:visit(item)
    if frame is not None:visit(frame.prefix);visit(frame.continuation);visit(frame.options)
    if game._state.status!='playing':return
    for pid,instance in programs:
        plan=instance.issued_spell_set
        if len(plan.allocations)<3 and not any((e.player_id,e.battlecry_id,e.index)==(pid,plan.battlecry_id,len(plan.allocations))for e in members):
            raise ValueError('Issued program lost its next actual physical delivery')
    from .hero_health_history import effective_events
    events=effective_events(game._events);delivered={dict(e.data)['instance_id']for e in events if e.kind=='issued_spell_set_reward_delivered'}
    removed={dict(e.data)['acceptance_id']for e in events if e.kind=='issued_spell_program_removed'}
    retained={e.issued_spell_set.acceptance_event for _,e in programs}|{e.issued_spell_set.acceptance_event for e in installing}
    for event in events:
        if event.kind=='issued_spell_set_accepted' and dict(event.data)['selected'] and event.sequence not in retained|removed:
            raise ValueError('Issued acceptance lost its entire original source-independent program')
    for event in events:
        if event.kind!='issued_spell_set_consumed' or dict(event.data)['instance_id']in delivered:continue
        if not any(e.instance.id==dict(event.data)['instance_id']and encode_instance(game,e.instance)==dict(event.data)['instance_json']for e in rewards):
            raise ValueError('Consumed issued set lost its accepted reward work')


def register(mechanics):
    mechanics.register_payload_type(IssuedSpellSet)
    mechanics.register(CreateIssuedSpellSet,start);mechanics.register(DeliverIssuedMember,deliver_member)
    mechanics.register(CheckIssuedPlay,check_play);mechanics.register(DeliverIssuedReward,reward)
