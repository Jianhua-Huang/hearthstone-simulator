"""Immutable ordinary minion copy recipes shared by quantity deliveries.

Local bases/attachments are frozen before the first body. Derived aura caches
and later source mutations are not material. Existing board/stored lifecycle
recipes remain distinct; printed self-source rebinding is an explicit local
copy policy pending CN calibration.
"""
from dataclasses import dataclass,fields,is_dataclass,replace

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import _integer
from .card_creation import CreatedMinionGrant,validate_minion_grant
from .model import AbilityInstance,CardType,Enchantment,Entity,HandLifetime,HandPreparation,SummonStats,Zone,ChooseBranchSelection,validate_summon_stats


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
class CapturedCardCopyMaterial:
    """Original card material; board minions permit only printed base copies."""
    origin:SourceAllocationFact
    local:CopyLocalState
    components:tuple[str,...]
    durability:int
    galakrond_invocations:int|None
    preparation:HandPreparation|None
    jade_size:int|None
    turn:int
    action:int
    next_attachment_id:int

    def __post_init__(self):
        if type(self.origin)is not SourceAllocationFact or type(self.local)is not CopyLocalState:
            raise ValueError('Captured card copy requires typed original material')
        self.origin.__post_init__();self.local.__post_init__()
        if (self.origin.zone not in(Zone.HAND,Zone.DECK,Zone.GRAVEYARD,Zone.BOARD,Zone.WEAPON)or self.origin.kind not in(
                CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO)or
                self.origin.zone==Zone.BOARD and self.origin.kind!=CardType.MINION or
                self.origin.zone==Zone.WEAPON and self.origin.kind!=CardType.WEAPON):
            raise ValueError('Captured card copy requires an original stored/spent card or board minion')
        if type(self.components)is not tuple or any(type(cid)is not str or not cid for cid in self.components):
            raise ValueError('Captured copy requires ordered component identities')
        for name,floor in(('durability',0),('turn',1),('action',0),('next_attachment_id',1)):
            _integer(getattr(self,name),'captured copy '+name,floor)
        for name in('galakrond_invocations','jade_size'):
            if getattr(self,name)is not None:_integer(getattr(self,name),'captured copy '+name,0)
        if self.preparation is not None:
            if type(self.preparation)is not HandPreparation:raise ValueError('Captured copy preparation must be typed')
            self.preparation.__post_init__()
            if self.preparation.cost_id not in{e.id for e in self.local.enchantments}:
                raise ValueError('Captured preparation lost its original cost attachment')
        for row in(*self.local.enchantments,*self.local.abilities):
            if row.id>=self.next_attachment_id or row.source_id is not None and row.source_id>=self.origin.next_entity_id:
                raise ValueError('Captured copy has a future attachment or source')

    @classmethod
    def capture(cls,state,entity):
        return cls(SourceAllocationFact.capture(state,entity),CopyLocalState.capture(entity),entity.components,
            entity.durability,entity.galakrond_invocations,entity.preparation,entity.jade_size,
            state.turn,state.action_number,state.next_attachment_id)

    def entity(self):
        value=self.local;origin=self.origin
        return Entity(origin.entity_id,origin.card_id,origin.owner,origin.controller,origin.zone,
            kind=origin.kind,zone_epoch=origin.zone_epoch,entered_order=origin.entered_order,
            base_attack=value.base_attack,base_health=value.base_health,base_cost=value.base_cost,
            damage=value.damage,corpse_value=value.corpse_value,herald_rank=value.herald_rank,
            silenced=value.silenced,hand_lifetime=value.hand_lifetime,choose_branch=value.choose_branch,
            enchantments=list(value.enchantments),abilities=list(value.abilities),components=self.components,
            durability=self.durability,galakrond_invocations=self.galakrond_invocations,
            preparation=self.preparation,jade_size=self.jade_size)


