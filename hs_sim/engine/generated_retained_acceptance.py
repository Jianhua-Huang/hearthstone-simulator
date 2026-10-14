"""Pure original-window acceptance for intrinsic generated physical outcomes.

Preparation for the runtime bridge: this module does not schedule an outcome,
allocate a record, consume family policies, or change the installed carrier.
Its operands are a real whole-card child and its complete physical acceptance.
"""
from dataclasses import dataclass, fields

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .errors import ResolutionLimitExceeded
from .generated_activation_receipts import GeneratedActivationReceipt, FAMILY_PROFILE, RETAINED_PROFILE
from .lifecycle import active_abilities
from .model import (BattlecryPayload, BattlecryRepeatPlan, CardType, ComboPayload,
    ComboRepeatPlan, Keyword, RewindSpec, Zone)
from .whole_card_history import integer


@dataclass(frozen=True)
class RetentionHolderFact:
    source: SourceAllocationFact
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact:
            raise ValueError('Retention holder requires its original physical allocation')
        self.source.__post_init__()
        if self.source.kind != CardType.MINION or self.source.zone != Zone.BOARD:
            raise ValueError('Retention holder must be an original board minion')
        if type(self.ability_ids) is not tuple or not self.ability_ids or len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError('Retention holder requires all distinct original live declarations')
        for identity in self.ability_ids: integer(identity, 'retention ability')


@dataclass(frozen=True)
class GeneratedRetainedAcceptance:
    activation: GeneratedActivationReceipt
    before_outcome_id: int
    printed_spec: RewindSpec | None
    active_rewind: bool
    holders: tuple[RetentionHolderFact, ...]
    status: str
    total: int
    on_play: tuple[str, ...]
    battlecries: tuple[BattlecryPayload, ...]
    combos: tuple[ComboPayload, ...]
    battlecry_plan: BattlecryRepeatPlan | None
    combo_plan: ComboRepeatPlan | None

    def __post_init__(self):
        if type(self.activation) is not GeneratedActivationReceipt:
            raise ValueError('Generated outcomes require their actual independent activation')
        self.activation.__post_init__()
        if self.activation.profile_id not in (FAMILY_PROFILE, RETAINED_PROFILE):
            raise ValueError('Retained family acceptance cannot borrow a legacy or BC-only profile')
        integer(self.before_outcome_id, 'generated original outcome allocation')
        integer(self.total, 'accepted generated result count')
        if type(self.active_rewind) is not bool:
            raise ValueError('Original active Rewind marker must be boolean')
        if self.printed_spec is not None:
            if type(self.printed_spec) is not RewindSpec:
                raise ValueError('Original generated Rewind budget requires its typed declaration')
            self.printed_spec.__post_init__()
        if self.active_rewind and self.printed_spec is None:
            raise ValueError('Active generated Rewind lost its registered budget')
        if type(self.holders) is not tuple or any(type(h) is not RetentionHolderFact for h in self.holders):
            raise ValueError('Retention holders require their full ordered immutable facts')
        for holder in self.holders:
            holder.__post_init__()
            if holder.source.controller != self.activation.player_id:
                raise ValueError('Retention holder borrowed another player seat')
        identities = tuple(h.source.entity_id for h in self.holders)
        abilities = tuple(i for h in self.holders for i in h.ability_ids)
        if len(set(identities)) != len(identities) or len(set(abilities)) != len(abilities):
            raise ValueError('Generated retention duplicated a carrier or independent ability')
        expected_status = 'no_rewind' if not self.active_rewind else 'retained' if self.holders else 'no_holder'
        expected_total = self.printed_spec.retries + 1 if expected_status == 'retained' else 1
        if (self.status, self.total) != (expected_status, expected_total):
            raise ValueError('Generated result quota differs from the original non-stacking policy')
        if type(self.on_play) is not tuple or any(type(b) is not str or not b for b in self.on_play):
            raise ValueError('Generated outcomes require their complete ordered generic body')
        for payloads, kind in ((self.battlecries, BattlecryPayload), (self.combos, ComboPayload)):
            if type(payloads) is not tuple or any(type(b) is not kind for b in payloads):
                raise ValueError('Generated outcomes require their complete typed family bodies')
            for payload in payloads: payload.__post_init__()
            if len({b.ability_id for b in payloads}) != len(payloads):
                raise ValueError('Generated outcome duplicated a family body declaration')
        for payloads, plan, kind in ((self.battlecries, self.battlecry_plan, BattlecryRepeatPlan),
                (self.combos, self.combo_plan, ComboRepeatPlan)):
            if bool(payloads) != (plan is not None) or plan is not None and type(plan) is not kind:
                raise ValueError('Generated retained bodies lost their independent complete family plans')
            if plan is not None: plan.__post_init__()

    @property
    def segment_count(self):
        return len(self.on_play) + sum(len(payloads) * (plan.repetitions if plan else 1)
            for payloads, plan in ((self.battlecries, self.battlecry_plan), (self.combos, self.combo_plan)))

    @property
    def key(self):
        return self.activation.origin, self.activation.root_id, self.activation.child_id


