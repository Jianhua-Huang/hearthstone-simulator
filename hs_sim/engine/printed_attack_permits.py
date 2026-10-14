"""Temporary permission for one native printed restriction, never blanket eligibility."""
from dataclasses import dataclass

from .effects import Effect
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, CardType, PrintedAttackPolicyDeclaration,
    SelfPrintedAttackReference, PrintedAttackPermitRequest, PrintedAttackPermit, Zone)
from .board_presence import capture_board_presence, resolve_board_presence
from .owner_turns import current_owner_turn


def declaration_spec(registry, declaration, *, restriction=False):
    if type(declaration) is not PrintedAttackPolicyDeclaration:
        raise ValueError('Expected exact printed attack declaration')
    declaration.__post_init__()
    if registry is None:
        raise ValueError('Printed attack declarations require the fixed registry')
    definition = registry.card(declaration.definition_id)
    if declaration.policy_index >= len(definition.attack_policies):
        raise ValueError('Unknown printed attack declaration slot')
    spec = definition.attack_policies[declaration.policy_index]
    if restriction and spec.mode != 'cannot_attack':
        raise ValueError('Printed attack permission can only suppress cannot_attack')
    return spec


def _native_row(card_id, ability, declaration, spec):
    return (ability.kind == 'attack_policy' and ability.origin == 'printed' and not ability.consumed
            and ability.attack_policy_declaration == declaration and declaration.definition_id == card_id
            and ability.attack_policy == spec)


def _interval(state, owner_turn_id):
    if type(owner_turn_id) is not int or not 0 < owner_turn_id <= len(state.owner_turn_history):
        raise ValueError('Unknown printed permission owner interval')
    interval = state.owner_turn_history[owner_turn_id - 1]
    if interval.id != owner_turn_id:
        raise ValueError('Printed permission owner interval identity mismatch')
    return interval


def capture_printed_attack_permit(state, registry, carrier_id, declaration):
    """Pure producer: capture the residence, local row and real clock at the original window."""
    spec = declaration_spec(registry, declaration, restriction=True)
    if type(carrier_id) is not int or carrier_id <= 0 or carrier_id not in state.entities:
        raise ValueError('Unknown printed permission carrier')
    carrier = state.entities[carrier_id]
    if (carrier.zone != Zone.BOARD or carrier.kind != CardType.MINION or not carrier.active
            or carrier.health <= 0 or carrier.doomed):
        return None
    rows = [a for a in active_abilities(carrier, 'attack_policy')
            if _native_row(carrier.card_id, a, declaration, spec)]
    if len(rows) > 1:
        raise ValueError('Ambiguous native printed attack declaration')
    if not rows:
        return None
    reference = SelfPrintedAttackReference(capture_board_presence(state, carrier_id), declaration, rows[0].id)
    return PrintedAttackPermitRequest(reference, current_owner_turn(state).id)


def validate_request(state, registry, request):
    if type(request) is not PrintedAttackPermitRequest:
        raise ValueError('Expected PrintedAttackPermitRequest')
    request.__post_init__()
    declaration_spec(registry, request.reference.declaration, restriction=True)
    ref = request.reference
    if ref.carrier.entity_id not in state.entities:
        raise ValueError('Unknown original printed permission carrier')
    if ref.carrier.presence_id >= state.next_order or ref.ability_id >= state.next_attachment_id:
        raise ValueError('Printed permission reference has not been allocated')
    # Current foreign owners prove an invalid reference. Removed original rows /
    # residences remain known stale, and must never be recaptured or rejected
    # simply because the original carrier is currently absent or inactive.
    for entity in state.entities.values():
        if entity.id != ref.carrier.entity_id:
            if entity.board_presence_id == ref.carrier.presence_id:
                raise ValueError('Printed permission residence belongs to another physical carrier')
            if any(a.id == ref.ability_id for a in entity.abilities):
                raise ValueError('Printed permission row belongs to another physical carrier')
    for death in state.death_history:
        if death.entity_id != ref.carrier.entity_id and any(a.id == ref.ability_id for a in death.abilities):
            raise ValueError('Printed permission row belongs to another historical physical carrier')
    carrier = state.entities[ref.carrier.entity_id]
    local = next((a for a in carrier.abilities if a.id == ref.ability_id), None)
    if local is not None and (local.kind != 'attack_policy' or local.origin != 'printed' or
            local.attack_policy_declaration != ref.declaration or
            local.attack_policy != declaration_spec(registry, ref.declaration, restriction=True)):
        raise ValueError('Printed permission reference identifies a different local declaration')
    return _interval(state, request.expires_owner_turn_id)


