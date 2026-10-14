"""Actual Battlecry policy captures and one-use transitions across origins.

Hand plans and generated body plans keep separate accepted source identities.
This ledger records all matched player policies, including unlimited policies;
board aura matching and max selection remain in the shared family producer.
No PlayRecord or payment is constructed here. Completed receipts are structural
consistency evidence; full original-window proofs remain owned by the caller.
"""
from dataclasses import dataclass, fields, replace

from .effects import _integer, _player
from .errors import ResolutionError
from .model import BattlecryRecipient, BattlecryRepeatModifier, BattlecryRepeatPlan


@dataclass(frozen=True)
class BattlecryPolicyUseReceipt:
    id: int
    origin: str
    origin_id: int
    player_id: int
    turn: int
    action: int
    recipient: BattlecryRecipient
    plan: BattlecryRepeatPlan
    modifiers: tuple[BattlecryRepeatModifier, ...]

    def __post_init__(self):
        for name in ('id', 'origin_id', 'turn'): _integer(getattr(self, name), name, 1)
        _integer(self.action, 'policy acceptance action', 0); _player(self.player_id)
        if self.origin not in ('paid_hand', 'generated_body'):
            raise ValueError('Unknown Battlecry policy consumption origin')
        if type(self.recipient) is not BattlecryRecipient or type(self.plan) is not BattlecryRepeatPlan:
            raise ValueError('Battlecry use lost its accepted recipient/max plan')
        self.recipient.__post_init__(); self.plan.__post_init__()
        if type(self.modifiers) is not tuple or any(type(m) is not BattlecryRepeatModifier for m in self.modifiers):
            raise ValueError('Battlecry uses require complete immutable player policy captures')
        for modifier in self.modifiers: modifier.__post_init__()
        identities = tuple(m.id for m in self.modifiers)
        if (tuple(sorted(set(identities))) != identities or not set(identities) <= set(self.plan.contributors)
                or tuple(m.id for m in self.modifiers if m.uses_remaining is not None) != self.plan.consumable_ids):
            raise ValueError('Battlecry use lost its complete finite/unlimited policy roles')


def receipt_at(state, identity):
    _integer(identity, 'Battlecry use receipt', 1)
    if identity > len(state.battlecry_policy_uses): raise ValueError('Unknown actual Battlecry policy use')
    return state.battlecry_policy_uses[identity - 1]


def matched_modifiers(state, player_id, plan):
    return tuple(m for m in state.players[player_id].battlecry_modifiers if m.id in plan.contributors)


def consume(r, *, origin, origin_id, player_id, recipient, plan, expected_modifiers=None):
    """Record before consumption events; return each finite transition to caller."""
    player = r.player(player_id)
    modifiers = matched_modifiers(r.state, player_id, plan)
    if expected_modifiers is not None and modifiers != expected_modifiers:
        raise ResolutionError('Battlecry policies changed before their accepted consumption')
    receipt = BattlecryPolicyUseReceipt(len(r.state.battlecry_policy_uses) + 1, origin, origin_id,
        player_id, r.state.turn, r.state.action_number, recipient, plan, modifiers)
    if any((u.origin, u.origin_id) == (origin, origin_id) for u in r.state.battlecry_policy_uses):
        raise ResolutionError('Accepted Battlecry policies can consume only once')
    ids = set(plan.consumable_ids)
    if {m.id for m in modifiers if m.uses_remaining is not None} != ids:
        raise ResolutionError('Battlecry use lost a captured finite policy')
    r.state.battlecry_policy_uses.append(receipt)
    changes = []; updated = []
    for modifier in player.battlecry_modifiers:
        if modifier.id not in ids: updated.append(modifier); continue
        remaining = modifier.uses_remaining - 1
        if remaining: updated.append(replace(modifier, uses_remaining=remaining))
        changes.append((modifier, remaining))
    player.battlecry_modifiers = updated
    return receipt, tuple(changes)


