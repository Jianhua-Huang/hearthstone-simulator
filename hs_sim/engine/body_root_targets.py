"""Separate trusted ordinary play/Choose One targets from physical body slots.

Host plans only. Existing player commands and accepted play execution still use
their legacy contract. The runtime consumer must connect this complete split
plan to the original payment proof and actual per-family acceptance windows.
"""
from dataclasses import dataclass, replace

from .actions import PlayCard
from .body_conditions import BodyPlayConditions
from .body_grants import BodyReference
from .body_target_authority import BodyTargetAuthority, body_target_authorities
from .body_target_preflight import (PaidBodyTargetPlan, PaidBodyTargetRequest,
    PaidBodyTargetSubmission, _paid_body_target_plan)
from .effects import _behavior, _integer, _source
from .errors import IllegalAction
from .lifecycle import active_abilities
from .model import AbilityInstance, CardType, PaymentType, TargetSpec, Zone
from .target_conditions import TARGET_CONDITIONS,target_condition_active


@dataclass(frozen=True)
class BodyRootTargetBinding:
    carrier_card_id: str
    profile_id: str
    mode: str
    targeting: TargetSpec | None = None
    target_rule: str = 'any_entity'
    target_condition: str | None = None
    manathirst_threshold: int | None = None

    def __post_init__(self):
        for value in (self.carrier_card_id, self.profile_id, self.target_rule):
            _behavior(value)
        if type(self.mode) is not str or self.mode not in ('body_only', 'preserve_root', 'explicit_root'):
            raise ValueError('Unknown ordinary/body target separation policy')
        if self.targeting is not None:
            if type(self.targeting) is not TargetSpec:
                raise ValueError('Root target binding requires an exact TargetSpec')
            self.targeting.__post_init__()
        if self.target_condition is not None and (type(self.target_condition) is not str or
                self.target_condition not in TARGET_CONDITIONS):
            raise ValueError('Unknown ordinary root target condition')
        if self.manathirst_threshold is not None:
            _integer(self.manathirst_threshold, 'ordinary root target threshold', 1)
        if self.mode != 'explicit_root' and (self.targeting is not None or self.target_rule != 'any_entity' or
                self.target_condition is not None or self.manathirst_threshold is not None):
            raise ValueError('Only explicit root policies may override ordinary target declarations')
        if self.target_condition is not None and self.targeting is None:
            raise ValueError('Conditional root targeting requires its own target domain')
        if (self.target_condition == 'manathirst') != (self.manathirst_threshold is not None):
            raise ValueError('Explicit root Manathirst requires exactly its own threshold')


def validate_root_binding(registry, binding):
    if type(binding) is not BodyRootTargetBinding:
        raise ValueError('Expected exact typed BodyRootTargetBinding')
    binding.__post_init__()
    profile = registry.body_target_profile(binding.profile_id)
    if (profile.origin, profile.selection, profile.acceptance_window) != ('paid_hand', 'manual', 'pre_payment'):
        raise ValueError('Ordinary root separation requires its registered manual paid policy')
    definition = registry.card(binding.carrier_card_id)
    if definition.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO) or not definition.hand_playable:
        raise ValueError('Body root target policy requires a playable physical carrier')
    if binding.mode == 'body_only' and (definition.on_play is not None or definition.choose_one is not None):
        raise ValueError('Body-only targeting cannot erase an ordinary or Choose One payload')
    if binding.mode == 'explicit_root' and (definition.on_play is None or definition.choose_one is not None):
        raise ValueError('Explicit ordinary root targeting requires a declared non-Choose One payload')
    registry.target_rule(binding.target_rule)


