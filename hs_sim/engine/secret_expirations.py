"""Source-bound Secret lifetimes over real CASTs and the shared owner clock."""
from dataclasses import asdict,dataclass
import json
from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import Effect,_integer
from .model import CardType,Keyword,KeywordExpiry,Zone,_name
from .pools import GenerationPolicy,PoolQuery

QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,keywords_all=(Keyword.SECRET,))
KEY='_secret_expiration'


@dataclass(frozen=True)
class SecretExpiryProfile:
    card_id:str
    pool_id:str
    card_ids:tuple[str,...]
    count:int=5

    def __post_init__(self):
        _name(self.card_id,'expiring Secret producer');_name(self.pool_id,'expiring Secret pool')
        if self.count!=5 or type(self.count)is not int or type(self.card_ids)is not tuple or not self.card_ids or len(set(self.card_ids))!=len(self.card_ids):
            raise ValueError('Secret lifetime requires its complete finite five-cast source')
        for cid in self.card_ids:_name(cid,'original Secret candidate')


def validate_profile(registry,profile):
    if type(profile)is not SecretExpiryProfile:raise ValueError('Expected a SecretExpiryProfile')
    profile.__post_init__();source=registry.card(profile.card_id)
    if source.kind!=CardType.SPELL or source.on_play is None or source.secret is not None:
        raise ValueError('Secret lifetime belongs to its actual spell producer')
    for cid in profile.card_ids:
        card=registry.card(cid)
        if card.kind!=CardType.SPELL or card.secret is None:raise ValueError('Secret source contains a non-executable original candidate')


def parent_for(state,registry,child):
    from .spell_casts import active_cast
    if child.caster_id is None:return None
    parent=active_cast(state,child.caster_id,child.player_id)
    return parent if parent is not None and parent.card_id in registry.secret_expiry_profiles else None


def original_deadline(state,parent):
    origin=parent.owner_turn_id
    if type(origin)is not int or not 1<=origin<=len(state.owner_turn_history):
        raise ValueError('Expiring Secrets require their genuine producer owner interval')
    previous=next((v for v in reversed(state.owner_turn_history[:origin])if v.player_id==parent.player_id),None)
    return KeywordExpiry(parent.player_id,parent.turn,(previous.owner_index if previous is not None else 0)+1,'turn_started',origin)


def validate_batch(state,registry,spec,*,allow_closed=False):
    from .spell_casts import active_cast
    if spec.source_id is None:return
    parent=active_cast(state,spec.source_id,spec.player_id)
    if parent is None and allow_closed:
        parent=next((v for v in reversed(state.cast_history)if v.source_id==spec.source_id and v.player_id==spec.player_id),None)
    profile=None if parent is None else registry.secret_expiry_profiles.get(parent.card_id)
    if profile is None:
        entity=state.entities.get(spec.source_id)
        if entity is not None and entity.card_id in registry.secret_expiry_profiles:
            raise ValueError('Expiring Secret batch lost its original active producer CAST')
        return
    if (spec.pool_id!=profile.pool_id or spec.query!=QUERY or spec.count!=profile.count or
            spec.replacement is not True or spec.refresh!='per_cast' or spec.while_source_in_play or
            spec.target_id is not None or spec.target_ids or spec.targeting!='random' or spec.choices!='random' or spec.policy!=GenerationPolicy() or spec.target_preference is not None):
        raise ValueError('Expiring Secret producer changed its original full five-cast request')


@dataclass(frozen=True)
class SecretExpiry:
    parent_cast_id:int
    cast_id:int
    card:SourceAllocationFact
    instance_id:int
    deadline:KeywordExpiry
    turn:int
    action:int
    sequence:int

    def __post_init__(self):
        for name in('parent_cast_id','cast_id','instance_id','turn','sequence'):_integer(getattr(self,name),name,1)
        _integer(self.action,'Secret expiration action',0)
        if type(self.card)is not SourceAllocationFact or type(self.deadline)is not KeywordExpiry:
            raise ValueError('Secret expiration requires its original physical allocation and owner clock')
        self.card.__post_init__();self.deadline.__post_init__()
        if self.card.kind!=CardType.SPELL or self.card.zone!=Zone.SECRET or self.deadline.boundary!='turn_started' or self.parent_cast_id>=self.cast_id:
            raise ValueError('Secret expiration changed its actual deployment or producer ancestry')


def from_dict(value):
    if value is None:return None
    from .serialization import _row
    row=_row(value,SecretExpiry);row['card']=allocation_from_dict(row['card'])
    row['deadline']=KeywordExpiry(**_row(row['deadline'],KeywordExpiry))
    return SecretExpiry(**row)


def validate_value(state,registry,value):
    from .spell_casts import cast_record
    from .timed_keywords import validate_deadline
    value.__post_init__();validate_allocation(state,registry,value.card);validate_deadline(state,value.deadline)
    parent=cast_record(state,value.parent_cast_id);child=cast_record(state,value.cast_id)
    profile=registry.secret_expiry_profiles.get(parent.card_id)
    if (profile is None or child.card_id not in profile.card_ids or registry.card(child.card_id).secret is None or
            child.card_id!=value.card.card_id or child.caster_id!=parent.source_id or
            child.player_id!=parent.player_id or value.card.controller!=parent.player_id or
            not parent.payload_started or parent.failure is not None or not child.payload_started or child.failure is not None or
            value.deadline!=original_deadline(state,parent) or value.instance_id>=state.next_attachment_id or
            not child.turn<=value.turn<=state.turn or not child.action<=value.action<=state.action_number):
        raise ValueError('Secret expiration borrowed another CAST, producer, owner clock or instance')
    return parent,child


