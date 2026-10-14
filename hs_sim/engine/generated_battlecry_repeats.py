"""Declared generated Battlecry family profile with complete shared max plans.

The first window is the whole primary body's original after-install acceptance,
before on_play and its reactions. Each captured BC payload executes its accepted
count in order. Generated Combo records/repetition and retained outcome iteration
remain later integration work; this profile is explicitly Battlecry-only.
"""
from dataclasses import dataclass, fields

from .effects import _integer
from .errors import ResolutionLimitExceeded
from .model import BattlecryRecipient, BattlecryRepeatModifier, BattlecryRepeatPlan


PROFILE = 'generated_battlecry_repeat_after_install_v1'


@dataclass(frozen=True)
class GeneratedBattlecryAcceptance:
    recipient: BattlecryRecipient
    plan: BattlecryRepeatPlan
    modifiers: tuple[BattlecryRepeatModifier, ...]
    use_id: int

    def __post_init__(self):
        from .battlecry_policy_uses import BattlecryPolicyUseReceipt
        _integer(self.use_id, 'generated Battlecry policy-use identity', 1)
        # Reuse the same complete modifier/finite-role structural contract.
        BattlecryPolicyUseReceipt(self.use_id, 'generated_body', 1, 1, 1, 0,
            self.recipient, self.plan, self.modifiers)


def capture(state, registry, source_id, player_id, payloads, profile_id):
    if profile_id not in (PROFILE, 'generated_family_repeat_after_install_v1', 'generated_retained_family_after_install_v1') or not payloads: return None
    from .battlecry_matching import capture_recipient
    from .battlecry_repeats import capture_plan_from_state
    from .battlecry_policy_uses import matched_modifiers
    recipient = capture_recipient(state, registry, source_id)
    plan = capture_plan_from_state(state, registry, player_id, recipient)
    return GeneratedBattlecryAcceptance(recipient, plan, matched_modifiers(state, player_id, plan),
        len(state.battlecry_policy_uses) + 1)


def consume(r, progress):
    accepted = progress.battlecry_repeat_acceptance
    if accepted is None: return
    if len(progress.battlecries) * accepted.plan.repetitions > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Complete generated Battlecry plan exceeds resolution budget')
    from .battlecry_policy_uses import consume as consume_uses
    from .battlecry_modifiers import emit_change
    receipt, changes = consume_uses(r, origin='generated_body', origin_id=progress.child_id,
        player_id=progress.player_id, recipient=accepted.recipient, plan=accepted.plan,
        expected_modifiers=accepted.modifiers)
    if receipt.id != accepted.use_id: raise ValueError('Generated Battlecry lost its original policy-use allocation')
    for modifier, remaining in changes:
        emit_change(r, 'battlecry_modifier_used', progress.player_id, modifier, uses_remaining=remaining)


def validate(state, registry, progress):
    accepted = progress.battlecry_repeat_acceptance
    if accepted is None: return
    accepted.__post_init__()
    if (progress.activation is None or progress.activation.profile_id not in (PROFILE, 'generated_family_repeat_after_install_v1', 'generated_retained_family_after_install_v1') or not progress.battlecries
            or (accepted.recipient.carrier_id, accepted.recipient.card_id, accepted.recipient.kind) !=
                (progress.source.entity_id, progress.source.card_id, progress.source.kind)):
        raise ValueError('Generated Battlecry plan lost its original whole-card acceptance')
    from .battlecry_repeats import validate_plan
    from .battlecry_policy_uses import receipt_at
    validate_plan(state, registry, accepted.plan, accepted.recipient)
    use = receipt_at(state, accepted.use_id)
    if (use.origin != 'generated_body' or use.origin_id != progress.child_id or use.player_id != progress.player_id
            or (use.recipient, use.plan, use.modifiers) != (accepted.recipient, accepted.plan, accepted.modifiers)):
        raise ValueError('Generated Battlecry plan erased or borrowed its actual consumption')


def acceptance_from_dict(value):
    from .serialization import _battlecry_recipient_from_dict, _battlecry_plan, _battlecry_modifier_from_dict
    if type(value) is not dict or set(value) != {f.name for f in fields(GeneratedBattlecryAcceptance)}:
        raise ValueError('Generated Battlecry acceptance requires exactly its complete wire fields')
    data = dict(value); data['recipient'] = _battlecry_recipient_from_dict(data['recipient'])
    data['plan'] = _battlecry_plan(data['plan'])
    if type(data['modifiers']) is not list: raise ValueError('Generated Battlecry requires complete ordered player captures')
    data['modifiers'] = tuple(_battlecry_modifier_from_dict(m) for m in data['modifiers'])
    return GeneratedBattlecryAcceptance(**data)
