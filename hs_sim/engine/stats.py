"""Pure ordered stat evaluation; damage and ongoing auras are separate layers.

Add/set operands are frozen at application. Refreshing never executes a spell
again, clears damage, or doubles a value again. See docs/m2-stats.md for the
provisional aura and health-removal contracts.
"""
from .model import CardType, StatReference, StatRelationLayer, StatRelationSpec, StatRelationOperand


def enchantment_stats(entity):
    attack, health = entity.base_attack, entity.base_health
    for enchantment in entity.enchantments:
        attack = (enchantment.set_attack if enchantment.set_attack is not None
                  else attack + enchantment.attack)
        health = (enchantment.set_health if enchantment.set_health is not None
                  else health + enchantment.health)
    return attack, health


def derived_attack(entity, ordinary):
    """Pure conditional addition and final self-health; no permanent writes."""
    relations = tuple(a for a in entity.abilities if a.kind == 'stat_relation' and not a.consumed)
    if not relations:
        return max(0, ordinary) + entity.weapon_attack
    for ability in relations:
        if type(ability.stat_relation) is not StatRelationSpec:
            raise ValueError('Unknown continuous stat relation payload')
        ability.stat_relation.__post_init__()
    armor = tuple(a for a in relations if a.stat_relation.operand == StatRelationOperand.CONTROLLER_ARMOR)
    if armor:
        if entity.kind != CardType.WEAPON or len(relations) != 1 or entity.components or entity.weapon_attack:
            raise ValueError('Unsupported controller-armor weapon Attack carrier')
        return max(0, entity.conditional_attack)
    additive_weapon = tuple(a for a in relations if a.stat_relation.operand in (
        StatRelationOperand.CONTROLLER_OVERLOADED_MANA,StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE))
    if additive_weapon:
        if entity.kind != CardType.WEAPON or len(relations) != 1 or entity.components or entity.weapon_attack:
            raise ValueError('Unsupported conditional weapon Attack carrier')
        return max(0, ordinary + entity.conditional_attack)
    if entity.kind != CardType.MINION or entity.components or entity.weapon_attack:
        raise ValueError('Unsupported continuous stat relation carrier')
    if any(a.stat_relation.layer == StatRelationLayer.FINAL_ATTACK for a in relations):
        return max(0, entity.health)
    bonus = (sum(a.stat_relation.amount for a in relations
                 if a.stat_relation.operand == StatRelationOperand.SELF_DAMAGED)
             if entity.damage > 0 else 0)
    return max(0, ordinary + bonus + entity.conditional_attack)


def resolve_stat(entity, value):
    """Resolve all references before applying any writes in a composite effect."""
    if isinstance(value, StatReference):
        return max(0, getattr(entity, value.value))
    return value
