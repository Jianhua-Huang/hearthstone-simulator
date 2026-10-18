"""A physical weapon pays durability instead of incoming hero damage.

Ordinary packet modifiers remain frozen for a simultaneous batch. Unlike those
modifiers, this finite resource is checked and consumed for each committed hit.
"""
from .effects import ModifyWeapon
from .errors import ResolutionError
from .model import CardType, EquippedWeaponReference, HealthFlow, HealthLayer, HealthOp, HealthRule, Zone

RULE = HealthRule(HealthFlow.DAMAGE,HealthOp.WEAPON_DURABILITY,layer=HealthLayer.TARGET,
                  target_relation='friendly',target_kinds=(CardType.HERO,))


def validate_definition(card):
    if any(rule.operation == HealthOp.WEAPON_DURABILITY for rule in card.health_rules) and card.kind != CardType.WEAPON:
        raise ValueError('Incoming durability replacement must be printed on a weapon')


def validate_carrier(registry,card_id,kind,abilities):
    rows = tuple(a for a in abilities if a.kind == 'health_rule' and
                 a.health_rule.operation == HealthOp.WEAPON_DURABILITY)
    if not rows:
        return
    card = registry.card(card_id)
    if (kind != CardType.WEAPON or card.kind != CardType.WEAPON or
            any(a.origin != 'printed' or a.health_rule not in card.health_rules for a in rows)):
        raise ValueError('Weapon damage replacement lost its original printed carrier')


def replace_damage(r, frozen_state, rules, packet, target, pending_events):
    if packet.flow != HealthFlow.DAMAGE or packet.amount <= 0 or target.kind != CardType.HERO:
        return None
    from .health_rules import matches
    from .equipment import modify_weapon
    for row in rules:
        ability_id,holder_id,controller,rule = row
        if rule.operation != HealthOp.WEAPON_DURABILITY or not matches(frozen_state,r.registry,packet,row):
            continue
        original = frozen_state.entities[holder_id]
        weapon = r.state.entities.get(holder_id)
        if (weapon is None or weapon.kind != CardType.WEAPON or weapon.zone != Zone.WEAPON or
                not weapon.active or weapon.doomed or weapon.durability <= 0 or
                r.player(controller).weapon_id != holder_id or r.player(controller).hero_id != target.id or
                (weapon.card_id,weapon.controller,weapon.zone_epoch,weapon.entered_order) !=
                (original.card_id,controller,original.zone_epoch,original.entered_order)):
            continue
        ability = next((a for a in weapon.abilities if a.id==ability_id and not a.consumed),None)
        if ability is None or ability.kind != 'health_rule' or ability.health_rule != rule:
            continue
        if rule != RULE:
            raise ResolutionError('Unsupported durability damage replacement profile')
        modify_weapon(r,ModifyWeapon(EquippedWeaponReference.capture(weapon),durability=-1,source_id=weapon.id),
                      pending_events=pending_events)
        return ability_id
    return None
