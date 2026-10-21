"""Final health loss, separate from damage packets, healing and cost amounts.

Damage keeps its nominal non-prevented amount for damage triggers/lifesteal;
only the health debit is replaced. Payment is never routed through damage.
These precise windows are a versioned prototype contract pending CN calibration.
"""
from copy import deepcopy
from dataclasses import dataclass, fields

from .effects import Effect, _integer, _player, _source
from .lifecycle import active_abilities, attachment_id, refresh_entity
from .model import (AbilityInstance, CardType, Enchantment, HealthLossKind,
                    HealthLossReplacementSpec, Zone)


@dataclass(frozen=True)
class GrantHealthLossReplacement(Effect):
    target_id: int
    spec: HealthLossReplacementSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'health loss replacement holder', 1)
        _source(self.source_id)
        if type(self.spec) is not HealthLossReplacementSpec:
            raise ValueError('Expected HealthLossReplacementSpec')
        self.spec.__post_init__()
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'health loss replacement expiry', 1)


@dataclass(frozen=True)
class LoseHealth(Effect):
    """Direct loss bypasses armor, damage rules, immunity, shields and lifesteal."""
    target_id: int
    amount: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'health loss target', 1)
        _integer(self.amount, 'health loss amount', 0)
        _source(self.source_id)


@dataclass(frozen=True)
class ConvertHeroHealthToArmor(Effect):
    """Explicit loss and its actual remaining-health debit become armor."""
    player_id: int
    amount: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'health to armor amount', 0)
        _integer(self.source_id, 'health to armor source', 1)


@dataclass(frozen=True)
class SetHeroHealth(Effect):
    """Assign remaining Hero health without changing maximum or using healing/loss."""
    target_id: int
    health: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id,'physical Hero health target',1)
        _integer(self.health,'requested remaining Hero health',0)
        _source(self.source_id)


@dataclass(frozen=True)
class GainMaxHealth(Effect):
    player_id: int
    amount: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'max health gain', 0)
        _source(self.source_id)


@dataclass(frozen=True)
class ChangeHeroMaxHealth(Effect):
    """Permanent signed maximum change; explicitly select remaining-health policy."""
    player_id: int
    amount: int
    source_id: int | None = None
    health_policy: str = 'preserve_missing'

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'maximum health change')
        _source(self.source_id)
        if type(self.health_policy) is not str or self.health_policy not in ('preserve_missing', 'clamp_current'):
            raise ValueError('Invalid remaining-health policy')


@dataclass(frozen=True)
class StealHeroHealth(Effect):
    """Atomic transfer of available maximum health, preserving both deficits."""
    player_id: int
    from_player_id: int
    amount: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _player(self.from_player_id)
        _integer(self.amount, 'stolen health amount', 0)
        _source(self.source_id)
        if self.player_id == self.from_player_id:
            raise ValueError('Health transfer requires distinct players')


@dataclass(frozen=True)
class LossReplacement:
    source_id: int
    ability_id: int


def replacement_for(state, target_id, kind):
    """Pure eligibility shared by payment validation and actual settlement."""
    target = state.entities.get(target_id)
    if target is None or target.zone != Zone.HERO or target.doomed or target.health <= 0:
        return None
    player = state.players[target.controller]
    candidates = []
    for source_id in player.board:
        source = state.entities[source_id]
        if source.kind != CardType.MINION or not source.active or source.health <= 0 or source.doomed:
            continue
        for ability in active_abilities(source, 'health_loss_replacement'):
            spec = ability.health_loss_replacement
            if kind in spec.kinds and (not spec.own_turn_only or state.active_player == player.id):
                candidates.append(LossReplacement(source.id, ability.id))
    # The original loss is consumed by one replacement, not doubled per source.
    return min(candidates, key=lambda c: c.ability_id) if candidates else None


@dataclass(frozen=True)
class HealthLossProjection:
    target: object
    next_attachment_id: int
    events: tuple
    loss_result: object | None = None


def project_max_health(state, target, amount, source_id, health_policy):
    """Pure detached target projection of the existing ordered growth formula."""
    result = deepcopy(target)
    amount = max(-max(0, result.max_health), amount)
    if not amount:
        return HealthLossProjection(result, state.next_attachment_id, ())
    old_health, old_max = result.health, result.max_health
    enchantment = Enchantment(state.next_attachment_id, source_id=source_id, health=amount,
        label='max_health_gain' if amount > 0 else 'max_health_loss', remove_on_silence=False)
    result.enchantments.append(enchantment)
    refresh_entity(result)
    if health_policy == 'clamp_current':
        result.damage = max(0, result.max_health - old_health)
    from .death_causes import dying, capture
    if dying(result):
        source = result if source_id == result.id else state.entities.get(source_id)
        if source_id is not None and source is None: raise ValueError('Death cause source does not exist')
        if result.death_cause is None:
            result.death_cause = capture(state, result, 'health_state', 'maximum_health_change', source)
    event = ('max_health_gained' if amount > 0 else 'max_health_lost', dict(source_id=source_id,
        target_id=result.id, player_id=result.controller, amount=abs(amount), old_health=old_health,
        old_max_health=old_max, health=result.health, max_health=result.max_health, enchantment_id=enchantment.id))
    return HealthLossProjection(result, state.next_attachment_id + 1, (event,))