def validate_captured_card_copy(state,registry,material):
    if type(material)is not CapturedCardCopyMaterial:raise ValueError('Expected captured card copy material')
    material.__post_init__();validate_allocation(state,registry,material.origin)
    from .native_conditions import validate_carrier as validate_native_condition
    validate_native_condition(registry, material.origin.card_id, material.origin.kind,
        material.local.abilities, material.components)
    from .consumed_cards import validate_payload as validate_consumed_payload
    for ability in material.local.abilities:
        validate_consumed_payload(state,registry,ability)
    if material.turn>state.turn or material.action>state.action_number or material.next_attachment_id>state.next_attachment_id:
        raise ValueError('Captured copy has future acceptance bounds')
    for cid in material.components:registry.card(cid)
    if any(a.deathrattle_memory is not None for a in material.local.abilities):
        from .deathrattle_memory import validate_carrier
        validate_carrier(state,registry,material.origin.card_id,material.origin.kind,material.local.abilities,material.components)
    if material.local.choose_branch is not None:
        from .choose_branch_state import validate_selection
        validate_selection(registry,material.local.choose_branch,card_id=material.origin.card_id)
    from .cthun import validate_stamp
    def references(value):
        if is_dataclass(value):
            for field in fields(value):
                child=getattr(value,field.name)
                if type(child)is str:
                    if field.name=='behavior_id':registry.behavior(child)
                    elif field.name=='card_id'or field.name.endswith('_card_id'):registry.card(child)
                elif is_dataclass(child)or type(child)in(tuple,list):references(child)
        elif type(value)in(tuple,list):
            for child in value:references(child)
    for row in(*material.local.enchantments,*material.local.abilities):
        validate_stamp(state,registry,row)
        if type(row)is Enchantment and row.hand_play_lock is not None:
            from .hand_play_locks import validate_clock
            validate_clock(state,row.hand_play_lock)
    references(material.local.abilities)


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
    on_summon:str|None=None
    minion_grant:CreatedMinionGrant|None=None
    grant_source_id:int|None=None
    stored_components:tuple[str,...]=()

    def __post_init__(self):
        if (type(self.stored_components)is not tuple or any(type(x)is not str or not x for x in self.stored_components)
                or self.stored_components and (self.profile not in ('stored_copy','remembered_copy') or self.mode!='current')):
            raise ValueError('Stored composition requires its current physical minion recipe')
        validate_minion_grant(self.minion_grant)
        if self.minion_grant is None:
            if self.grant_source_id is not None:raise ValueError('Copy grant source requires an actual entry grant')
        else:
            _integer(self.grant_source_id,'copy entry grant source',1)
            if self.profile!='stored_copy' or self.grant_source_id>=self.origin.next_entity_id:
                raise ValueError('Copy entry grant requires its accepted stored copy and original source')
        if self.on_summon is not None:
            from .effects import _behavior
            _behavior(self.on_summon)
            if self.profile != 'board_copy': raise ValueError('Copy followup requires original board-copy material')
        if type(self.dormant_entry) is not bool:
            raise ValueError('Copied dormancy entry requires bool')
        if self.dormant_entry and (self.profile not in ('board_copy','remembered_copy') or self.mode != 'current'):
            raise ValueError('Dormant entry belongs to a current board copy')
        if type(self.card_id)is not str or not self.card_id:raise ValueError('Copy material requires a card')
        if type(self.origin)is not SourceAllocationFact:raise ValueError('Copy material requires original physical allocation')
        self.origin.__post_init__()
        if self.origin.card_id!=self.card_id or self.origin.kind!=CardType.MINION:raise ValueError('Copy material differs from its physical minion face')
        if self.profile not in ('board_copy','stored_copy','discard_copy','discard_summon_copy','remembered_copy')or self.mode not in ('current','base'):raise ValueError('Unknown ordinary minion copy recipe')
        if self.profile=='remembered_copy' and (self.mode!='current' or self.stats is not None):
            raise ValueError('Remembered copy requires its full original current minion recipe')
        zones=(Zone.BOARD,)if self.profile in ('board_copy','remembered_copy')else(Zone.GRAVEYARD,)if self.profile in ('discard_copy','discard_summon_copy')else(Zone.HAND,Zone.DECK)
        if self.origin.zone not in zones:raise ValueError('Copy recipe has another original zone')
        for n,floor in (('captured_turn',1),('captured_action',0),('next_attachment_id',1)):_integer(getattr(self,n),'copy material '+n,floor)
        if (self.mode=='current')!=(self.local is not None):raise ValueError('Copy local state differs from current/base recipe')
        if self.local is not None:
            if type(self.local)is not CopyLocalState:raise ValueError('Typed original local copy state required')
            self.local.__post_init__()
            for x in (*self.local.enchantments,*self.local.abilities):
                if x.id>=self.next_attachment_id or x.source_id is not None and x.source_id>=self.origin.next_entity_id:
                    raise ValueError('Future copied attachment or source identity')
        if self.profile in ('discard_copy','discard_summon_copy'):
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
            if self.profile not in ('stored_copy','discard_copy','discard_summon_copy')or self.mode!='current'or self.local.herald_rank is not None:raise ValueError('Deferred entry strength requires an uninitialized stored current copy')

    @property
    def components(self):
        return self.discard.components if self.profile=='discard_summon_copy' else self.stored_components

    @classmethod
    def capture(cls,state,source,profile,mode,stats=None,*,registry=None,player_id=None,discard=None,on_summon=None,minion_grant=None,grant_source_id=None):
        if source.components and profile!='discard_summon_copy' and not(profile in ('stored_copy','remembered_copy')and mode=='current'):
            raise ValueError('Composite copy material is unsupported by this ordinary profile')
        if profile in ('discard_copy','discard_summon_copy'):
            from .discard_history import validate_material,validate_base_copy
            validate_discard=validate_base_copy if profile=='discard_summon_copy' else validate_material
            if registry is None:raise ValueError('Discard capture requires its original registry')
            validate_discard(state,registry,discard)
            if source is not state.entities[discard.entity_id] or player_id!=discard.player_id:
                raise ValueError('Discard copy capture lost its original physical source and recipient')
        entry_count=None
        if registry is not None and mode=='current'and profile in ('stored_copy','discard_copy','discard_summon_copy')and source.herald_rank is None and registry.card(source.card_id).herald_scaling:
            from .herald import herald_count
            entry_count=herald_count(state,player_id)
        local=CopyLocalState.capture(source)if mode=='current'else None
        if profile in ('discard_copy','discard_summon_copy')and local is not None:local=replace(local,hand_lifetime=None)
        result=cls(source.card_id,SourceAllocationFact.capture(state,source),profile,mode,state.turn,state.action_number,
            state.next_attachment_id,local,stats,entry_count,source.jade_size,discard,
            source.dormancy is not None and profile in ('board_copy','remembered_copy') and mode == 'current')
        if on_summon is not None:result=replace(result,on_summon=on_summon)
        if minion_grant is not None:result=replace(result,minion_grant=minion_grant,grant_source_id=grant_source_id)
        if profile in ('stored_copy','remembered_copy')and mode=='current':result=replace(result,stored_components=source.components)
        if profile in ('discard_copy','discard_summon_copy'):validate_scope(state,registry,result,hand_copy=profile=='discard_copy')
        return result


