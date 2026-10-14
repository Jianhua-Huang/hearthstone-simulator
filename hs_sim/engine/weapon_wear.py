"""Synchronous original combat wear; compact facts, no before-loss callbacks.

Pre-wear/current and combat-accept/original are explicit local profiles. This is
internal consistency of unsigned facts, never external source authentication.
"""
from dataclasses import asdict,dataclass,fields,is_dataclass
from enum import Enum
from typing import get_type_hints,get_origin,get_args,Union
from types import UnionType
from . import model
from .model import (CardType,Zone,Enchantment,AbilityInstance,WeaponWearProfile,WeaponWearPredicate,
    WeaponWearSpec,PrintedWeaponWearDeclaration,WeaponWearRow,WeaponWearCarrier,
    WeaponWearInputs,WeaponWearDecision,WeaponWearPlan,WeaponWearReceipt)
from .effects import Effect,_grant
from .allocation_facts import SourceAllocationFact,allocation_from_payload,validate_allocation
from .lifecycle import attachment_id
from .errors import ResolutionError


def allocation(state,entity):
    fact=SourceAllocationFact.capture(state,entity)
    return tuple((k,v.value if isinstance(v,Enum)else v)for k,v in fact.payload())


def declared_spec(registry,declaration):
    if type(declaration)is not PrintedWeaponWearDeclaration:raise ValueError('Expected printed wear declaration')
    declaration.__post_init__();card=registry.card(declaration.card_id)
    if declaration.index>=len(card.weapon_wear_policies):raise ValueError('Unknown original printed wear row')
    return card.weapon_wear_policies[declaration.index]


def carrier(state,registry,entity):
    from .tribes import tribe_changes, tribe_state
    changes=tribe_changes(entity)
    current=tribe_state(registry, entity)
    tribes=None if current is None else current.members
    excluded=() if current is None else current.excluded
    rows=tuple(WeaponWearRow(a.id,a.weapon_wear_policy,a.origin,a.source_id,a.expires_turn,
        a.weapon_wear_declaration,a.consumed,allocation(state,state.entities[a.source_id])if a.source_id is not None else None)
        for a in sorted(entity.abilities,key=lambda a:a.id)if a.kind=='weapon_wear_policy')
    return WeaponWearCarrier(allocation(state,entity),entity.health,entity.attack,entity.durability,
        entity.doomed,entity.active,entity.silenced,entity.board_presence_id,tribes,rows,changes,excluded)


def capture_inputs(r,record):
    combat=record.combat
    from .owner_turns import current_owner_turn
    interval=current_owner_turn(r.state)
    weapon=r.state.entities[combat.weapon_id]
    board=tuple(carrier(r.state,r.registry,r.state.entities[i])for p in (1,2)for i in r.state.players[p].board
        if r.state.entities[i].kind==CardType.MINION)
    # The actual accepted attack target, independent of health-packet redirect.
    defender_kind=r.registry.card(combat.defender_card_id).kind
    return WeaponWearInputs(record.declaration.identity.record_id,combat.attacker_controller,
        r.state.active_player,r.state.turn,interval.id,r.state.action_number,r.root_action_number,
        len(r.game._events),r.state.next_attachment_id,defender_kind,
        allocation(r.state,r.state.entities[combat.identity.physical_hero_id]),
        carrier(r.state,r.registry,weapon),board)


def accept(r,record):
    if record.combat.weapon_id is None:return record
    from .hero_attack_history import update
    if record.wear_acceptance is not None:raise ResolutionError('Duplicate original wear acceptance')
    return update(r.state,record,wear_acceptance=capture_inputs(r,record))


def alive(c,presence):
    return presence=='board_present' or c.health>0 and not c.doomed and (presence!='active_living' or c.active)


def enabled(inputs,c,row):
    f=allocation_from_payload(c.allocation);s=row.spec;p=s.profile
    eligible=not row.consumed and f.controller==inputs.player_id
    if p.scope=='self_weapon':eligible=eligible and c is inputs.weapon and f.zone==Zone.WEAPON and c.durability>0 and not c.doomed
    else:eligible=eligible and f.kind==CardType.MINION and f.zone==Zone.BOARD and alive(c,p.presence)
    for pred in s.predicates:
        if pred.kind=='defender_kind':ok=inputs.defender_kind.value==pred.value
        elif pred.kind=='own_turn':ok=inputs.active_player==f.controller
        else:
            witnesses=[w for w in inputs.board if allocation_from_payload(w.allocation).controller==inputs.player_id and alive(w,pred.presence)]
            if any(w.tribes is None for w in witnesses):raise ValueError('Unknown current minion tribe metadata for weapon wear')
            from .tribes import TribeState
            ok=any(TribeState(w.tribes, w.tribe_exclusions).matches_any((pred.value,)) for w in witnesses)
        eligible=eligible and ok
    return eligible


