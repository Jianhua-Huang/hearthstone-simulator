"""Player-owned skill values; reuse original effects, activation and health math."""
from dataclasses import dataclass, replace

from .effects import Effect, GainArmor, _integer, _player, _source
from .model import PlayerEffect, PlayerEffectSpec

ARMOR = 'hero_power_armor'
NEXT_DAMAGE = 'next_power_damage'
KINDS = (ARMOR, NEXT_DAMAGE)


@dataclass(frozen=True)
class HeroPowerValueProfile:
    effect_id: str
    amount: int

    def __post_init__(self):
        from .construction import name
        name(self.effect_id, 'personal skill value program')
        _integer(self.amount, 'personal skill value addition', 1)


def validate_profile(registry, profile):
    if type(profile) is not HeroPowerValueProfile:
        raise ValueError('Skill values require their explicit finite registry profile')
    profile.__post_init__()
    spec = registry.player_effect(profile.effect_id)
    if spec.kind not in KINDS or spec != PlayerEffectSpec(spec.id, spec.card_id, spec.kind):
        raise ValueError('Skill value program cannot combine other player-effect text')


def profile_for(registry, effect_id, kind):
    profile = registry.hero_power_value_profiles.get(effect_id)
    if profile is None:
        raise ValueError('Personal skill value program lost its numeric declaration')
    validate_profile(registry, profile)
    if registry.player_effect(effect_id).kind != kind:
        raise ValueError('Personal skill value borrowed another kind of program')
    return profile


def validate_configuration(registry):
    for spec in registry.player_effects.values():
        if spec.kind in KINDS:
            profile_for(registry, spec.id, spec.kind)


@dataclass(frozen=True)
class HeroPowerValuePlan:
    player_id: int
    turn: int
    before: tuple[PlayerEffect, ...]
    claimed: tuple[PlayerEffect, ...]

    def __post_init__(self):
        _player(self.player_id); _integer(self.turn, 'skill value turn', 1)
        for rows in (self.before, self.claimed):
            if type(rows) is not tuple or any(type(e) is not PlayerEffect for e in rows):
                raise ValueError('Skill value plan requires complete immutable player effects')
            for effect in rows:
                effect.__post_init__()
                if effect.created_turn > self.turn:
                    raise ValueError('Skill value plan borrowed future player effects')
            if any(a.id >= b.id or a.entered_order >= b.entered_order for a,b in zip(rows, rows[1:])):
                raise ValueError('Skill value plan changed original acquisition order')
        if not self.claimed or any(e not in self.before for e in self.claimed):
            raise ValueError('Skill value plan must claim its original pending instances')


def validate_plan(state, registry, plan, *, acceptance=False):
    if type(plan) is not HeroPowerValuePlan:
        raise ValueError('Expected a typed original personal skill value plan')
    plan.__post_init__()
    expected = tuple(e for e in plan.before if registry.player_effect(e.spec_id).kind == NEXT_DAMAGE)
    if expected != plan.claimed:
        raise ValueError('Skill value plan omitted part of its original pending account')
    for effect in plan.before:
        registry.player_effect(effect.spec_id); registry.card(effect.source_card_id)
        if effect.id >= state.next_attachment_id or effect.entered_order >= state.next_order or effect.source_id not in state.entities:
            raise ValueError('Skill value plan has an unknown or future original allocation')
    for effect in plan.claimed:
        profile_for(registry, effect.spec_id, NEXT_DAMAGE)
        if effect.created_turn != plan.turn or effect.remaining_turns is not None:
            raise ValueError('Skill value plan borrowed an expired or timed pending instance')
    if acceptance:
        remaining = tuple(e for e in plan.before if e not in plan.claimed)
        if tuple(state.players[plan.player_id].player_effects) != remaining:
            raise ValueError('Skill acceptance changed its complete original post-consumption account')