@dataclass(frozen=True)
class PaidBodyRootTargetRequirement:
    binding: BodyRootTargetBinding
    carrier: BodyReference
    branch_id: str | None
    branch_behavior_id: str | None
    root_abilities: tuple[AbilityInstance, ...]
    targeting: TargetSpec | None
    target_rule: str
    target_visibility: str
    target_condition: str | None
    conditions: BodyPlayConditions
    target_active: bool
    target_choices: tuple[int | None, ...]

    def __post_init__(self):
        if type(self.binding) is not BodyRootTargetBinding or type(self.carrier) is not BodyReference:
            raise ValueError('Root requirement needs its registered policy and physical hand source')
        self.binding.__post_init__(); self.carrier.__post_init__()
        if self.carrier.card_id != self.binding.carrier_card_id or self.carrier.zone != Zone.HAND:
            raise ValueError('Ordinary target root differs from its registered physical carrier')
        for value in (self.branch_id, self.branch_behavior_id, self.target_condition):
            if value is not None: _behavior(value)
        if (self.branch_id is None) != (self.branch_behavior_id is None):
            raise ValueError('Ordinary target root lost its actual selected branch')
        if type(self.root_abilities) is not tuple or any(type(a) is not AbilityInstance for a in self.root_abilities):
            raise ValueError('Ordinary root payloads require original typed physical abilities')
        for a in self.root_abilities:
            a.__post_init__()
            if a.kind != 'on_play' or a.consumed:
                raise ValueError('Root target requirement borrowed another physical ability family')
        if self.binding.mode == 'body_only' and self.root_abilities:
            raise ValueError('Body-only root cannot erase a current ordinary payload')
        if self.targeting is not None:
            if type(self.targeting) is not TargetSpec: raise ValueError('Expected typed root target domain')
            self.targeting.__post_init__()
        _behavior(self.target_rule)
        if self.target_visibility not in ('builtin', 'player', 'omniscient'):
            raise ValueError('Unknown root target predicate permission')
        if type(self.conditions) is not BodyPlayConditions: raise ValueError('Expected original root target conditions')
        self.conditions.__post_init__()
        if type(self.target_active) is not bool or self.target_active != (self.targeting is not None and
                target_condition_active(self.target_condition,self.conditions)):
            raise ValueError('Root target condition disagrees with its original facts')
        if type(self.target_choices) is not tuple or len(set(self.target_choices)) != len(self.target_choices):
            raise ValueError('Root target choices require an ordered unique tuple')
        for target in self.target_choices: _source(target)
        if not self.target_active and self.target_choices != (None,):
            raise ValueError('Disabled root target requires its explicit empty selection')


@dataclass(frozen=True)
class PaidBodyRootTargetPlan:
    bodies: PaidBodyTargetPlan
    root: PaidBodyRootTargetRequirement
    authorities: tuple[BodyTargetAuthority, ...]

    def __post_init__(self):
        if type(self.bodies) is not PaidBodyTargetPlan or type(self.root) is not PaidBodyRootTargetRequirement:
            raise ValueError('Separated target plan requires its complete typed root and body plans')
        self.bodies.__post_init__(); self.root.__post_init__()
        if (self.root.carrier, self.root.binding.profile_id, self.root.branch_id) != (
                self.bodies.carrier, self.bodies.profile_id, self.bodies.action.branch_id):
            raise ValueError('Root target plan borrowed another source, profile or branch')
        if self.bodies.action.target_id not in self.root.target_choices:
            raise ValueError('Original root target is outside its own accepted preflight choices')
        if type(self.authorities) is not tuple or any(type(a) is not BodyTargetAuthority for a in self.authorities):
            raise ValueError('Separated body route requires every physical source authority')
        for a in self.authorities: a.__post_init__()
        if tuple(a.declaration for a in self.authorities) != tuple(r.declaration for r in self.bodies.requirements):
            raise ValueError('Separated body target plan lost its complete trusted source vector')


@dataclass(frozen=True)
class PaidBodyRootTargetSubmission:
    request: PaidBodyTargetRequest
    plan: PaidBodyRootTargetPlan
    selected: tuple

    def __post_init__(self):
        if type(self.plan) is not PaidBodyRootTargetPlan: raise ValueError('Expected typed separated target plan')
        self.plan.__post_init__()
        PaidBodyTargetSubmission(self.request, self.plan.bodies, self.selected)


