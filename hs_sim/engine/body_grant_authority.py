"""Pure authority for a proposed physical body; no target selection or payment.

A registered manual paid route authorizes storage of heterogeneous bodies.
Actual candidates, activation and the complete selection vector remain the
original payment window's responsibility. Other producers need their own route.
"""
from dataclasses import replace

from .body_grants import BodyReference
from .body_target_authority import matching_body_target_authorities
from .body_target_origin import require_audited_predicate
from .body_root_targets import validate_root_binding
from .errors import IllegalAction, ResolutionError


def authorize_grant(state, registry, entity, ability):
    """Check all current bodies plus this proposed body without mutating state.

Only a single complete, registered, connected policy is admissible. A matching
printed contract cannot bypass incomplete bindings on a bound carrier. No user
profile string, target predicate, quote, behavior or random sample is executed.
"""
    proposed = replace(entity, abilities=[*entity.abilities, ability])
    prospective = replace(state, entities={**state.entities, entity.id: proposed})
    complete = []
    for (card_id, profile_id), binding in registry.body_root_target_bindings.items():
        if card_id != entity.card_id:
            continue
        validate_root_binding(registry, binding)
        authorities = matching_body_target_authorities(prospective, registry,
            BodyReference.capture(proposed), profile_id)
        if authorities is None or not any(a.declaration.reference.ability_id == ability.id for a in authorities):
            continue
        try:
            for authority in authorities:
                require_audited_predicate(registry, authority.declaration.contract.target_rule)
            # Ordinary root predicates are a separate selection/execution policy.
            # Trusted registration is checked above; storing a body must not
            # invoke or require its unrelated ordinary target predicate. Actual
            # paid/player consumers still reject unsupported root predicates
            # before candidate evaluation, payment or behavior.
            complete.append(profile_id)
        except (IllegalAction, ValueError):
            continue
    if not complete:
        from .indirect_body_targets import grant_authority
        complete = list(grant_authority(state,registry,entity,ability))
    if not complete:
        from .generated_body_targets import grant_authority as generated_authority
        complete = list(generated_authority(state,registry,entity,ability))
    if len(complete) != 1:
        raise ResolutionError('Body grant requires exactly one complete connected origin target policy')
    return complete[0]