def project_loss(state, target, amount, kind, source_id, replacement, *, floor_plan=None, event_sequence=None):
    if floor_plan is not None:
        from .health_loss_floors import project_floor_loss
        return project_floor_loss(state, target, amount, kind, source_id, replacement, floor_plan, event_sequence)
    result = deepcopy(target)
    if not amount:
        return HealthLossProjection(result, state.next_attachment_id, ())
    if replacement is None:
        result.damage += amount
        if kind != HealthLossKind.DAMAGE:
            from .death_causes import dying, capture
            if dying(result):
                source = result if source_id == result.id else state.entities.get(source_id)
                if source_id is not None and source is None: raise ValueError('Death cause source does not exist')
                if result.death_cause is None:
                    result.death_cause = capture(state, result, 'health_loss', kind.value, source)
        return HealthLossProjection(result, state.next_attachment_id, ())
    growth = project_max_health(state, result, amount, replacement.source_id, 'preserve_missing')
    event = ('health_loss_replaced', dict(source_id=source_id, target_id=result.id,
        player_id=result.controller, amount=amount, loss_kind=kind.value,
        replacement_source_id=replacement.source_id, replacement_ability_id=replacement.ability_id))
    return HealthLossProjection(growth.target, growth.next_attachment_id, (event, *growth.events))


def apply_health_projection(state, target, projection):
    # Retain the actual Entity object/identity, applying only changed fields.
    for field in fields(type(target)):
        value = getattr(projection.target, field.name)
        if getattr(target, field.name) != value:
            setattr(target, field.name, deepcopy(value))
    state.next_attachment_id = projection.next_attachment_id


def add_max_health(r, hero, amount, source_id):
    """Atomic growth preserving missing health; does not emit a healing event."""
    return adjust_max_health(r, hero, amount, source_id, 'preserve_missing')


def adjust_max_health(r, hero, amount, source_id, health_policy):
    from .hero_health_history import commit as commit_hero_health, snapshot as hero_health_snapshot
    before = hero_health_snapshot(hero)
    projection = project_max_health(r.state, hero, amount, source_id, health_policy)
    apply_health_projection(r.state, hero, projection)
    events = [(kind, dict(data)) for kind, data in projection.events]
    if events:
        kind, data = events[0]
        data.update(commit_hero_health(r.state, before, hero_health_snapshot(hero), kind))
    return events


def current_living_hero(r, player_id):
    hero = r.state.entities[r.player(player_id).hero_id]
    return hero if hero.zone == Zone.HERO and hero.health > 0 and not hero.doomed else None


def set_hero_health(r,effect):
    from .resolver import validate_attachment_source
    from .hero_health_history import snapshot as hero_health_snapshot
    from .death_causes import mark
    effect.__post_init__(); validate_attachment_source(r,effect.source_id,None)
    hero=r.state.entities.get(effect.target_id)
    if hero is not None and hero.kind!=CardType.HERO:
        raise ValueError('SetHeroHealth requires a Hero target')
    if (hero is None or hero.zone!=Zone.HERO or not hero.active or hero.health<=0 or hero.doomed
            or r.player(hero.controller).hero_id!=hero.id):
        r.stale(effect,effect.target_id); return ()
    before=hero_health_snapshot(hero)
    old_health=hero.health
    # The target maximum is preserved. Over-maximum clamping is an explicit
    # local policy pending CN calibration, not an implicit healing operation.
    assigned=min(effect.health,hero.max_health)
    hero.damage=hero.max_health-assigned
    if assigned==0: mark(r,hero,'health_state','remaining_health_assignment',effect.source_id)
    r.emit('hero_health_set',source_id=effect.source_id,target_id=hero.id,player_id=hero.controller,
        amount=assigned-old_health,requested=effect.health,old_health=old_health,
        health=assigned,max_health=hero.max_health,_hero_health_before=before)
    return ()


def change_hero_max_health(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, None)
    hero = current_living_hero(r, effect.player_id)
    if hero is None:
        return ()
    for kind, data in adjust_max_health(r, hero, effect.amount, effect.source_id, effect.health_policy):
        r.emit(kind, **data)
    return ()