def paid_body_root_target_plan(game, action, profile_id):
    """Full original legality with separately authorized root/body targeting.

Normal-entry requirements are reserved even when a magnetic host currently
exists, according to the registered reserve_fallback policy. No source enters
PLAY, no payment occurs and no accepted runtime history is fabricated here.
"""
    if type(action) is not PlayCard: raise ValueError('Separated targets require an original PlayCard')
    action.__post_init__(); game._require_boundary()
    state = game.state
    source = state.entities.get(action.entity_id)
    if source is None or source.zone != Zone.HAND or source.controller != action.player_id:
        raise IllegalAction('Separated body targets require the actual owned physical hand card')
    carrier = BodyReference.capture(source)
    authorities = body_target_authorities(state, game.registry, carrier, profile_id)
    binding = game.registry.body_root_target_binding(source.card_id, profile_id)
    validate_root_binding(game.registry, binding)
    abilities = tuple(active_abilities(source, 'on_play'))
    if binding.mode == 'body_only' and abilities:
        raise IllegalAction('Body-only target policy cannot erase current ordinary payloads')
    definition = game.registry.card(source.card_id)
    from .choose_one import branch, effective, selection_error
    if reason := selection_error(state, definition, action.player_id, action.branch_id, game.ruleset, entity=source):
        raise IllegalAction(reason)
    selected_branch = branch(definition, action.branch_id)
    raw = effective(definition, action.branch_id)
    if binding.mode == 'body_only':
        raw = replace(raw, requires_target=False, targeting=None, target_rule='any_entity', target_condition=None, manathirst=None)
    elif binding.mode == 'explicit_root':
        raw = replace(raw, requires_target=False, targeting=binding.targeting, target_rule=binding.target_rule,
            target_condition=binding.target_condition, manathirst=binding.manathirst_threshold)
    from .costs import quote_cost
    from .play_history import preplay_conditions
    quote = quote_cost(state, game.registry, source)
    common = preplay_conditions(state, source)
    player = state.players[action.player_id]
    conditions = BodyPlayConditions(common['combo'], common['outcast'],
        player.mana - (quote.amount if quote.payment == PaymentType.MANA else 0) == 0,
        common['quickdraw'], raw.manathirst is not None and player.max_mana >= raw.manathirst,
        player.max_mana, raw.manathirst)
    from .targeting import target_spec, target_choices
    domain = target_spec(raw)
    active = domain is not None and target_condition_active(raw.target_condition,conditions)
    effective_root = raw if active else replace(raw, requires_target=False, targeting=None, target_rule='any_entity')
    bodies = _paid_body_target_plan(game, action, profile_id,
        validator=lambda value: game._validate_action(value, play_target_definition=effective_root))
    from .player_api import context_factory
    choices = target_choices(state, game.registry, source, effective_root,
        context_factory=context_factory(game, action.player_id)) if active else (None,)
    root = PaidBodyRootTargetRequirement(binding, carrier, action.branch_id,
        None if selected_branch is None else selected_branch.behavior_id, abilities, domain,
        raw.target_rule, game.registry.target_visibility(raw.target_rule), raw.target_condition,
        conditions, active, choices)
    return PaidBodyRootTargetPlan(bodies, root, authorities)


def preflight_paid_body_root_targets(game, request):
    if type(request) is not PaidBodyTargetRequest: raise ValueError('Expected exact separated paid target request')
    request.__post_init__()
    plan = paid_body_root_target_plan(game, request.action, request.profile_id)
    expected = tuple(r.declaration.reference for r in plan.bodies.requirements)
    entries = {s.body: s for s in request.selections}
    if set(entries) != set(expected): raise IllegalAction('Separated target vector has missing, extra or stale physical bodies')
    selected = tuple(entries[reference] for reference in expected)
    for s, requirement in zip(selected, plan.bodies.requirements):
        if s.target_id not in requirement.target_choices:
            raise IllegalAction('Separated body target violates its own original requirement')
    return PaidBodyRootTargetSubmission(request, plan, selected)


def validate_paid_body_root_target_submission(game, submission):
    if type(submission) is not PaidBodyRootTargetSubmission: raise ValueError('Expected original separated target preflight')
    submission.__post_init__()
    actual = preflight_paid_body_root_targets(game, submission.request)
    if actual != submission: raise IllegalAction('Separated targets no longer match original state and trusted policies')
    return actual