def validate_material(registry,material,*,hand_copy=False):
    from .summon_quantities import SummonEntryMaterial,validate_material as validate_plain_material
    material.__post_init__()
    if material.profile in ('stored_copy','remembered_copy'):
        card=registry.card(material.card_id)
        if card.kind!=CardType.MINION or not card.hand_playable or card.choice_only or bool(card.starship_for)!=bool(material.components):
            raise ValueError('Stored entry lost its complete physical minion or composition')
        for cid in material.components:
            if registry.card(cid).kind!=CardType.MINION:raise ValueError('Stored composition has a non-minion component')
    elif material.profile=='discard_summon_copy':
        from .discard_history import validate_base_recipe
        validate_base_recipe(registry,material.discard)
        card=registry.card(material.card_id)
        if not card.hand_playable or card.choice_only:
            raise ValueError('Discard summon requires its original physical minion face')
    else:
        # Board copies restore accepted material and delegate native Colossal
        # entry. Stored first/extra entries use the physical branch above.
        validate_plain_material(registry, SummonEntryMaterial(material.card_id),
                                allow_colossal=material.profile=='board_copy')
    if material.on_summon is not None:registry.behavior(material.on_summon)
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
    needs_entry_rank=material.mode=='current'and material.profile in ('stored_copy','discard_copy','discard_summon_copy')and material.local.herald_rank is None and registry.card(material.card_id).herald_scaling
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
    if material.profile=='discard_summon_copy':
        from .discard_history import validate_base_copy
        validate_base_copy(state,registry,material.discard)
    if material.local is not None:
        from .native_conditions import validate_carrier as validate_native_condition
        validate_native_condition(registry, material.card_id, material.origin.kind, material.local.abilities, material.components)
        from .timed_keywords import validate_deadline
        for ability in material.local.abilities:
            if ability.limited_trigger_deadline is not None:
                if ability.limited_trigger_deadline.created_turn > material.captured_turn:
                    raise ValueError('Copied finite start deadline is newer than its original material')
                validate_deadline(state, ability.limited_trigger_deadline)
        if any(a.deathrattle_memory is not None for a in material.local.abilities):
            from .deathrattle_memory import validate_carrier
            validate_carrier(state,registry,material.card_id,material.origin.kind,material.local.abilities,material.components)
        from .cthun import validate_stamp
        for attachment in (*material.local.enchantments, *material.local.abilities):
            validate_stamp(state, registry, attachment)
    if material.captured_turn>state.turn or material.captured_action>state.action_number or material.next_attachment_id>state.next_attachment_id:
        raise ValueError('Future physical copy acceptance facts')


