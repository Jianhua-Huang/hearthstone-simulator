"""A bounded two-use primary power exchange retaining the actual original entity."""
from dataclasses import dataclass, replace

from .effects import Effect, ReplaceHeroPower, _player, _source
from .model import CardType, HeroPowerRecord, TemporaryHeroPowerReturn, Zone, _name


@dataclass(frozen=True)
class TemporaryHeroPowerProfile:
    card_id: str
    stages: tuple[str, str]

    def __post_init__(self):
        _name(self.card_id, 'temporary power source')
        if type(self.stages) is not tuple or len(self.stages) != 2 or len(set(self.stages)) != 2:
            raise ValueError('Temporary power requires its two distinct original use faces')
        for cid in self.stages: _name(cid, 'temporary power face')


def validate_profile(registry, profile):
    if type(profile) is not TemporaryHeroPowerProfile: raise ValueError('Expected temporary power profile')
    profile.__post_init__(); source = registry.card(profile.card_id)
    if source.kind != CardType.SPELL or source.on_play is None or source.choice_only:
        raise ValueError('Temporary power requires an ordinary native spell')
    faces = [registry.card(cid) for cid in profile.stages]
    if any(c.kind != CardType.HERO_POWER or c.on_use is None or c.passive_hero_power or c.choose_one is not None
           or c.choice_only or c.use_rule != 'always' or c.requires_board_space for c in faces):
        raise ValueError('Temporary faces require ordinary active native hero powers')
    if len({(c.cost, c.uses_per_turn) for c in faces}) != 1:
        raise ValueError('Temporary remaining-use faces must preserve cost and ordinary use limit')


def original_entity(state, binding):
    if binding.original_id is None: return None
    entity = state.entities.get(binding.original_id)
    if (entity is None or entity.kind != CardType.HERO_POWER or entity.controller != binding.player_id or
            entity.zone != Zone.SETASIDE or (entity.zone_epoch, entity.entered_order) !=
            (binding.original_epoch, binding.original_order)):
        raise ValueError('Temporary power lost its exact parked original entity')
    return entity


def historical_face_transitions(state, registry):
    """Compute actual declared evolutions once, rather than rescan per history row."""
    stages = {p.stages[0]: p.stages for p in registry.temporary_hero_power_profiles.values()}
    if not stages: return frozenset()
    return frozenset((row.source_id, *stages[row.card_id]) for row in state.hero_power_history
        if type(row) is HeroPowerRecord and row.card_id in stages and row.origin == 'manual'
        and row.completed and not row.interrupted and row.failure is None)


def validate_state(state, registry):
    bindings = state.temporary_power_returns
    if type(bindings) is not dict: raise ValueError('Temporary powers require their physical binding map')
    faces = {}
    for profile in registry.temporary_hero_power_profiles.values():
        validate_profile(registry, profile)
        for cid in profile.stages:
            if cid in faces: raise ValueError('Temporary power face belongs to multiple declarations')
            faces[cid] = profile
    incoming = {}
    for key, binding in bindings.items():
        if type(key) is not int or type(binding) is not TemporaryHeroPowerReturn or key != binding.power_id:
            raise ValueError('Temporary power lost its typed physical identity')
        binding.__post_init__()
        profile = registry.temporary_hero_power_profiles.get(binding.profile_card_id)
        power = state.entities.get(key)
        if (profile is None or power is None or power.kind != CardType.HERO_POWER or
                power.controller != binding.player_id or power.card_id != profile.stages[len(binding.use_ids)] or
                power.zone not in (Zone.HERO_POWER, Zone.SETASIDE)):
            raise ValueError('Temporary power differs from its actual original phase or carrier')
        if power.zone == Zone.HERO_POWER and state.players[binding.player_id].hero_power_id != key:
            raise ValueError('Temporary exchange may only occupy the primary power slot')
        original = original_entity(state, binding)
        if original is not None:
            if original.id in incoming: raise ValueError('Original hero power was borrowed by two exchanges')
            incoming[original.id] = key
        for use_id in binding.use_ids:
            if use_id > len(state.hero_power_history): raise ValueError('Temporary power borrowed a future use')
            row = state.hero_power_history[use_id-1]
            if (row.id, row.source_id, row.player_id, row.card_id, row.origin, row.completed, row.failure) != (
                    use_id, key, binding.player_id, profile.stages[0], 'manual', True, None):
                raise ValueError('Temporary power phase lacks its actual completed original use')
    for key in bindings:
        seen = set(); cursor = key
        while cursor in bindings:
            if cursor in seen: raise ValueError('Temporary power return chain is cyclic')
            seen.add(cursor); cursor = bindings[cursor].original_id
        if state.entities[key].zone == Zone.SETASIDE and key not in incoming:
            raise ValueError('Suspended temporary power has no owning outer exchange')
    for entity in state.entities.values():
        if entity.kind == CardType.HERO_POWER and entity.card_id in faces and entity.zone in (Zone.HERO_POWER, Zone.SETASIDE):
            if entity.id not in bindings: raise ValueError('Temporary power lacks its original return material')


