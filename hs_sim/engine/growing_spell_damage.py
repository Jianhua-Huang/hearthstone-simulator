"""One frozen native base, ordinary damage, and a newly shuffled successor."""
from dataclasses import dataclass

from .effects import Damage,Effect,_integer
from .lifecycle import attachment_id
from .model import AbilityInstance,CardType,DamageKind,GrowingSpellDamageValue,Zone,_name


@dataclass(frozen=True)
class GrowingDamageProfile:
    card_id: str
    initial_amount: int
    policy: str = 'shuffle_base_plus_one'

    def __post_init__(self):
        _name(self.card_id, 'growing damage spell')
        _integer(self.initial_amount, 'printed growing spell damage', 1)
        if type(self.policy) is not str or self.policy != 'shuffle_base_plus_one':
            raise ValueError('Growing spell requires its declared new-successor policy')


def validate_profile(registry,profile):
    if type(profile) is not GrowingDamageProfile:
        raise ValueError('Expected the complete growing spell profile')
    profile.__post_init__();card=registry.card(profile.card_id)
    if card.kind!=CardType.SPELL or not card.hand_playable or card.on_play is None:
        raise ValueError('Growing damage requires its actual ordinary spell')


def validate_value(state,registry,value):
    """Walk strictly older cast values without Python recursion or a new ledger."""
    if type(value) is not GrowingSpellDamageValue:
        raise ValueError('Expected complete growing spell material')
    value.__post_init__();profile=registry.spell_value_profiles.get(value.card_id)
    validate_profile(registry,profile)
    first=None;cursor=value
    while True:
        cursor.__post_init__()
        if cursor.card_id!=profile.card_id or cursor.parent_cast_id>len(state.cast_history):
            raise ValueError('Growing spell lost its original parent face or cast')
        parent=state.cast_history[cursor.parent_cast_id-1]
        if (parent.id!=cursor.parent_cast_id or parent.card_id!=profile.card_id or
                not parent.payload_started or parent.failure is not None):
            raise ValueError('Growing spell parent never executed its original payload')
        if first is None:first=parent
        ability=parent.native_spell_value
        if ability is None:
            if cursor.amount!=profile.initial_amount+1:
                raise ValueError('First successor differs from its printed parent base plus one')
            return first
        ability.__post_init__()
        previous=ability.spell_base_value
        if (ability.kind!='spell_base_value' or type(previous) is not GrowingSpellDamageValue or
                ability.id>=state.next_attachment_id or previous.parent_cast_id>=parent.id or
                previous.card_id!=profile.card_id or cursor.amount!=previous.amount+1):
            raise ValueError('Growing spell ancestry is inconsistent or not strictly older')
        previous.__post_init__()
        origin=state.cast_history[previous.parent_cast_id-1]
        if ability.source_id!=origin.source_id:
            raise ValueError('Growing spell ancestry borrowed another original source')
        cursor=previous


def validate_ability(state,registry,ability):
    ability.__post_init__()
    if ability.kind!='spell_base_value':raise ValueError('Expected a native damage value ability')
    parent=validate_value(state,registry,ability.spell_base_value)
    if ability.source_id!=parent.source_id:
        raise ValueError('Growing spell material changed its original cast source')


def install(state,registry,entity,value):
    parent=validate_value(state,registry,value)
    from .native_spell_values import VALUE_KINDS
    if entity.kind!=CardType.SPELL or entity.card_id!=value.card_id or any(a.kind in VALUE_KINDS for a in entity.abilities):
        raise ValueError('Growing spell requires its single matching physical carrier')
    ability=AbilityInstance(attachment_id(state),'spell_base_value',source_id=parent.source_id,spell_base_value=value)
    validate_ability(state,registry,ability);entity.abilities.append(ability)


