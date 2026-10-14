"""Immutable ordinary minion copy recipes shared by quantity deliveries.

Local bases/attachments are frozen before the first body. Derived aura caches
and later source mutations are not material. Existing board/stored lifecycle
recipes remain distinct; printed self-source rebinding is an explicit local
copy policy pending CN calibration.
"""
from dataclasses import dataclass,fields,is_dataclass,replace

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import _integer
from .model import AbilityInstance,CardType,Enchantment,Entity,HandLifetime,SummonStats,Zone,ChooseBranchSelection,validate_summon_stats


@dataclass(frozen=True)
class CopyLocalState:
    base_attack:int
    base_health:int
    base_cost:int
    damage:int
    corpse_value:int
    silenced:bool
    frozen:bool
    herald_rank:int|None
    hand_lifetime:HandLifetime|None
    enchantments:tuple[Enchantment,...]
    abilities:tuple[AbilityInstance,...]
    choose_branch:ChooseBranchSelection|None=None

    def __post_init__(self):
        for n in ('base_attack','base_health','base_cost','damage','corpse_value'):_integer(getattr(self,n),'copy local '+n,0)
        if type(self.silenced)is not bool or type(self.frozen)is not bool:raise ValueError('Typed original copy flags required')
        if self.herald_rank is not None:_integer(self.herald_rank,'original copied herald rank',0)
        if self.hand_lifetime is not None:
            if type(self.hand_lifetime)is not HandLifetime:raise ValueError('Typed original temporary lifetime required')
            self.hand_lifetime.__post_init__()
        if self.choose_branch is not None:
            if type(self.choose_branch) is not ChooseBranchSelection: raise ValueError('Copy preselection requires its typed physical recipe')
            self.choose_branch.__post_init__()
        for values,kind in ((self.enchantments,Enchantment),(self.abilities,AbilityInstance)):
            if type(values)is not tuple or any(type(x)is not kind for x in values):raise ValueError('Complete ordered local copy attachments required')
            for x in values:x.__post_init__()
        ids=[x.id for x in (*self.enchantments,*self.abilities)]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate original copied attachment identity')

    @classmethod
    def capture(cls,entity):
        return cls(entity.base_attack,entity.base_health,entity.base_cost,entity.damage,entity.corpse_value,
            entity.silenced,entity.frozen,entity.herald_rank,entity.hand_lifetime,
            tuple(entity.enchantments),tuple(entity.abilities),entity.choose_branch)


@dataclass(frozen=True)
class CopyEntryMaterial:
    card_id:str
    origin:SourceAllocationFact
    profile:str
    mode:str
    captured_turn:int
    captured_action:int
    next_attachment_id:int
    local:CopyLocalState|None=None
    stats:SummonStats|None=None
    entry_herald_count:int|None=None
    jade_size:int|None=None
    discard:object|None=None
    dormant_entry:bool=False

    def __post_init__(self):
        if type(self.dormant_entry) is not bool:
            raise ValueError('Copied dormancy entry requires bool')
        if self.dormant_entry and (self.profile != 'board_copy' or self.mode != 'current'):
            raise ValueError('Dormant entry belongs to a current board copy')
        if type(self.card_id)is not str or not self.card_id:raise ValueError('Copy material requires a card')
        if type(self.origin)is not SourceAllocationFact:raise ValueError('Copy material requires original physical allocation')
        self.origin.__post_init__()
        if self.origin.card_id!=self.card_id or self.origin.kind!=CardType.MINION:raise ValueError('Copy material differs from its physical minion face')
        if self.profile not in ('board_copy','stored_copy','discard_copy')or self.mode not in ('current','base'):raise ValueError('Unknown ordinary minion copy recipe')
        zones=(Zone.BOARD,)if self.profile=='board_copy'else(Zone.GRAVEYARD,)if self.profile=='discard_copy'else(Zone.HAND,Zone.DECK)
        if self.origin.zone not in zones:raise ValueError('Copy recipe has another original zone')
        for n,floor in (('captured_turn',1),('captured_action',0),('next_attachment_id',1)):_integer(getattr(self,n),'copy material '+n,floor)
        if (self.mode=='current')!=(self.local is not None):raise ValueError('Copy local state differs from current/base recipe')
        if self.local is not None:
            if type(self.local)is not CopyLocalState:raise ValueError('Typed original local copy state required')
            self.local.__post_init__()
            for x in (*self.local.enchantments,*self.local.abilities):
                if x.id>=self.next_attachment_id or x.source_id is not None and x.source_id>=self.origin.next_entity_id:
                    raise ValueError('Future copied attachment or source identity')
        if self.profile=='discard_copy':
            from .discard_history import material_value
            material_value(self.discard)
            row=self.discard
            if (self.mode!='current' or self.stats is not None or self.local.hand_lifetime is not None or
                    (self.captured_turn,self.captured_action)!=(row.turn,row.action) or
                    (self.origin.entity_id,self.origin.card_id,self.origin.kind,self.origin.owner,self.origin.controller,self.origin.zone_epoch)!=
                    (row.entity_id,row.card_id,row.kind,row.card.owner,row.player_id,row.card.zone_epoch+1)):
                raise ValueError('Discard copy lost its original accepted material and acquisition cleanup')
        elif self.discard is not None:
            raise ValueError('Only original discard copies carry a successful discard fact')
        validate_summon_stats(self.stats)
        if self.jade_size is not None:
            from .jade import size_value
            size_value(self.jade_size)
        if self.entry_herald_count is not None:
            _integer(self.entry_herald_count,'captured stored entry herald count',0)
            if self.profile not in ('stored_copy','discard_copy')or self.mode!='current'or self.local.herald_rank is not None:raise ValueError('Deferred entry strength requires an uninitialized stored current copy')

    @classmethod
    def capture(cls,state,source,profile,mode,stats=None,*,registry=None,player_id=None,discard=None):
        if source.components:raise ValueError('Composite copy material is unsupported by this ordinary profile')
        if profile=='discard_copy':
            from .discard_history import validate_material as validate_discard
            if registry is None:raise ValueError('Discard capture requires its original registry')
            validate_discard(state,registry,discard)
            if source is not state.entities[discard.entity_id] or player_id!=discard.player_id:
                raise ValueError('Discard copy capture lost its original physical source and recipient')
        entry_count=None
        if registry is not None and mode=='current'and profile in ('stored_copy','discard_copy')and source.herald_rank is None and registry.card(source.card_id).herald_scaling:
            from .herald import herald_count
            entry_count=herald_count(state,player_id)
        local=CopyLocalState.capture(source)if mode=='current'else None
        if profile=='discard_copy'and local is not None:local=replace(local,hand_lifetime=None)
        result=cls(source.card_id,SourceAllocationFact.capture(state,source),profile,mode,state.turn,state.action_number,
            state.next_attachment_id,local,stats,entry_count,source.jade_size,discard,
            source.dormancy is not None and profile == 'board_copy' and mode == 'current')
        if profile=='discard_copy':validate_scope(state,registry,result,hand_copy=True)
        return result


