"""Native outgoing hero damage becomes ordinary counted deck generation."""
from .deck_generation import ShuffleGeneratedCopies
from .model import CardType,HealthFlow,HealthLayer,HealthOp,HealthRule,Zone

BLIGHT='JAIL_443t'
RULE=HealthRule(HealthFlow.DAMAGE,HealthOp.BLIGHT_SHUFFLE,layer=HealthLayer.SOURCE,
    source_relation='self',target_kinds=(CardType.HERO,))


def validate_definition(card):
    rows=tuple(rule for rule in card.health_rules if rule.operation==HealthOp.BLIGHT_SHUFFLE)
    if rows and (card.kind!=CardType.MINION or rows!=(RULE,)):
        raise ValueError('Blight replacement requires one exact native minion source rule')


def validate_carrier(registry,card_id,kind,abilities):
    rows=tuple(a for a in abilities if a.kind=='health_rule' and a.health_rule.operation==HealthOp.BLIGHT_SHUFFLE)
    if not rows:return
    card=registry.card(card_id);validate_definition(card)
    if kind!=CardType.MINION or card.kind!=CardType.MINION or len(rows)!=1 or any(a.origin!='printed' or a.health_rule!=RULE or a.health_rule not in card.health_rules for a in rows):
        raise ValueError('Blight replacement lost its original native printed carrier')


def select(r,frozen,rules,packet,target):
    if packet.flow!=HealthFlow.DAMAGE or packet.prevented or packet.amount<=0 or target.kind!=CardType.HERO:return None
    from .health_rules import matches
    for row in rules:
        aid,holder,controller,rule=row
        if rule.operation!=HealthOp.BLIGHT_SHUFFLE or not matches(frozen,r.registry,packet,row):continue
        original=frozen.entities[holder];source=r.state.entities.get(holder)
        if source is None or source.zone!=Zone.BOARD or not source.active or (source.card_id,source.controller,source.zone_epoch,source.entered_order)!=(original.card_id,controller,original.zone_epoch,original.entered_order):continue
        if not any(a.id==aid and a.kind=='health_rule' and a.health_rule==rule and not a.consumed for a in source.abilities):continue
        validate_carrier(r.registry,source.card_id,source.kind,source.abilities)
        r.registry.card(BLIGHT)  # Unknown required content is rejected even at full capacity.
        return row
    return None


def complete(row,packet,target):
    _,holder,controller,_=row
    return (ShuffleGeneratedCopies(target.controller,controller,BLIGHT,packet.amount,holder),)