def holder_facts(state, player_id):
    from .rewind_outcomes import retention_sources
    return tuple(RetentionHolderFact(SourceAllocationFact.capture(state, state.entities[identity]),
        tuple(a.id for a in active_abilities(state.entities[identity], 'rewind_retention')))
        for identity in retention_sources(state, player_id))


def capture_from_state(state, registry, accepted, max_resolution_steps):
    """Capture on the real after-install window before either family consumes."""
    from .whole_card_physical import PhysicalReplayProgress, child_for, current_source, original_body
    from .generated_activation_receipts import capture as capture_activation
    from .generated_battlecry_repeats import capture as capture_bc
    from .generated_combo_repeats import capture as capture_combo
    from .whole_card_replay_ledger import ReplayChildStatus
    integer(max_resolution_steps, 'generated retained resolution budget')
    if type(accepted) is not PhysicalReplayProgress:
        raise ValueError('Generated retention requires the actual complete physical acceptance')
    accepted.__post_init__()
    if (accepted.phase != 'running' or accepted.cursor != 0 or accepted.battlecry_ids or accepted.combo_ids
            or accepted.active_battlecry_id is not None or accepted.active_combo_id is not None
            or accepted.activation is None or accepted.activation.profile_id not in (FAMILY_PROFILE, RETAINED_PROFILE)):
        raise ValueError('Generated retention must precede its first actual body execution')
    profile_id = accepted.activation.profile_id
    child = child_for(state, accepted.child_id)
    root = state.whole_card_replay_ledger.roots[child.root_id - 1]
    prior = child.physical
    if (child.status != ReplayChildStatus.RUNNING or root.active_child_id != child.id or prior is None
            or prior.phase != 'installing' or prior.source != accepted.source or not current_source(state, prior)):
        raise ValueError('Generated retention cannot borrow a settled, paid or unrelated carrier')
    activation = capture_activation(state, registry, root, child, prior.source, accepted.selection.target_id,
        profile_id)
    _, conditions, bodies, battlecries, combos = original_body(state, registry, prior)
    bc = capture_bc(state, registry, prior.source.entity_id, prior.player_id, battlecries, profile_id)
    combo, _ = capture_combo(state, registry, activation, profile_id)
    if (activation != accepted.activation or bodies != accepted.on_play or battlecries != accepted.battlecries
            or combos != accepted.combos or any(getattr(accepted, k) != v for k, v in conditions.items())
            or bc != accepted.battlecry_repeat_acceptance or combo != accepted.combo_repeat_acceptance):
        raise ValueError('Generated retained body substituted its original complete family acceptance')
    definition = registry.card(accepted.card_id)
    active = definition.rewind is not None and Keyword.REWIND in state.entities[prior.source.entity_id].keywords
    holders = holder_facts(state, accepted.player_id)
    status = 'no_rewind' if not active else 'retained' if holders else 'no_holder'
    receipt = GeneratedRetainedAcceptance(activation, len(state.rewind_outcomes) + 1, definition.rewind, active,
        holders, status, definition.rewind.retries + 1 if status == 'retained' else 1,
        bodies, battlecries, combos, None if bc is None else bc.plan, None if combo is None else combo.plan)
    if receipt.total > max_resolution_steps or receipt.segment_count * receipt.total > max_resolution_steps:
        raise ResolutionLimitExceeded('Complete generated retained body exceeds its original resolution budget')
    return receipt


def validate_original(receipt, proof, registry):
    """Full original operands bind holder eligibility and every accepted plan."""
    from .whole_card_physical import validate_body_proof
    receipt.__post_init__()
    validate_body_proof(proof, registry)
    if receipt != capture_from_state(proof.before_state, registry, proof.accepted, proof.rules.max_resolution_steps):
        raise ValueError('Generated retention changed its complete original acceptance')