def steal_hero_health(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, None)
    recipient = current_living_hero(r, effect.player_id)
    donor = current_living_hero(r, effect.from_player_id)
    if recipient is None or donor is None:
        return ()
    amount = min(effect.amount, max(0, donor.max_health))
    if not amount:
        return ()
    # A maximum-health transfer is a stat operation, not a health debit.
    # Armor, damage/healing rules and HealthLossReplacement do not intercept it.
    # Both changes happen before any trigger captures state or a death checkpoint.
    events = adjust_max_health(r, donor, -amount, effect.source_id, 'preserve_missing')
    events += adjust_max_health(r, recipient, amount, effect.source_id, 'preserve_missing')
    for kind, data in events:
        r.emit(kind, **data)
    r.emit('hero_health_stolen', source_id=effect.source_id, target_id=donor.id,
           player_id=effect.player_id, amount=amount, requested=effect.amount,
           donor_player_id=effect.from_player_id, recipient_id=recipient.id)
    return ()


def commit_loss(r, target, amount, kind, source_id, replacement):
    """Return old events, without an additional checkpoint."""
    projection = project_loss(r.state, target, amount, kind, source_id, replacement)
    apply_health_projection(r.state, target, projection)
    return list(projection.events)


def lose_health(r, effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, None)
    target = r.live_character(effect.target_id)
    if target is None:
        r.stale(effect, effect.target_id)
        return
    from .hero_health_history import commit as commit_hero_health, snapshot as hero_health_snapshot
    before = hero_health_snapshot(target)
    replacement = replacement_for(r.state, target.id, HealthLossKind.EFFECT)
    from .health_loss_floors import capture_plan, result_payload
    plan = capture_plan(r.state, r.registry, target, effect.source_id, replacement)
    if plan is None:
        events = commit_loss(r, target, effect.amount, HealthLossKind.EFFECT, effect.source_id, replacement)
        actual_lost = effect.amount if replacement is None else 0
    else:
        projection = project_loss(r.state, target, effect.amount, HealthLossKind.EFFECT, effect.source_id, replacement,
            floor_plan=plan, event_sequence=len(r.game._events)+1)
        apply_health_projection(r.state, target, projection)
        result = projection.loss_result
        health_data = commit_hero_health(r.state, before, hero_health_snapshot(target), 'health_loss_floor_resolved')
        r.emit('health_loss_floor_resolved', source_id=effect.source_id, target_id=target.id,
            player_id=target.controller, amount=result.actual_lost, _capture=False,
            loss_floor_result=result_payload(result), **health_data)
        events = projection.events
        actual_lost = result.actual_lost
    events = [(kind, dict(data)) for kind, data in events]
    health_data = {}
    if plan is None:
        origin_index = next((i for i, (kind, _) in enumerate(events)
                             if kind in ('max_health_gained', 'max_health_lost')), None)
        origin = events[origin_index][0] if origin_index is not None else 'health_lost'
        health_data = commit_hero_health(r.state, before, hero_health_snapshot(target), origin)
        if origin_index is not None:
            events[origin_index][1].update(health_data)
            health_data = {}
    for kind, data in events:
        r.emit(kind, **data)
    if actual_lost:
        r.emit('health_lost', source_id=effect.source_id, target_id=target.id,
               player_id=target.controller, amount=actual_lost, loss_kind=HealthLossKind.EFFECT.value, **health_data)


def gain_max_health(r, effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, None)
    hero = r.state.entities[r.player(effect.player_id).hero_id]
    for kind, data in add_max_health(r, hero, effect.amount, effect.source_id):
        r.emit(kind, **data)


def convert_hero_health_to_armor(r, effect):
    from .effects import GainArmor
    from .resolver import armor, validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, None)
    hero = current_living_hero(r, effect.player_id)
    if hero is None:
        return ()
    before = hero.health
    # Reuse the original EFFECT loss, including replacement and explicit floors.
    # Freeze its delta before reactions can heal, replace or otherwise change it.
    lose_health(r, LoseHealth(hero.id, effect.amount, effect.source_id))
    actual = max(0, before-hero.health)
    if actual:
        # Both numeric commits precede the normal single checkpoint. Armor does
        # not rescue a lethal loss; the ordinary fatal coordinator still owns it.
        armor(r, GainArmor(effect.player_id, actual))
    return ()


def grant(r, effect):
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id)
        return
    ability = AbilityInstance(attachment_id(r.state), 'health_loss_replacement',
        source_id=effect.source_id, health_loss_replacement=effect.spec, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def register(mechanics):
    mechanics.register(GrantHealthLossReplacement, grant)
    mechanics.register(LoseHealth, lose_health)
    mechanics.register(ConvertHeroHealthToArmor, convert_hero_health_to_armor)
    mechanics.register(SetHeroHealth, set_hero_health)
    mechanics.register(GainMaxHealth, gain_max_health)
    mechanics.register(ChangeHeroMaxHealth, change_hero_max_health)
    mechanics.register(StealHeroHealth, steal_hero_health)
