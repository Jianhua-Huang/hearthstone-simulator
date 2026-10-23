"""Physical native damage spells made from a captured minion Attack.

This material is distinct from an actual Deathrattle's recorded Attack. The
allocation and value are frozen at body acceptance; later source changes never
reprice an existing spell. Allocation consistency is not unsigned-origin proof.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import AddToHand, Effect, _player
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, SourceAttackSpellValue, _name


@dataclass(frozen=True)
class SourceAttackSpellProfile:
    card_id: str
    source_card_id: str
    behavior_id: str

    def __post_init__(self):
        for field in ('card_id', 'source_card_id', 'behavior_id'):
            _name(getattr(self, field), 'source Attack spell '+field)


def validate_profile(registry, profile):
    from .native_spell_values import SpellBaseDamageProfile, validate_profile as validate_native
    if type(profile) is not SourceAttackSpellProfile:
        raise ValueError('Expected a complete source Attack spell declaration')
    profile.__post_init__()
    native = registry.spell_value_profiles.get(profile.card_id)
    if (type(native) is not SpellBaseDamageProfile or
            native.source_card_id != profile.source_card_id):
        raise ValueError('Source Attack spell differs from its original native spell declaration')
    validate_native(registry, native)
    registry.behavior(profile.behavior_id)


def validate_value(state, registry, value):
    if type(value) is not SourceAttackSpellValue:
        raise ValueError('Expected captured source Attack spell material')
    value.__post_init__()
    validate_profile(registry, registry.source_attack_spell_profiles.get(value.card_id))
    validate_allocation(state, registry, value.source)
    source = registry.card(value.source.card_id)
    if (source.kind != CardType.MINION or source.interactable is not None or
            value.turn > state.turn or value.action > state.action_number):
        raise ValueError('Source Attack spell lost its ordinary minion or original chronology')


def validate_ability(state, registry, ability):
    ability.__post_init__()
    if ability.kind != 'spell_base_value':
        raise ValueError('Source Attack spell requires a native damage attachment')
    validate_value(state, registry, ability.spell_base_value)
    if ability.source_id != ability.spell_base_value.source.entity_id:
        raise ValueError('Source Attack spell borrowed another physical source')


def install(state, registry, entity, value):
    from .native_spell_values import VALUE_KINDS
    validate_value(state, registry, value)
    if (entity.kind != CardType.SPELL or entity.card_id != value.card_id or
            any(a.kind in VALUE_KINDS for a in entity.abilities)):
        raise ValueError('Source Attack spell requires its single original spell face')
    entity.abilities.append(AbilityInstance(attachment_id(state), 'spell_base_value',
        source_id=value.source.entity_id, spell_base_value=value))


@dataclass(frozen=True)
class CreateSourceAttackSpell(Effect):
    player_id: int
    value: SourceAttackSpellValue

    def __post_init__(self):
        _player(self.player_id)
        if type(self.value) is not SourceAttackSpellValue:
            raise ValueError('Source Attack creation requires complete original material')
        self.value.__post_init__()
        if self.player_id != self.value.source.controller:
            raise ValueError('Source Attack spell changed its original recipient')


def request(context, card_id):
    return CreateSourceAttackSpell(context.player_id, SourceAttackSpellValue(card_id,
        max(0, context.source.attack), SourceAllocationFact.capture(context.state, context.source),
        context.state.turn, context.state.action_number))


def create(r, effect):
    from .opening import create_hand_card
    effect.__post_init__()
    validate_value(r.state, r.registry, effect.value)
    create_hand_card(r, AddToHand(effect.player_id, effect.value.card_id,
        effect.value.source.entity_id), native_spell_value=effect.value)
    return ()


def register(mechanics):
    mechanics.register(CreateSourceAttackSpell, create)