def plan_for(accepted,current):
    # Capture every row, including inactive, foreign, false, and losing rows.
    choices={}
    for inputs in (accepted,current):
        desired='combat_accept_original' if inputs is accepted else 'pre_wear_current'
        for c in (inputs.weapon,*inputs.board):
            fid=allocation_from_payload(c.allocation).entity_id
            for row in c.rows:
                if row.spec.profile.window==desired:
                    choices[(fid,row.ability_id)]=(inputs,c,row)
    keys=sorted(choices)
    decisions=tuple(WeaponWearDecision(*k,enabled(*choices[k]))for k in keys)
    eligible=[(k,choices[k][2])for k,d in zip(keys,decisions)if d.eligible]
    replacements=[(k,row)for k,row in eligible if row.spec.mode=='replace_with_attack']
    selected=min(replacements,key=lambda x:(x[1].spec.priority,x[0][1],x[0][0]))if replacements else None
    prevention=tuple(k for k,row in eligible if row.spec.mode=='prevent_durability')
    return WeaponWearPlan(decisions,selected[0]if selected else None,prevention,
        'attack' if selected else 'durability',1 if selected or not prevention else 0)


def original_stale(accepted,current):
    a=allocation_from_payload(accepted.weapon.allocation);b=allocation_from_payload(current.weapon.allocation)
    return (a.entity_id,a.card_id,a.controller,a.zone_epoch,a.entered_order)!=(b.entity_id,b.card_id,b.controller,b.zone_epoch,b.entered_order)or b.zone!=Zone.WEAPON


def commit(r,combat):
    if combat.weapon_id is None:return
    from .hero_attack_history import record,update
    old=record(r.state,combat.hero_attack.identity.record_id)
    if old.wear_acceptance is None or old.wear_receipt is not None:raise ResolutionError('Wear lost its unique original accepted exchange')
    current=capture_inputs(r,old);plan=plan_for(old.wear_acceptance,current)
    weapon=r.state.entities[combat.weapon_id]
    stale=original_stale(old.wear_acceptance,current)
    before_durability,before_attack=weapon.durability,weapon.attack
    eid=None
    if not stale:
        if plan.axis=='durability':
            weapon.durability-=plan.amount
            if weapon.durability<=0 or weapon.doomed:
                from .death_causes import mark
                mark(r,weapon,'durability','combat_wear',combat.attacker_id)
        else:
            eid=attachment_id(r.state)
            weapon.enchantments.append(Enchantment(eid,source_id=combat.attacker_id,attack=-plan.amount,label='combat_wear_attack'))
            # Do not run the ordinary ModifyWeapon/checkpoint producer again.
            from .equipment import refresh_equipment
            refresh_equipment(r.state)
    receipt=WeaponWearReceipt(current,plan,before_durability,weapon.durability,before_attack,weapon.attack,
        eid,stale,len(r.game._events))
    update(r.state,old,wear_receipt=receipt)
    r.emit('weapon_wear_committed',source_id=combat.attacker_id,target_id=combat.weapon_id,
        accepted=asdict(old.wear_acceptance),receipt=asdict(receipt),combat=asdict(old.combat))
    if not stale and plan.axis=='durability' and plan.amount:
        r.emit('weapon_durability_spent',source_id=combat.attacker_id,target_id=weapon.id,
            amount=plan.amount,durability=weapon.durability)
    elif not stale and plan.axis=='attack':
        r.emit('weapon_changed',source_id=combat.attacker_id,target_id=weapon.id,attack=weapon.attack,durability=weapon.durability)


