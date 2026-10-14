"""Pure Combo window matching without assuming a paid PlayRecord.

This component extracts the existing two-window operands, witness query and max
semantics. Callers still own the real original acceptance, full policy capture
and consumption proof. Generated callers select only activation policies; paid
callers may supply their previously accepted play policies without rematching
those old policies against a later recipient face. This module does not perform
an activation, spend a use, create a play record, emit an event or advance RNG.
"""
from hs_sim.engine.effects import _player
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardType, ComboRepeatModifier, ComboRepeatPlan
from hs_sim.engine.combo_matching import (capture_recipient, validate_recipient,
    combo_repeat_recipient_matches)
from hs_sim.engine.repeat_source_conditions import (validate_source_declaration,
    qualifying_repeat_witnesses)


def actual_recipient(state, registry, recipient):
    definition = validate_recipient(state, registry, recipient)
    if recipient != capture_recipient(state, registry, recipient.carrier_id):
        raise ValueError('Combo matching must capture the original window physical face')
    return definition


def capture_player_modifiers(state, registry, player_id, phase, recipient, eligible):
    _player(player_id)
    if phase not in ('play', 'activation') or type(eligible) is not bool:
        raise ValueError('Invalid Combo policy acceptance phase or gate')
    # This operand is the face accepted in this policy's own window. The paid
    # caller's full window proof or generated factory binds its actual face.
    # Do not recapture a later live face here; play and activation may differ.
    definition = validate_recipient(state, registry, recipient)
    # An ineligible family has no queries or unrelated metadata requirements.
    if not eligible: return ()
    result = []
    for modifier in state.players[player_id].combo_modifiers:
        validate_source_declaration(registry, modifier.spec, allow_source=False)
        if modifier.trigger == phase and combo_repeat_recipient_matches(modifier.spec,
                recipient=recipient, recipient_definition=definition):
            result.append(modifier)
    return tuple(result)


def capture_repeat_plan(state, registry, player_id, recipient, accepted_modifiers):
    """Complete max of live board sources and already accepted player policies."""
    _player(player_id)
    definition = actual_recipient(state, registry, recipient)
    if type(accepted_modifiers) is not tuple or any(type(m) is not ComboRepeatModifier for m in accepted_modifiers):
        raise ValueError('Combo plans require complete immutable accepted policy captures')
    seen = set()
    for modifier in accepted_modifiers:
        modifier.__post_init__()
        if modifier.id in seen or modifier.id >= state.next_attachment_id:
            raise ValueError('Combo plan reused or invented an accepted player policy identity')
        validate_source_declaration(registry, modifier.spec, allow_source=False)
        seen.add(modifier.id)
    repetitions = 1; contributors = []; consumable = []
    for entity_id in state.players[player_id].board:
        entity = state.entities[entity_id]
        if entity.kind != CardType.MINION or not entity.active or entity.doomed or entity.health <= 0:
            continue
        for ability in active_abilities(entity, 'combo_repeat'):
            spec = ability.combo_repeat
            condition = validate_source_declaration(registry, spec)
            source_matches = condition is None or bool(qualifying_repeat_witnesses(
                state, registry, player_id=player_id, carrier_id=entity.id, eligibility=condition))
            recipient_matches = combo_repeat_recipient_matches(spec, recipient=recipient,
                recipient_definition=definition, carrier_id=entity.id)
            if source_matches and recipient_matches:
                repetitions = max(repetitions, spec.repetitions); contributors.append(ability.id)
    # A paid caller's old play-policy face was checked at its own first window;
    # do not reinterpret that accepted policy using this later physical face.
    for modifier in accepted_modifiers:
        repetitions = max(repetitions, modifier.spec.repetitions); contributors.append(modifier.id)
        if modifier.uses_remaining is not None: consumable.append(modifier.id)
    return ComboRepeatPlan(repetitions, tuple(sorted(contributors)), tuple(sorted(consumable)))


def capture_generated_activation(state, registry, activation, payloads):
    """Query at a real independent body acceptance; generated play phase is absent."""
    from hs_sim.engine.generated_activation_receipts import GeneratedActivationReceipt, validate
    from hs_sim.engine.combo_matching import capture_recipient
    if type(activation) is not GeneratedActivationReceipt:
        raise ValueError('Generated Combo query requires its actual independent activation')
    activation.__post_init__()
    ledger = state.whole_card_replay_ledger
    if activation.child_id > len(ledger.children) or activation.root_id > len(ledger.roots):
        raise ValueError('Generated Combo query borrowed an unknown actual acceptance')
    root = ledger.roots[activation.root_id - 1]; child = ledger.children[activation.child_id - 1]
    validate(state, registry, activation, root, child)
    from hs_sim.engine.whole_card_physical import current_source
    if (root.id not in ledger.stack or root.active_child_id != child.id or child.physical is None
            or not current_source(state, child.physical)
            or (state.turn, state.action_number) != (activation.turn, activation.action)):
        raise ValueError('Generated Combo query must use its actual current original acceptance window')
    from hs_sim.engine.model import ComboPayload
    if type(payloads) is not tuple or any(type(p) is not ComboPayload for p in payloads):
        raise ValueError('Generated Combo query requires the complete original typed declaration tuple')
    for payload in payloads: payload.__post_init__()
    if len({p.ability_id for p in payloads}) != len(payloads):
        raise ValueError('Generated Combo query reused a declaration identity')
    from hs_sim.engine.combos import capture
    if payloads != capture(state.entities[activation.source.entity_id]):
        raise ValueError('Generated Combo query erased or substituted an original declaration')
    if activation.source.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
        if payloads: raise ValueError('Unsupported generated physical Combo kind')
        return None, ()
    recipient = capture_recipient(state, registry, activation.source.entity_id)
    if (recipient.card_id, recipient.kind) != (activation.source.card_id, activation.source.kind):
        raise ValueError('Generated Combo query differs from its original independent face')
    eligible = activation.combo and bool(payloads)
    from .generated_combo_repeats import SINGLE_PROFILES
    if activation.profile_id in SINGLE_PROFILES:
        # An actual invocation identity is independent of repetition permission.
        # Do not query board witnesses or player policies for these source rules.
        return (ComboRepeatPlan() if eligible else None), ()
    modifiers = capture_player_modifiers(state, registry, activation.player_id, 'activation', recipient, eligible)
    if not eligible: return None, modifiers
    return capture_repeat_plan(state, registry, activation.player_id, recipient, modifiers), modifiers
