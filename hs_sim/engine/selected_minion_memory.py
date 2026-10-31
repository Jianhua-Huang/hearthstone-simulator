"""Original Battlecry minion subjects retained by their native Deathrattle.

Selection is remembered before ordinary control publication. Copying, movement,
summoning, control and death execution remain owned by the existing writers.
"""
from dataclasses import dataclass,replace
from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .board_presence import resolve_board_presence
from .battlecries import battlecry_record
from .copy_materials import CopyEntryMaterial,from_dict as copy_from_dict,validate_scope
from .effects import Effect,Silence,_integer,_source
from .model import BoardPresenceReference,CardType,NativeDeathrattleSpec,Zone
from .sacrifice import MinionReference,live_minion,reference_value

KINDS=('selected_copy','control_return')


@dataclass(frozen=True)
class RememberedMinionSubject:
    kind:str
    battlecry_id:int
    source:SourceAllocationFact
    target:SourceAllocationFact
    presence:BoardPresenceReference
    turn:int
    action:int
    copy:CopyEntryMaterial|None=None

    def __post_init__(self):
        if self.kind not in KINDS:raise ValueError('Unknown native selected-minion role')
        _integer(self.battlecry_id,'original selected-minion Battlecry',1)
        _integer(self.turn,'selected-minion turn',1);_integer(self.action,'selected-minion action',0)
        for value in(self.source,self.target):
            if type(value)is not SourceAllocationFact:raise ValueError('Selected subject requires complete original allocations')
            value.__post_init__()
            if(value.kind,value.zone)!=(CardType.MINION,Zone.BOARD):raise ValueError('Selected subject requires original board minions')
        if(self.source.entity_id==self.target.entity_id or
                (self.source.next_entity_id,self.source.next_order)!=(self.target.next_entity_id,self.target.next_order)):
            raise ValueError('Selected source/target must share one original distinct physical window')
        if type(self.presence)is not BoardPresenceReference:raise ValueError('Selected subject requires its original residence')
        self.presence.__post_init__()
        if self.presence.entity_id!=self.target.entity_id or self.presence.presence_id>=self.target.next_order:
            raise ValueError('Selected subject borrowed another or future residence')
        if self.kind=='selected_copy':
            if(type(self.copy)is not CopyEntryMaterial or self.copy.profile!='remembered_copy' or self.copy.mode!='base' or
                    self.copy.origin!=self.target or (self.copy.captured_turn,self.copy.captured_action)!=(self.turn,self.action)or
                    self.copy.stats is not None or self.copy.on_summon is not None or self.copy.minion_grant is not None):
                raise ValueError('Selected copy requires its one original plain printed physical recipe')
            self.copy.__post_init__()
        elif self.copy is not None:raise ValueError('Control return cannot borrow copy material')


def subject_from_dict(value):
    from .serialization import _row
    row=_row(value,RememberedMinionSubject)
    for key in('source','target'):row[key]=allocation_from_dict(row[key])
    row['presence']=BoardPresenceReference(**_row(row['presence'],BoardPresenceReference))
    if row['copy']is not None:row['copy']=copy_from_dict(CopyEntryMaterial,row['copy'])
    return RememberedMinionSubject(**row)


def validate_subject(state,registry,subject,*,closed=False):
    if type(subject)is not RememberedMinionSubject:raise ValueError('Expected original typed selected-minion subject')
    subject.__post_init__()
    for value in(subject.source,subject.target):validate_allocation(state,registry,value,closed=closed)
    if subject.turn>state.turn or subject.action>state.action_number:raise ValueError('Future selected-minion window')
    spec=registry.card(subject.source.card_id).native_deathrattle
    if spec!=NativeDeathrattleSpec(subject.kind):raise ValueError('Selected subject lost its original native declaration')
    if not closed:
        row=battlecry_record(state,subject.battlecry_id)
        if(row.source_id!=subject.source.entity_id or row.card_id!=subject.source.card_id or
                row.target_id!=subject.target.entity_id or not row.payload_started or row.failure is not None or
                row.player_id==subject.target.controller or row.turn!=subject.turn or not row.action<=subject.action):
            raise ValueError('Selected subject borrowed another actual Battlecry source, target or window')
    if subject.copy is not None:validate_scope(state,registry,subject.copy,closed=closed)


@dataclass(frozen=True)
class RememberBattlecryMinion(Effect):
    source:MinionReference
    target:MinionReference
    battlecry_id:int

    def __post_init__(self):
        reference_value(self.source);reference_value(self.target)
        _integer(self.battlecry_id,'original subject Battlecry',1)
        if self.source.entity_id==self.target.entity_id:raise ValueError('Native selection requires another minion')

    def validate_in_state(self,state,registry):
        self.__post_init__();row=battlecry_record(state,self.battlecry_id)
        if(row.source_id,row.card_id,row.target_id)!=(self.source.entity_id,self.source.card_id,self.target.entity_id)or not row.payload_started or row.completed or row.interrupted or row.failure is not None:
            raise ValueError('Remembered selection requires its actual active original Battlecry')
        spec=registry.card(row.card_id).native_deathrattle
        if spec is None or spec.kind not in KINDS or self.target.player_id==row.player_id:
            raise ValueError('Remembered selection changed its native role or original enemy target')
        for ref in(self.source,self.target):
            entity=state.entities.get(ref.entity_id)
            if entity is None or ref.zone_epoch>entity.zone_epoch or ref.entered_order>=state.next_order:
                raise ValueError('Remembered selection borrowed an unknown or future minion')
        return row,spec


