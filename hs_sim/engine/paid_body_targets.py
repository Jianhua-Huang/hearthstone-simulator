"""Actual manual paid body targets with a compact, original payment receipt.

This consumer admits built-in and registered declarative structural predicates. Player/omniscient target
predicates and other producers still require their own observation/proof paths.
Heterogeneous grants use trusted manual paid bindings; other origin contracts
remain separate producer requirements.
"""
from copy import deepcopy
from dataclasses import replace

from .actions import PlayCard, PlayBodyTarget
from .body_grants import BodyReference
from .body_target_authority import body_target_authorities
from .body_targets import body_target_contract
from .errors import IllegalAction, ResolutionError
from .model import CardType, Keyword, PaidBodyTargetReceipt, PaymentType, Zone
from .serialization import canonical_hash, state_to_dict
from .targeting import target_choices, target_spec, accepts_target


def _selection(reference, target_id):
    return PlayBodyTarget(reference.family, reference.ability_id,
        reference.declaration_card_id, reference.behavior_id, reference.origin,
        reference.grant_source_id, reference.expires_turn, reference.carrier.card_id,
        reference.carrier.zone_epoch, target_id)


def play_with_body_targets(submission):
    """Convert a complete host preflight into the actual, strictly coded action."""
    from .body_root_targets import PaidBodyRootTargetSubmission
    if type(submission) is not PaidBodyRootTargetSubmission:
        raise ValueError('Expected complete separated root/body preflight')
    submission.__post_init__()
    return replace(submission.request.action,
        body_target_profile_id=submission.request.profile_id,
        body_targets=tuple(_selection(v.body, v.target_id) for v in submission.request.selections))


def _facts(state, registry, source, quote=None):
    from .costs import quote_cost
    from .play_history import preplay_conditions
    quote = quote or quote_cost(state, registry, source)
    values = preplay_conditions(state, source)
    player = state.players[source.controller]
    values['finale'] = player.mana - (quote.amount if quote.payment == PaymentType.MANA else 0) == 0
    return values, player.max_mana


def _condition(values, crystals, name, threshold):
    return True if name is None else (threshold is not None and crystals >= threshold
        if name == 'manathirst' else values[name])


def _root(state, registry, source, action, values, crystals):
    from .body_root_targets import validate_root_binding
    from .choose_one import effective
    from .lifecycle import active_abilities
    binding = registry.body_root_target_binding(source.card_id, action.body_target_profile_id)
    validate_root_binding(registry, binding)
    raw = effective(registry.card(source.card_id), action.branch_id)
    if binding.mode == 'body_only':
        if active_abilities(source, 'on_play'):
            raise IllegalAction('Body-only policy cannot discard an actual ordinary payload')
        raw = replace(raw, requires_target=False, targeting=None, target_rule='any_entity', target_condition=None, manathirst=None)
    elif binding.mode == 'explicit_root':
        raw = replace(raw, requires_target=False, targeting=binding.targeting, target_rule=binding.target_rule,
            target_condition=binding.target_condition, manathirst=binding.manathirst_threshold)
    from .body_target_origin import require_audited_predicate
    require_audited_predicate(registry, raw.target_rule)
    if not _condition(values, crystals, raw.target_condition, raw.manathirst):
        raw = replace(raw, requires_target=False, targeting=None, target_rule='any_entity')
    return raw


def root_definition(state, registry, action):
    source = state.entities[action.entity_id]
    values, crystals = _facts(state, registry, source)
    return _root(state, registry, source, action, values, crystals)