def original_cast(state,registry,cast_id):
    from .spell_casts import active_cast,cast_record
    cast=cast_record(state,cast_id);profile=registry.spell_value_profiles.get(cast.card_id)
    validate_profile(registry,profile)
    if (not cast.payload_started or cast.completed or cast.interrupted or cast.failure is not None or
            active_cast(state,cast.source_id,cast.player_id)!=cast):
        raise ValueError('Growing damage lost its actual active original cast')
    return cast,profile


def base_amount(state,registry,cast,profile):
    if cast.native_spell_value is None:return profile.initial_amount
    validate_ability(state,registry,cast.native_spell_value)
    value=cast.native_spell_value.spell_base_value
    if value.card_id!=cast.card_id:raise ValueError('Growing cast borrowed another native face')
    return value.amount


@dataclass(frozen=True)
class DamageGrowingSpell(Effect):
    cast_id: int
    def __post_init__(self):_integer(self.cast_id,'growing damage cast',1)
    def validate_in_state(self,state,registry):
        self.__post_init__();return original_cast(state,registry,self.cast_id)


@dataclass(frozen=True)
class ShuffleGrowingSpell(DamageGrowingSpell):
    pass


def damage(r,request):
    cast,profile=request.validate_in_state(r.state,r.registry)
    amount=base_amount(r.state,r.registry,cast,profile)
    fact=cast.target_origin;target=r.state.entities.get(cast.target_id)
    follow=(ShuffleGrowingSpell(cast.id),)
    if (fact is None or fact.kind not in (CardType.HERO,CardType.MINION) or fact.zone not in (Zone.HERO,Zone.BOARD)):
        raise ValueError('Growing damage lost its original character allocation')
    if (target is None or not target.active or
            (target.card_id,target.kind,target.owner,target.controller,target.zone,target.zone_epoch,target.entered_order)!=
            (fact.card_id,fact.kind,fact.owner,fact.controller,fact.zone,fact.zone_epoch,fact.entered_order)):
        r.stale(request,fact.entity_id);return follow
    return (Damage(target.id,amount,cast.source_id,DamageKind.SPELL),*follow)


def shuffle(r,request):
    cast,profile=request.validate_in_state(r.state,r.registry)
    value=GrowingSpellDamageValue(cast.card_id,base_amount(r.state,r.registry,cast,profile)+1,cast.id)
    validate_value(r.state,r.registry,value)
    from .zones import AddToDeck,create_deck_card
    create_deck_card(r,AddToDeck(cast.player_id,cast.card_id,source_id=cast.source_id),native_spell_value=value)
    return ()


def inherit_play(r,entity,original_state,play_id):
    from .play_history import play_record
    original=play_record(original_state,play_id)
    if original.card_id!=entity.card_id or original.kind!=CardType.SPELL:
        raise ValueError('Growing replay borrowed another selected physical occurrence')
    casts=tuple(c for c in original_state.cast_history if c.play_id==original.id and c.card_id==original.card_id)
    actual=next((c for c in casts if c.payload_started and c.failure is None),None)
    if actual is not None:
        if actual.native_spell_value is None:return
        abilities=(actual.native_spell_value,)
    else:
        abilities=tuple(c.native_spell_value for c in casts if c.native_spell_value is not None)
        if not abilities:
            abilities=tuple(a for a in original_state.entities[original.source_id].abilities if a.kind=='spell_base_value' and
                type(a.spell_base_value) is GrowingSpellDamageValue and a.spell_base_value.card_id==entity.card_id)
    if not abilities:return
    if any(a.spell_base_value!=abilities[0].spell_base_value for a in abilities):
        raise ValueError('Growing replay has ambiguous original native material')
    for ability in abilities:validate_ability(original_state,r.registry,ability)
    install(r.state,r.registry,entity,abilities[0].spell_base_value)


def register(mechanics):
    mechanics.register(DamageGrowingSpell,damage)
    mechanics.register(ShuffleGrowingSpell,shuffle)
    mechanics.register_payload_type(GrowingSpellDamageValue)