def claim(r, record):
    before = tuple(r.player(record.player_id).player_effects)
    claimed = tuple(e for e in before if r.registry.player_effect(e.spec_id).kind == NEXT_DAMAGE)
    if not claimed:
        return record
    if record.failure is not None or record.value_plan is not None:
        raise ValueError('Next-skill damage requires one successful new activation')
    plan = HeroPowerValuePlan(record.player_id, record.turn, before, claimed)
    validate_plan(r.state, r.registry, plan)
    record = replace(record, value_plan=plan)
    r.state.hero_power_history[record.id-1] = record
    used = {e.id for e in claimed}
    r.player(record.player_id).player_effects = [e for e in before if e.id not in used]
    from .player_effects import public_effect
    for effect in claimed:
        data = public_effect(r.registry, effect); data['remaining_turns'] = 0
        r.emit('player_effect_expired', source_id=effect.source_id, player_id=record.player_id, **data)
    return record


def validate_acceptance(state, registry, record):
    if record.value_plan is None:
        if any(registry.player_effect(e.spec_id).kind == NEXT_DAMAGE
                for e in state.players[record.player_id].player_effects):
            raise ValueError('Skill acceptance omitted its pending next-power value')
    else:
        validate_plan(state, registry, record.value_plan, acceptance=True)


def validate_history(state, registry):
    if not registry.hero_power_value_profiles and not any(r.value_plan is not None for r in state.hero_power_history):
        return
    live = {e.id for p in state.players.values() for e in p.player_effects}
    claimed = set()
    for record in state.hero_power_history:
        if record.value_plan is None:
            continue
        plan = record.value_plan; validate_plan(state, registry, plan)
        if (plan.player_id, plan.turn) != (record.player_id, record.turn) or record.failure is not None:
            raise ValueError('Skill value plan borrowed another original activation')
        for effect in plan.claimed:
            if effect.id in live or effect.id in claimed:
                raise ValueError('Skill value instance was reused after original consumption')
            claimed.add(effect.id)


def damage_bonus(state, registry, source_id, player_id):
    record = next((r for r in reversed(state.hero_power_history) if r.source_id == source_id and
        r.player_id == player_id and not r.completed and not r.interrupted and r.failure is None), None)
    if record is None or record.value_plan is None:
        return 0
    return sum(profile_for(registry, e.spec_id, NEXT_DAMAGE).amount for e in record.value_plan.claimed)


@dataclass(frozen=True)
class GainHeroPowerArmor(Effect):
    player_id: int
    source_id: int
    power_id: int
    amount: int

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if self.source_id is None: raise ValueError('Skill Armor requires its original source')
        _integer(self.power_id, 'original skill activation', 1)
        _integer(self.amount, 'base skill Armor', 0)


def armor_effect(context, amount, registry):
    if context.power is None or not registry.hero_power_value_profiles:
        return GainArmor(context.player_id, amount)
    return GainHeroPowerArmor(context.player_id, context.source_id, context.power.id, amount)


def armor(r, request):
    from .hero_powers import power_record
    request.__post_init__(); record = power_record(r.state, request.power_id)
    if ((record.source_id, record.player_id) != (request.source_id, request.player_id) or
            record.completed or record.interrupted or record.failure is not None):
        raise ValueError('Skill Armor lost its original active activation')
    bonus = sum(profile_for(r.registry, e.spec_id, ARMOR).amount
        for e in r.player(request.player_id).player_effects if r.registry.player_effect(e.spec_id).kind == ARMOR)
    return (GainArmor(request.player_id, request.amount+bonus),)


def plan_from_dict(value):
    if value is None: return None
    from .serialization import _row, _list, player_effect_from_dict
    row = _row(value, HeroPowerValuePlan)
    for key in ('before', 'claimed'):
        row[key] = tuple(player_effect_from_dict(e) for e in _list(row[key], 'skill value '+key))
    return HeroPowerValuePlan(**row)


def register(mechanics):
    mechanics.register(GainHeroPowerArmor, armor)
    mechanics.register_payload_type(HeroPowerValuePlan)