def validate_material(registry,material,*,hand_copy=False):
    from .summon_quantities import SummonEntryMaterial,validate_material as validate_plain_material
    material.__post_init__();validate_plain_material(registry,SummonEntryMaterial(material.card_id))
    if material.dormant_entry and registry.card(material.card_id).dormant_turns == 0:
        raise ValueError('Dormant copy requires its printed entry dormancy')
    if material.profile=='discard_copy'and not hand_copy:
        raise ValueError('Discard copy material only supports its own hand delivery')
    from .jade import family_for
    family = family_for(registry, material.card_id)
    if (family is None) != (material.jade_size is None) or family is not None and family.card_for(material.jade_size) != material.card_id:
        raise ValueError('Copy material lost its original innate Jade size')
    if family is not None and material.local is not None and (
            material.local.base_attack, material.local.base_health, material.local.base_cost) != (
            material.jade_size, material.jade_size, min(10, material.jade_size)):
        raise ValueError('Copied Jade base differs from its frozen innate size')
    needs_entry_rank=material.mode=='current'and material.profile in ('stored_copy','discard_copy')and material.local.herald_rank is None and registry.card(material.card_id).herald_scaling
    if needs_entry_rank!=(material.entry_herald_count is not None):raise ValueError('Stored copy lost its captured deferred entry strength')
    if material.local is not None:
        from .cthun import is_cthun
        if any(a.cthun_ritual is not None for a in (*material.local.enchantments, *material.local.abilities)) and not is_cthun(registry, material.card_id):
            raise ValueError('Frozen ritual increments require their original Cthun face')
        if material.local.choose_branch is not None:
            from .choose_branch_state import validate_selection
            validate_selection(registry, material.local.choose_branch, card_id=material.card_id)
        # Nested payloads carry declaration/upgrade cards and behavior references;
        # AbilityInstance itself has several explicit provenance fields, no card_id.
        def registered_references(value):
            if is_dataclass(value):
                for field in fields(value):
                    child=getattr(value,field.name)
                    if child is not None and type(child)is str:
                        if field.name=='behavior_id':registry.behavior(child)
                        elif field.name=='card_id'or field.name.endswith('_card_id'):registry.card(child)
                    elif is_dataclass(child)or type(child)in(tuple,list):registered_references(child)
            elif type(value)in(tuple,list):
                for child in value:registered_references(child)
        registered_references(material.local.abilities)
        for a in material.local.abilities:
            if a.kind=='summon_quantity'and a.origin=='printed'and(a.source_id!=material.origin.entity_id or a.summon_quantity not in registry.card(material.card_id).summon_quantities):
                raise ValueError('Original copied quantity row differs from registered printed source')


