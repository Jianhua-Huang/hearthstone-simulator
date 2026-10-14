"""Trusted declaration bindings for future body-target dispatch.

These are host-only, current-state authority checks. They do not accept a play,
pay, execute bodies, create player capabilities or authenticate a saved game.
Ordinary target planning deliberately remains separate from authorization.
"""
from dataclasses import dataclass

from .body_grants import BodyReference
from .body_targets import (BodyTargetDeclaration, BodyTargetReference,
                          body_target_declaration, body_target_declarations)
from .body_target_preflight import (PaidBodyTargetRequest, PaidBodyTargetSubmission,
                                   preflight_paid_body_targets)
from .effects import _behavior
from .errors import IllegalAction
from .model import CardType


@dataclass(frozen=True)
class BodyTargetBinding:
    declaration_card_id: str
    family: str
    profile_id: str
    origins: tuple[str, ...] = ('printed', 'granted')
    carrier_kinds: tuple[CardType, ...] = (CardType.MINION, CardType.WEAPON, CardType.HERO)
    carrier_card_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _behavior(self.declaration_card_id)
        _behavior(self.profile_id)
        if type(self.family) is not str or self.family not in ('battlecry', 'combo'):
            raise ValueError('Body target binding requires its exact family')
        if (type(self.origins) is not tuple or not self.origins or
                any(type(o) is not str or o not in ('printed', 'granted') for o in self.origins) or
                len(set(self.origins)) != len(self.origins)):
            raise ValueError('Body target binding requires unique explicit physical origins')
        if (type(self.carrier_kinds) is not tuple or not self.carrier_kinds or
                any(type(k) is not CardType or k not in (CardType.MINION, CardType.WEAPON, CardType.HERO)
                    for k in self.carrier_kinds) or len(set(self.carrier_kinds)) != len(self.carrier_kinds)):
            raise ValueError('Body target binding requires unique supported physical carrier kinds')
        if type(self.carrier_card_ids) is not tuple or len(set(self.carrier_card_ids)) != len(self.carrier_card_ids):
            raise ValueError('Body target carrier restrictions require unique immutable card IDs')
        for card_id in self.carrier_card_ids:
            _behavior(card_id)


def validate_binding(registry, binding):
    """Validate trusted registration references without executing callbacks."""
    if type(binding) is not BodyTargetBinding:
        raise ValueError('Expected exact typed BodyTargetBinding')
    binding.__post_init__()
    registry.body_target_profile(binding.profile_id)
    from .body_targets import body_target_contract
    body_target_contract(registry, binding.declaration_card_id, binding.family)
    for card_id in binding.carrier_card_ids:
        if registry.card(card_id).kind not in binding.carrier_kinds:
            raise ValueError('Body target carrier restriction differs from its allowed physical kinds')


@dataclass(frozen=True)
class BodyTargetAuthority:
    binding: BodyTargetBinding
    declaration: BodyTargetDeclaration

    def __post_init__(self):
        if type(self.binding) is not BodyTargetBinding or type(self.declaration) is not BodyTargetDeclaration:
            raise ValueError('Body target authority needs its exact binding and physical declaration')
        self.binding.__post_init__()
        self.declaration.__post_init__()
        b, d = self.binding, self.declaration
        ref = d.reference
        if (b.declaration_card_id, b.family, b.profile_id) != (
                ref.declaration_card_id, ref.family, d.profile.id):
            raise ValueError('Body target authority borrowed another declaration, family or profile')
        if (ref.origin not in b.origins or d.source_kind not in b.carrier_kinds or
                b.carrier_card_ids and ref.carrier.card_id not in b.carrier_card_ids):
            raise ValueError('Body target authority exceeds its registered provenance or carrier scope')


def _authority(registry, declaration):
    ref = declaration.reference
    binding = registry.body_target_binding(ref.declaration_card_id, ref.family, declaration.profile.id)
    validate_binding(registry, binding)
    try:
        return BodyTargetAuthority(binding, declaration)
    except ValueError as exc:
        raise IllegalAction(str(exc)) from None