def validate_entity(state,registry,entity):
    value=entity.secret_expiry
    if value is None:return
    if type(value)is not SecretExpiry:raise ValueError('Secret expiration requires its complete typed deployment')
    validate_value(state,registry,value);a=value.card
    if (entity.id,entity.card_id,entity.owner,entity.controller,entity.zone,entity.zone_epoch,entity.entered_order,entity.secret_instance_id)!=(
            a.entity_id,a.card_id,a.owner,a.controller,a.zone,a.zone_epoch,a.entered_order,value.instance_id):
        raise ValueError('Secret expiration lost its original continuous deployed instance')


def attach(r,entity,cast_id):
    if cast_id is None:return
    from .spell_casts import cast_record,active_cast
    child=cast_record(r.state,cast_id)
    if (child.card_id!=entity.card_id or child.player_id!=entity.controller or not child.payload_started or child.completed or
            active_cast(r.state,child.source_id,child.player_id)!=child):
        raise ValueError('Secret deployment lost its actual currently executing CAST')
    parent=parent_for(r.state,r.registry,child)
    if parent is None:return
    value=SecretExpiry(parent.id,child.id,SourceAllocationFact.capture(r.state,entity),entity.secret_instance_id,
        original_deadline(r.state,parent),r.state.turn,r.state.action_number,len(r.game._events)+1)
    entity.secret_expiry=value;validate_entity(r.state,r.registry,entity)


def event_data(entity):
    return {}if entity.secret_expiry is None else{KEY:json.dumps(asdict(entity.secret_expiry),sort_keys=True,separators=(',',':'))}


def due(state):
    from .owner_turns import owner_turn_index
    return tuple(e.secret_expiry for e in sorted(state.entities.values(),key=lambda e:(e.entered_order,e.id))if e.secret_expiry is not None and
        e.secret_expiry.deadline.player_id==state.active_player and
        e.secret_expiry.deadline.owner_turn_index<=owner_turn_index(state,state.active_player))


def validate_event(state,registry,value,events):
    from .hero_health_history import effective_events
    matches=[e for e in effective_events(events)if e.sequence==value.sequence]
    if len(matches)!=1:raise ValueError('Secret expiration lost its original unique deployment event')
    event=matches[0];data=dict(event.data)
    if (event.kind!='secret_set' or set(data)!={KEY} or type(data[KEY])is not str or from_dict(json.loads(data[KEY]))!=value or
            (event.source_id,event.player_id,event.action)!=(value.card.entity_id,value.card.controller,value.action)):
        raise ValueError('Secret expiration changed its actual original hidden deployment proof')


@dataclass(frozen=True)
class ExpireSecret(Effect):
    original:SecretExpiry

    def __post_init__(self):
        if type(self.original)is not SecretExpiry:raise ValueError('Secret cleanup requires its original typed deployment')
        self.original.__post_init__()

    def validate_in_state(self,state,registry,events=None):
        from .owner_turns import owner_turn_index
        self.__post_init__();validate_value(state,registry,self.original)
        if owner_turn_index(state,self.original.deadline.player_id)<self.original.deadline.owner_turn_index:
            raise ValueError('Secret cleanup precedes its original next owner start')
        if events is not None:validate_event(state,registry,self.original,events)


def expire(r,request):
    request.validate_in_state(r.state,r.registry,r.game.events);value=request.original
    entity=r.state.entities[value.card.entity_id]
    if entity.secret_expiry!=value:return ()
    validate_entity(r.state,r.registry,entity)
    from .secrets import consume
    consume(r,entity,'secret_removed');return ()


def validate_boundary(game):
    from .hero_health_history import effective_events
    seen={}
    original_events=tuple(game._events)
    for event in effective_events(original_events):
        data=dict(event.data)
        if KEY not in data:continue
        if type(data[KEY])is not str:raise ValueError('Secret deployment lost its complete expiration proof')
        value=from_dict(json.loads(data[KEY]));validate_value(game._state,game.registry,value)
        validate_event(game._state,game.registry,value,original_events)
        if value.instance_id in seen:raise ValueError('Secret lifetime borrowed another deployed instance')
        seen[value.instance_id]=value
    for entity in game._state.entities.values():
        validate_entity(game._state,game.registry,entity)
        if entity.secret_expiry is not None and seen.get(entity.secret_instance_id)!=entity.secret_expiry:
            raise ValueError('Active expiring Secret lost its actual original deployment')
        if entity.zone==Zone.SECRET and entity.secret_instance_id in seen and entity.secret_expiry!=seen[entity.secret_instance_id]:
            raise ValueError('Original deployed Secret silently dropped its expiration')


def register(mechanics):
    mechanics.register_payload_type(SecretExpiry)
    mechanics.register(ExpireSecret,expire)
