"""Pure paid-hand body-vector preflight for the future dispatch consumer.

The original carrier PlayCard must still satisfy the current action contract.
No accepted history, target producer, player capability, payment or dispatch is
created here. The plan is a host artifact describing this exact stable state.
"""
from dataclasses import dataclass, replace
import re

from .actions import PlayCard
from .body_conditions import BodyPlayConditions
from .body_grants import BodyReference
from .body_targets import BodyTargetDeclaration, BodyTargetReference, body_target_declarations
from .costs import CostQuote, quote_cost
from .effects import _behavior, _source
from .errors import IllegalAction
from .model import PaymentType, Zone


@dataclass(frozen=True)
class BodyTargetSelection:
    body: BodyTargetReference
    target_id: int | None

    def __post_init__(self):
        if type(self.body) is not BodyTargetReference: raise ValueError('Target selection requires its exact physical body')
        self.body.__post_init__(); _source(self.target_id)


@dataclass(frozen=True)
class PaidBodyTargetRequest:
    action: PlayCard
    profile_id: str
    selections: tuple[BodyTargetSelection, ...]

    def __post_init__(self):
        if type(self.action) is not PlayCard: raise ValueError('Paid body targets require an original PlayCard')
        self.action.__post_init__(); _behavior(self.profile_id)
        if type(self.selections) is not tuple or any(type(s) is not BodyTargetSelection for s in self.selections):
            raise ValueError('Paid body selections require a typed immutable vector')
        for s in self.selections:
            s.__post_init__()
            if (s.body.carrier.entity_id, s.body.carrier.player_id) != (self.action.entity_id, self.action.player_id):
                raise ValueError('Body selection borrowed another carrier or seat')
        if len({s.body.ability_id for s in self.selections}) != len(self.selections):
            raise ValueError('A physical body attachment may appear only once in the submitted vector')


@dataclass(frozen=True)
class PaidBodyTargetRequirement:
    declaration: BodyTargetDeclaration
    conditions: BodyPlayConditions
    body_active: bool
    target_active: bool
    target_choices: tuple[int | None, ...]

    def __post_init__(self):
        if type(self.declaration) is not BodyTargetDeclaration or type(self.conditions) is not BodyPlayConditions:
            raise ValueError('Body target requirement needs its typed declaration and own conditions')
        self.declaration.__post_init__(); self.conditions.__post_init__()
        if type(self.body_active) is not bool or type(self.target_active) is not bool or self.target_active and not self.body_active:
            raise ValueError('Body target activation flags disagree')
        if type(self.target_choices) is not tuple or len(set(self.target_choices)) != len(self.target_choices):
            raise ValueError('Body target choices must be an ordered unique immutable tuple')
        for target in self.target_choices: _source(target)
        if not self.target_active and self.target_choices != (None,):
            raise ValueError('Disabled body targeting must retain its explicit empty selection')


@dataclass(frozen=True)
class PaidBodyTargetPlan:
    action: PlayCard
    profile_id: str
    carrier: BodyReference
    quote: CostQuote
    registry_fingerprint: str
    original_state_hash: str
    magnetic_host: BodyReference | None
    requirements: tuple[PaidBodyTargetRequirement, ...]

    def __post_init__(self):
        if type(self.action) is not PlayCard: raise ValueError('Expected original paid PlayCard')
        self.action.__post_init__(); _behavior(self.profile_id)
        if type(self.carrier) is not BodyReference: raise ValueError('Expected original physical hand carrier')
        self.carrier.__post_init__()
        if self.carrier.zone != Zone.HAND or (self.carrier.entity_id, self.carrier.player_id) != (self.action.entity_id, self.action.player_id):
            raise ValueError('Paid target plan lost its actual original hand source')
        if type(self.quote) is not CostQuote or (self.quote.entity_id, self.quote.player_id) != (self.action.entity_id, self.action.player_id):
            raise ValueError('Paid target quote belongs to another source')
        if self.magnetic_host is not None:
            if type(self.magnetic_host) is not BodyReference: raise ValueError('Expected captured magnetic host')
            self.magnetic_host.__post_init__()
            if self.magnetic_host.zone != Zone.BOARD or self.magnetic_host.player_id != self.action.player_id:
                raise ValueError('Magnetic target plan has an invalid original host')
        for value in (self.registry_fingerprint, self.original_state_hash):
            if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None: raise ValueError('Expected exact host fingerprint')
        if type(self.requirements) is not tuple or any(type(r) is not PaidBodyTargetRequirement for r in self.requirements):
            raise ValueError('Paid body requirements must be a typed immutable vector')
        for r in self.requirements:
            r.__post_init__()
            if r.declaration.reference.carrier != self.carrier or r.declaration.profile.id != self.profile_id:
                raise ValueError('Body requirement differs from its original source or profile')
        if len({r.declaration.reference.ability_id for r in self.requirements}) != len(self.requirements):
            raise ValueError('Paid target plan duplicated a physical body')