def validate_effect_scope(state,registry,effect):
    from .summon_quantities import validate_cause
    validate_cause(state,registry,effect.cause)
    if getattr(effect,'on_summon',None) is not None:registry.behavior(effect.on_summon)
    if hasattr(effect,'target_id'):
        from .model import BoardPresenceReference
        target=effect.target_id
        if type(target)is BoardPresenceReference:
            effect.validate_in_state(state);target=target.entity_id
        if target>=state.next_entity_id:raise ValueError('Queued attributed copy has a future physical target')
    else:
        effect.card.__post_init__();registry.card(effect.card.card_id)
        if effect.card.entity_id>=state.next_entity_id:raise ValueError('Queued stored copy has a future physical reference')


def accept_copy(r,effect,source,profile):
    from .summon_quantities import SummonByCard,DeliverCardSummon,FinishCardSummon,accept,deliver
    validate_effect_scope(r.state,r.registry,effect)
    grant=getattr(effect,'minion_grant',None)
    material=CopyEntryMaterial.capture(r.state,source,profile,effect.mode,getattr(effect,'stats',None),registry=r.registry,player_id=effect.player_id,on_summon=getattr(effect,'on_summon',None),
        minion_grant=grant,grant_source_id=effect.cause.source.entity_id if grant is not None else None)
    request=SummonByCard(effect.player_id,(material,),effect.cause,position=effect.position)
    accept(r,request);root=r.state.card_summon_history[-1]
    # First actual body remains inside the original Copy effect checkpoint.
    return (*deliver(r,DeliverCardSummon(root.id,0)),FinishCardSummon(root.id))


