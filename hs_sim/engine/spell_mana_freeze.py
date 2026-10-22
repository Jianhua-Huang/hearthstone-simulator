"""Native conditional Freeze, driven by original committed spell-Mana facts.

The ordinary Freeze bit, payment executors and thaw notifications remain shared.
Private receipts prove local consistency, not authentication of unsigned saves.
"""
from dataclasses import dataclass, fields, replace

from .model import CardType, Zone, _int, _name

BIRTH='spell_mana_freeze_entered'
PROGRESS='spell_mana_freeze_progress'
RELEASE='spell_mana_freeze_released'


@dataclass(frozen=True)
class SpellManaFreezeProfile:
    card_id:str
    amount:int=15

    def __post_init__(self):
        _name(self.card_id,'native spell-Mana Freeze card');_int(self.amount,'native spell-Mana Freeze budget',1)


@dataclass(frozen=True)
class SpellManaFreezeStep:
    kind:str
    record_id:int
    controller:int
    amount:int

    def __post_init__(self):
        if self.kind not in ('play','consume'):raise ValueError('Unknown conditional Freeze payment source')
        _int(self.record_id,'conditional Freeze original payment',1)
        if type(self.controller)is not int or self.controller not in (1,2):raise ValueError('Unknown conditional Freeze controller')
        _int(self.amount,'conditional Freeze credited Mana',0)


@dataclass(frozen=True)
class SpellManaFreezeState:
    id:int
    entity_id:int
    card_id:str
    presence_id:int
    start_play_id:int
    start_consumption_id:int
    controller_at_entry:int
    amount:int
    steps:tuple[SpellManaFreezeStep,...]=()
    released_reason:str|None=None

    @property
    def origin(self):return (self.id,self.entity_id,self.card_id,self.presence_id,self.start_play_id,
        self.start_consumption_id,self.controller_at_entry,self.amount)

    @property
    def remaining(self):return max(0,self.amount-sum(x.amount for x in self.steps))

    def __post_init__(self):
        for key in ('id','entity_id','presence_id','start_play_id','start_consumption_id','amount'):
            _int(getattr(self,key),'conditional Freeze '+key,1)
        _name(self.card_id,'conditional Freeze printed card')
        if type(self.controller_at_entry)is not int or self.controller_at_entry not in (1,2):raise ValueError('Unknown original Freeze controller')
        if type(self.steps)is not tuple:raise ValueError('Conditional Freeze requires immutable payment steps')
        next_ids={'play':self.start_play_id,'consume':self.start_consumption_id}
        total=0
        for step in self.steps:
            if type(step)is not SpellManaFreezeStep:raise ValueError('Conditional Freeze lost a typed payment step')
            step.__post_init__()
            if step.record_id!=next_ids[step.kind] or total>=self.amount:raise ValueError('Conditional Freeze omitted, repeated or continued a closed payment prefix')
            next_ids[step.kind]+=1;total+=step.amount
        if self.released_reason not in (None,'mana','silence','unfreeze','cannot_be_frozen'):raise ValueError('Unknown conditional Freeze release')
        if (self.released_reason=='mana')!=(total>=self.amount):raise ValueError('Conditional Freeze release disagrees with original credited Mana')


def validate_profile(registry,profile):
    if type(profile)is not SpellManaFreezeProfile:raise ValueError('Expected native spell-Mana Freeze profile')
    profile.__post_init__();card=registry.card(profile.card_id)
    if card.kind!=CardType.MINION or card.choice_only or card.starship_for:
        raise ValueError('Conditional Freeze requires its native physical minion')


def locked(entity):
    value=entity.spell_mana_freeze
    return value is not None and value.released_reason is None


def initialize(state,registry,entity):
    entity.spell_mana_freeze=None
    profile=registry.spell_mana_freeze_profiles.get(entity.card_id)
    if profile is None or entity.zone!=Zone.BOARD or entity.kind!=CardType.MINION:return
    from .lifecycle import attachment_id
    from .combat import freeze_deadline
    entity.spell_mana_freeze=SpellManaFreezeState(attachment_id(state),entity.id,entity.card_id,
        entity.board_presence_id,len(state.play_history)+1,len(state.mana_consumption_history)+1,
        entity.controller,profile.amount)
    entity.frozen_until_owner_turn=freeze_deadline(state,entity,registry=registry)


