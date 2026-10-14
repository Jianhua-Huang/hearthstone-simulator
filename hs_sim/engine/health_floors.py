"""DAMAGE/TARGET floor: frozen eligibility, packet-local live HP allowance.

Armor is consumed before the floor. Max of accepted rows is local policy M6.
These bounded allocation facts do not authenticate unsigned snapshots or prove
candidate completeness. Direct HP loss/payment, stats and Destroy are unrelated.
"""
from dataclasses import asdict, fields, is_dataclass

from .model import (CardType, DamageKind, Event, GameState, HealthFlow, HealthOp,
                    HealthFloorPlan, HealthFloorRow, Keyword, SpellSchool, Zone)


def validate_face(card):
    if (card.kind not in (CardType.HERO, CardType.MINION, CardType.WEAPON) or card.starship_for or
            Keyword.MAGNETIC in card.keywords or Keyword.STARSHIP_PIECE in card.keywords):
        raise ValueError('Health floors require ordinary non-composite health-rule carriers')


def validate_carrier(registry, card_id, kind, abilities, components=(), *, definition=None):
    rows=tuple(a for a in abilities if a.kind == 'health_rule' and a.health_rule.operation == HealthOp.FLOOR)
    if not rows and definition is None: return
    card=definition if definition is not None else registry.card(card_id)
    validate_face(card)
    if kind != card.kind or components: raise ValueError('Unsupported composite floor carrier')
    for ability in rows:
        ability.__post_init__()
        if ability.origin == 'printed' and (ability.health_rule not in card.health_rules or
                ability.source_id is None or ability.expires_turn is not None or ability.consumed):
            raise ValueError('Printed health floor differs from its native row')


def validate_grant(state, registry, effect):
    if effect.rule.operation != HealthOp.FLOOR: return
    effect.__post_init__()
    target=state.entities.get(effect.target_id)
    if target is None or (effect.source_id is not None and effect.source_id not in state.entities):
        raise ValueError('Unknown or future health floor grant reference')
    # Known off-board/dead/expired work keeps the existing delivery stale policy.
    validate_face(registry.card(target.card_id))
    if target.components: raise ValueError('Composite health floor grant is unsupported')


def capture_plan(state, registry, packet, rules):
    if packet.flow != HealthFlow.DAMAGE: return None
    from .health_rules import matches
    selected=[]
    for row in rules:
        if row[3].operation != HealthOp.FLOOR or not matches(state, registry, packet, row): continue
        carrier=state.entities[row[1]]
        ability=next(a for a in carrier.abilities if a.id == row[0])
        validate_carrier(registry, carrier.card_id, carrier.kind, (ability,), carrier.components)
        selected.append(HealthFloorRow(ability,carrier.id,carrier.card_id,carrier.kind,carrier.controller,
            carrier.zone,carrier.zone_epoch,carrier.entered_order))
    if not selected: return None
    target=state.entities[packet.target_id]
    return HealthFloorPlan(tuple(selected),max(r.ability.health_rule.amount for r in selected),state.turn,
        state.next_entity_id,state.next_attachment_id,state.next_order,packet.source_id,packet.source_controller,
        packet.damage_kind,packet.school,target.id,target.card_id,target.kind,target.controller,target.zone_epoch,target.entered_order)


def plan_payload(plan):
    if plan is None: return None
    def freeze(value):
        if type(value) is dict: return tuple((k,freeze(v)) for k,v in value.items())
        if isinstance(value,(tuple,list)): return tuple(freeze(v) for v in value)
        return value
    return freeze(asdict(plan))


def plan_from_payload(raw):
    if raw is None: return None
    from .serialization import _ability_from_dict
    def obj(value, cls):
        if (type(value) is not tuple or any(type(r) is not tuple or len(r)!=2 or type(r[0]) is not str for r in value) or
                len(dict(value)) != len(value) or set(dict(value)) != {f.name for f in fields(cls)}):
            raise ValueError('Health floor payload requires exact frozen declared fields')
        return dict(value)
    def thaw(value):
        if type(value) is tuple:
            if value and all(type(r) is tuple and len(r)==2 and type(r[0]) is str for r in value):
                if len(dict(value))!=len(value): raise ValueError('Duplicate floor ability payload fields')
                return {k:thaw(v) for k,v in value}
            return [thaw(v) for v in value]
        return value
    values=obj(raw,HealthFloorPlan)
    if type(values['rows']) is not tuple: raise ValueError('Floor rows must be frozen')
    rows=[]
    for raw_row in values['rows']:
        row=obj(raw_row,HealthFloorRow)
        row['ability']=_ability_from_dict(thaw(row['ability']))
        row['kind']=CardType(row['kind']);row['zone']=Zone(row['zone'])
        rows.append(HealthFloorRow(**row))
    values['rows']=tuple(rows);values['target_kind']=CardType(values['target_kind'])
    values['damage_kind']=DamageKind(values['damage_kind'])
    if values['school'] is not None: values['school']=SpellSchool(values['school'])
    return HealthFloorPlan(**values)


