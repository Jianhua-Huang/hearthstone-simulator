"""Explicit local Assemble exclusions, separate from official pool eligibility."""
from dataclasses import dataclass

from .model import _name


@dataclass(frozen=True)
class AssembleLocalRestriction:
    card_id: str
    policy_id: str
    # Empty means the source is excluded in both text roles. Otherwise only
    # recipes using this source's suffix at these unresolved timings are denied.
    suffix_timings: tuple[str, ...] = ()

    def __post_init__(self):
        from .assemble_faces import TIMINGS
        _name(self.card_id, 'locally restricted assembly source')
        _name(self.policy_id, 'local assembly restriction policy')
        if (type(self.suffix_timings) is not tuple or
                any(type(t) is not str or t not in TIMINGS for t in self.suffix_timings) or
                len(set(self.suffix_timings)) != len(self.suffix_timings)):
            raise ValueError('Local assembly restriction requires unique known timings')


def validate_restriction(registry, profile):
    if type(profile) is not AssembleLocalRestriction:
        raise ValueError('Local assembly restriction requires an explicit declaration')
    profile.__post_init__()
    if profile.card_id not in registry._cards:
        raise ValueError('Local assembly restriction requires a known physical source')
    if profile.suffix_timings:
        template = registry.assemble_templates.get(profile.card_id)
        if template is None or not set(profile.suffix_timings) <= set(template.suffix.pending_timings):
            raise ValueError('Local suffix restriction must name explicitly unresolved source timings')


def source_restriction(registry, card_id):
    profile = registry.assemble_local_restrictions.get(card_id)
    return profile if profile is not None and not profile.suffix_timings else None


def suffix_restriction(registry, prefix, suffix_card_id):
    from .assemble_faces import prefix_timings
    profile = registry.assemble_local_restrictions.get(suffix_card_id)
    return profile if profile is not None and any(
        timing in profile.suffix_timings for timing in prefix_timings(prefix)) else None


def require_recipe(registry, recipe, prefix=None):
    for card_id in (recipe.primary_card_id, recipe.secondary_card_id):
        profile = source_restriction(registry, card_id)
        if profile is not None:
            raise ValueError('Locally restricted assembly source: '+card_id+' ['+profile.policy_id+']')
    if prefix is not None:
        suffix_id = recipe.secondary_card_id if recipe.half == 'bottom' else recipe.primary_card_id
        profile = suffix_restriction(registry, prefix, suffix_id)
        if profile is not None:
            raise ValueError('Locally restricted assembly timing remains explicitly unimplemented: '+
                ','.join(profile.suffix_timings)+' ['+profile.policy_id+']')