def capture(state, registry, action, quote=None, *, rewind_session=None, game=None,
            player_observation=None, retry_observation=None):
    """Recompute the whole original vector before payment; mutate nothing."""
    if type(action) is not PlayCard: raise ValueError('Body targets require an exact paid action')
    action.__post_init__()
    profile = registry.body_target_profile(action.body_target_profile_id)
    if (profile.origin, profile.selection, profile.acceptance_window) != ('paid_hand', 'manual', 'pre_payment'):
        raise IllegalAction('This dispatcher requires its explicit manual paid-hand policy')
    source = state.entities.get(action.entity_id)
    if source is None or source.controller != action.player_id or source.zone != Zone.HAND or source.id not in state.players[action.player_id].hand:
        raise IllegalAction('Body vector requires the current owned hand source')
    if state.pending_choice is not None or state.status != 'playing' or state.active_player != action.player_id:
        raise IllegalAction('Body submission requires its actual active boundary')
    authorities = body_target_authorities(state, registry, BodyReference.capture(source), profile.id)
    from .body_target_origin import require_audited_predicate
    for authority in authorities:
        require_audited_predicate(registry, authority.declaration.contract.target_rule)
    # Undo/retry changes the paid face/window. Retention can reuse this one
    # accepted vector, but a fresh retry producer has not been connected yet.
    definition = registry.card(source.card_id)
    if Keyword.REWIND in source.keywords and definition.rewind is not None:
        from .rewind_outcomes import retention_sources
        if not retention_sources(state, action.player_id):
            from .paid_body_retries import require_policy
            require_policy(state, registry, action)
    values, crystals = _facts(state, registry, source, quote)
    root = _root(state, registry, source, action, values, crystals)
    observed = registry.target_visibility(root.target_rule) == 'player' or any(
        a.declaration.contract.target_visibility == 'player' for a in authorities)
    context = None
    if observed:
        from .player_target_inputs import capture as observe, validate_full_state, factory
        if player_observation is None:
            if game is None:
                raise ValueError('Player target reconstruction requires its original observation inputs')
            player_observation = observe(game, state, source)
        validate_full_state(state, registry, source, player_observation)
        context = factory(player_observation)
    elif player_observation is not None:
        raise ValueError('Built-in target receipt cannot borrow unrelated observation inputs')
    ordered, choices, flags, root_choices = _target_requirements(state, registry, source, action, authorities, values, crystals, context_factory=context)
    from .body_target_origin import capture_origin, origin_hash
    state_hash = canonical_hash(state_to_dict(state))
    origin = capture_origin(state, source, state_hash, player_observation)
    from .player_target_inputs import validate_origin
    validate_origin(registry, origin, source, history_state=state)
    receipt = PaidBodyTargetReceipt(action, ordered, choices, flags, root_choices,
        state_hash, registry.fingerprint(), origin, origin_hash(origin))
    if rewind_session is not None and rewind_session.attempt > 0:
        from .paid_body_retries import attach_retry_origin
        if observed and retry_observation is None:
            from .player_target_inputs import rewind_root_observation
            retry_observation = rewind_root_observation(game, rewind_session)
        receipt = attach_retry_origin(state, registry, receipt, quote, rewind_session,
            player_observation=retry_observation)
    return receipt


def _target_requirements(state, registry, source, action, authorities, values, crystals, *, context_factory=None):
    from .body_target_origin import require_audited_predicate
    submitted = {v.ability_id: v for v in action.body_targets}
    if set(submitted) != {a.declaration.reference.ability_id for a in authorities}:
        raise IllegalAction('Body vector has missing, extra or stale physical slots')
    ordered = []
    for a in authorities:
        v = submitted[a.declaration.reference.ability_id]
        if v != _selection(a.declaration.reference, v.target_id):
            raise IllegalAction('Body vector changed its complete physical identity')
        ordered.append(v)
    raw = _root(state, registry, source, action, values, crystals)
    root_choices = target_choices(state, registry, source, raw, context_factory=context_factory)
    if action.target_id not in root_choices:
        raise IllegalAction('Ordinary root target violates its independent requirement')
    choices, flags = [], []
    for a, selected in zip(authorities, ordered):
        contract = a.declaration.contract
        require_audited_predicate(registry, contract.target_rule)
        active = (contract.family != 'combo' or values['combo']) and contract.targeting is not None and _condition(values, crystals, contract.target_condition, contract.manathirst_threshold)
        body = replace(registry.card(contract.declaration_card_id), kind=source.kind)
        candidates = target_choices(state, registry, source, body, context_factory=context_factory) if active else (None,)
        if selected.target_id not in candidates:
            raise IllegalAction('Body target violates its own original activation/domain')
        choices.append(candidates); flags.append(active)
    return tuple(ordered), tuple(choices), tuple(flags), root_choices


def body_target(play, payload, family):
    if play.body_targets is None:
        return play.target_id
    selected = next((v for v in play.body_targets.selected if
        (v.family, v.ability_id, v.declaration_card_id, v.behavior_id) ==
        (family, payload.ability_id, payload.card_id, payload.behavior_id)), None)
    if selected is None:
        raise ResolutionError('Actual body was not submitted in the original paid target vector')
    return selected.target_id


def bind_actual_payloads(state, play, family, payloads):
    """Retain the existing family window; reject late or substituted bodies."""
    if play.body_targets is None: return
    source = state.entities[play.source_id]
    if source.controller != play.player_id:
        raise ResolutionError('Independent paid targets require the original accepted controller')
    for payload in payloads:
        body_target(play, payload, family)
        slot = next(v for v in play.body_targets.selected if v.ability_id == payload.ability_id)
        a = next((a for a in source.abilities if a.id == payload.ability_id), None)
        if a is None or (a.kind, a.behavior_id, a.origin, a.source_id, a.expires_turn) != (
                slot.family, slot.behavior_id, slot.origin, slot.grant_source_id, slot.expires_turn) or a.consumed:
            raise ResolutionError('Actual family window substituted its original physical body')


