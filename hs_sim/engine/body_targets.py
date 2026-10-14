"""Pure host declarations for per-body targeting; not an action dispatcher.

These values describe present physical bodies and registered origin policies.
They are neither accepted play proofs nor player-visible capabilities. Manual
submission, generated producers and durable accepted vectors are separate work.
"""
from dataclasses import dataclass

from .body_grants import BodyReference
from .effects import _behavior, _integer, _source
from .lifecycle import active_abilities
from .model import CardType, TargetSpec


@dataclass(frozen=True)
class BodyTargetProfile:
    id: str
    origin: str
    selection: str
    acceptance_window: str
    repeat_targets: str = 'reuse_accepted'
    retained_targets: str = 'reuse_accepted'
    late_bodies: str = 'reject_unsubmitted'
    stale_targets: str = 'skip_unavailable'
    magnetic_targets: str = 'reserve_fallback'
    retry_targets: str = 'reject'

    def __post_init__(self):
        _behavior(self.id)
        if type(self.origin) is not str or self.origin not in ('paid_hand', 'generated_whole', 'indirect_battlecry', 'historical_battlecry'):
            raise ValueError('Body targets require a declared paid or generated whole origin')
        if type(self.selection) is not str or type(self.acceptance_window) is not str:
            raise ValueError('Body target policy fields require strings')
        valid = (self.selection == 'manual' and self.acceptance_window == 'pre_payment') if self.origin == 'paid_hand' else (
            self.selection in ('random', 'explicit') and self.acceptance_window == (
                'indirect_invocation' if self.origin == 'indirect_battlecry' else
                'historical_invocation' if self.origin == 'historical_battlecry' else 'generated_acceptance'))
        if not valid:
            raise ValueError('Body target selection and acceptance window disagree with origin')
        if (type(self.retry_targets) is not str or self.retry_targets not in ('reject', 'reuse_original_selection') or
                self.retry_targets != 'reject' and self.origin != 'paid_hand'):
            raise ValueError('Unsupported body target retry policy')
        for name, expected in (('repeat_targets', 'reuse_accepted'), ('retained_targets', 'reuse_accepted'),
                               ('late_bodies', 'reject_unsubmitted'), ('stale_targets', 'skip_unavailable'),
                               ('magnetic_targets', 'reserve_fallback')):
            if type(getattr(self, name)) is not str or getattr(self, name) != expected:
                raise ValueError('Unsupported body target ' + name + ' policy')


@dataclass(frozen=True)
class BodyTargetContract:
    family: str
    declaration_card_id: str
    behavior_id: str
    targeting: TargetSpec | None
    target_rule: str
    target_visibility: str
    target_condition: str | None
    manathirst_threshold: int | None
    activation_condition: str | None

    def __post_init__(self):
        if type(self.family) is not str or self.family not in ('battlecry', 'combo'):
            raise ValueError('Body target contract requires its exact family')
        for name in ('declaration_card_id', 'behavior_id', 'target_rule'):
            _behavior(getattr(self, name))
        if self.targeting is not None:
            if type(self.targeting) is not TargetSpec: raise ValueError('Expected exact typed body target domain')
            self.targeting.__post_init__()
        if type(self.target_visibility) is not str or self.target_visibility not in ('builtin', 'player', 'omniscient'):
            raise ValueError('Unknown body target predicate visibility')
        if self.target_condition is not None and (type(self.target_condition) is not str or self.target_condition not in (
                'combo', 'outcast', 'finale', 'quickdraw', 'manathirst')):
            raise ValueError('Unknown body target condition')
        if self.manathirst_threshold is not None: _integer(self.manathirst_threshold, 'body target threshold', 1)
        if self.target_condition is not None and self.targeting is None:
            raise ValueError('Conditional body targeting requires its own target domain')
        if self.target_condition == 'manathirst' and self.manathirst_threshold is None:
            raise ValueError('Manathirst body target condition requires its own threshold')
        if self.activation_condition != ('combo' if self.family == 'combo' else None):
            raise ValueError('Body activation condition differs from its family')


