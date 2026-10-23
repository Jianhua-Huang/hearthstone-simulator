"""Finite live native minion permissions for originally untargeted skills."""
from dataclasses import dataclass

from .lifecycle import active_abilities
from .model import CardType, TargetSpec, Zone, _name

MARKER = 'hero_power_targets'


@dataclass(frozen=True)
class HeroPowerMinionTargetProfile:
    card_id: str
    power_ids: tuple[str, ...]

    def __post_init__(self):
        _name(self.card_id, 'native skill target source')
        if (type(self.power_ids) is not tuple or not self.power_ids or
                self.power_ids != tuple(sorted(set(self.power_ids)))):
            raise ValueError('Skill target permissions require an ordered finite skill family')
        for cid in self.power_ids:
            _name(cid, 'native targetable skill')


def validate_profile(registry, profile):
    if type(profile) is not HeroPowerMinionTargetProfile:
        raise ValueError('Expected a finite native skill target profile')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if (card.kind != CardType.MINION or card.choice_only or card.starship_for or
            card.interactable is not None):
        raise ValueError('Skill target permissions require an ordinary native minion')
    from .targeting import target_spec
    for cid in profile.power_ids:
        power = registry.card(cid)
        if (power.kind != CardType.HERO_POWER or power.passive_hero_power or not power.on_use or
                target_spec(power) is not None or power.choose_one is not None or
                power.target_rule != 'any_entity'):
            raise ValueError('Native minion targeting requires an original untargeted active skill')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    markers = tuple(a for a in abilities if a.kind == MARKER)
    if not markers:
        return
    if (kind != CardType.MINION or components or len(markers) != 1 or
            card_id not in registry.hero_power_target_profiles):
        raise ValueError('Skill target marker borrowed an undeclared native minion')
    markers[0].__post_init__()


def applies(state, registry, source, definition):
    if (not registry.hero_power_target_profiles or source.kind != CardType.HERO_POWER or
            definition.kind != CardType.HERO_POWER):
        return False
    for entity_id in state.players[source.controller].board:
        entity = state.entities[entity_id]
        if (entity.zone != Zone.BOARD or entity.kind != CardType.MINION or not entity.active or
                entity.silenced or entity.doomed or entity.health <= 0):
            continue
        markers = active_abilities(entity, MARKER)
        if not markers:
            continue
        validate_carrier(registry, entity.card_id, entity.kind, markers, entity.components)
        if definition.id in registry.hero_power_target_profiles[entity.card_id].power_ids:
            return True
    return False


def effective_spec(state, registry, source, definition, spec):
    return TargetSpec() if applies(state, registry, source, definition) else spec


def target_allowed(state, registry, source, definition, target):
    if not applies(state, registry, source, definition):
        return True
    return target.kind == CardType.MINION or (
        target.kind == CardType.HERO and target.controller != source.controller)