def validate_receipt(state, registry, play):
    """Rebuild terminal candidates/authority; pending payment also recaptures all inputs."""
    receipt = play.body_targets
    if receipt is None:
        if any(card_id == play.card_id for card_id, _ in registry.body_root_target_bindings):
            raise ValueError('Bound carrier history lost its original independent body target receipt')
        return
    receipt.__post_init__()
    if receipt.registry_fingerprint != registry.fingerprint():
        raise ValueError('Accepted body target policy differs from its trusted registry')
    profile = registry.body_target_profile(receipt.action.body_target_profile_id)
    if (profile.origin, profile.selection, profile.acceptance_window) != ('paid_hand', 'manual', 'pre_payment'):
        raise ValueError('Paid body history borrowed another origin policy')
    from .body_root_targets import validate_root_binding
    validate_root_binding(registry, registry.body_root_target_binding(play.card_id, profile.id))
    expected = tuple((family, p.ability_id, p.card_id, p.behavior_id) for family, payloads in
        (('battlecry', play.battlecries), ('combo', play.combos)) for p in payloads)
    actual = tuple((v.family, v.ability_id, v.declaration_card_id, v.behavior_id) for v in receipt.selected)
    if actual != expected: raise ValueError('Accepted vector differs from complete original physical body order')
    from .body_target_origin import reconstruct_origin
    original, source = reconstruct_origin(state, registry, play, receipt)
    from .paid_body_retries import validate_retry_origin
    validate_retry_origin(state, registry, play, original, source)
    from .magnetic import host_at_position
    host = host_at_position(original, registry, source, receipt.action.position)
    if play.magnetic_target_id != (None if host is None else host.id):
        raise ValueError('Accepted body root rewrote its original position-selected magnetic host')
    authorities = body_target_authorities(original, registry, BodyReference.capture(source), profile.id)
    values = {name: getattr(play, name) for name in ('combo', 'outcast', 'finale', 'quickdraw')}
    from .player_target_inputs import factory
    context = factory(receipt.origin.observation) if receipt.origin.observation is not None else None
    root = _root(original, registry, source, receipt.action, values, play.mana_crystals)
    observed = registry.target_visibility(root.target_rule) == 'player' or any(
        a.declaration.contract.target_visibility == 'player' for a in authorities)
    if observed != (receipt.origin.observation is not None):
        raise ValueError('Accepted target receipt lost or borrowed its original player inputs')
    selected, choices, active, root_choices = _target_requirements(original, registry, source, receipt.action, authorities, values, play.mana_crystals, context_factory=context)
    if (selected, choices, active, root_choices) != (receipt.selected, receipt.body_choices, receipt.body_target_active, receipt.root_choices):
        raise ValueError('Accepted targets differ from complete original candidate/authority reconstruction')
    for slot, choices, active in zip(receipt.selected, receipt.body_choices, receipt.body_target_active):
        contract = body_target_contract(registry, slot.declaration_card_id, slot.family)
        binding = registry.body_target_binding(slot.declaration_card_id, slot.family, profile.id)
        if (slot.carrier_card_id != play.card_id or slot.origin not in binding.origins or play.kind not in binding.carrier_kinds or
                binding.carrier_card_ids and play.card_id not in binding.carrier_card_ids or
                slot.ability_id >= state.next_attachment_id or slot.target_id is not None and slot.target_id not in state.entities):
            raise ValueError('Accepted body selection exceeds its original physical authority')
        from .body_target_origin import require_audited_predicate
        require_audited_predicate(registry, contract.target_rule)
        expected_active = (slot.family != 'combo' or play.combo) and contract.targeting is not None and _condition(values, play.mana_crystals, contract.target_condition, contract.manathirst_threshold)
        if active != expected_active: raise ValueError('Accepted body target rewrote its own frozen conditions')
        if any(t is not None and t not in state.entities for t in choices):
            raise ValueError('Original body target candidates contain a nonexistent physical entity')
    for family, acceptance in (('battlecry', play.battlecry_acceptance), ('combo', play.combo_acceptance)):
        if acceptance is not None:
            for payload in acceptance.payloads: body_target(play, payload, family)


def available(state, registry, play, payload, family, *, context_factory=None):
    if play.body_targets is None: return True
    target = body_target(play, payload, family)
    slot_index = next(i for i, v in enumerate(play.body_targets.selected) if v.family == family and v.ability_id == payload.ability_id)
    if not play.body_targets.body_target_active[slot_index] or target is None: return True
    source = deepcopy(state.entities[play.source_id])
    source.controller = play.player_id
    definition = replace(registry.card(payload.card_id), kind=play.kind)
    return accepts_target(state, registry, source, definition, target, context_factory=context_factory)