@dataclass(frozen=True)
class BodyTargetReference:
    carrier: BodyReference
    family: str
    ability_id: int
    declaration_card_id: str
    behavior_id: str
    origin: str
    grant_source_id: int | None
    expires_turn: int | None

    def __post_init__(self):
        if type(self.carrier) is not BodyReference: raise ValueError('Body target reference requires its physical carrier')
        self.carrier.__post_init__()
        if type(self.family) is not str or self.family not in ('battlecry', 'combo'):
            raise ValueError('Body target reference requires its exact family')
        _integer(self.ability_id, 'body target attachment', 1)
        _behavior(self.declaration_card_id); _behavior(self.behavior_id)
        if type(self.origin) is not str or self.origin not in ('printed', 'granted'):
            raise ValueError('Unknown physical body provenance')
        _source(self.grant_source_id)
        if self.expires_turn is not None: _integer(self.expires_turn, 'body target expiry', 1)


@dataclass(frozen=True)
class BodyTargetDeclaration:
    profile: BodyTargetProfile
    reference: BodyTargetReference
    contract: BodyTargetContract
    source_kind: CardType

    def __post_init__(self):
        for name, expected in (('profile', BodyTargetProfile), ('reference', BodyTargetReference), ('contract', BodyTargetContract)):
            value = getattr(self, name)
            if type(value) is not expected: raise ValueError('Body target declaration requires exact typed ' + name)
            value.__post_init__()
        if (self.reference.family, self.reference.declaration_card_id, self.reference.behavior_id) != (
                self.contract.family, self.contract.declaration_card_id, self.contract.behavior_id):
            raise ValueError('Physical body identity and registered target contract disagree')
        if type(self.source_kind) is not CardType or self.source_kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
            raise ValueError('Body target source kind requires a physical body carrier')


def body_target_contract(registry, declaration_card_id, family):
    """Describe a complete registered body without evaluating any condition."""
    if type(family) is not str or family not in ('battlecry', 'combo'):
        raise ValueError('Body target contract requires battlecry or combo')
    _behavior(declaration_card_id)
    definition = registry.card(declaration_card_id)
    behavior_id = getattr(definition, family)
    if behavior_id is None: raise ValueError('Registered declaration lacks this body family')
    registry.behavior(behavior_id); registry.target_rule(definition.target_rule)
    from .targeting import target_spec
    return BodyTargetContract(family, definition.id, behavior_id, target_spec(definition),
        definition.target_rule, registry.target_visibility(definition.target_rule),
        definition.target_condition, definition.manathirst, 'combo' if family == 'combo' else None)


def body_target_declarations(state, registry, carrier, profile_id):
    """Pure host query, family execution order then physical attachment order.

No target candidates, body condition evaluation, RNG, payments or behavior
callbacks occur here. A profile describes the future consumer's policy; this
query does not assert that its acceptance window has actually occurred.
"""
    if type(carrier) is not BodyReference: raise ValueError('Expected captured physical body carrier')
    carrier.__post_init__()
    profile = registry.body_target_profile(profile_id); profile.__post_init__()
    entity = state.entities.get(carrier.entity_id)
    if entity is None or BodyReference.capture(entity) != carrier:
        raise ValueError('Body target carrier changed its original physical identity')
    kind = registry.card(carrier.card_id).kind
    if kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
        raise ValueError('Body target declarations require a minion, weapon or hero carrier')
    result = []
    for family in ('battlecry', 'combo'):
        for ability in active_abilities(entity, family):
            declaration_id = getattr(ability, family + '_card_id')
            contract = body_target_contract(registry, declaration_id, family)
            if contract.behavior_id != ability.behavior_id:
                raise ValueError('Physical body behavior differs from its registered declaration')
            reference = BodyTargetReference(carrier, family, ability.id, declaration_id, ability.behavior_id,
                                            ability.origin, ability.source_id, ability.expires_turn)
            result.append(BodyTargetDeclaration(profile, reference, contract, kind))
    if len({r.reference.ability_id for r in result}) != len(result):
        raise ValueError('Duplicate physical body attachment identity')
    return tuple(result)


def body_target_declaration(state, registry, reference, profile_id):
    """Resolve exactly this current declaration, never a sibling attachment."""
    if type(reference) is not BodyTargetReference: raise ValueError('Expected captured body target reference')
    reference.__post_init__()
    for declaration in body_target_declarations(state, registry, reference.carrier, profile_id):
        if declaration.reference == reference: return declaration
    raise ValueError('Body target reference is absent, consumed or has changed its identity')
