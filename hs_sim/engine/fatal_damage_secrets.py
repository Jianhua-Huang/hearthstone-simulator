"""Printed secret prevention at the existing atomic damage commit boundary."""
from .effects import GrantKeyword
from .model import CardType,HealthFlow,HealthLayer,HealthLossKind,HealthOp,HealthRule,Keyword,Zone

RULE=HealthRule(HealthFlow.DAMAGE,HealthOp.SECRET_FATAL_IMMUNITY,layer=HealthLayer.TARGET,
    target_relation='friendly',target_kinds=(CardType.HERO,))


def validate_definition(card):
    rows=tuple(x for x in card.health_rules if x.operation==HealthOp.SECRET_FATAL_IMMUNITY)
    if rows and (rows!=(RULE,) or card.kind!=CardType.SPELL or card.secret is None or
            Keyword.SECRET not in card.keywords or card.secret.turn!='opponent' or card.secret.requires_board_space):
        raise ValueError('Fatal damage immunity requires one printed opponent-turn secret rule')


def validate_carrier(registry,card_id,kind,abilities):
    rows=tuple(a for a in abilities if a.kind=='health_rule' and a.health_rule.operation==HealthOp.SECRET_FATAL_IMMUNITY)
    if not rows:return
    card=registry.card(card_id);validate_definition(card)
    if kind!=CardType.SPELL or any(a.origin!='printed' or a.health_rule not in card.health_rules for a in rows):
        raise ValueError('Fatal damage secret lost its original printed carrier')


def prevent(r,frozen_state,rules,packet,target,result,pending_events):
    """Respect prior routing, numeric prevention, armor, floors and replacement."""
    if (packet.flow!=HealthFlow.DAMAGE or packet.amount<=0 or packet.prevented or
            target.kind!=CardType.HERO or target.health<=0 or result.prevention is not None or
            result.health_damage<target.health or target.controller==r.state.active_player):
        return None
    from .health_loss import replacement_for
    if replacement_for(frozen_state,target.id,HealthLossKind.DAMAGE) is not None:return None
    from .health_rules import matches
    from .secrets import consume
    from .resolver import _grant_to
    for row in rules:
        ability_id,holder_id,controller,rule=row
        if rule.operation!=HealthOp.SECRET_FATAL_IMMUNITY or not matches(frozen_state,r.registry,packet,row):continue
        original=frozen_state.entities[holder_id];secret=r.state.entities.get(holder_id)
        if (secret is None or secret.zone!=Zone.SECRET or not secret.active or secret.doomed or
                secret.id not in r.player(controller).secrets or r.player(controller).hero_id!=target.id or
                secret.secret_instance_id is None or
                (secret.card_id,secret.controller,secret.zone_epoch,secret.entered_order,secret.secret_instance_id)!=
                (original.card_id,controller,original.zone_epoch,original.entered_order,original.secret_instance_id)):
            continue
        ability=next((a for a in secret.abilities if a.id==ability_id and not a.consumed),None)
        if ability is None or ability.kind!='health_rule' or ability.health_rule!=rule:continue
        validate_definition(r.registry.card(secret.card_id))
        validate_carrier(r.registry,secret.card_id,secret.kind,(ability,))
        consume(r,secret,'secret_revealed',pending_events=pending_events)
        # Keep the already-frozen simultaneous batch's other aura statistics.
        _grant_to(r,GrantKeyword(target.id,Keyword.IMMUNE,secret.id,expires_turn=r.state.turn),
            target,notify=False,refresh=False)
        pending_events.append(('ability_granted',dict(target_id=target.id,source_id=secret.id,
            ability_id=target.abilities[-1].id,ability_kind='keyword')))
        return ability_id
    return None