def apply(r,material,entity):
    entity.origin_entity_id=material.origin.entity_id
    from .held_opponent_copies import copy_origin
    entity.copy_origin=copy_origin(material.origin)
    if material.jade_size is not None:
        from .jade import imprint
        imprint(entity, material.jade_size)
    if material.mode=='current':
        local=material.local
        if material.profile in ('board_copy','remembered_copy') and not material.dormant_entry:entity.dormancy=None
        entity.base_attack,entity.base_health,entity.base_cost=local.base_attack,local.base_health,local.base_cost
        entity.damage,entity.corpse_value=local.damage,local.corpse_value
        source=Entity(material.origin.entity_id,material.card_id,material.origin.owner,material.origin.controller,material.origin.zone,
            herald_rank=local.herald_rank,enchantments=list(local.enchantments),abilities=list(local.abilities),
            silenced=local.silenced,hand_lifetime=local.hand_lifetime,choose_branch=local.choose_branch,jade_size=material.jade_size,
            components=material.components)
        from .lifecycle import copy_attachments
        copy_attachments(r.state,source,entity,rebind_printed=True)
        if material.entry_herald_count is not None:
            from .herald import initialize_instance
            initialize_instance(r.state,entity,r.registry.card(material.card_id),count=material.entry_herald_count)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state,entity,material.stats)
    if material.minion_grant is not None:
        from types import SimpleNamespace
        from .card_creation import install
        install(r.state,entity,SimpleNamespace(spell_repeat=None,minion_grant=material.minion_grant,source_id=material.grant_source_id))
    if material.profile == 'remembered_copy':
        from .lifecycle import remove_attachments
        remove_attachments(entity, enchantment_predicate=lambda a: expired_remembered_attachment(r.state, a),
            ability_predicate=lambda a: expired_remembered_attachment(r.state, a))
    r.refresh_auras()
    if material.mode=='current'and material.profile in ('board_copy','remembered_copy')and material.local.frozen:
        from .combat import can_be_frozen,freeze_deadline
        if can_be_frozen(entity):
            entity.frozen_until_owner_turn=freeze_deadline(r.state,entity,ending_turn=r.ending_turn,registry=r.registry)


def expired_remembered_attachment(state, attachment):
    """Frozen material keeps original clocks; copying never restarts a lapsed one."""
    if attachment.expires_turn is not None and attachment.expires_turn < state.turn:
        return True
    for name in ('owner_turn_expiry', 'keyword_expiry', 'health_rule_expiry',
            'attack_policy_expiry', 'limited_trigger_deadline'):
        expiry = getattr(attachment, name, None)
        if expiry is None: continue
        interval = next((x for x in reversed(state.owner_turn_history) if x.player_id == expiry.player_id), None)
        index = 0 if interval is None else interval.owner_index
        if index > expiry.owner_turn_index: return True
        if index == expiry.owner_turn_index and (
                interval.closed or expiry.boundary == 'turn_started' and
                (interval.origin != 'actual' or interval.publication_event is not None)):
            return True
    return False


def enter(r,material,entity):
    from .colossal import enter_minion
    return enter_minion(r,entity,'copy',origin_id=material.origin.entity_id,copy_mode=material.mode)


def from_dict(cls,value):
    from .serialization import _row,_list,_ability_from_dict,_enchantment_from_dict
    row=_row(value,cls)
    if cls is CopyLocalState:
        if row['choose_branch'] is not None:
            from .choose_branch_state import selection_from_dict
            row['choose_branch'] = selection_from_dict(row['choose_branch'])
        row['hand_lifetime']=None if row['hand_lifetime']is None else HandLifetime(**_row(row['hand_lifetime'],HandLifetime))
        row['enchantments']=tuple(_enchantment_from_dict(x)for x in row['enchantments'])
        row['abilities']=tuple(_ability_from_dict(x)for x in row['abilities'])
    elif cls is CopyEntryMaterial:
        row['stored_components']=tuple(_list(row['stored_components'],'stored original minion components'))
        row['origin']=allocation_from_dict(row['origin'])
        row['local']=None if row['local']is None else from_dict(CopyLocalState,row['local'])
        row['stats']=None if row['stats']is None else SummonStats(**_row(row['stats'],SummonStats))
        if row['minion_grant'] is not None:
            from .model import Keyword
            grant=dict(_row(row['minion_grant'],CreatedMinionGrant));grant['keywords']=tuple(Keyword(k)for k in grant['keywords'])
            row['minion_grant']=CreatedMinionGrant(**grant)
        if row['discard'] is not None:
            from .discard_history import DiscardRecord
            row['discard']=dict(_row(row['discard'],DiscardRecord))
            row['discard']['card']=allocation_from_dict(row['discard']['card'])
            row['discard']['source']=allocation_from_dict(row['discard']['source'])
            row['discard']['components']=tuple(_list(row['discard']['components'],'discard original components'))
            row['discard']=DiscardRecord(**row['discard'])
    return cls(**row)


def register(mechanics):
    mechanics.register_payload_type(CopyLocalState);mechanics.register_payload_type(CopyEntryMaterial)
