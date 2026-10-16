"""Two real native provider qualifications; no dynamic grants or expression graph."""
from .model import CardType,CostAuraSpec,CostSpec,NativeSourceCondition


def leaf(condition):
    if type(condition)is not NativeSourceCondition:raise ValueError('Native source condition requires its typed declaration')
    condition.__post_init__()
    return 'spell_damage'if condition.kind=='self_damaged'else'cost_aura'


def validate_definition(card):
    condition=card.native_condition
    if condition is None:return
    kind=leaf(condition)
    if card.kind!=CardType.MINION or not card.hand_playable or card.starship_for:
        raise ValueError('Native source conditions require an ordinary physical minion')
    if kind=='spell_damage':
        if type(card.spell_damage)is not int or card.spell_damage<=0 or card.cost_auras:
            raise ValueError('Damaged provider requires positive native Spell Damage without conditional cost sharing')
    elif card.spell_damage or card.cost_auras!=(CostAuraSpec(CostSpec(set_to=0,card_types=(CardType.HERO_POWER,))),):
        raise ValueError('Small-hand provider requires one native friendly zero-cost Hero Power aura')


def validate_carrier(registry,card_id,kind,abilities,components=()):
    card=registry.card(card_id);rows=tuple(a for a in abilities if a.native_condition is not None)
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


def matches(state,holder,condition):
    if condition is None:return True
    leaf(condition)
    if condition.kind=='self_damaged':return holder.damage>0
    return len(state.players[holder.controller].hand)<=condition.max_hand