def body_target_authorities(state, registry, carrier, profile_id):
    """Resolve every current physical body through trusted declaration bindings.

The carrier's printed policy never implicitly authorizes a granted declaration.
Suppressed and untargeted bodies must have bindings too. A physical copy can
resolve a new authority, but cannot reuse the original reference or receipt.
"""
    return tuple(_authority(registry, d) for d in body_target_declarations(state, registry, carrier, profile_id))



def matching_body_target_authorities(state, registry, carrier, profile_id):
    """Pure complete-policy match, or None for an explicit binding/scope gap.

    Missing bindings and physical provenance/carrier mismatches are deliberate
    policy alternatives. Unknown profiles, definitions, malformed declarations
    and registrations still raise; no candidate, predicate or quote runs here.
    Empty bodies return (), which is not permission for a paid body route.
    """
    declarations = body_target_declarations(state, registry, carrier, profile_id)
    result = []
    complete = True
    for declaration in declarations:
        ref = declaration.reference
        binding = registry.body_target_bindings.get((ref.declaration_card_id, ref.family, profile_id))
        if binding is None:
            complete = False
            continue
        validate_binding(registry, binding)
        if (ref.origin not in binding.origins or declaration.source_kind not in binding.carrier_kinds or
                binding.carrier_card_ids and ref.carrier.card_id not in binding.carrier_card_ids):
            complete = False
            continue
        result.append(BodyTargetAuthority(binding, declaration))
    return tuple(result) if complete else None


def body_target_authority(state, registry, reference, profile_id):
    if type(reference) is not BodyTargetReference:
        raise ValueError('Expected exact captured body target reference')
    return _authority(registry, body_target_declaration(state, registry, reference, profile_id))


@dataclass(frozen=True)
class AuthorizedPaidBodyTargetSubmission:
    submission: PaidBodyTargetSubmission
    authorities: tuple[BodyTargetAuthority, ...]

    def __post_init__(self):
        if type(self.submission) is not PaidBodyTargetSubmission:
            raise ValueError('Expected complete typed paid target preflight')
        self.submission.__post_init__()
        if (type(self.authorities) is not tuple or not self.authorities or
                any(type(a) is not BodyTargetAuthority for a in self.authorities)):
            raise ValueError('Authorized paid body route requires every actual physical authority')
        for a in self.authorities:
            a.__post_init__()
        if tuple(a.declaration for a in self.authorities) != tuple(
                r.declaration for r in self.submission.plan.requirements):
            raise ValueError('Body target authority vector differs from the complete original target plan')


def authorize_paid_body_targets(game, request):
    """Resolve trusted bindings before running any target predicates or quotes."""
    if type(request) is not PaidBodyTargetRequest:
        raise ValueError('Expected exact typed paid target request')
    request.__post_init__()
    game._require_boundary()
    source = game.state.entities.get(request.action.entity_id)
    if source is None:
        raise IllegalAction('Body target authority requires its actual physical carrier')
    authorities = body_target_authorities(game.state, game.registry, BodyReference.capture(source), request.profile_id)
    if not authorities:
        raise IllegalAction('An authorized body target route requires at least one actual body')
    submission = preflight_paid_body_targets(game, request)
    return AuthorizedPaidBodyTargetSubmission(submission, authorities)


def validate_authorized_paid_body_targets(game, authorization):
    """Recompute current bindings and preflight; never trust a host-made receipt."""
    if type(authorization) is not AuthorizedPaidBodyTargetSubmission:
        raise ValueError('Expected exact authorized paid target preflight')
    authorization.__post_init__()
    actual = authorize_paid_body_targets(game, authorization.submission.request)
    if actual != authorization:
        raise IllegalAction('Body target authority no longer matches its trusted bindings and original state')
    return actual
