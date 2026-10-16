"""Declarative target predicates with complete, reconstructible inputs.

These engine-owned rules only read facts already retained by paid-body origins.
They never call user predicates, inspect histories, or infer dynamic tribes from
printed metadata. Domains, relations and selectable protections stay in targeting.
"""
from dataclasses import dataclass

from .effects import _behavior
from .model import Keyword, Rarity, Zone


@dataclass(frozen=True)
class TargetPredicateSpec:
    id: str
    health_min: int | None = None
    health_max: int | None = None
    durability_min: int | None = None
    durability_max: int | None = None
    printed_tribes_any: tuple[str, ...] = ()
    keywords_all: tuple[Keyword, ...] = ()
    keywords_none: tuple[Keyword, ...] = ()
    attack_min: int | None = None
    attack_max: int | None = None
    max_health_min: int | None = None
    max_health_max: int | None = None
    damage_min: int | None = None
    damage_max: int | None = None
    damaged: bool | None = None
    current_tribes_any: tuple[str, ...] = ()
    printed_rarities: tuple[Rarity, ...] = ()

    def __post_init__(self):
        _behavior(self.id)
        for prefix in ('health', 'durability', 'attack', 'max_health', 'damage'):
            lower, upper = getattr(self, prefix + '_min'), getattr(self, prefix + '_max')
            for value in (lower, upper):
                if value is not None and (type(value) is not int or prefix in ('durability', 'damage') and value < 0):
                    raise ValueError('Target predicate bounds require exact integers; durability/damage are nonnegative')
            if lower is not None and upper is not None and lower > upper:
                raise ValueError('Target predicate lower bound exceeds its upper bound')
        for name, cls in (('printed_tribes_any', str), ('current_tribes_any', str), ('keywords_all', Keyword), ('keywords_none', Keyword), ('printed_rarities', Rarity)):
            values = getattr(self, name)
            if (type(values) is not tuple or any(type(value) is not cls for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError('Target predicate filters require unique immutable typed values')
            if cls is str:
                for value in values:
                    _behavior(value)
        if set(self.keywords_all) & set(self.keywords_none):
            raise ValueError('Target predicate cannot require and exclude the same keyword')
        if self.damaged is not None and type(self.damaged) is not bool:
            raise ValueError('Damaged target predicate requires an exact bool or None')
        if self.damaged is False and self.damage_min is not None and self.damage_min > 0:
            raise ValueError('Undamaged target predicate cannot require positive damage')
        if self.damaged is True and self.damage_max == 0:
            raise ValueError('Damaged target predicate cannot exclude all positive damage')


def evaluate(spec, registry, context):
    """Read only retained scalar stats, keywords and the printed card face."""
    target = context.state.entities.get(context.target_id)
    if target is None:
        return False
    if spec.printed_rarities and printed_rarity(registry, target.card_id) not in spec.printed_rarities:
        return False
    for prefix in ('health', 'durability', 'attack', 'max_health', 'damage'):
        value = getattr(target, prefix)
        lower, upper = getattr(spec, prefix + '_min'), getattr(spec, prefix + '_max')
        if lower is not None and value < lower or upper is not None and value > upper:
            return False
    if spec.damaged is not None and (target.damage > 0) != spec.damaged:
        return False
    if not set(spec.keywords_all) <= target.keywords or set(spec.keywords_none) & target.keywords:
        return False
    if spec.printed_tribes_any:
        metadata = registry.card(target.card_id).metadata
        if metadata is None or metadata.tribes is None:
            # Unknown is not the same thing as a known empty tribe tuple.
            from .registry import UnsupportedDefinitionError
            raise UnsupportedDefinitionError('Target predicate requires known printed tribes: ' + target.card_id)
        if 'all' not in metadata.tribes and not set(spec.printed_tribes_any) & set(metadata.tribes):
            return False
    if spec.current_tribes_any:
        from .tribes import has_any_tribe
        if not has_any_tribe(registry, target, spec.current_tribes_any):
            return False
    return True


def printed_rarity(registry, card_id):
    metadata = registry.card(card_id).metadata
    if metadata is None or metadata.rarity is None:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Printed rarity is unknown: ' + card_id)
    return metadata.rarity


def reconstructible(registry, name):
    """Explicit engine-owned declarations; a user callback cannot opt in by ID."""
    return (registry.target_visibility(name) == 'builtin' and
            (name in ('any_entity', 'any_character') or registry.target_predicate(name) is not None))


def player_domain_supported(registry, name, domain):
    """Reject blind opposing-hand filtering before any candidate is inspected."""
    if registry.target_predicate(name) is None or domain is None:
        return True
    return Zone.HAND not in domain.zones or domain.relation == 'friendly'