def validate_compact(state, registry, receipt):
    """Preserve old facts; later removal cannot re-decide an accepted quota."""
    from .whole_card_physical import child_for
    from .generated_activation_receipts import validate as validate_activation
    from .combos import validate_payload as validate_combo
    from .battlecry_repeats import validate_plan as validate_bc_plan
    from .combo_repeats import validate_plan as validate_combo_plan
    receipt.__post_init__()
    child = child_for(state, receipt.activation.child_id)
    root = state.whole_card_replay_ledger.roots[child.root_id - 1]
    validate_activation(state, registry, receipt.activation, root, child)
    definition = registry.card(receipt.activation.source.card_id)
    if definition.rewind != receipt.printed_spec or receipt.before_outcome_id > len(state.rewind_outcomes) + 1:
        raise ValueError('Generated retention lost its original card budget or history bound')
    progress = child.physical
    if (progress is None or progress.activation != receipt.activation or
            (progress.on_play, progress.battlecries, progress.combos) !=
                (receipt.on_play, receipt.battlecries, receipt.combos)):
        raise ValueError('Generated retention borrowed another independent full physical body')
    for holder in receipt.holders:
        validate_allocation(state, registry, holder.source)
        if any(i >= state.next_attachment_id for i in holder.ability_ids):
            raise ValueError('Generated retention invented a future holder declaration')
    if receipt.battlecry_plan is not None:
        if progress.battlecry_repeat_acceptance is None or progress.battlecry_repeat_acceptance.plan != receipt.battlecry_plan:
            raise ValueError('Generated retention changed its Battlecry plan')
        validate_bc_plan(state, registry, receipt.battlecry_plan, progress.battlecry_repeat_acceptance.recipient)
    if receipt.combo_plan is not None:
        if progress.combo_repeat_acceptance is None or progress.combo_repeat_acceptance.plan != receipt.combo_plan:
            raise ValueError('Generated retention changed its Combo plan')
        validate_combo_plan(state, receipt.combo_plan)
    for behavior in receipt.on_play: registry.behavior(behavior)
    for payload in receipt.battlecries:
        registry.behavior(payload.behavior_id)
        if payload.ability_id >= state.next_attachment_id or registry.card(payload.card_id).battlecry != payload.behavior_id:
            raise ValueError('Generated retained Battlecry lost its registered declaration')
    for payload in receipt.combos: validate_combo(state, registry, payload)


def receipt_from_dict(value):
    from .generated_activation_receipts import receipt_from_dict as activation_from_dict
    from .serialization import _battlecry_plan, _combo_plan
    if type(value) is not dict or set(value) != {f.name for f in fields(GeneratedRetainedAcceptance)}:
        raise ValueError('Generated retention wire requires exactly its complete acceptance fields')
    data = dict(value)
    data['activation'] = activation_from_dict(data['activation'])
    if data['printed_spec'] is not None:
        if type(data['printed_spec']) is not dict or set(data['printed_spec']) != {f.name for f in fields(RewindSpec)}:
            raise ValueError('Generated Rewind wire requires its complete registered budget')
        data['printed_spec'] = RewindSpec(**data['printed_spec'])
    for name in ('holders', 'on_play', 'battlecries', 'combos'):
        if type(data[name]) is not list:
            raise ValueError('Generated retained wire requires complete ordered arrays')
        data[name] = tuple(data[name])
    holders = []
    for holder in data['holders']:
        if type(holder) is not dict or set(holder) != {f.name for f in fields(RetentionHolderFact)} or type(holder['ability_ids']) is not list:
            raise ValueError('Generated retained wire lost its complete holder operands')
        holders.append(RetentionHolderFact(allocation_from_dict(holder['source']), tuple(holder['ability_ids'])))
    data['holders'] = tuple(holders)
    data['battlecries'] = tuple(BattlecryPayload(**p) for p in data['battlecries'])
    data['combos'] = tuple(ComboPayload(**p) for p in data['combos'])
    data['battlecry_plan'] = None if data['battlecry_plan'] is None else _battlecry_plan(data['battlecry_plan'])
    data['combo_plan'] = None if data['combo_plan'] is None else _combo_plan(data['combo_plan'])
    return GeneratedRetainedAcceptance(**data)