def typed_value(annotation,raw):
    origin,args=get_origin(annotation),get_args(annotation)
    if origin in (Union,UnionType):
        failures=[]
        for kind in args:
            try:return typed_value(kind,raw)
            except (ValueError,TypeError,KeyError)as e:failures.append(str(e))
        raise ValueError('Wrong typed wear union: '+str(failures))
    if origin is tuple:
        if type(raw)not in (tuple,list):raise ValueError('Expected immutable wear tuple')
        if len(args)==2 and args[1]is Ellipsis:return tuple(typed_value(args[0],v)for v in raw)
        if len(raw)!=len(args):raise ValueError('Wrong wear tuple arity')
        return tuple(typed_value(a,v)for a,v in zip(args,raw))
    if isinstance(annotation,type)and issubclass(annotation,Enum):return annotation(raw)
    if annotation in (int,str,bool,type(None)):
        if type(raw)is not annotation:raise ValueError('Wrong primitive wear field')
        return raw
    if isinstance(annotation,type)and is_dataclass(annotation):return from_dict(annotation,raw)
    raise ValueError('Unsupported typed wear field')


def from_dict(cls,raw):
    if type(raw)is not dict or set(raw)!={f.name for f in fields(cls)}:raise ValueError('Wear value requires all exact fields')
    hints=get_type_hints(cls)
    return cls(**{k:typed_value(hints[k],v)for k,v in raw.items()})


def validate_inputs(state,registry,inputs,*,closed=False,event_limit=None):
    inputs.__post_init__()
    if inputs.record_id>=state.next_window_id or inputs.next_attachment_id>state.next_attachment_id or inputs.action_number>state.action_number or inputs.root_action_number>inputs.action_number or inputs.turn>state.turn:
        raise ValueError('Future original wear allocation/window/action')
    if event_limit is not None and inputs.event_cursor>event_limit:raise ValueError('Future wear event cursor')
    if not 0<inputs.owner_turn_id<=len(state.owner_turn_history):raise ValueError('Unknown wear owner interval')
    owner=state.owner_turn_history[inputs.owner_turn_id-1]
    if (owner.player_id,owner.turn)!=(inputs.active_player,inputs.turn):raise ValueError('Foreign wear owner interval')
    h=allocation_from_payload(inputs.hero_allocation);validate_allocation(state,registry,h,closed=closed)
    if h.kind!=CardType.HERO or h.controller!=inputs.player_id:raise ValueError('Invalid original wear hero allocation')
    used=[];entity_ids=[]
    for c in (inputs.weapon,*inputs.board):
        a=allocation_from_payload(c.allocation);validate_allocation(state,registry,a,closed=closed);entity_ids.append(a.entity_id)
        if c is inputs.weapon:
            if a.kind!=CardType.WEAPON:raise ValueError('Original wear carrier is not a weapon')
        elif a.kind!=CardType.MINION or a.zone!=Zone.BOARD or c.presence_id is None or c.presence_id>=a.next_order:
            raise ValueError('Invalid original wear board residence')
        card=registry.card(a.card_id)
        from .tribes import tribe_state_for
        original=tribe_state_for(registry,a.card_id,c.tribe_changes)
        tribes=None if original is None else original.members
        excluded=() if original is None else original.excluded
        if (c.tribes,c.tribe_exclusions)!=(tribes,excluded):raise ValueError('Wear witness differs from its original effective tribe changes')
        for change in c.tribe_changes:
            used.append(change.id)
            if (change.id>=inputs.next_attachment_id or change.source_id is not None and not 0<change.source_id<a.next_entity_id
                    or change.expires_turn is not None and change.expires_turn<inputs.turn):
                raise ValueError('Original wear tribe change exceeds its allocation or lifetime window')
            if not closed and change.source_id is not None and change.source_id not in state.entities:
                raise ValueError('Unknown original wear tribe grant source')
        printed=[]
        for row in c.rows:
            row.__post_init__();used.append(row.ability_id)
            if row.ability_id>=inputs.next_attachment_id:raise ValueError('Future wear source attachment')
            if row.source_id is not None and not 0<row.source_id<a.next_entity_id:raise ValueError('Future wear grant source')
            if not closed and row.source_id is not None and row.source_id not in state.entities:raise ValueError('Unknown wear grant source')
            if row.grant_allocation is not None:validate_allocation(state,registry,allocation_from_payload(row.grant_allocation),closed=closed)
            if row.declaration is not None and declared_spec(registry,row.declaration)!=row.spec:raise ValueError('Foreign original printed wear specification')
            if row.origin=='printed':
                if row.declaration.card_id!=a.card_id:raise ValueError('Printed wear row belongs to another carrier face')
                printed.append(row.declaration.index)
        if not c.silenced and sorted(printed)!=list(range(len(card.weapon_wear_policies))):raise ValueError('Incomplete original printed wear rows')
        if c.silenced and printed:raise ValueError('Silenced carrier retains original printed wear rows')
    if len(set(used))!=len(used)or len(set(entity_ids))!=len(entity_ids):raise ValueError('Duplicated original wear physical/attachment identity')


