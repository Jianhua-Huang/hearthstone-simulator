"""Original physical draw/hand links and finite Secret draw transformations.

Accepted draw identity, native/granted declaration and replacement ancestry stay
in DrawRecord. A transformation records the actual physical result separately.
"""
from dataclasses import asdict,dataclass,replace
import json
from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import Effect,_integer
from .model import CardType,DrawRecord,Event,Zone

ROOT='YOP_017'
BANANA='EX1_014t'
HAND_ENTRY_KEY='_draw_hand_entry_id'
OBSERVER_KEY='_draw_observer'
EVENT='draw_card_transformed'
KEY='_draw_transformation'


def observer_from_dict(value):
    from .serialization import _row,_list
    from .deathrattle_memory import DrawForDeathrattle
    from .sacrifice import MinionReference
    row=_row(value,DrawForDeathrattle)
    row['reference']=MinionReference(**_row(row['reference'],MinionReference))
    row['ability_ids']=tuple(_list(row['ability_ids'],'original draw observer abilities'))
    return DrawForDeathrattle(**row)


def observer_event_data(record):
    return {}if record.observer is None else{OBSERVER_KEY:json.dumps(asdict(record.observer),sort_keys=True,separators=(',',':'))}


@dataclass(frozen=True)
class DrawTransformation:
    draw_id:int
    source:SourceAllocationFact
    draw_event:Event
    accepted_action:int
    before:SourceAllocationFact
    after:SourceAllocationFact
    hand_entry_id:int|None
    turn:int
    action:int

    def __post_init__(self):
        for key in('draw_id','turn'):_integer(getattr(self,key),key,1)
        for key in('accepted_action','action'):_integer(getattr(self,key),key,0)
        if self.hand_entry_id is not None:_integer(self.hand_entry_id,'transformed draw entry',1)
        for key in('source','before','after'):
            value=getattr(self,key)
            if type(value)is not SourceAllocationFact:raise ValueError('Draw transformation requires complete physical allocations')
            value.__post_init__()
        if type(self.draw_event)is not Event or self.draw_event.kind!='card_drawn':
            raise ValueError('Draw transformation requires its original physical draw event')
        if (self.source.card_id,self.source.kind,self.source.zone)!=(ROOT,CardType.SPELL,Zone.GRAVEYARD):
            raise ValueError('Draw transformation requires its revealed real Secret source')
        a,z=self.before,self.after
        if ((a.entity_id,a.owner,a.controller)!=(z.entity_id,z.owner,z.controller) or
                z.card_id!=BANANA or z.kind!=CardType.SPELL or a.zone not in(Zone.HAND,Zone.GRAVEYARD) or
                z.zone not in(Zone.HAND,Zone.GRAVEYARD) or self.source.controller==a.controller or
                z.zone_epoch<=a.zone_epoch or (z.zone==Zone.HAND)!=(self.hand_entry_id is not None) or
                self.accepted_action>self.action or self.draw_event.action>self.accepted_action or
                (self.draw_event.target_id,self.draw_event.player_id)!=(a.entity_id,a.controller) or
                dict(self.draw_event.data).get('draw_id')!=self.draw_id):
            raise ValueError('Draw transformation changed its original source, target, entry or clocks')


def transformation_from_dict(value):
    from .serialization import _row,event_from_dict
    row=_row(value,DrawTransformation)
    for key in('source','before','after'):row[key]=allocation_from_dict(row[key])
    event=dict(row['draw_event'])
    if isinstance(event.get('data'),list):
        pairs=event['data']
        if any(type(x)is not list or len(x)!=2 or type(x[0])is not str for x in pairs)or len({x[0]for x in pairs})!=len(pairs):
            raise ValueError('Draw transformation event requires unique original data')
        event['data']=dict(pairs)
    row['draw_event']=event_from_dict(event)
    return DrawTransformation(**row)


def payload(value):
    from .serialization import event_to_dict
    row=asdict(value);row['draw_event']=event_to_dict(value.draw_event);return row