def remember(r,effect):
    row,spec=effect.validate_in_state(r.state,r.registry)
    target=live_minion(r.state,effect.target)
    if target is None:return ()
    source=live_minion(r.state,effect.source)
    if source is not None:
        from .lifecycle import active_abilities
        ids={a.id for a in active_abilities(source,'deathrattle')if a.deathrattle_memory is not None and a.deathrattle_memory.spec==spec
            and a.deathrattle_card_id==row.card_id and a.deathrattle_inherited_from is None and a.deathrattle_copied_from is None}
        if ids:
            material=CopyEntryMaterial.capture(r.state,target,'remembered_copy','base',registry=r.registry)if spec.kind=='selected_copy'else None
            subject=RememberedMinionSubject(spec.kind,row.id,SourceAllocationFact.capture(r.state,source),
                SourceAllocationFact.capture(r.state,target),BoardPresenceReference.capture(r.state,target.id),
                r.state.turn,r.state.action_number,material)
            validate_subject(r.state,r.registry,subject)
            updated=[]
            for ability in source.abilities:
                if ability.id in ids:
                    memory=ability.deathrattle_memory
                    if any(x.battlecry_id==row.id for x in memory.selected_subjects):raise ValueError('Original Battlecry subject cannot be remembered twice')
                    ability=replace(ability,deathrattle_memory=replace(memory,selected_subjects=(*memory.selected_subjects,subject)))
                updated.append(ability)
            source.abilities=updated
    if spec.kind=='control_return':
        from .cross_zone import TakeCapturedMinion
        return(TakeCapturedMinion(effect.target,row.player_id,effect.source.entity_id),)
    return ()


def validate_copy_request(state,registry,request,material,*,closed=False):
    if request.player_id!=request.cause.player_id or request.cause.origin!='card_effect':
        raise ValueError('Remembered base summon requires its original Deathrattle recipient')
    if closed:return
    for row in state.deathrattle_history:
        capture=row.capture;memory=capture.ability.deathrattle_memory
        if(row.execution_order is None or capture.carrier_id!=request.cause.source.entity_id or
                capture.player_id!=request.player_id or capture.kind!=request.cause.source.kind or
                capture.turn>request.cause.turn or capture.action>request.cause.action or
                memory is None or memory.spec.kind!='selected_copy'):
            continue
        for subject in memory.selected_subjects:
            if subject.copy==material:
                validate_subject(state,registry,subject);return
    raise ValueError('Remembered base summon lost its actual original Deathrattle and selected recipe')


@dataclass(frozen=True)
class ReturnRememberedMinion(Effect):
    deathrattle_id:int
    index:int

    def __post_init__(self):
        _integer(self.deathrattle_id,'actual return Deathrattle',1);_integer(self.index,'original selected subject index',0)

    def validate_in_state(self,state,registry):
        from .deathrattles import record
        self.__post_init__();row=record(state,self.deathrattle_id);memory=row.capture.ability.deathrattle_memory
        if row.execution_order is None or row.completed or row.interrupted or memory is None or memory.spec.kind!='control_return'or self.index>=len(memory.selected_subjects):
            raise ValueError('Control return lost its actual active original Deathrattle memory')
        subject=memory.selected_subjects[self.index];validate_subject(state,registry,subject)
        return row,subject


def return_subject(r,effect):
    row,subject=effect.validate_in_state(r.state,r.registry)
    entity=resolve_board_presence(r.state,subject.presence)
    if entity is None:
        r.emit('zone_target_skipped',target_id=subject.target.entity_id,reason='original_control_subject_departed')
        return ()
    if entity.doomed or entity.health<=0 or entity.controller==subject.target.controller:return ()
    from .resolver import return_present_control
    kind,data=return_present_control(r,entity,subject.target.controller,row.capture.carrier_id,
        board_full_reason='native_selected_control_return_board_full')
    if kind=='control_changed':r.refresh_auras(rebind_frozen_ids=(entity.id,))
    r.emit(kind,**data)
    return ()


@dataclass(frozen=True)
class SilenceCapturedMinion(Effect):
    target:MinionReference
    source_id:int|None=None

    def __post_init__(self):reference_value(self.target);_source(self.source_id)

    def validate_in_state(self,state,registry):
        self.__post_init__();entity=state.entities.get(self.target.entity_id)
        if entity is None or self.target.zone_epoch>entity.zone_epoch or self.target.entered_order>=state.next_order:
            raise ValueError('Captured silence borrowed an unknown or future minion')
        if self.source_id is not None and self.source_id not in state.entities:raise ValueError('Unknown captured silence source')


def silence_captured(r,effect):
    effect.validate_in_state(r.state,r.registry)
    if live_minion(r.state,effect.target)is None:
        r.stale(effect,effect.target.entity_id);return ()
    from .resolver import silence
    silence(r,Silence(effect.target.entity_id))
    return ()


def register(mechanics):
    for typ,handler in((RememberBattlecryMinion,remember),(ReturnRememberedMinion,return_subject),(SilenceCapturedMinion,silence_captured)):
        mechanics.register(typ,handler)
    mechanics.register_payload_type(RememberedMinionSubject)