@dataclass(frozen=True)
class PaidBodyTargetSubmission:
    request: PaidBodyTargetRequest
    plan: PaidBodyTargetPlan
    selected: tuple[BodyTargetSelection, ...]

    def __post_init__(self):
        if type(self.request) is not PaidBodyTargetRequest or type(self.plan) is not PaidBodyTargetPlan:
            raise ValueError('Paid target submission requires its typed request and original plan')
        self.request.__post_init__(); self.plan.__post_init__()
        if (self.request.action, self.request.profile_id) != (self.plan.action, self.plan.profile_id):
            raise ValueError('Submitted target plan differs from its original action')
        if type(self.selected) is not tuple or any(type(s) is not BodyTargetSelection for s in self.selected):
            raise ValueError('Accepted preflight selections require a typed ordered vector')
        if set(self.selected) != set(self.request.selections) or len(self.selected) != len(self.request.selections):
            raise ValueError('Canonical target selections differ from the original submission')
        if tuple(s.body for s in self.selected) != tuple(r.declaration.reference for r in self.plan.requirements):
            raise ValueError('Submitted selections do not cover every current declared body in order')
        for s, r in zip(self.selected, self.plan.requirements):
            s.__post_init__()
            if s.target_id not in r.target_choices: raise ValueError('Submitted body target was outside its original choices')


def paid_body_target_plan(game, action, profile_id):
    return _paid_body_target_plan(game, action, profile_id, validator=game.validate)


def _paid_body_target_plan(game, action, profile_id, *, validator):
    """Check all current carrier legality and price facts without paying.

Reserve a normal-entry target vector even when position currently selects a
magnetic host. The registered reserve_fallback policy records that obligation;
the eventual consumer must still prove the actual accepted route separately.
"""
    if type(action) is not PlayCard: raise ValueError('Paid target plan requires a PlayCard')
    action.__post_init__(); game._require_boundary()
    profile = game.registry.body_target_profile(profile_id)
    if (profile.origin, profile.selection, profile.acceptance_window) != ('paid_hand', 'manual', 'pre_payment'):
        raise ValueError('This preflight requires an explicit manual paid-hand target profile')
    validator(action)
    state = game.state; source = state.entities[action.entity_id]
    carrier = BodyReference.capture(source)
    declarations = body_target_declarations(state, game.registry, carrier, profile_id)
    quote = quote_cost(state, game.registry, source)
    from .play_history import preplay_conditions
    common = preplay_conditions(state, source)
    player = state.players[action.player_id]
    finale = player.mana - (quote.amount if quote.payment == PaymentType.MANA else 0) == 0
    from .magnetic import host_at_position
    host = host_at_position(state, game.registry, source, action.position)
    from .player_api import context_factory
    context = context_factory(game, action.player_id)
    from .targeting import target_choices
    requirements = []
    for declaration in declarations:
        contract = declaration.contract; threshold = contract.manathirst_threshold
        conditions = BodyPlayConditions(common['combo'], common['outcast'], finale, common['quickdraw'],
            threshold is not None and player.max_mana >= threshold, player.max_mana, threshold)
        active = contract.activation_condition is None or getattr(conditions, contract.activation_condition)
        target_active = active and contract.targeting is not None and (contract.target_condition is None or getattr(conditions, contract.target_condition))
        if target_active:
            # Selectability protections depend on the physical carrier kind,
            # while domain/predicate/condition come from this complete body.
            definition = replace(game.registry.card(contract.declaration_card_id), kind=source.kind)
            choices = target_choices(state, game.registry, source, definition, context_factory=context)
        else:
            choices = (None,)
        requirements.append(PaidBodyTargetRequirement(declaration, conditions, active, target_active, choices))
    from .serialization import canonical_hash
    return PaidBodyTargetPlan(action, profile_id, carrier, quote, game.registry.fingerprint(), canonical_hash(game.snapshot()),
                              None if host is None else BodyReference.capture(host), tuple(requirements))


def preflight_paid_body_targets(game, request):
    """Validate a complete vector and return an immutable canonical host plan."""
    if type(request) is not PaidBodyTargetRequest: raise ValueError('Expected typed paid body target submission')
    request.__post_init__()
    plan = paid_body_target_plan(game, request.action, request.profile_id)
    expected = tuple(r.declaration.reference for r in plan.requirements)
    selected = {s.body: s for s in request.selections}
    if set(selected) != set(expected): raise IllegalAction('Body target submission has missing, extra or changed physical bodies')
    ordered = tuple(selected[reference] for reference in expected)
    for selection, requirement in zip(ordered, plan.requirements):
        if selection.target_id not in requirement.target_choices:
            raise IllegalAction('Body target is invalid, unavailable or conflicts with its own frozen condition')
    return PaidBodyTargetSubmission(request, plan, ordered)


def validate_paid_body_target_submission(game, submission):
    """Recompute in the original stable state; this is not save authentication."""
    if type(submission) is not PaidBodyTargetSubmission: raise ValueError('Expected original typed preflight submission')
    submission.__post_init__()
    actual = preflight_paid_body_targets(game, submission.request)
    if actual != submission: raise IllegalAction('Paid target preflight no longer matches the original stable state')
    return actual