def successful_prefix(state,draw):
    return tuple(row for row in state.draw_history[:draw.id]if row.player_id==draw.player_id and
        row.turn==draw.turn and row.outcome in('hand','cast'))


def hand_reference(state,record,*,completed=False):
    from .hand_history import hand_entry
    from .zones import CardReference
    if completed and not record.completed:raise ValueError('Draw beneficiary precedes original completion')
    value=record.transformation
    if value is not None:
        if value.after.zone!=Zone.HAND:return None
        a=value.after;return CardReference(a.entity_id,a.controller,Zone.HAND,a.card_id,a.zone_epoch)
    if record.outcome!='hand':return None
    if record.hand_entry_id is None:raise ValueError('Successful draw lost its original hand entry')
    e=hand_entry(state,record.hand_entry_id)
    return CardReference(e.entity_id,e.player_id,Zone.HAND,e.card_id,e.zone_epoch)


def validate_draw_links(state,registry,record):
    from .hand_history import hand_entry
    if record.observer is not None:
        from .deathrattle_memory import validate_reference
        request=record.observer;validate_reference(state,request.reference,request.ability_ids)
        if registry.card(request.reference.card_id).kind!=CardType.MINION:
            raise ValueError('Draw observer lost its original physical minion source')
    if record.outcome=='hand':
        if record.hand_entry_id is None:raise ValueError('Successful physical draw lacks its original hand entry')
        entry=hand_entry(state,record.hand_entry_id)
        if (entry.entity_id,entry.player_id,entry.card_id,entry.turn,entry.action,entry.reason,entry.source_id)!=(
                record.entity_id,record.player_id,record.card_id,record.turn,record.action,'draw',record.source_id):
            raise ValueError('Physical draw borrowed another successful acquisition')
    if record.transformation is not None:validate_transformation(state,registry,record.transformation)


def validate_transformation(state,registry,value):
    from .draw_casts import draw_record
    from .hand_history import hand_entry
    value.__post_init__();record=draw_record(state,value.draw_id)
    for item in(value.source,value.before,value.after):validate_allocation(state,registry,item)
    if (record.transformation!=value or record.outcome not in('hand','cast') or
            record.entity_id!=value.before.entity_id or record.player_id!=value.before.controller or
            record.turn!=value.turn or not record.action<=value.accepted_action<=value.action<=state.action_number or
            (value.draw_event.source_id,value.draw_event.action)!=(record.source_id,record.action) or
            len(successful_prefix(state,record))!=2 or value.turn>state.turn):
        raise ValueError('Draw transformation borrowed another original second draw')
    if record.outcome=='hand':
        if value.before.zone!=Zone.HAND or value.after.zone!=Zone.HAND or value.after.zone_epoch!=value.before.zone_epoch+1:
            raise ValueError('Original hand transformation lost its continuous physical body')
    else:
        if value.before.zone!=Zone.GRAVEYARD or value.before.card_id!=record.card_id or value.before.kind!=CardType.SPELL:
            raise ValueError('Draw-cast transformation lost its original pending caster')
        if value.hand_entry_id is not None:
            entry=hand_entry(state,value.hand_entry_id)
            if (entry.entity_id,entry.player_id,entry.card_id,entry.turn,entry.action,entry.zone_epoch,entry.reason,entry.source_id)!=(
                    record.entity_id,record.player_id,BANANA,value.turn,value.action,value.after.zone_epoch,'draw',record.source_id):
                raise ValueError('Converted draw-cast lost its actual Banana acquisition')
        elif value.after.zone!=Zone.GRAVEYARD:
            raise ValueError('Failed converted hand delivery must retain its actual spent body')


