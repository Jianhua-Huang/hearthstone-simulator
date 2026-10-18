"""Hit counts belong to physical Divine Shield abilities, not their providers."""
from dataclasses import replace
from .model import CardType,HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,Zone

RULE=HealthRule(HealthFlow.DAMAGE,HealthOp.SHIELD_HITS,3,layer=HealthLayer.TARGET,target_relation='friendly')


def validate_definition(card):
    rows=tuple(s for s in card.health_rules if s.operation==HealthOp.SHIELD_HITS)
    if rows and (card.kind!=CardType.MINION or rows!=(RULE,)):
        raise ValueError('Native shield-hit provider requires one ordinary printed minion profile')


def validate_carrier(registry,card_id,kind,abilities):
    rows=tuple(a for a in abilities if a.kind=='health_rule'and a.health_rule.operation==HealthOp.SHIELD_HITS)
    if not rows:return
    card=registry.card(card_id);validate_definition(card)
    if kind!=CardType.MINION or len(rows)!=1 or any(a.origin!='printed'or a.health_rule not in card.health_rules for a in rows):
        raise ValueError('Native shield-hit provider lost its original printed carrier')


def shields(entity):
    return tuple(a for a in entity.abilities if a.kind=='keyword'and a.keyword==Keyword.DIVINE_SHIELD and not a.consumed)


def current_limit(state,registry,player_id):
    from .health_rules import rule_sources
    return max((rule.amount for _,_,controller,rule in rule_sources(state)
        if controller==player_id and rule.operation==HealthOp.SHIELD_HITS),default=1)


def consume_hit(r,frozen,rules,packet,target):
    from .health_rules import matches
    from .lifecycle import consume_keyword
    rows=tuple(row for row in rules if row[3].operation==HealthOp.SHIELD_HITS and matches(frozen,r.registry,packet,row))
    limit=max((row[3].amount for row in rows),default=1);active=shields(target)
    if limit>1 and not active:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Three-hit shielding requires its original physical Divine Shield ability')
    used=max((a.divine_shield_hits for a in active),default=0)
    if limit==1 and used==0:
        consume_keyword(target,Keyword.DIVINE_SHIELD)
        return True,()
    used+=1;lost=used>=limit
    ids={a.id for a in active}
    target.abilities=[replace(a,divine_shield_hits=used,consumed=lost)if a.id in ids else a for a in target.abilities]
    from .lifecycle import refresh_entity
    refresh_entity(target)
    return lost,tuple(row[0]for row in rows)


def public_shield(state,registry,entity):
    rows=shields(entity)
    if not rows:return None
    used=max(a.divine_shield_hits for a in rows);limit=current_limit(state,registry,entity.controller)
    return dict(hits_taken=used,hits_to_break=limit,remaining_hits=max(1,limit-used),active=bool(entity.active))


def validate_public(value):
    if value is None:return
    if type(value)is not dict or set(value)!={'hits_taken','hits_to_break','remaining_hits','active'}:
        raise ValueError('Public Divine Shield requires only its visible durability fields')
    used,limit,left=value['hits_taken'],value['hits_to_break'],value['remaining_hits']
    if (type(used)is not int or not 0<=used<=2 or type(limit)is not int or limit not in(1,3)or
            type(left)is not int or left!=max(1,limit-used)or type(value['active'])is not bool):
        raise ValueError('Public Divine Shield durability is inconsistent')
