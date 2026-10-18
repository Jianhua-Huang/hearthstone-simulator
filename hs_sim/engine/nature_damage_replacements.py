"""Finite native Nature replacements compose ordinary buffs and pool summons.

Health quoting stays pure. Each positive original packet accepts a replacement;
its health receipt closes before growth, and batch notifications remain buffered.
"""
from .allocation_facts import SourceAllocationFact
from .effects import Buff
from .model import CardType,DamageKind,HealthFlow,HealthLayer,HealthOp,HealthRule,SpellSchool,Zone
from .pools import PoolQuery,SummonFromPool
from .summon_quantities import SummonCause

OPERATIONS=(HealthOp.NATURE_GROWTH,HealthOp.NATURE_SUMMON)
RULES={op:HealthRule(HealthFlow.DAMAGE,op,layer=HealthLayer.TARGET,source_relation='friendly',
    target_relation='self',target_kinds=(CardType.MINION,),damage_kinds=(DamageKind.SPELL,),schools=(SpellSchool.NATURE,))for op in OPERATIONS}
POOL='constructed.cards'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=5,max_cost=5)


def validate_definition(card):
    rows=tuple(rule for rule in card.health_rules if rule.operation in OPERATIONS)
    if rows and (card.kind!=CardType.MINION or any(rule!=RULES[rule.operation]for rule in rows) or len(rows)!=1):
        raise ValueError('Native Nature replacement requires one complete printed minion profile')


def validate_carrier(registry,card_id,kind,abilities):
    rows=tuple(a for a in abilities if a.kind=='health_rule'and a.health_rule.operation in OPERATIONS)
    if not rows:return
    card=registry.card(card_id);validate_definition(card)
    if kind!=CardType.MINION or card.kind!=CardType.MINION or len(rows)!=1 or any(a.origin!='printed'or a.health_rule not in card.health_rules for a in rows):
        raise ValueError('Native Nature replacement lost its original printed carrier')


def select(r,frozen,rules,packet,target):
    if packet.flow!=HealthFlow.DAMAGE or packet.prevented or packet.amount<=0:return None
    from .health_rules import matches
    for row in rules:
        aid,holder,controller,rule=row
        if rule.operation not in OPERATIONS or not matches(frozen,r.registry,packet,row):continue
        original=frozen.entities[holder]
        if (target.id!=holder or target.kind!=CardType.MINION or target.zone!=Zone.BOARD or
                (target.card_id,target.controller,target.zone_epoch,target.entered_order)!=
                (original.card_id,controller,original.zone_epoch,original.entered_order)):continue
        ability=next((a for a in target.abilities if a.id==aid and a.kind=='health_rule'and not a.consumed),None)
        if ability is None or ability.health_rule!=rule:continue
        validate_carrier(r.registry,target.card_id,target.kind,tuple(target.abilities))
        return row
    return None


def complete(r,row,target,pending_events):
    _,holder,controller,rule=row
    if rule.operation==HealthOp.NATURE_GROWTH:
        from .resolver import _buff_to
        enchantment=_buff_to(r,Buff(target.id,attack=2,health=1,source_id=holder),target,notify=False)
        pending_events.append(('stats_changed',dict(source_id=holder,target_id=target.id,
            enchantment_id=enchantment.id,attack_delta=2,health_delta=1)))
        return ()
    cause=SummonCause(SourceAllocationFact.capture(r.state,target),controller,r.state.turn,r.state.action_number,'card_effect')
    return (SummonFromPool(controller,POOL,QUERY,source_id=holder,cause=cause),)