@dataclass(frozen=True)
class TransformDrawnCard(Effect):
    original:DrawRecord
    source:SourceAllocationFact
    event:Event
    before:SourceAllocationFact
    accepted_action:int

    def __post_init__(self):
        if type(self.original)is not DrawRecord or type(self.source)is not SourceAllocationFact or type(self.before)is not SourceAllocationFact or type(self.event)is not Event:
            raise ValueError('Original draw transformation requires complete typed material')
        self.original.__post_init__();self.source.__post_init__();self.before.__post_init__()
        row=self.original;_integer(self.accepted_action,'draw transformation acceptance',0)
        if (row.transformation is not None or row.completed or row.interrupted or
                row.outcome not in('hand','cast') or row.phase!=('drawing'if row.outcome=='hand'else'pending_cast') or
                (self.source.card_id,self.source.kind,self.source.zone)!=(ROOT,CardType.SPELL,Zone.GRAVEYARD) or
                self.source.controller==row.player_id or self.event.kind!='card_drawn' or
                (self.event.target_id,self.event.player_id,self.event.source_id,self.event.action)!=(row.entity_id,row.player_id,row.source_id,row.action) or
                dict(self.event.data).get('draw_id')!=row.id or row.action>self.accepted_action or
                (self.before.entity_id,self.before.controller,self.before.zone)!=(row.entity_id,row.player_id,Zone.HAND if row.outcome=='hand'else Zone.GRAVEYARD)):
            raise ValueError('Draw transformation changed its original accepted draw or revealed Secret')

    def validate_in_state(self,state,registry,events=None,*,allow_committed=True):
        from .draw_casts import draw_record
        self.__post_init__();row=draw_record(state,self.original.id)
        for value in(self.source,self.before):validate_allocation(state,registry,value)
        if len(successful_prefix(state,self.original))!=2 or self.accepted_action>state.action_number:
            raise ValueError('Draw transformation requires the original successful second draw')
        if row.transformation is None:
            if row!=self.original:raise ValueError('Draw transformation lost its original pending record')
        else:
            t=row.transformation
            original=replace(row,phase=self.original.phase,interrupted=self.original.interrupted,
                hand_entry_id=self.original.hand_entry_id,transformation=None)
            if (not allow_committed or original!=self.original or t.source!=self.source or
                    t.draw_event!=self.event or t.accepted_action!=self.accepted_action):
                raise ValueError('Draw transformation was duplicated or borrowed another committed result')
        if events is not None:validate_events(self.event,self.source,self.accepted_action,events)


def validate_events(event,source,accepted_action,events):
    from .hero_health_history import effective_events
    current=effective_events(events)
    if sum(e==event for e in current)!=1 or not any(e.kind=='secret_revealed'and
            (e.source_id,e.player_id,e.action)==(source.entity_id,source.controller,accepted_action)and
            e.sequence>event.sequence for e in current):
        raise ValueError('Draw transformation lost its actual draw and subsequent Secret reveal')