def validate_result_numbers(result):
    plan=result.floor_plan
    if plan is None:
        if result.floor_prevented: raise ValueError('Floor prevention has no accepted plan')
        return
    if type(plan) is not HealthFloorPlan: raise ValueError('Health floor requires typed accepted plan')
    plan.__post_init__()
    if (result.flow != HealthFlow.DAMAGE.value or
            (plan.turn,plan.source_id,plan.source_controller,plan.damage_kind.value,
             plan.target_id,plan.target_card_id,plan.target_kind.value,plan.target_controller,
             plan.target_zone_epoch,plan.target_entered_order) !=
            (result.turn,result.source_id,result.source_controller,result.damage_kind,
             result.target_id,result.target_card_id,result.target_kind,result.target_controller,
             result.target_zone_epoch,result.target_entered_order) or
            not all(row.ability.id in result.rule_ids for row in plan.rows)):
        raise ValueError('Accepted floor plan differs from captured packet identity')
    if result.prevention:
        if result.floor_prevented: raise ValueError('Earlier prevention cannot also consume floor budget')
        return
    armor=min(result.armor_before,result.modified_amount)
    remainder=result.modified_amount-armor
    accepted=min(remainder,max(0,result.health_before-plan.floor))
    if (result.armor_absorbed != armor or result.health_lost+result.health_replaced != accepted or
            result.floor_prevented != remainder-accepted):
        raise ValueError('Health floor settlement disagrees with packet-local live HP allowance')


def validate_plan(state, registry, plan):
    plan.__post_init__()
    if (plan.turn>state.turn or plan.next_entity_id>state.next_entity_id or
            plan.next_attachment_id>state.next_attachment_id or plan.next_order>state.next_order):
        raise ValueError('Health floor plan exceeds the original allocated state domain')
    if registry.card(plan.target_card_id).kind != plan.target_kind:
        raise ValueError('Floor target native face kind differs')
    allocated={a.id:(entity,a) for entity in state.entities.values() for a in entity.abilities}
    for row in plan.rows:
        card=registry.card(row.card_id)
        validate_carrier(registry,row.card_id,row.kind,(row.ability,))
        if card.kind != row.kind: raise ValueError('Floor carrier native kind differs')
        known=allocated.get(row.ability.id)
        if known is not None:
            original,current=known
            if original.id != row.carrier_id or current != row.ability:
                raise ValueError('Accepted floor row differs from its original allocated physical carrier')
            if original.zone_epoch == row.zone_epoch and (original.card_id,original.kind) != (row.card_id,row.kind):
                raise ValueError('Accepted floor row native face differs in the same incarnation')
        carrier=state.entities.get(row.carrier_id)
        if carrier is not None:
            if row.zone_epoch>carrier.zone_epoch: raise ValueError('Future floor carrier incarnation')
            current=next((a for a in carrier.abilities if a.id==row.ability.id),None)
            if current is not None and current != row.ability:
                raise ValueError('Accepted floor row differs from allocated original attachment')
        # A removed row/Retry-deleted carrier can remain in historical accepted
        # facts. Bounds and native declaration validate it; no present rematching.
    target=state.entities.get(plan.target_id)
    if target is not None and plan.target_zone_epoch>target.zone_epoch:
        raise ValueError('Future health floor target incarnation')


def validate_result(state, registry, result):
    if result.floor_plan is None: return
    validate_result_numbers(result);validate_plan(state,registry,result.floor_plan)
    if result.source_card_id is not None and registry.card(result.source_card_id).spell_school != result.floor_plan.school:
        raise ValueError('Floor source school differs from captured native source')


def validate_event_results(state, registry, events):
    from .health_outcomes import health_result
    for event in events:
        result=health_result(event)
        if result is not None: validate_result(state,registry,result)


def validate_frame_references(state, registry, value):
    from .effects import GrantHealthRule
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    from .health_outcomes import HealthResult, health_result
    def visit(item,scope,depth):
        if depth>FrameCodec.MAX_DEPTH: raise ValueError('Health floor frame references exceed codec depth')
        if type(item) is GrantHealthRule: validate_grant(scope,registry,item);return
        if type(item) is HealthFloorPlan: validate_plan(scope,registry,item);return
        if type(item) is HealthResult: validate_result(scope,registry,item);return
        if type(item) is Event:
            result=health_result(item)
            if result is not None: validate_result(scope,registry,result)
            return
        if type(item) is RuleContext:
            for f in fields(item):
                if f.name!='state': visit(getattr(item,f.name),item.state,depth+1)
            return
        if type(item) is PaidHandChoiceBoundaryProof:
            visit(item.work,item.state,depth+1);return
        if type(item) is GameState: return
        if isinstance(item,(list,tuple)):
            for child in item: visit(child,scope,depth+1)
        elif isinstance(item,dict):
            for child in item.values(): visit(child,scope,depth+1)
        elif is_dataclass(item) and not isinstance(item,type):
            for f in fields(item): visit(getattr(item,f.name),scope,depth+1)
    visit(value,state,0)