def publish_birth(r,entity):
    value=entity.spell_mana_freeze
    if value is not None:
        r.emit(BIRTH,source_id=entity.id,target_id=entity.id,player_id=entity.controller,
            origin=value.origin,_capture=False)


def amount_for(record,kind,controller):
    if kind=='play':
        from .player_spell_mana_costs import row_for
        return row_for(record).mana_for(controller)
    return record.mana_for(controller)


def note_payment(state,record,kind):
    for entity in state.entities.values():
        if entity.zone!=Zone.BOARD or not locked(entity):continue
        value=entity.spell_mana_freeze
        step=SpellManaFreezeStep(kind,record.id,entity.controller,amount_for(record,kind,entity.controller))
        steps=(*value.steps,step)
        released=sum(x.amount for x in steps)>=value.amount
        entity.spell_mana_freeze=replace(value,steps=steps,released_reason='mana'if released else None)
        if released:entity.frozen_until_owner_turn=None


def publish_progress(r,record,kind):
    updates=[e for e in r.state.entities.values()if e.spell_mana_freeze is not None and
        e.spell_mana_freeze.steps and (e.spell_mana_freeze.steps[-1].kind,e.spell_mana_freeze.steps[-1].record_id)==(kind,record.id)]
    if not updates:return
    from .remaining_mana_numbers import payment_window
    from contextlib import nullcontext
    with payment_window(r,record.source_id) if record.source_id is not None else nullcontext():
        if any(e.spell_mana_freeze.released_reason=='mana'for e in updates):r.refresh_auras()
        for entity in updates:
            value=entity.spell_mana_freeze;step=value.steps[-1]
            r.emit(PROGRESS,source_id=record.source_id,target_id=entity.id,player_id=record.player_id,
                origin=value.origin,step=(step.kind,step.record_id,step.controller,step.amount),_capture=False)
            if value.released_reason=='mana':
                r.emit(RELEASE,source_id=entity.id,target_id=entity.id,player_id=entity.controller,
                    origin=value.origin,reason='mana',_capture=False)
                r.emit('unfrozen',target_id=entity.id,reason='spell_mana')


def release(r,entity,reason):
    if not locked(entity):return
    value=entity.spell_mana_freeze
    entity.spell_mana_freeze=replace(value,released_reason=reason)
    r.emit(RELEASE,source_id=entity.id,target_id=entity.id,player_id=entity.controller,
        origin=value.origin,reason=reason,_capture=False)


def synchronize(r):
    from .combat import can_be_frozen
    for entity in r.state.entities.values():
        if not locked(entity):continue
        if entity.silenced:release(r,entity,'silence')
        elif not can_be_frozen(entity):release(r,entity,'cannot_be_frozen')


def from_dict(value):
    if value is None:return None
    if type(value)is not dict or set(value)!={f.name for f in fields(SpellManaFreezeState)}:
        raise ValueError('Conditional Freeze requires its complete saved fields')
    row=dict(value);steps=row['steps']
    if type(steps)is not list:raise ValueError('Conditional Freeze payments must be an array')
    expected={f.name for f in fields(SpellManaFreezeStep)}
    if any(type(x)is not dict or set(x)!=expected for x in steps):raise ValueError('Conditional Freeze step fields changed')
    row['steps']=tuple(SpellManaFreezeStep(**x)for x in steps)
    result=SpellManaFreezeState(**row);result.__post_init__();return result


def validate_step(state,step):
    step.__post_init__()
    rows=state.play_history if step.kind=='play'else state.mana_consumption_history
    if step.record_id>len(rows) or step.amount!=amount_for(rows[step.record_id-1],step.kind,step.controller):
        raise ValueError('Conditional Freeze changed its original spell-Mana payment')