def transform(r,request):
    from .draw_casts import draw_record,update
    from .cross_zone import reset_stored_entity,announce_stored_transform
    from .hand_capacity import hand_capacity
    from .hand_history import publish
    from .errors import ResolutionError
    request.validate_in_state(r.state,r.registry,r.game.events,allow_committed=False)
    row=draw_record(r.state,request.original.id);entity=r.state.entities[row.entity_id]
    if row.outcome=='hand':
        if (entity.zone,entity.controller,entity.hand_entry_id)!=(Zone.HAND,row.player_id,row.hand_entry_id):
            r.emit('zone_target_skipped',target_id=entity.id,reason='original_draw_hand_departed');return ()
    else:
        before=request.before
        if (entity.card_id,entity.kind,entity.owner,entity.controller,entity.zone,entity.zone_epoch,entity.entered_order)!=(
                before.card_id,before.kind,before.owner,before.controller,before.zone,before.zone_epoch,before.entered_order):
            raise ResolutionError('Original pending draw-cast left its accepted physical residence')
    actual=SourceAllocationFact.capture(r.state,entity);old_card=entity.card_id
    definition=r.registry.card(BANANA)
    if definition.kind!=CardType.SPELL or not definition.hand_playable:raise ResolutionError('Missing real playable Bananas definition')
    reset_stored_entity(r,entity,definition)
    entry_id=row.hand_entry_id;overflow=None
    if row.outcome=='cast':
        if len(r.player(row.player_id).hand)<hand_capacity(r.player(row.player_id),r.rules):
            r.move(entity,Zone.HAND,hand_entry_reason='draw',hand_entry_source_id=row.source_id);entry_id=entity.hand_entry_id
        else:
            entry_id=None;overflow=SourceAllocationFact.capture(r.state,entity)
            r.move(entity,Zone.GRAVEYARD)
    value=DrawTransformation(row.id,request.source,request.event,request.accepted_action,actual,
        SourceAllocationFact.capture(r.state,entity),entry_id,r.state.turn,r.state.action_number)
    row=update(r.state,row,transformation=value,hand_entry_id=entry_id)
    validate_draw_links(r.state,r.registry,row)
    r.emit(EVENT,source_id=request.source.entity_id,target_id=entity.id,player_id=row.player_id,
        **{KEY:json.dumps(payload(value),sort_keys=True,separators=(',',':'))},_capture=False)
    if row.outcome=='cast'and entity.zone==Zone.HAND and row.observer is not None:
        from .deathrattle_memory import remember_draw
        remember_draw(r,row.observer,row.id,entity)
    announce_stored_transform(r,entity,old_card,source_id=request.source.entity_id)
    if row.outcome=='cast':
        if entity.zone==Zone.HAND:publish(r,entry_id)
        else:
            from .zones import emit_burn
            emit_burn(r,entity,profile='graveyard_delivery_overflow',original=overflow,
                source_id=request.source.entity_id,player_id=row.player_id,reason='draw_conversion_hand_full')
    return ()


def validate_boundary(game):
    from .draw_casts import draw_record
    from .hero_health_history import effective_events
    events=effective_events(game.events);draws=set();transformed=set()
    for event in events:
        data=dict(event.data)
        if event.kind=='card_drawn':
            row=draw_record(game._state,data.get('draw_id'))
            if (row.id in draws or row.outcome not in('hand','cast')or
                    (event.source_id,event.target_id,event.player_id,event.action)!=(row.source_id,row.entity_id,row.player_id,row.action)):
                raise ValueError('Physical draw lost its original event or was published twice')
            if row.outcome=='hand'and data.get(HAND_ENTRY_KEY)!=row.hand_entry_id:
                raise ValueError('Physical draw event lost its exact original hand entry')
            if row.outcome=='cast'and HAND_ENTRY_KEY in data:raise ValueError('Accepted draw-cast cannot claim an initial hand entry')
            if row.observer is not None:
                if type(data.get(OBSERVER_KEY))is not str or observer_from_dict(json.loads(data[OBSERVER_KEY]))!=row.observer:
                    raise ValueError('Original native draw observer lost its private acceptance proof')
            elif OBSERVER_KEY in data:raise ValueError('Ordinary draw borrowed a native observer')
            draws.add(row.id)
        if event.kind==EVENT:
            if set(data)!={KEY}or type(data[KEY])is not str:raise ValueError('Draw transformation requires its complete private receipt')
            value=transformation_from_dict(json.loads(data[KEY]));validate_transformation(game._state,game.registry,value)
            if (value.draw_id in transformed or(event.source_id,event.target_id,event.player_id,event.action)!=
                    (value.source.entity_id,value.after.entity_id,value.after.controller,value.action)):
                raise ValueError('Draw transformation lost its unique actual commit event')
            validate_events(value.draw_event,value.source,value.accepted_action,events);transformed.add(value.draw_id)
    expected={r.id for r in game._state.draw_history if r.outcome in('hand','cast')}
    if draws!=expected:raise ValueError('Accepted successful draws and physical event proofs disagree')
    if transformed!={r.id for r in game._state.draw_history if r.transformation is not None}:
        raise ValueError('Draw transformations and actual private commits disagree')


def register(mechanics):
    mechanics.register_payload_type(DrawTransformation)
    mechanics.register(TransformDrawnCard,transform)
