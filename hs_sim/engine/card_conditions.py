"""Shared structural card predicates for real instances and fresh candidates."""
from .model import CardAbilityCondition


class UnknownCardFactError(ValueError):
    """A required structural fact is missing; it is not a negative match."""


def matches_ability_values(condition, *, printed, current):
    """Match explicit structural facts; None is unknown, never absent."""
    if type(condition) is not CardAbilityCondition:
        raise ValueError('Expected CardAbilityCondition')
    condition.__post_init__()
    for value in (printed, current):
        if value is not None and type(value) is not bool:
            raise ValueError('Ability presence requires boolean or unknown')
    present = printed if condition.basis == 'printed' else current
    if present is None:
        raise UnknownCardFactError('Unknown candidate Battlecry identity')
    return present == condition.present


def has_battlecry(abilities):
    """Frozen death attachments and live attachments share structural identity."""
    return any(a.kind == 'battlecry' and not a.consumed for a in abilities)


def matches_ability(condition, definition, entity=None):
    if type(condition) is not CardAbilityCondition:
        raise ValueError('Expected CardAbilityCondition')
    condition.__post_init__()
    if entity is not None and (entity.card_id, entity.kind) != (definition.id, definition.kind):
        raise ValueError('Card condition instance and definition disagree')
    # A generated candidate represents a fresh instance. Current and printed
    # identities coincide until lifecycle operations alter its attachments.
    printed = definition.battlecry is not None
    # Structural presence differs from activation eligibility (e.g. dormancy).
    current = printed if entity is None else has_battlecry(entity.abilities)
    return matches_ability_values(condition, printed=printed, current=current)
