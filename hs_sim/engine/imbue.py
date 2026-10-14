"""Player-owned Imbue history and explicitly versioned class power mappings.

R-100: attempts and successful growth are separate. A declared class without a
power has no growth; a missing adapter is an error. Replacing an unrelated power
creates a fresh instance; upgrading the current power preserves its usage/costs.
"""
from dataclasses import dataclass, replace

from .construction import name
from .effects import Effect, ReplaceHeroPower, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardClass, CardType, ImbueRecord


PLAYABLE_CLASSES = frozenset(c for c in CardClass if c != CardClass.NEUTRAL)


@dataclass(frozen=True)
class ImbueClass:
    hero_class: CardClass
    power_card_id: str | None

    def __post_init__(self):
        if type(self.hero_class) is not CardClass or self.hero_class not in PLAYABLE_CLASSES:
            raise ValueError('Imbue requires a playable hero class')
        if self.power_card_id is not None:
            name(self.power_card_id, 'Imbued power')


@dataclass(frozen=True)
class ImbueProfile:
    id: str
    version: str
    classes: tuple[ImbueClass, ...]

    def __post_init__(self):
        name(self.id, 'Imbue profile'); name(self.version, 'Imbue profile version')
        if type(self.classes) is not tuple or any(type(c) is not ImbueClass for c in self.classes):
            raise ValueError('Imbue class mappings must be immutable typed declarations')
        for rule in self.classes:
            rule.__post_init__()
        if len(self.classes) != len(PLAYABLE_CLASSES) or {c.hero_class for c in self.classes} != PLAYABLE_CLASSES:
            raise ValueError('Every playable class needs an explicit Imbue mapping')

    def power_for(self, hero_class):
        if type(hero_class) is not CardClass or hero_class not in PLAYABLE_CLASSES:
            raise ValueError('Imbue requires a known current hero class')
        return next(c.power_card_id for c in self.classes if c.hero_class == hero_class)


def validate_profiles(registry):
    for profile in registry.imbue_profiles.values():
        profile.__post_init__()
        for rule in profile.classes:
            # A named, not-yet-adapted power remains an explicit execution gap.
            # It must never be downgraded to None by inspecting implemented cards.
            if rule.power_card_id in registry.cards and registry.card(rule.power_card_id).kind != CardType.HERO_POWER:
                raise ValueError('Imbue mappings require hero power definitions')


def imbue_count(state, player_id, *, applied_only=False):
    _player(player_id)
    if type(applied_only) is not bool:
        raise ValueError('Imbue count filter must be boolean')
    return sum(x.player_id == player_id and (not applied_only or x.power_card_id is not None)
               for x in state.imbue_history)


def imbue_value(state, player_id, *, base=1, step=1):
    """Capture scalable effect parameters at activation; this never changes cost."""
    _integer(base, 'Imbue base amount', 0); _integer(step, 'Imbue growth amount', 0)
    return base + max(0, imbue_count(state, player_id, applied_only=True) - 1) * step


@dataclass(frozen=True)
class Imbue(Effect):
    player_id: int
    source_id: int | None = None
    count: int = 1
    profile_id: str = 'imbue'

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        _integer(self.count, 'Imbue count', 0); name(self.profile_id, 'Imbue profile')


def imbue(r, effect):
    from .zones import source_exists
    from .hero_powers import install_hero_power
    effect.__post_init__(); source_exists(r, effect.source_id)
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Imbue count exceeds resolution budget')
    if effect.count == 0:
        return ()
    profile = r.registry.imbue_profile(effect.profile_id)
    player = r.player(effect.player_id)
    power_card_id = profile.power_for(player.hero_class)
    history = [x for x in r.state.imbue_history if x.player_id == player.id]
    if history and history[-1].profile_id != profile.id:
        raise ResolutionError('A player cannot switch Imbue profiles during a match')
    if power_card_id is not None and r.registry.card(power_card_id).kind != CardType.HERO_POWER:
        raise ResolutionError('Imbue target must be a hero power')
    old_id = player.hero_power_id
    old = r.state.entities.get(old_id)
    replacing = power_card_id is not None and (old is None or old.card_id != power_card_id)
    applied_before = sum(x.power_card_id is not None for x in history)
    if replacing:
        _, power = install_hero_power(r, ReplaceHeroPower(player.id, power_card_id))
        power_id = power.id
    else:
        power_id = old_id if power_card_id is not None else None
    record = ImbueRecord(len(r.state.imbue_history) + 1, player.id, effect.source_id,
        player.hero_class, profile.id, profile.version, len(history), applied_before,
        old_id, power_id, power_card_id, r.state.turn, r.state.action_number)
    r.state.imbue_history.append(record)
    if replacing:
        r.emit('hero_power_replaced', source_id=old_id, target_id=power_id, player_id=player.id)
    r.emit('imbued' if power_card_id is not None else 'imbue_no_effect', source_id=effect.source_id,
           target_id=power_id, player_id=player.id, amount=len(history) + 1,
           level=applied_before + int(power_card_id is not None))
    return (replace(effect, count=effect.count - 1),) if effect.count > 1 else ()


def validate_history(state, registry):
    if type(state.imbue_history) is not list:
        raise ValueError('Imbue history must be a list')
    counts = {1:0, 2:0}; applied = {1:0, 2:0}; profiles = {}; previous_time = (0,0)
    for index, record in enumerate(state.imbue_history, 1):
        if type(record) is not ImbueRecord:
            raise ValueError('Invalid Imbue history record')
        record.__post_init__()
        profile = registry.imbue_profile(record.profile_id)
        power_card_id = profile.power_for(record.hero_class)
        if (record.id != index or record.count_before != counts[record.player_id] or
                record.applied_before != applied[record.player_id] or record.profile_version != profile.version or
                record.power_card_id != power_card_id or
                profiles.get(record.player_id, profile.id) != profile.id or
                record.source_id is not None and record.source_id not in state.entities or
                not previous_time <= (record.turn,record.action) <= (state.turn,state.action_number)):
            raise ValueError('Invalid Imbue progress, profile or provenance')
        for entity_id in (record.old_power_id, record.power_id):
            if entity_id is None:
                continue
            entity = state.entities.get(entity_id)
            if entity is None or entity.kind != CardType.HERO_POWER or entity.owner != record.player_id:
                raise ValueError('Imbue history refers to an invalid power identity')
        if power_card_id is not None:
            if registry.card(power_card_id).kind != CardType.HERO_POWER:
                raise ValueError('Imbue history refers to a non-power definition')
            if record.power_id != record.old_power_id and (
                    record.old_power_id is not None and record.power_id <= record.old_power_id or
                    record.source_id is not None and record.power_id <= record.source_id):
                raise ValueError('Imbue replacement identity predates its source')
            applied[record.player_id] += 1
        counts[record.player_id] += 1; profiles[record.player_id] = profile.id
        previous_time = (record.turn,record.action)


def progress(state, player_id):
    return {'count':imbue_count(state, player_id), 'level':imbue_count(state, player_id, applied_only=True)}


def register(mechanics):
    mechanics.register(Imbue, imbue)