def validate_scope(state,registry,material,*,closed=False,hand_copy=False):
    validate_material(registry,material,hand_copy=hand_copy);validate_allocation(state,registry,material.origin,closed=closed)
    if material.local is not None:
        from .cthun import validate_stamp
        for attachment in (*material.local.enchantments, *material.local.abilities):
            validate_stamp(state, registry, attachment)
    if material.captured_turn>state.turn or material.captured_action>state.action_number or material.next_attachment_id>state.next_attachment_id:
        raise ValueError('Future physical copy acceptance facts')


def validate_effect_scope(state,registry,effect):
    from .summon_quantities import validate_cause
    validate_cause(state,registry,effect.cause)
    if hasattr(effect,'target_id'):
        if effect.target_id>=state.next_entity_id:raise ValueError('Queued attributed copy has a future physical target')
    else:
        effect.card.__post_init__();registry.card(effect.card.card_id)
        if effect.card.entity_id>=state.next_entity_id:raise ValueError('Queued stored copy has a future physical reference')


def accept_copy(r,effect,source,profile):
    from .summon_quantities import SummonByCard,DeliverCardSummon,FinishCardSummon,accept,deliver
    validate_effect_scope(r.state,r.registry,effect)
    material=CopyEntryMaterial.capture(r.state,source,profile,effect.mode,getattr(effect,'stats',None),registry=r.registry,player_id=effect.player_id)
    request=SummonByCard(effect.player_id,(material,),effect.cause,position=effect.position)
    accept(r,request);root=r.state.card_summon_history[-1]
    # First actual body remains inside the original Copy effect checkpoint.
    return (*deliver(r,DeliverCardSummon(root.id,0)),FinishCardSummon(root.id))


def apply(r,material,entity):
    entity.origin_entity_id=material.origin.entity_id
    if material.jade_size is not None:
        from .jade import imprint
        imprint(entity, material.jade_size)
    if material.mode=='current':
        local=material.local
        if material.profile=='board_copy' and not material.dormant_entry:entity.dormancy=None
        entity.base_attack,entity.base_health,entity.base_cost=local.base_attack,local.base_health,local.base_cost
        entity.damage,entity.corpse_value=local.damage,local.corpse_value
        source=Entity(material.origin.entity_id,material.card_id,material.origin.owner,material.origin.controller,material.origin.zone,
            herald_rank=local.herald_rank,enchantments=list(local.enchantments),abilities=list(local.abilities),
            silenced=local.silenced,hand_lifetime=local.hand_lifetime,choose_branch=local.choose_branch,jade_size=material.jade_size)
        from .lifecycle import copy_attachments
        copy_attachments(r.state,source,entity,rebind_printed=True)
        if material.entry_herald_count is not None:
            from .herald import initialize_instance
            initialize_instance(r.state,entity,r.registry.card(material.card_id),count=material.entry_herald_count)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state,entity,material.stats)
    r.refresh_auras()
    if material.mode=='current'and material.profile=='board_copy'and material.local.frozen:
        from .combat import can_be_frozen,freeze_deadline
        if can_be_frozen(entity):
            entity.frozen_until_owner_turn=freeze_deadline(r.state,entity,ending_turn=r.ending_turn,registry=r.registry)


def enter(r,material,entity):
    from .colossal import enter_minion
    return enter_minion(r,entity,'copy',origin_id=material.origin.entity_id,copy_mode=material.mode)


def from_dict(cls,value):
    from .serialization import _row,_ability_from_dict,_enchantment_from_dict
    row=_row(value,cls)
    if cls is CopyLocalState:
        if row['choose_branch'] is not None:
            from .choose_branch_state import selection_from_dict
            row['choose_branch'] = selection_from_dict(row['choose_branch'])
        row['hand_lifetime']=None if row['hand_lifetime']is None else HandLifetime(**_row(row['hand_lifetime'],HandLifetime))
        row['enchantments']=tuple(_enchantment_from_dict(x)for x in row['enchantments'])
        row['abilities']=tuple(_ability_from_dict(x)for x in row['abilities'])
    elif cls is CopyEntryMaterial:
        row['origin']=allocation_from_dict(row['origin'])
        row['local']=None if row['local']is None else from_dict(CopyLocalState,row['local'])
        row['stats']=None if row['stats']is None else SummonStats(**_row(row['stats'],SummonStats))
        if row['discard'] is not None:
            from .discard_history import DiscardRecord
            row['discard']=dict(_row(row['discard'],DiscardRecord))
            row['discard']['card']=allocation_from_dict(row['discard']['card'])
            row['discard']['source']=allocation_from_dict(row['discard']['source'])
            row['discard']=DiscardRecord(**row['discard'])
    return cls(**row)


def register(mechanics):
    mechanics.register_payload_type(CopyLocalState);mechanics.register_payload_type(CopyEntryMaterial)
