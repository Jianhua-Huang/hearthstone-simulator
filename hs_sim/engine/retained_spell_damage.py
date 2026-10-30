"""A real spell's damage remainder, tied to its cast and settled health receipt."""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact
from .effects import Damage, Effect, _integer
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, DamageKind, HealthFlow, SpellRemainderDamageValue, Zone, _name
from .sacrifice import MinionReference, reference_value, live_minion


@dataclass(frozen=True)
class ReturningDamageProfile:
    card_id: str
    initial_amount: int

    def __post_init__(self):
        _name(self.card_id, 'returning damage spell')
        _integer(self.initial_amount, 'printed returning spell damage', 1)


def validate_profile(registry, profile):
    if type(profile) is not ReturningDamageProfile:
        raise ValueError('Expected a complete returning damage profile')
    profile.__post_init__(); card = registry.card(profile.card_id)
    if card.kind != CardType.SPELL or not card.hand_playable or card.on_play is None:
        raise ValueError('Returning damage requires its actual ordinary spell')


def remainder(result):
    if (result.original_flow != HealthFlow.DAMAGE.value or result.flow != HealthFlow.DAMAGE.value or
            result.damage_kind != DamageKind.SPELL.value or result.target_kind != CardType.MINION.value or
            result.prevention is not None or result.converted or result.from_lifesteal or
            result.health_before <= 0 or result.doomed_before): return 0
    return max(0, result.health_lost-result.health_before)


def validate_value(state, registry, value):
    if type(value) is not SpellRemainderDamageValue:
        raise ValueError('Expected original settled spell remainder')
    value.__post_init__(); profile = registry.spell_value_profiles.get(value.card_id)
    validate_profile(registry, profile)
    from .spell_casts import cast_record
    cast = cast_record(state, value.cast_id)
    if not 1 <= value.damage_id <= len(state.damage_history):
        raise ValueError('Spell remainder lost its original damage result')
    row = state.damage_history[value.damage_id-1]; result = row.health_result
    from .next_spell_bodies import possible_body_target_ids
    if (row.id != value.damage_id or cast.card_id != value.card_id or not cast.payload_started or
            cast.failure is not None or result.batch_id <= cast.recorded_event or row.action < cast.action or
            (result.source_id, result.source_card_id, result.source_controller) !=
            (cast.source_id, cast.card_id, cast.player_id) or
            result.original_target_id not in possible_body_target_ids(registry, cast) or remainder(result) != value.amount):
        raise ValueError('Spell remainder differs from its actual cast and original excess damage')
    return cast


def validate_ability(state, registry, ability):
    ability.__post_init__()
    cast = validate_value(state, registry, ability.spell_base_value)
    if ability.kind != 'spell_base_value' or ability.source_id != cast.source_id:
        raise ValueError('Spell remainder changed its original source allocation')


def install(state, registry, entity, value):
    cast = validate_value(state, registry, value)
    from .native_spell_values import VALUE_KINDS
    if entity.kind != CardType.SPELL or entity.card_id != value.card_id or any(a.kind in VALUE_KINDS for a in entity.abilities):
        raise ValueError('Spell remainder requires its single matching physical carrier')
    ability = AbilityInstance(attachment_id(state), 'spell_base_value', source_id=cast.source_id,
        spell_base_value=value)
    validate_ability(state, registry, ability); entity.abilities.append(ability)


@dataclass(frozen=True)
class DamageReturningSpell(Effect):
    cast_id: int
    target: MinionReference

    def __post_init__(self):
        _integer(self.cast_id, 'returning damage cast', 1); reference_value(self.target)

    def validate_in_state(self, state, registry):
        self.__post_init__()
        from .spell_casts import cast_record, active_cast
        cast = cast_record(state, self.cast_id)
        profile = registry.spell_value_profiles.get(cast.card_id); validate_profile(registry, profile)
        from .next_spell_bodies import body_target_id
        if (not cast.payload_started or cast.completed or cast.interrupted or cast.failure is not None or
                body_target_id(registry, cast) != self.target.entity_id or active_cast(state, cast.source_id, cast.player_id) != cast):
            raise ValueError('Returning damage lost its original active cast or target')
        target = state.entities.get(self.target.entity_id)
        if (target is None or self.target.zone_epoch > target.zone_epoch or self.target.entered_order >= state.next_order):
            raise ValueError('Returning damage borrowed an unknown or future target')
        return cast, profile


def damage(r, request):
    cast, profile = request.validate_in_state(r.state, r.registry)
    if live_minion(r.state, request.target) is None:
        r.stale(request, request.target.entity_id); return ()
    amount = profile.initial_amount
    if cast.native_spell_value is not None:
        value = cast.native_spell_value.spell_base_value
        validate_ability(r.state, r.registry, cast.native_spell_value)
        if type(value) is not SpellRemainderDamageValue:
            raise ResolutionError('Returning spell borrowed unrelated native parameters')
        amount = value.amount
    source = r.state.entities[cast.source_id]
    fact = SourceAllocationFact.capture(r.state, source) if source.zone == Zone.GRAVEYARD else None
    damage_id = r.state.next_damage_id
    from .resolver import settle_health_batch
    continued = settle_health_batch(r, (Damage(request.target.entity_id, amount, cast.source_id, DamageKind.SPELL),))
    if fact is None or damage_id >= r.state.next_damage_id: return continued
    result = r.state.damage_history[damage_id-1].health_result
    amount = remainder(result)
    if not amount: return continued
    value = SpellRemainderDamageValue(cast.card_id, amount, cast.id, damage_id)
    validate_value(r.state, r.registry, value)
    from .spent_spells import ReturnSpentSpell
    return (*continued, ReturnSpentSpell(fact, cast.player_id, native_value=value))


def inherit_play(r, entity, original_state, play_id):
    from .play_history import play_record
    original = play_record(original_state, play_id)
    if original.card_id != entity.card_id or original.kind != CardType.SPELL:
        raise ValueError('Returning spell replay borrowed another physical hand occurrence')
    casts = tuple(c for c in original_state.cast_history if c.play_id == original.id and c.card_id == original.card_id)
    actual = next((c for c in casts if c.payload_started and c.failure is None), None)
    if actual is not None:
        if actual.native_spell_value is None: return
        abilities = (actual.native_spell_value,)
    else:
        source = original_state.entities[original.source_id]
        abilities = tuple(a for a in source.abilities if a.kind == 'spell_base_value' and
            type(a.spell_base_value) is SpellRemainderDamageValue and a.spell_base_value.card_id == entity.card_id)
    if not abilities: return
    if len(abilities) != 1: raise ValueError('Returning replay has ambiguous original native parameters')
    validate_ability(original_state, r.registry, abilities[0])
    install(r.state, r.registry, entity, abilities[0].spell_base_value)


def register(mechanics):
    mechanics.register(DamageReturningSpell, damage)
    mechanics.register_payload_type(SpellRemainderDamageValue)
