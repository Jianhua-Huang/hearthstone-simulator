"""Explicit original Colossal material follows the actually selected text prefix."""
from dataclasses import dataclass

from .model import AppendageSpec, CardType, Keyword, _name


@dataclass(frozen=True)
class AssembleColossalSource:
    card_id: str
    appendages: tuple[AppendageSpec, ...]

    def __post_init__(self):
        _name(self.card_id, 'assembly Colossal source')
        if self.card_id.startswith('assemble:'):
            raise ValueError('Assembly Colossal material requires a static original source')
        if type(self.appendages) is not tuple or not self.appendages:
            raise ValueError('Assembly Colossal material requires its complete ordered native appendages')
        for spec in self.appendages:
            if type(spec) is not AppendageSpec:
                raise ValueError('Assembly Colossal material requires native appendage declarations')
            spec.__post_init__()


def validate_source(registry, profile):
    if type(profile) is not AssembleColossalSource:
        raise ValueError('Invalid assembly Colossal source declaration')
    profile.__post_init__()
    original = registry._cards.get(profile.card_id)
    if (original is None or original.kind != CardType.MINION or original.choice_only or
            Keyword.COLOSSAL not in original.keywords or original.colossal != profile.appendages):
        raise ValueError('Assembly Colossal source changed its complete original appendage material')
    for spec in profile.appendages:
        limb = registry._cards.get(spec.card_id)
        if limb is None or limb.kind != CardType.MINION or limb.choice_only:
            raise ValueError('Assembly Colossal source requires every executable original appendage')


def prefix_appendages(registry, source):
    profile = registry._assemble_colossal_sources.get(source.card_id)
    if Keyword.COLOSSAL not in source.prefix.keywords:
        if profile is not None:
            raise ValueError('Assembly Colossal source lost its actual native prefix')
        return ()
    if profile is None:
        raise ValueError('Assembly Colossal prefix requires its reviewed complete original source')
    validate_source(registry, profile)
    return profile.appendages


def validate_sources(registry):
    for cid, profile in registry._assemble_colossal_sources.items():
        validate_source(registry, profile)
        template = registry._assemble_templates.get(cid)
        if (cid != profile.card_id or template is None or Keyword.COLOSSAL not in template.prefix.keywords or
                cid in registry._assemble_projections):
            raise ValueError('Assembly Colossal declaration requires its actual native minion template')
