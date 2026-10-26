"""Two real native provider qualifications; no dynamic grants or expression graph."""
from .model import CardType,CostAuraSpec,CostSpec,NativeSourceCondition


def leaf(condition):
    if type(condition)is not NativeSourceCondition:raise ValueError('Native source condition requires its typed declaration')
    condition.__post_init__()
    return ('spell_damage' if condition.kind == 'self_damaged' else
        'transform_replacement' if condition.kind == 'transform_destination_plus_two' else 'cost_aura')


def validate_definition(card):
    condition=card.native_condition
    if condition is None:return
    kind=leaf(condition)
    if card.kind!=CardType.MINION or not card.hand_playable or card.starship_for:
        raise ValueError('Native source conditions require an ordinary physical minion')
    if kind=='spell_damage':
        if type(card.spell_damage)is not int or card.spell_damage<=0 or card.cost_auras:
            raise ValueError('Damaged provider requires positive native Spell Damage without conditional cost sharing')
    elif kind == 'transform_replacement':
        if card.spell_damage or card.cost_auras:
            raise ValueError('Native transformation replacement cannot share conditional numeric providers')
    else:
        expected=(CostAuraSpec(CostSpec(delta=-2,card_types=(CardType.SPELL,)),relation='friendly_arcane_spells')if condition.kind=='controller_other_dragon'
            else CostAuraSpec(CostSpec(set_to=0,card_types=(CardType.HERO_POWER,))))
        if card.spell_damage or card.cost_auras!=(expected,):raise ValueError('Native conditional cost provider differs from its complete declared recipe')


def validate_carrier(registry,card_id,kind,abilities,components=()):
    from .blight_damage_replacement import validate_carrier as validate_blight_carrier
    validate_blight_carrier(registry,card_id,kind,abilities)
    from .remaining_mana_numbers import validate_carrier as validate_remaining_carrier
    validate_remaining_carrier(registry,card_id,kind,abilities,components)
    from .rotating_discovery_classes import validate_carrier as validate_discovery_class_carrier
    validate_discovery_class_carrier(registry,card_id,kind,abilities,components)
    from .colossal_reserves import validate_carrier as validate_colossal_reserve_carrier
    validate_colossal_reserve_carrier(registry,card_id,kind,abilities,components)
    from .native_stat_gains import validate_carrier as validate_stat_gain_carrier
    validate_stat_gain_carrier(registry,card_id,kind,abilities,components)
    card=registry.card(card_id);rows=tuple(a for a in abilities if a.native_condition is not None)
    from .crafted_faces import PREFIX, recipe_from_id
    if card_id.startswith(PREFIX):
        from collections import Counter
        recipe=recipe_from_id(card_id)
        if kind!=CardType.MINION or components!=recipe.parts:
            raise ValueError('Crafted conditional provider lost its original ordered parts')
        parts=tuple(registry.card(cid) for cid in recipe.parts)
        if not rows and not any(p.native_condition is not None for p in parts):return
        for part in parts:
            validate_definition(part)
            if part.native_condition is not None and part.native_condition.kind!='self_damaged':
                raise ValueError('Crafted provider has an unreviewed native condition')
        declared=Counter((p.native_condition,p.spell_damage,p.spell_damage_schools) for p in parts if p.spell_damage)
        installed=Counter()
        for ability in abilities:
            if ability.native_condition is not None or ability.kind=='spell_damage' and ability.origin=='printed':
                ability.__post_init__()
                key=(ability.native_condition,ability.spell_damage,ability.spell_damage_schools)
                if ability.kind!='spell_damage' or ability.origin!='printed':
                    raise ValueError('Crafted condition borrowed a foreign provider kind')
                installed[key]+=1
                if installed[key]>declared[key]:
                    raise ValueError('Crafted Spell Damage changed its native conditional material')
        return
    if not rows and card.native_condition is None:return
    validate_definition(card)
    if kind!=CardType.MINION or components:raise ValueError('Native conditional providers require non-composite minions')
    declared=card.native_condition;installed=0
    for ability in abilities:
        if ability.native_condition is None:
            if declared is not None and ability.origin=='printed'and ability.kind==leaf(declared):
                raise ValueError('Native provider lost its original qualification')
            continue
        ability.__post_init__()
        if declared is None or ability.native_condition!=declared or ability.kind!=leaf(declared):
            raise ValueError('Conditional provider borrowed a different native declaration')
        if ability.kind=='spell_damage'and(ability.spell_damage!=card.spell_damage or ability.spell_damage_schools!=card.spell_damage_schools):
            raise ValueError('Conditional Spell Damage differs from its native provider')
        if ability.kind=='cost_aura'and ability.cost_aura!=card.cost_auras[0]:
            raise ValueError('Conditional cost aura differs from its native provider')
        installed+=1
        if installed>1:raise ValueError('Duplicate native conditional provider')


def matches(state,holder,condition,*,registry=None):
    if condition is None:return True
    leaf(condition)
    if condition.kind=='self_damaged':return holder.damage>0
    if condition.kind == 'transform_destination_plus_two':
        from .model import Zone
        return holder.zone == Zone.BOARD and holder.active and not holder.doomed and holder.health > 0
    if condition.kind=='controller_other_dragon':
        if registry is None:raise ValueError('Current Dragon condition requires the original registry')
        from .arcane_dragon_providers import other_dragons
        return bool(other_dragons(state,registry,holder.controller,holder.id))
    return len(state.players[holder.controller].hand)<=condition.max_hand