def validate_pair(state,registry,accepted,receipt,combat,*,closed=False,event_limit=None):
    validate_inputs(state,registry,accepted,closed=closed,event_limit=event_limit)
    identity=combat.identity
    aw=allocation_from_payload(accepted.weapon.allocation)
    ah=allocation_from_payload(accepted.hero_allocation)
    if (accepted.record_id,accepted.root_action_number,ah.entity_id,ah.card_id,ah.controller,aw.entity_id)!=(identity.record_id,identity.root_action_number,identity.physical_hero_id,combat.attacker_card_id,combat.attacker_controller,combat.weapon_id):raise ValueError('Foreign original wear combat/hero/weapon')
    if ah.zone!=Zone.HERO or aw.zone!=Zone.WEAPON or accepted.defender_kind!=registry.card(combat.defender_card_id).kind:raise ValueError('Wrong original accepted wear physical zone/defender')
    if receipt is None:return
    receipt.__post_init__();current=receipt.current
    validate_inputs(state,registry,current,closed=closed,event_limit=event_limit)
    cw=allocation_from_payload(current.weapon.allocation)
    if (accepted.record_id,current.record_id,accepted.root_action_number,current.root_action_number)!=(identity.record_id,identity.record_id,identity.root_action_number,identity.root_action_number):raise ValueError('Wear borrowed another original hero window/root')
    if (ah.entity_id,ah.card_id,ah.controller,aw.entity_id)!=(identity.physical_hero_id,combat.attacker_card_id,combat.attacker_controller,combat.weapon_id)or cw.entity_id!=aw.entity_id:
        raise ValueError('Wear borrowed another physical hero/weapon')
    if accepted.defender_kind!=registry.card(combat.defender_card_id).kind or current.defender_kind!=accepted.defender_kind:
        raise ValueError('Wear used a health redirect instead of accepted defender kind')
    if accepted.event_cursor>current.event_cursor or accepted.action_number>current.action_number or current.event_cursor>receipt.event_cursor or event_limit is not None and receipt.event_cursor>=event_limit:
        raise ValueError('Wear phase chronology/cursor is invalid')
    if plan_for(accepted,current)!=receipt.plan:raise ValueError('Original full wear plan was changed/cropped')
    stale=original_stale(accepted,current)
    if stale!=receipt.original_stale or receipt.durability_before!=current.weapon.durability or receipt.attack_before!=current.weapon.attack:
        raise ValueError('Wear original resident/before operands changed')
    plan=receipt.plan
    loss=plan.amount if not stale and plan.axis=='durability'else 0
    after=max(0,receipt.attack_before-plan.amount)if not stale and plan.axis=='attack'else receipt.attack_before
    if receipt.durability_after!=receipt.durability_before-loss or receipt.attack_after!=after:
        raise ValueError('Wear result does not match its original single loss')
    needs_attack=not stale and plan.axis=='attack'
    if bool(receipt.attack_enchantment_id)!=needs_attack or needs_attack and receipt.attack_enchantment_id!=current.next_attachment_id:
        raise ValueError('Wear lost its unique signed attack allocation')
    if needs_attack and receipt.attack_enchantment_id>=state.next_attachment_id:raise ValueError('Future wear attack allocation')


def validate_history(state,registry,event_limit=None):
    if registry is None:return
    for record in state.hero_attack_history:
        a,receipt=record.wear_acceptance,record.wear_receipt
        expected=record.combat is not None and record.combat.weapon_id is not None
        if bool(a)!=expected or receipt is not None and a is None:raise ValueError('Hero combat lost its original wear acceptance')
        if a is not None:
            validate_pair(state,registry,a,receipt,record.combat,event_limit=event_limit)
        if record.terminal is not None and record.terminal.outcome=='completed'and expected and receipt is None:
            raise ValueError('Completed weapon attack lacks its single wear receipt')
        if receipt is not None and record.terminal is not None and record.terminal.outcome!='completed':raise ValueError('Cancelled hero attack cannot have wear')


