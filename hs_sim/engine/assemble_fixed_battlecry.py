"""Original targetless Battlecry material retained by an actual death prefix."""
from dataclasses import dataclass

from .model import CardType, _name


@dataclass(frozen=True)
class AssembleFixedBattlecrySource:
    card_id: str
    battlecry_id: str

    def __post_init__(self):
        _name(self.card_id, 'assembly fixed Battlecry source')
        _name(self.battlecry_id, 'assembly fixed Battlecry body')
        if self.card_id.startswith('assemble:'):
            raise ValueError('Fixed Battlecry material requires its original static minion')


def validate_source(registry, source):
    if type(source) is not AssembleFixedBattlecrySource:
        raise ValueError('Invalid assembly fixed Battlecry source')
    source.__post_init__()
    original = registry._cards.get(source.card_id)
    if (original is None or original.kind != CardType.MINION or original.choice_only or
            original.battlecry != source.battlecry_id or original.deathrattle is None or
            original.requires_target or original.targeting is not None or original.target_rule != 'any_entity'):
        raise ValueError('Fixed Battlecry material changed its complete original targetless body')
    registry.behavior(source.battlecry_id)


def prefix_battlecry(registry, template):
    source = registry._assemble_fixed_battlecry_sources.get(template.card_id)
    if source is None:
        original = registry._cards.get(template.card_id)
        if (template.prefix.timing == 'deathrattle' and original is not None and
                original.kind == CardType.MINION and original.battlecry is not None):
            raise ValueError('Death prefix requires its reviewed original fixed Battlecry material')
        return None
    validate_source(registry, source)
    if template.prefix.timing != 'deathrattle':
        raise ValueError('Fixed Battlecry material requires its actual native death prefix')
    return source.battlecry_id


def validate_sources(registry):
    for cid, source in registry._assemble_fixed_battlecry_sources.items():
        validate_source(registry, source)
        if (cid != source.card_id or cid not in registry._assemble_templates or
                cid in registry._assemble_projections):
            raise ValueError('Fixed Battlecry material requires its actual original minion template')
        prefix_battlecry(registry, registry._assemble_templates[cid])