@dataclass(frozen=True)
class SwapTemporaryHeroPower(Effect):
    player_id: int
    profile_card_id: str
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _name(self.profile_card_id, 'temporary power source'); _source(self.source_id)


def swap(r, request):
    from .hero_powers import install_hero_power
    request.__post_init__()
    profile = r.registry.temporary_hero_power_profiles.get(request.profile_card_id)
    validate_profile(r.registry, profile)
    old_id, power = install_hero_power(r, ReplaceHeroPower(request.player_id, profile.stages[0],
        source_id=request.source_id), retirement_zone=Zone.SETASIDE)
    old = r.state.entities[old_id] if old_id is not None else None
    binding = TemporaryHeroPowerReturn(power.id, request.player_id, profile.card_id,
        old_id, old.zone_epoch if old else None, old.entered_order if old else None)
    r.state.temporary_power_returns[power.id] = binding
    validate_state(r.state, r.registry)
    r.emit('hero_power_replaced', source_id=old_id, target_id=power.id, player_id=request.player_id)
    return ()


def cancel(r, power_id):
    """A foreign removal/replacement abandons the entire parked return chain."""
    retired = []
    while (binding := r.state.temporary_power_returns.pop(power_id, None)) is not None:
        original = original_entity(r.state, binding)
        if original is None: break
        retired.append(original); power_id = original.id
    for original in reversed(retired): r.move(original, Zone.GRAVEYARD)


def change_face(r, power, card_id):
    from .lifecycle import install_printed
    definition = r.registry.card(card_id)
    granted = [a for a in power.abilities if a.origin != 'printed']
    power.card_id, power.name, power.base_cost = card_id, definition.name, definition.cost
    install_printed(r.state, power, definition, r.registry)
    power.abilities.extend(granted)


def after_use(r, record):
    """One completed paid activation, independent of repeated/triggered payloads."""
    if record.origin != 'manual' or record.failure is not None: return
    binding = r.state.temporary_power_returns.get(record.source_id)
    if binding is None: return  # A legitimate foreign replacement may already have cancelled it.
    validate_state(r.state, r.registry)
    profile = r.registry.temporary_hero_power_profiles[binding.profile_card_id]
    power = r.state.entities[binding.power_id]
    if record.card_id != profile.stages[len(binding.use_ids)] or record.player_id != binding.player_id:
        raise ValueError('Temporary power use belongs to another original phase')
    if not binding.use_ids:
        r.state.temporary_power_returns[power.id] = replace(binding, use_ids=(record.id,))
        change_face(r, power, profile.stages[1])
        if power.zone == Zone.HERO_POWER:
            r.emit('hero_power_replaced', source_id=power.id, target_id=power.id, player_id=binding.player_id)
        return
    original = original_entity(r.state, binding)
    r.state.temporary_power_returns.pop(power.id)
    if power.zone == Zone.SETASIDE:
        parents = [key for key, value in r.state.temporary_power_returns.items() if value.original_id == power.id]
        if len(parents) != 1: raise ValueError('Exhausted suspended power lost its outer exchange')
        parent = r.state.temporary_power_returns[parents[0]]
        r.state.temporary_power_returns[parents[0]] = replace(parent, original_id=binding.original_id,
            original_epoch=binding.original_epoch, original_order=binding.original_order)
        r.move(power, Zone.GRAVEYARD)
        return
    r.move(power, Zone.GRAVEYARD)
    if original is not None:
        r.move(original, Zone.HERO_POWER)
        original.uses_this_turn = 0  # The ordinary fresh installation policy, without rebuilding material.
        r.emit('hero_power_replaced', source_id=power.id, target_id=original.id, player_id=binding.player_id)
    else:
        r.emit('hero_power_removed', source_id=power.id, target_id=power.id, player_id=binding.player_id)


def register(mechanics): mechanics.register(SwapTemporaryHeroPower, swap)