def validate_committed_events(game):
    # Real outer restore only; never called for Rewind.before / captured states.
    seen={}
    for event in game._events:
        if event.kind!='weapon_wear_committed':continue
        data=dict(event.data)
        if set(data)!={'accepted','receipt','combat'}:raise ValueError('Closed wear fact requires all exact fields')
        a=from_dict(WeaponWearInputs,data['accepted']);r=from_dict(WeaponWearReceipt,data['receipt'])
        c=from_dict(model.HeroAttackCombatFact,data['combat']);identity=c.identity
        validate_pair(game._state,game.registry,a,r,c,closed=True,event_limit=event.sequence)
        if (event.source_id,event.target_id,event.action,event.sequence)!=(identity.physical_hero_id,c.weapon_id,r.current.action_number,r.event_cursor+1):raise ValueError('Closed wear fact borrowed another event envelope')
        if identity.record_id in seen:raise ValueError('Duplicated closed intrinsic wear')
        if identity.record_id>=game._state.next_window_id or identity.root_action_number>event.action or identity.hero_card_id not in game.registry.cards:
            raise ValueError('Future/unknown original closed hero identity')
        if identity.record_id!=identity.window_id or not 0<identity.owner_turn_id<=len(game._state.owner_turn_history):raise ValueError('Unknown original closed hero window/owner interval')
        owner=game._state.owner_turn_history[identity.owner_turn_id-1]
        if (owner.player_id,owner.turn)!=(identity.player_id,identity.turn)or identity.turn>game._state.turn:raise ValueError('Foreign original closed hero owner interval')
        hero=allocation_from_payload(a.hero_allocation);weapon=allocation_from_payload(a.weapon.allocation)
        if hero.owner!=identity.player_id or game.registry.card(identity.hero_card_id).kind!=CardType.HERO:raise ValueError('Foreign original closed hero physical owner/face')
        if not 0<identity.declared_target_id<weapon.next_entity_id or not 0<c.defender_id<weapon.next_entity_id:raise ValueError('Future original closed combat participant')
        if (c.delivery.identity!=identity or c.delivery.target_id!=c.defender_id or identity.root_action_number>c.delivery.action_number or
                c.delivery.action_number>c.action_number or c.action_number>a.action_number or
                c.delivery.event_cursor>c.event_cursor or c.event_cursor>a.event_cursor):raise ValueError('Closed original hero delivery/combat chronology changed')
        if c.weapon_id!=allocation_from_payload(a.weapon.allocation).entity_id:raise ValueError('Closed wear original weapon changed')
        seen[identity.record_id]=(a,r,c)
    for record in game._state.hero_attack_history:
        if record.wear_receipt is not None and seen.get(record.declaration.identity.record_id)!=(record.wear_acceptance,record.wear_receipt,record.combat):
            raise ValueError('Wear history differs from its unique closed original fact')


@dataclass(frozen=True)
class GrantWeaponWearPolicy(Effect):
    target_id: int
    spec: WeaponWearSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _grant(self.target_id,self.source_id,self.expires_turn)
        if type(self.spec)is not WeaponWearSpec:raise ValueError('Expected typed weapon wear specification')
        self.spec.__post_init__()


def grant(r,effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r,effect.source_id,effect.expires_turn)
    e=r.state.entities.get(effect.target_id)
    expected=CardType.WEAPON if effect.spec.profile.scope=='self_weapon'else CardType.MINION
    zone=Zone.WEAPON if expected==CardType.WEAPON else Zone.BOARD
    if e is None or e.kind!=expected or e.zone!=zone:
        r.stale(effect,effect.target_id);return
    e.abilities.append(AbilityInstance(attachment_id(r.state),'weapon_wear_policy',source_id=effect.source_id,
        expires_turn=effect.expires_turn,weapon_wear_policy=effect.spec))
    r.emit('ability_granted',source_id=effect.source_id,target_id=e.id,ability_id=e.abilities[-1].id,ability_kind='weapon_wear_policy')


def validate_frame(game):
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    def walk(value,state):
        if type(value)is model.GameState:return
        if type(value)is RuleContext:state=value.state
        if type(value)is PaidHandChoiceBoundaryProof:
            for item in value.work:walk(item,value.state)
            return
        if type(value)is GrantWeaponWearPolicy:
            if value.target_id not in state.entities or value.source_id is not None and value.source_id not in state.entities:
                raise ValueError('Unknown queued wear physical reference')
        if is_dataclass(value):
            for f in fields(value):walk(getattr(value,f.name),state)
        elif type(value)in (tuple,list):
            for v in value:walk(v,state)
    if game._frame is not None:walk(game._frame,game._state)


def register(mechanics):mechanics.register(GrantWeaponWearPolicy,grant)