def validate_origin(state, receipt):
    if receipt.origin == 'paid_hand':
        from .play_history import play_record
        play = play_record(state, receipt.origin_id); accepted = play.battlecry_acceptance
        if (accepted is None or not accepted.payloads or (accepted.player_id, accepted.recipient, accepted.plan) !=
                (receipt.player_id, receipt.recipient, receipt.plan) or receipt.turn != play.turn or receipt.action < play.action):
            raise ValueError('Battlecry use differs from its original paid activation')
    else:
        ledger = state.whole_card_replay_ledger
        if receipt.origin_id > len(ledger.children): raise ValueError('Battlecry use borrowed an unknown generated child')
        progress = ledger.children[receipt.origin_id - 1].physical
        accepted = None if progress is None else progress.battlecry_repeat_acceptance
        if (accepted is None or accepted.use_id != receipt.id or progress.player_id != receipt.player_id
                or (accepted.recipient, accepted.plan, accepted.modifiers) != (receipt.recipient, receipt.plan, receipt.modifiers)
                or (progress.activation.turn, progress.activation.action) != (receipt.turn, receipt.action)):
            raise ValueError('Battlecry use differs from its independent generated acceptance')


def validate_history(state, registry):
    from .battlecry_matching import validate_recipient, battlecry_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration
    from .repeat_provenance import checked_live_attachments
    if type(state.battlecry_policy_uses) is not list: raise ValueError('Battlecry policy uses require a complete list')
    seen = set(); captured = {}; previous = (0, 0)
    for index, receipt in enumerate(state.battlecry_policy_uses, 1):
        if type(receipt) is not BattlecryPolicyUseReceipt: raise ValueError('Battlecry use lost its concrete type')
        receipt.__post_init__(); key = receipt.origin, receipt.origin_id
        if (receipt.id != index or key in seen or not previous <= (receipt.turn, receipt.action) <= (state.turn, state.action_number)):
            raise ValueError('Battlecry policy use lost its dense identity/original chronology')
        validate_origin(state, receipt); definition = validate_recipient(state, registry, receipt.recipient)
        for modifier in receipt.modifiers:
            validate_source_declaration(registry, modifier.spec, allow_source=False)
            if (modifier.id >= state.next_attachment_id or modifier.created_turn > receipt.turn
                    or modifier.expires_turn is not None and modifier.expires_turn < receipt.turn
                    or modifier.source_id is not None and modifier.source_id not in state.entities
                    or not battlecry_repeat_recipient_matches(modifier.spec, recipient=receipt.recipient, recipient_definition=definition)):
                raise ValueError('Invalid captured Battlecry player policy')
            if modifier.source_card_id is not None: registry.card(modifier.source_card_id)
            if modifier.id in captured:
                owner, old = captured[modifier.id]
                remaining = old.uses_remaining
                if remaining is not None: remaining -= 1
                if owner != receipt.player_id or remaining is not None and remaining < 1 or modifier != replace(old, uses_remaining=remaining):
                    raise ValueError('Battlecry uses changed their owner, policy or remaining budget across origins')
            captured[modifier.id] = receipt.player_id, modifier
        seen.add(key); previous = receipt.turn, receipt.action
    live = checked_live_attachments(state)
    for identity, (owner, old) in captured.items():
        current = live.get(identity)
        if current is None: continue
        family, current_owner, modifier = current
        remaining = old.uses_remaining
        if remaining is not None: remaining -= 1
        if (family != 'battlecry_modifiers' or current_owner != owner or remaining is not None and remaining < 1
                or modifier != replace(old, uses_remaining=remaining)):
            raise ValueError('Surviving Battlecry policy differs from its last actual consumption')
    for play in state.play_history:
        accepted = play.battlecry_acceptance
        if (play.completed and accepted is not None and accepted.payloads and ('paid_hand', play.id) not in seen):
            raise ValueError('Completed paid Battlecry erased its original policy-use acceptance')


def receipt_from_dict(value):
    from .serialization import _battlecry_modifier_from_dict, _battlecry_plan, _battlecry_recipient_from_dict
    if type(value) is not dict or set(value) != {f.name for f in fields(BattlecryPolicyUseReceipt)}:
        raise ValueError('Battlecry use requires exactly its complete wire fields')
    data = dict(value); data['recipient'] = _battlecry_recipient_from_dict(data['recipient'])
    data['plan'] = _battlecry_plan(data['plan'])
    if type(data['modifiers']) is not list: raise ValueError('Battlecry uses require a complete ordered policy array')
    data['modifiers'] = tuple(_battlecry_modifier_from_dict(m) for m in data['modifiers'])
    return BattlecryPolicyUseReceipt(**data)