def validate_state(state,registry):
    used=set()
    for entity in state.entities.values():
        value=entity.spell_mana_freeze
        required=entity.zone==Zone.BOARD and entity.kind==CardType.MINION and entity.card_id in registry.spell_mana_freeze_profiles
        if value is None:
            if required:raise ValueError('Native conditional Freeze lost its original in-play binding')
            continue
        if not required or type(value)is not SpellManaFreezeState:raise ValueError('Conditional Freeze escaped its native resident')
        value.__post_init__();profile=registry.spell_mana_freeze_profiles[value.card_id]
        if (value.entity_id,value.card_id,value.presence_id,value.amount)!=(entity.id,entity.card_id,entity.board_presence_id,profile.amount):
            raise ValueError('Conditional Freeze borrowed another printed body or residence')
        if value.id in used or value.id>=state.next_attachment_id:raise ValueError('Conditional Freeze reused or invented an activation')
        used.add(value.id)
        if value.start_play_id>len(state.play_history)+1 or value.start_consumption_id>len(state.mana_consumption_history)+1:
            raise ValueError('Conditional Freeze borrowed a future payment cursor')
        for step in value.steps:validate_step(state,step)
        if locked(entity):
            if not entity.frozen:raise ValueError('Active conditional Freeze lost its ordinary frozen state')
            for kind,start,size in (('play',value.start_play_id,len(state.play_history)),('consume',value.start_consumption_id,len(state.mana_consumption_history))):
                if start+sum(x.kind==kind for x in value.steps)!=size+1:raise ValueError('Conditional Freeze omitted an accepted payment')


def validate_boundary(game):
    from .hero_health_history import effective_events
    state=game._state;births={};steps={};releases={}
    for event in effective_events(game._events):
        if event.kind not in (BIRTH,PROGRESS,RELEASE):continue
        data=dict(event.data);expected={'origin'}|({'step'}if event.kind==PROGRESS else {'reason'}if event.kind==RELEASE else set())
        if set(data)!=expected or type(data['origin'])not in (tuple,list)or len(data['origin'])!=8:
            raise ValueError('Conditional Freeze receipt lost its complete original fields')
        original=SpellManaFreezeState(*data['origin']);original.__post_init__();key=original.origin
        if (original.entity_id not in state.entities or original.id>=state.next_attachment_id or
                original.presence_id>=state.next_order or original.card_id not in game.registry.spell_mana_freeze_profiles):
            raise ValueError('Conditional Freeze receipt borrowed an unknown original source')
        if event.kind==BIRTH:
            if key in births or (event.source_id,event.target_id,event.player_id)!=(original.entity_id,original.entity_id,original.controller_at_entry):
                raise ValueError('Conditional Freeze entry was repeated or rebound')
            births[key]=event.sequence;steps[key]=[]
        elif key not in births or event.sequence<=births[key]:raise ValueError('Conditional Freeze lost its original entry receipt')
        elif event.kind==PROGRESS:
            if key in releases or type(data['step'])not in (tuple,list)or len(data['step'])!=4:raise ValueError('Conditional Freeze payment escaped its original open gate')
            step=SpellManaFreezeStep(*data['step']);validate_step(state,step)
            rows=state.play_history if step.kind=='play'else state.mana_consumption_history;row=rows[step.record_id-1]
            if (event.source_id,event.target_id,event.player_id,event.action)!=(row.source_id,original.entity_id,row.player_id,row.action):
                raise ValueError('Conditional Freeze receipt changed its actual payment envelope')
            steps[key].append(step)
            total=sum(x.amount for x in steps[key]);SpellManaFreezeState(*key,tuple(steps[key]),'mana'if total>=original.amount else None).__post_init__()
        else:
            if key in releases or (event.source_id,event.target_id)!=(original.entity_id,original.entity_id):raise ValueError('Conditional Freeze release was repeated or rebound')
            candidate=SpellManaFreezeState(*key,tuple(steps[key]),data['reason']);candidate.__post_init__();releases[key]=data['reason']
    for entity in state.entities.values():
        value=entity.spell_mana_freeze
        if value is not None and (value.origin not in births or tuple(steps[value.origin])!=value.steps or releases.get(value.origin)!=value.released_reason):
            raise ValueError('Conditional Freeze changed or lost original entry/payment/release witnesses')


def register(mechanics):
    for kind in (SpellManaFreezeProfile,SpellManaFreezeStep,SpellManaFreezeState):mechanics.register_payload_type(kind)
