"""Exact native static rules travel with the actually selected text prefix."""
from dataclasses import dataclass

from .model import CardType, KeywordAuraSpec, MinionDeathCostSpec, _name


@dataclass(frozen=True)
class AssembleStaticMaterialSource:
    card_id: str
    keyword_auras: tuple[KeywordAuraSpec, ...] = ()
    minion_death_cost: MinionDeathCostSpec | None = None

    def __post_init__(self):
        _name(self.card_id, 'assembly static material source')
        if self.card_id.startswith('assemble:'):
            raise ValueError('Assembly static material requires an original static source')
        if type(self.keyword_auras) is not tuple:
            raise ValueError('Assembly static material requires its complete ordered aura tuple')
        for spec in self.keyword_auras:
            if type(spec) is not KeywordAuraSpec:
                raise ValueError('Assembly static material requires native keyword aura declarations')
            spec.__post_init__()
        if self.minion_death_cost is not None:
            if type(self.minion_death_cost) is not MinionDeathCostSpec:
                raise ValueError('Assembly static material requires a native death-price declaration')
            self.minion_death_cost.__post_init__()
        if not self.keyword_auras and self.minion_death_cost is None:
            raise ValueError('Assembly static material cannot be an empty substitute')


def validate_source(registry, profile):
    if type(profile) is not AssembleStaticMaterialSource:
        raise ValueError('Invalid assembly static material declaration')
    profile.__post_init__()
    original = registry._cards.get(profile.card_id)
    if (original is None or original.kind != CardType.MINION or original.choice_only or
            original.keyword_auras != profile.keyword_auras or
            original.minion_death_cost != profile.minion_death_cost):
        raise ValueError('Assembly static material changed its complete original native declarations')


def prefix_materials(registry, source):
    profile = registry._assemble_static_material_sources.get(source.card_id)
    if profile is None:
        original = registry._cards.get(source.card_id)
        if original is not None and (original.keyword_auras or original.minion_death_cost is not None):
            raise ValueError('Assembly static prefix requires its reviewed complete original material')
        return (), None
    validate_source(registry, profile)
    return profile.keyword_auras, profile.minion_death_cost


def validate_sources(registry):
    for cid, profile in registry._assemble_static_material_sources.items():
        validate_source(registry, profile)
        if cid != profile.card_id or cid not in registry._assemble_templates or cid in registry._assemble_projections:
            raise ValueError('Assembly static material requires its actual original minion template')