def validate_frame_references(state, registry, value):
    """State-bound references are separate from the codec's closed type whitelist."""
    from dataclasses import fields, is_dataclass
    from .model import GameState
    from .registry import RuleContext
    from .continuations import FrameCodec
    def visit(item, scope, depth):
        if depth > FrameCodec.MAX_DEPTH:
            raise ValueError('Printed permission frame references exceed codec depth')
        if type(item) is PrintedAttackPermitRequest:
            validate_request(scope, registry, item)
            return
        if type(item) is RuleContext:
            for field in fields(item):
                if field.name != 'state':
                    visit(getattr(item, field.name), item.state, depth + 1)
            return
        if type(item) is GameState:
            # Its saved attachments are already checked by model invariants.
            return
        if isinstance(item, (tuple, list)):
            for child in item: visit(child, scope, depth + 1)
        elif isinstance(item, dict):
            for child in item.values(): visit(child, scope, depth + 1)
        elif is_dataclass(item) and not isinstance(item, type):
            for field in fields(item): visit(getattr(item, field.name), scope, depth + 1)
    visit(value, state, 0)


def validate_attachment(state, registry, ability):
    if ability.attack_policy_declaration is not None:
        if declaration_spec(registry, ability.attack_policy_declaration) != ability.attack_policy:
            raise ValueError('Printed attack declaration differs from its exact registry slot')
    permit = ability.printed_attack_permit
    if permit is None:
        return
    declaration_spec(registry, permit.declaration, restriction=True)
    if permit.permitted_ability_id >= state.next_attachment_id:
        raise ValueError('Local printed permission row has not been allocated')
    if ability.expires_turn != _interval(state, permit.expires_owner_turn_id).turn:
        raise ValueError('Printed permission expiry differs from its original real interval')


def validate_carrier(state, registry, card_id, kind, abilities):
    for ability in abilities:
        permit = ability.printed_attack_permit
        if permit is None:
            continue
        if kind != CardType.MINION:
            raise ValueError('Printed attack permission requires a minion carrier')
        spec = declaration_spec(registry, permit.declaration, restriction=True)
        local = next((a for a in abilities if a.id == permit.permitted_ability_id), None)
        # Removed rows remain inert; never search another carrier or rematch by declaration.
        if local is not None and not _native_row(card_id, local, permit.declaration, spec):
            raise ValueError('Printed attack permission does not identify its native local restriction')


def permitted_rows(state, carrier, registry=None):
    permits = active_abilities(carrier, 'printed_attack_permit')
    if not permits:
        return frozenset()
    if state is None:
        raise ValueError('Printed permissions require the current real owner interval')
    current = current_owner_turn(state)
    result = set()
    for ability in permits:
        validate_attachment(state, registry, ability)
        permit = ability.printed_attack_permit
        interval = _interval(state, permit.expires_owner_turn_id)
        if interval.closed or interval.id != current.id:
            continue
        local = next((a for a in carrier.abilities if a.id == permit.permitted_ability_id), None)
        spec = declaration_spec(registry, permit.declaration, restriction=True)
        if local is not None and _native_row(carrier.card_id, local, permit.declaration, spec):
            result.add(local.id)
    return frozenset(result)


@dataclass(frozen=True)
class GrantPrintedAttackPermit(Effect):
    request: PrintedAttackPermitRequest

    def __post_init__(self):
        if type(self.request) is not PrintedAttackPermitRequest:
            raise ValueError('GrantPrintedAttackPermit requires a captured typed request')
        self.request.__post_init__()


def grant(r, effect):
    interval = validate_request(r.state, r.registry, effect.request)
    ref = effect.request.reference
    carrier = resolve_board_presence(r.state, ref.carrier)
    spec = declaration_spec(r.registry, ref.declaration, restriction=True)
    row = next((a for a in carrier.abilities if a.id == ref.ability_id), None) if carrier else None
    if (carrier is None or not carrier.active or carrier.health <= 0 or carrier.doomed
            or interval.closed or interval.id != current_owner_turn(r.state).id
            or row is None or not _native_row(carrier.card_id, row, ref.declaration, spec)):
        r.stale(effect, ref.carrier.entity_id)
        return ()
    payload = PrintedAttackPermit(ref.declaration, row.id, interval.id)
    ability = AbilityInstance(attachment_id(r.state), 'printed_attack_permit', source_id=carrier.id,
                             expires_turn=interval.turn, printed_attack_permit=payload)
    carrier.abilities.append(ability)
    r.refresh_auras()
    r.emit('ability_granted', source_id=carrier.id, target_id=carrier.id,
           ability_id=ability.id, ability_kind=ability.kind)


def register(mechanics):
    for kind in (PrintedAttackPolicyDeclaration, SelfPrintedAttackReference,
                 PrintedAttackPermitRequest, PrintedAttackPermit):
        mechanics.register_payload_type(kind)
    mechanics.register(GrantPrintedAttackPermit, grant)
