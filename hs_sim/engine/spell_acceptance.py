"""Two original acceptance windows for a paid hand spell.

The durable play keeps compact declarations. Only its pending tail control
holds detached states, including a resolved countered window with no payload.
This control is diagnostic: its handler must run without a gameplay checkpoint.
"""
from copy import deepcopy
from dataclasses import dataclass, fields, replace

from .effects import Effect
from .errors import ResolutionError, ResolutionLimitExceeded
from .lifecycle import active_abilities
from .model import (CardType, Zone, GameState, PlayRecord, SpellSubmissionReceipt,
                    SpellRepeatContributor, SpellPayloadReceipt)
from .play_history import play_record
from .registry import RuleContext
from .spell_cost_proof import HandPlayCostProof


_PROGRESS = frozenset(('countered', 'completed', 'interrupted',
                       'spell_submission', 'spell_payload',
                       'spell_acceptance_closed', 'paid_hand_close', 'paid_hand_interrupt'))


def _identity(play):
    return tuple(getattr(play, f.name) for f in fields(PlayRecord)
                 if f.name not in _PROGRESS)


def _context_play(context):
    if (type(context) is not RuleContext or type(context.state) is not GameState or
            type(context.play) is not PlayRecord or context.play.kind != CardType.SPELL):
        raise ValueError('Spell acceptance requires a captured hand spell')
    if type(context.rewind_attempt) is not int or context.rewind_attempt != 0:
        raise ValueError('Spell acceptance requires its original root window')
    play = context.play
    if (context.source_id, context.player_id) != (play.source_id, play.player_id):
        raise ValueError('Spell acceptance has inconsistent source or player')
    if (play_record(context.state, play.id) != play or
            context.source_id not in context.state.entities or
            context.target_id is not None and context.target_id not in context.state.entities):
        raise ValueError('Spell acceptance is absent from its original state')
    if any(getattr(context, name) is not None for name in
           ('event', 'death', 'choice', 'player_effect', 'window', 'trigger',
            'cast', 'draw', 'power', 'battlecry', 'combo', 'deathrattle',
            'power_payload', 'end_turn')):
        raise ValueError('Spell acceptance cannot borrow another callback origin')
    return play


@dataclass(frozen=True)
class FinishSpellAcceptance(Effect):
    submission: RuleContext
    cost_proof: HandPlayCostProof
    resolution: RuleContext | None = None

    def __post_init__(self):
        original = _context_play(self.submission)
        if type(self.cost_proof) is not HandPlayCostProof:
            raise ValueError('Spell acceptance requires its complete prepayment cost proof')
        self.cost_proof.__post_init__()
        if self.cost_proof.prepared_play != original:
            raise ValueError('Spell acceptance cost proof belongs to a different prepared play')
        if original.completed or original.interrupted or original.countered:
            raise ValueError('Spell submission must precede its outcome')
        if self.resolution is not None:
            resolved = _context_play(self.resolution)
            if (resolved.completed or resolved.interrupted or
                    _identity(resolved) != _identity(original)):
                raise ValueError('Spell resolution belongs to another hand play')

    @property
    def play_id(self):
        return self.submission.play.id


def capture_submission(state, registry, play):
    """Pure matching at the existing pre-consumption submission window."""
    from .repeat_matching import spell_repeat_matches
    from .costs import capture_spell_cost_facts
    if type(play) is not PlayRecord or play.kind != CardType.SPELL:
        raise ValueError('Only a hand spell accepts submission policies')
    player = state.players[play.player_id]
    definition = registry.card(play.card_id)
    _validate_original_declarations(state, registry)
    facts = capture_spell_cost_facts(state, registry, play, tuple(m.spec for m in player.spell_modifiers))
    modifiers = tuple(m for m in player.spell_modifiers if spell_repeat_matches(
        m.spec, recipient_definition=definition, hero_class=player.hero_class,
        submitted_cost=play.submitted_cost, cost_facts=facts))
    return SpellSubmissionReceipt(player.hero_class, modifiers, facts)


def _validate_original_declarations(state, registry):
    """Every raw ID and declaration is checked before recipient/source false."""
    from .repeat_provenance import checked_live_attachments
    from .repeat_source_conditions import validate_source_declaration
    from .repeat_matching import validate_repeat_cost_declaration
    checked_live_attachments(state)
    for entity in state.entities.values():
        for ability in entity.abilities:
            if ability.kind == 'spell_repeat':
                if registry.card(entity.card_id).kind != CardType.MINION:
                    raise ValueError('Spell repeat sources require their physical minion carrier')
                validate_source_declaration(registry, ability.spell_repeat)
                validate_repeat_cost_declaration(registry, ability.spell_repeat)
    for death in state.death_history:
        for ability in death.abilities:
            if ability.kind == 'spell_repeat':
                if registry.card(death.card_id).kind != CardType.MINION:
                    raise ValueError('Frozen Spell repeat sources require a minion face')
                validate_source_declaration(registry, ability.spell_repeat)
                validate_repeat_cost_declaration(registry, ability.spell_repeat)
    for player in state.players.values():
        for modifier in player.spell_modifiers:
            validate_source_declaration(registry, modifier.spec, allow_source=False)
            validate_repeat_cost_declaration(registry, modifier.spec)


def capture_payload(state, registry, play, target_id):
    """Pure late board plan; the recipient remains the submitted card face."""
    if play.kind != CardType.SPELL or play.countered or play.spell_submission is None:
        raise ValueError('A spell payload requires an uncountered submission')
    player = state.players[play.player_id]
    definition = registry.card(play.card_id)
    from .costs import capture_spell_cost_facts
    _validate_original_declarations(state, registry)
    declarations = tuple(a.spell_repeat for identity in player.board
        for a in active_abilities(state.entities[identity], 'spell_repeat')
        if state.entities[identity].kind == CardType.MINION and state.entities[identity].active
        and not state.entities[identity].doomed and state.entities[identity].health > 0)
    facts = capture_spell_cost_facts(state, registry, play, declarations)
    contributors = capture_board_contributors(state, registry, play, cost_facts=facts)
    counts = [1]
    counts.extend(a.spell_repeat.casts for a in play.card_spell_repeats)
    counts.extend(m.spec.casts for m in play.spell_submission.modifiers)
    counts.extend(s.ability.spell_repeat.casts for s in contributors)
    behaviors = tuple(a.behavior_id for a in
                     active_abilities(state.entities[play.source_id], 'on_play'))
    return SpellPayloadReceipt(target_id, behaviors, player.hero_class,
                               contributors, max(counts), facts)


def capture_board_contributors(state, registry, play, *, cost_facts=None):
    """Shared pure late query, including every source's required witness facts."""
    from .repeat_matching import spell_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration, qualifying_repeat_witnesses
    player = state.players[play.player_id]
    definition = registry.card(play.card_id)
    _validate_original_declarations(state, registry)
    contributors = []
    for entity_id in player.board:
        entity = state.entities[entity_id]
        if (entity.kind != CardType.MINION or not entity.active or
                entity.doomed or entity.health <= 0):
            continue
        for ability in active_abilities(entity, 'spell_repeat'):
            condition = validate_source_declaration(registry, ability.spell_repeat)
            source_matches = (condition is None or bool(qualifying_repeat_witnesses(
                state, registry, player_id=player.id, carrier_id=entity.id, eligibility=condition)))
            recipient_matches = spell_repeat_recipient_matches(ability.spell_repeat,
                recipient_definition=definition, hero_class=player.hero_class,
                submitted_cost=play.submitted_cost, cost_facts=cost_facts)
            if source_matches and recipient_matches:
                contributors.append(SpellRepeatContributor(entity.id, ability))
    return tuple(contributors)


def accept_submission(r, play, cost_proof):
    """Install compact facts without consuming policies or emitting events."""
    live = play_record(r.state, play.id)
    if (live != play or play.kind != CardType.SPELL or play.completed or
            play.interrupted or play.spell_submission is not None or
            play.spell_payload is not None or play.spell_acceptance_closed):
        raise ResolutionError('A spell submission can be accepted only once')
    # Before the legacy receipt is appended: its live-use invariant describes
    # post-consumption states, which this original window deliberately is not.
    context = RuleContext(deepcopy(r.state), play.source_id, play.player_id,
                          play.target_id, play=play)
    receipt = capture_submission(context.state, r.registry, play)
    updated = replace(play, spell_submission=receipt)
    r.state.play_history[play.id - 1] = updated
    return updated, FinishSpellAcceptance(context, cost_proof)


def accept_resolution(r, play, target_id):
    """Bind the reached ResolveSpell window to its existing queued tail."""
    if (play_record(r.state, play.id) != play or play.kind != CardType.SPELL or
            play.completed or play.interrupted or play.spell_submission is None or
            play.spell_payload is not None or play.spell_acceptance_closed or
            any(w.play_id == play.id for w in r.state.action_windows)):
        raise ResolutionError('Spell resolution requires its closed original window')
    queue = r._work_queue
    found = [(i, w) for i, w in enumerate(queue)
             if type(w) is FinishSpellAcceptance and w.play_id == play.id]
    if len(found) != 1 or found[0][1].resolution is not None:
        raise ResolutionError('Spell resolution requires one unbound acceptance tail')
    index, proof = found[0]
    context = RuleContext(deepcopy(r.state), play.source_id, play.player_id,
                          target_id, play=play)
    receipt = None if play.countered else capture_payload(
        context.state, r.registry, play, target_id)
    if receipt is not None and receipt.casts > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Spell repetition exceeds resolution budget')
    updated = replace(play, spell_payload=receipt)
    r.state.play_history[play.id - 1] = updated
    queue[index] = replace(proof, resolution=context)
    return updated


def validate_acceptance(work, registry):
    """Recompute both original windows, without a Game or stable-frame audit."""
    if type(work) is not FinishSpellAcceptance:
        raise ValueError('Invalid spell acceptance proof')
    work.__post_init__()
    context = work.submission
    original = context.play
    from .spell_cost_proof import validate_hand_cost_proof
    validate_hand_cost_proof(work.cost_proof, registry, submission_state=context.state)
    if (context.source.zone != Zone.HAND or
            context.source.controller != original.player_id or
            context.source.kind != CardType.SPELL or
            context.source.card_id != original.card_id):
        raise ValueError('Spell submission lost its original physical hand card')
    if context.target_id != original.target_id:
        raise ValueError('Spell submission changed its original paid target')
    if (original.spell_submission is not None or original.spell_payload is not None or
            original.spell_acceptance_closed or
            any(w.play_id == original.id for w in context.state.action_windows) or
            any(c.play_id == original.id for c in context.state.cast_history) or
            any(x.play_id == original.id for x in context.state.spell_policy_receipts)):
        raise ValueError('Spell submission proof is not its pre-consumption window')
    from .card_spell_repeats import capture
    if original.card_spell_repeats != capture(context.source):
        raise ValueError('Spell submission lost its complete physical attachments')
    submission = capture_submission(context.state, registry, original)
    if work.resolution is None:
        return submission, None
    resolved = work.resolution.play
    state = work.resolution.state
    if (resolved.spell_submission != submission or resolved.spell_payload is not None or
            resolved.spell_acceptance_closed or
            any(w.play_id == resolved.id for w in state.action_windows) or
            any(c.play_id == resolved.id for c in state.cast_history) or
            any(x.play_id == resolved.id for x in state.spell_repeats)):
        raise ValueError('Spell resolution proof is not its pre-payload window')
    if resolved.countered:
        return submission, None
    payload = capture_payload(state, registry, resolved, work.resolution.target_id)
    for behavior in payload.behavior_ids:
        registry.behavior(behavior)
    return submission, payload


def _live_attachments(state):
    """Global IDs cannot move between attachment families or physical carriers."""
    from .repeat_provenance import checked_live_attachments
    return checked_live_attachments(state)


def _bind_original_board_sources(original, state):
    """Bind surviving declarations, including sources which accepted nothing.

    Control, zone and witnesses may change after acceptance. An attachment's
    physical carrier and static declaration cannot change under the same ID.
    Later allocations are independent; removed attachments need not survive.
    """
    before, live = _live_attachments(original), _live_attachments(state)
    identities = {identity for identity, (kind, _, value) in before.items()
                  if kind == 'ability' and value.kind == 'spell_repeat'}
    # A surviving pre-window source cannot be deleted from the original proof,
    # even when its condition was false and the contributor list was empty.
    identities.update(identity for identity, (kind, _, value) in live.items()
                      if identity < original.next_attachment_id and
                      kind == 'ability' and value.kind == 'spell_repeat')
    for identity in identities:
        current = live.get(identity)
        if current is None:
            continue
        previous = before.get(identity)
        if previous is None:
            raise ValueError('Spell original window lost a surviving board source')
        kind, carrier, ability = previous
        current_kind, current_carrier, current_ability = current
        if (kind != 'ability' or ability.kind != 'spell_repeat' or
                current_kind != 'ability' or current_carrier != carrier or
                replace(current_ability, consumed=ability.consumed) != ability or
                ability.consumed and not current_ability.consumed):
            raise ValueError('Spell original board source changed its surviving identity')


def _validate_contributors(state, registry, play, receipt, live):
    from .repeat_matching import spell_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration
    receipt.__post_init__()
    for source in receipt.contributors:
        ability = source.ability
        # Historical receipts validate declarations and identity, not witnesses
        # which may legitimately have changed since their original acceptance.
        validate_source_declaration(registry, ability.spell_repeat)
        if (source.carrier_id not in state.entities or
                ability.id >= state.next_attachment_id or
                ability.source_id is not None and ability.source_id not in state.entities or
                ability.expires_turn is not None and ability.expires_turn < play.turn or
                not spell_repeat_recipient_matches(ability.spell_repeat,
                    recipient_definition=registry.card(play.card_id),
                    hero_class=receipt.hero_class, submitted_cost=play.submitted_cost,
                    cost_facts=receipt.cost_facts)):
            raise ValueError('Invalid captured spell board contributor')
        current = live.get(ability.id)
        if current is not None:
            kind, carrier, value = current
            if (kind != 'ability' or carrier != source.carrier_id or
                    replace(value, consumed=ability.consumed) != ability):
                raise ValueError('Spell board source changed its surviving identity')
    counts = [1, *(a.spell_repeat.casts for a in play.card_spell_repeats),
              *(m.spec.casts for m in play.spell_submission.modifiers),
              *(s.ability.spell_repeat.casts for s in receipt.contributors)]
    if receipt.casts != max(counts):
        raise ValueError('Spell accepted count differs from its complete max plan')
    for behavior in receipt.behavior_ids:
        registry.behavior(behavior)


def _validate_cast_progress(state, play, *, allocated=False):
    casts = [c for c in state.cast_history if c.play_id == play.id]
    repeats = [x for x in state.spell_repeats if x.play_id == play.id]
    if len(repeats) > 1:
        raise ValueError('A spell cannot have multiple repetition roots')
    receipt = play.spell_payload
    if receipt is None:
        if repeats or not play.countered and casts:
            raise ValueError('Spell executions have no accepted payload')
        if (len(casts) > 1 or any(c.failure != 'countered' for c in casts) or
                (play.completed or allocated) and play.countered and len(casts) != 1):
            raise ValueError('Countered spell differs from its one denied cast')
        return
    if (len(casts) > receipt.casts or
            any(c.target_id != receipt.target_id or c.failure is not None for c in casts)):
        raise ValueError('Spell casts differ from their accepted count or target')
    if receipt.casts == 1:
        if repeats or allocated and len(casts) != 1:
            raise ValueError('A unit spell has inconsistent actual execution')
    elif repeats:
        repeat = repeats[0]
        if (repeat.casts, repeat.target_id, repeat.behavior_ids) != (
                receipt.casts, receipt.target_id, receipt.behavior_ids):
            raise ValueError('Spell repetition differs from its original acceptance')
        if repeat.interrupted:
            if len(casts) not in (repeat.completed, repeat.completed + 1):
                raise ValueError('Interrupted spell lost an allocated cast')
        elif len(casts) != repeat.completed + int(repeat.running):
            raise ValueError('Spell iteration progress lost an allocated cast')
    elif allocated:
        raise ValueError('A repeated spell lost its repetition record')
    if play.completed:
        if len(casts) != receipt.casts or any(not c.completed for c in casts):
            raise ValueError('Completed spell lost accepted executions')
        if receipt.casts > 1 and (not repeats or not repeats[0].finished):
            raise ValueError('Completed spell lost its finished repetition')
    for outcome in state.rewind_outcomes:
        if outcome.play_id == play.id and (outcome.behavior_ids != receipt.behavior_ids or
                outcome.target_id != receipt.target_id or
                outcome.cast_id not in {c.id for c in casts}):
            raise ValueError('Retained spell result differs from its original payload')


def validate_history(state, registry):
    """Compact invariants only: original contexts may precede acceptance writes."""
    from .repeat_matching import spell_repeat_matches
    from .spell_cost_proof import validate_compact_spell_costs
    _validate_original_declarations(state, registry)
    live = _live_attachments(state)
    captured = {}
    for play in state.play_history:
        if play.kind != CardType.SPELL:
            continue
        validate_compact_spell_costs(state, registry, play)
        receipt = play.spell_submission
        policies = [x for x in state.spell_policy_receipts if x.play_id == play.id]
        if receipt is None:
            if play.completed or play.interrupted or policies or play.spell_payload is not None:
                raise ValueError('Settled spell lost its durable submission acceptance')
            # An original context captured before accept_submission writes its
            # receipt is valid GameState data, but never a live stable root.
            continue
        receipt.__post_init__()
        if receipt.modifiers:
            if (len(policies) != 1 or
                    (policies[0].hero_class, policies[0].modifiers) !=
                    (receipt.hero_class, receipt.modifiers)):
                raise ValueError('Spell policy ledger differs from its submission receipt')
        elif policies:
            raise ValueError('Empty spell submission acquired a policy ledger')
        for modifier in receipt.modifiers:
            modifier.__post_init__()
            if (modifier.id >= state.next_attachment_id or modifier.created_turn > play.turn or
                    modifier.expires_turn is not None and modifier.expires_turn < play.turn or
                    modifier.source_id is not None and modifier.source_id not in state.entities or
                    not spell_repeat_matches(modifier.spec,
                        recipient_definition=registry.card(play.card_id),
                        hero_class=receipt.hero_class, submitted_cost=play.submitted_cost,
                        cost_facts=receipt.cost_facts)):
                raise ValueError('Invalid durable spell submission source')
            if modifier.source_card_id is not None:
                registry.card(modifier.source_card_id)
            if modifier.id in captured:
                owner, old = captured[modifier.id]
                expected = None if old.uses_remaining is None else old.uses_remaining - 1
                if (owner != play.player_id or old.uses_remaining == 1 or
                        modifier != replace(old, uses_remaining=expected)):
                    raise ValueError('Spell submission sources disagree on consumed uses')
            captured[modifier.id] = (play.player_id, modifier)
        if play.spell_payload is not None:
            _validate_contributors(state, registry, play, play.spell_payload, live)
        elif not play.countered and play.completed:
            raise ValueError('Completed spell lost its explicit payload acceptance')
        _validate_cast_progress(state, play)
    for identity, (owner, original) in captured.items():
        current = live.get(identity)
        if current is None:
            continue
        kind, current_owner, modifier = current
        expected = None if original.uses_remaining is None else original.uses_remaining - 1
        if (kind != 'spell_modifiers' or current_owner != owner or expected == 0 or
                modifier != replace(original, uses_remaining=expected)):
            raise ValueError('Spell submission source changed its surviving identity or uses')


def _bind_live(state, proof, registry):
    from .payment_projection import validate_cost_source_history
    submission, payload = validate_acceptance(proof, registry)
    _bind_prefix_and_references(proof.cost_proof.payment_state, state, registry)
    _bind_prefix_and_references(proof.submission.state, state, registry)
    validate_cost_source_history(proof.cost_proof.payment_state, state, registry)
    _bind_original_board_sources(proof.submission.state, state)
    if proof.resolution is not None:
        _bind_prefix_and_references(proof.submission.state, proof.resolution.state, registry)
        _bind_prefix_and_references(proof.resolution.state, state, registry)
        _bind_original_board_sources(proof.submission.state, proof.resolution.state)
        _bind_original_board_sources(proof.resolution.state, state)
    play = play_record(state, proof.play_id)
    if (_identity(play) != _identity(proof.submission.play) or
            play.spell_submission != submission or play.spell_payload != payload or
            proof.resolution is not None and play.countered != proof.resolution.play.countered):
        raise ValueError('Spell acceptance proof differs from its durable root')
    if proof.resolution is None and play.spell_payload is not None:
        raise ValueError('Spell payload was accepted without its resolution proof')
    _validate_retained_progress(state, proof, play, registry)
    return play


def _validate_retained_progress(state, proof, play, registry):
    """Every allocated paid-root cast owes the original session's full outcome.

    The true session before state supplies retention eligibility. This does
    not query today's retainer zone/controller or open another cost window.
    """
    from .model import Keyword
    from .rewind_outcomes import retention_sources
    from .repeat_provenance import _static_compatible
    session = proof.cost_proof.rewind_session
    contributors = ()
    definition = registry.card(play.card_id)
    if session is not None:
        original = session.before
        source = original.entities[play.source_id]
        if definition.rewind is not None and Keyword.REWIND in source.keywords:
            contributors = retention_sources(original, play.player_id)
        before, live = _live_attachments(original), _live_attachments(state)
        # All original retention declarations, including hostile/inactive ones,
        # keep their physical full identity if they still exist.
        for identity, (family, carrier, ability) in before.items():
            if family != 'ability' or ability.kind != 'rewind_retention' or identity not in live:
                continue
            current = live[identity]
            if current[:2] != (family, carrier) or not _static_compatible(family, ability, current[2]):
                raise ValueError('Spell original retention source changed its full physical identity')
    casts = [cast for cast in state.cast_history if cast.play_id == play.id]
    records = [record for record in state.rewind_outcomes if record.play_id == play.id]
    expected_casts = [cast for cast in casts if contributors and cast.payload_started and cast.failure is None]
    if len(records) != len(expected_casts):
        raise ValueError('Paid Spell lost or invented its mandatory original retained outcome span')
    for cast in expected_casts:
        matches = [record for record in records if record.cast_id == cast.id]
        if len(matches) != 1 or play.spell_payload is None:
            raise ValueError('Paid Spell cast lost its unique complete retained result obligation')
        record = matches[0]
        if ((record.source_id, record.player_id, record.card_id, record.turn, record.action,
                record.target_id, record.behavior_ids, record.contributors, record.total,
                record.play_id, record.cast_id, record.power_id, record.battlecries,
                record.combos, record.battlecry_plan, record.combo_plan) !=
                (play.source_id, play.player_id, cast.card_id, cast.turn, cast.action,
                play.spell_payload.target_id, play.spell_payload.behavior_ids, contributors,
                definition.rewind.retries + 1, play.id, cast.id, None, (), (), None, None) or
                cast.completed and (not record.finished or record.interrupted or record.completed != record.total)):
            raise ValueError('Paid Spell changed its accepted retained count, payload or execution identity')


def _bind_prefix_and_references(original, state, registry):
    """Bind full accepted slots, including later fields on an older PlayRecord."""
    from .choose_policies import validate_prefix as validate_choose_prefix
    validate_choose_prefix(original, state)
    from .payment_projection import validate_cost_source_history
    from .repeat_provenance import accepted_repeat_source_references, _reference_matches
    validate_cost_source_history(original, state, registry)
    if ((state.turn, state.action_number) < (original.turn, original.action_number) or
            any(getattr(state, name) < getattr(original, name) for name in
                ('next_entity_id', 'next_attachment_id', 'next_order', 'next_death_id', 'next_death_batch')) or
            len(state.play_history) < len(original.play_history) or
            state.death_history[:len(original.death_history)] != original.death_history or
            state.spell_policy_receipts[:len(original.spell_policy_receipts)] != original.spell_policy_receipts):
        raise ValueError('Spell acceptance moved its complete history/allocation prefix backwards')
    for old, new in zip(original.play_history, state.play_history):
        progress = _PROGRESS | {'minion_result', 'battlecry_acceptance', 'combo_submission_receipt_id', 'combo_acceptance'}
        fixed = lambda value: tuple(getattr(value, field.name) for field in fields(PlayRecord) if field.name not in progress)
        if (fixed(old) != fixed(new) or old.completed and not new.completed or
                old.interrupted and not new.interrupted or old.countered and not new.countered or
                old.spell_acceptance_closed and not new.spell_acceptance_closed or
                old.paid_hand_close is not None and old.paid_hand_close != new.paid_hand_close or
                old.paid_hand_interrupt is not None and old.paid_hand_interrupt != new.paid_hand_interrupt or
                any(getattr(old, name) is None and getattr(new, name) is not None
                    and getattr(new, name).action < original.action_number
                    for name in ('paid_hand_close', 'paid_hand_interrupt')) or
                old.spell_submission is not None and old.spell_submission != new.spell_submission or
                old.spell_payload is not None and old.spell_payload != new.spell_payload or
                any(getattr(old, name) is not None and getattr(new, name) != getattr(old, name)
                    for name in ('minion_result', 'battlecry_acceptance', 'combo_submission_receipt_id', 'combo_acceptance'))):
            raise ValueError('Spell acceptance rewrote an existing full hand root or accepted receipt')
    before, current = _live_attachments(original), _live_attachments(state)
    if any(identity < original.next_attachment_id and identity not in before for identity in current):
        raise ValueError('Later acceptance resurrected an absent old global source identity')
    earlier = accepted_repeat_source_references(original)
    later = accepted_repeat_source_references(state)
    if any(later.get(key) != reference for key, reference in earlier.items()):
        raise ValueError('Spell acceptance rewrote an already accepted typed source slot')
    for key, reference in later.items():
        if key in earlier or reference.identity >= original.next_attachment_id:
            continue
        item = before.get(reference.identity)
        if item is not None:
            if not _reference_matches(item, reference, registry):
                raise ValueError('Later repeat/fee window changed the original complete typed source')
            if reference.value is None and reference.identity in current:
                from .repeat_provenance import _static_compatible
                live = current[reference.identity]
                if live[:2] != item[:2] or not _static_compatible(item[0], item[2], live[2]):
                    raise ValueError('Later ID-only source changed its full surviving physical identity')
        elif not any((old.family, old.carrier, old.owner, old.value, old.spec_index, old.spec) ==
                (reference.family, reference.carrier, reference.owner, reference.value, reference.spec_index, reference.spec)
                for old in earlier.values() if old.identity == reference.identity):
            raise ValueError('Later acceptance borrowed an absent or foreign old global source identity')


def _bind_foreign_windows(registry, proofs, work):
    from .repeat_windows import original_acceptance_windows
    from .end_turn_acceptance import _window_precedes
    for context, phase, identity in original_acceptance_windows(work):
        for proof in proofs:
            if work is proof:
                continue
            if _window_precedes(proof.submission.state, context, phase, identity, registry, work):
                continue
            if len(context.state.play_history) < proof.play_id:
                raise ValueError('Later foreign window lost its accepted paid Spell root')
            _bind_live(context.state, proof, registry)


def validate_control_work(r, work):
    """Actual popped work remains covered until its callback/branch is checked."""
    proofs = [item for item in r._work_queue if type(item) is FinishSpellAcceptance]
    if type(work) is FinishSpellAcceptance:
        proofs.append(work)
    owed = [play.id for play in r.state.play_history
            if play.kind == CardType.SPELL and not play.spell_acceptance_closed]
    if sorted(proof.play_id for proof in proofs) != owed:
        raise ValueError('Popped Spell control lost or duplicated a complete active root proof')
    for proof in proofs:
        _bind_live(r.state, proof, r.registry)
        from .spell_cost_proof import validate_hand_cost_proof_live
        validate_hand_cost_proof_live(proof.cost_proof, r.game)
    _bind_foreign_windows(r.registry, proofs, work)


def _belongs_to_play(work, play, state):
    """Bind tagged controls and callbacks, without guessing from source IDs."""
    from .resolver import BehaviorCall, FinishPlay
    from .spell_casts import FinishSpellCast
    from .spell_repeats import StartSpellIteration
    from .rewind_outcomes import StartRewindOutcome
    if type(work) is BehaviorCall:
        context = work.context
        belongs = False
        if context.play is not None and context.play.id == play.id:
            if (_identity(context.play) != _identity(play) or
                    context.play.spell_acceptance_closed != play.spell_acceptance_closed):
                raise ValueError('Spell callback belongs to a different frozen hand play')
            belongs = True
        if context.cast is not None and context.cast.play_id == play.id:
            captured = play_record(context.state, play.id)
            if (_identity(captured) != _identity(play) or
                    captured.spell_acceptance_closed != play.spell_acceptance_closed):
                raise ValueError('Spell cast callback belongs to a different frozen hand play')
            belongs = True
        return belongs
    return (type(work) is FinishPlay and work.play_id == play.id or
            isinstance(work, StartSpellIteration) and work.play_id == play.id or
            type(work) is FinishSpellCast and any(c.id == work.cast_id and
                c.play_id == play.id for c in state.cast_history) or
            isinstance(work, StartRewindOutcome) and any(o.id == work.record_id and
                o.play_id == play.id for o in state.rewind_outcomes))


def _validate_callback_roots(queue, state):
    """Completed historical callbacks are valid when their root is still closed."""
    from .resolver import BehaviorCall
    for work in queue:
        if type(work) is not BehaviorCall:
            continue
        context = work.context
        ids = set()
        if context.play is not None and context.play.kind == CardType.SPELL:
            ids.add(context.play.id)
        if context.cast is not None and context.cast.play_id is not None:
            ids.add(context.cast.play_id)
        for identity in ids:
            play = play_record(state, identity)
            if play.kind != CardType.SPELL or not _belongs_to_play(work, play, state):
                raise ValueError('Spell callback lost its durable hand root')


def validate_queue(state, registry, queue, max_resolution_steps, *, terminal=False, closing=None):
    """Bind the complete pending span, including an actually popped closing tail."""
    from .interrupts import SpellTargetPhase, ResolveSpell
    from .resolver import FinishPlay
    if type(state) is not GameState or type(terminal) is not bool:
        raise ValueError('Spell queue proof requires a complete typed current state')
    queue = tuple(queue)
    if closing is not None:
        if type(closing) is not FinishSpellAcceptance or any(w is closing for w in queue):
            raise ValueError('Spell closing proof must be the actual unique popped tail')
        queue = (closing, *queue)
    proofs = [(i, w) for i, w in enumerate(queue) if type(w) is FinishSpellAcceptance]
    proof_ids = tuple(w.play_id for _, w in proofs)
    if any(a <= b for a, b in zip(proof_ids, proof_ids[1:])):
        raise ValueError('Spell acceptance tails are duplicated or reordered')
    _validate_callback_roots(queue, state)
    owed = [p for p in state.play_history if p.kind == CardType.SPELL and
            not p.spell_acceptance_closed]
    for play in state.play_history:
        if play.kind == CardType.SPELL and play.spell_submission is None:
            raise ValueError('Live spell root lost its submission obligation')
    if state.status != 'playing' and not terminal:
        if proofs:
            raise ValueError('Terminal spell acceptance cannot keep queued work')
        return
    if sorted(w.play_id for _, w in proofs) != [p.id for p in owed]:
        raise ValueError('Spell roots and acceptance tails differ')
    for index, proof in proofs:
        play = _bind_live(state, proof, registry)
        if play.spell_acceptance_closed or play.interrupted:
            raise ValueError('Settled spell retained its acceptance tail')
        windows = [w for w in state.action_windows if w.play_id == play.id]
        if proof.resolution is None:
            if (len(windows) != 1 or windows[0].kind != 'spell' or
                    play.completed or play.spell_payload is not None):
                raise ValueError('Unresolved spell acceptance lost its real window')
            starters = [i for i, w in enumerate(queue) if
                        type(w) in (SpellTargetPhase, ResolveSpell) and w.window_id == windows[0].id]
            if len(starters) != 1 or starters[0] >= index:
                raise ValueError('Spell resolution follows its acceptance closure')
            if any(c.play_id == play.id for c in state.cast_history):
                raise ValueError('Unresolved spell already allocated casts')
        else:
            if windows:
                raise ValueError('Resolved spell acceptance retained its action window')
            finishers = [i for i, w in enumerate(queue) if
                         type(w) is FinishPlay and w.play_id == play.id]
            if (play.completed and finishers or not play.completed and
                    (len(finishers) != 1 or finishers[0] >= index)):
                raise ValueError('Resolved spell lost its correctly ordered play completion')
            _validate_cast_progress(state, play, allocated=True)
            if play.spell_payload is not None and play.spell_payload.casts > max_resolution_steps:
                raise ValueError('Spell accepted plan exceeds the resolution budget')
        for position, work in enumerate(queue):
            if _belongs_to_play(work, play, state) and position >= index:
                raise ValueError('Spell work follows its full acceptance proof')
    for work in queue:
        _bind_foreign_windows(registry, [proof for _, proof in proofs], work)
    from .rewind_outcomes import validate_queue as validate_outcome_queue
    validate_outcome_queue(state, queue, max_resolution_steps)


def validate_boundary(game):
    """Live roots owe a unique proof; captured GameStates do not owe a frame."""
    from .spell_cost_proof import validate_hand_cost_proof_live
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    proofs = [w for w in queue if type(w) is FinishSpellAcceptance]
    ledger = game._frame.spell_acceptances if game._frame else ()
    if (type(ledger) is not tuple or any(type(i) is not int or i < 1 for i in ledger) or
            any(a <= b for a, b in zip(ledger, ledger[1:])) or
            tuple(w.play_id for w in proofs) != ledger):
        raise ValueError('Spell acceptance tails differ from their ordered frame obligations')
    for proof in proofs:
        validate_hand_cost_proof_live(proof.cost_proof, game)
    validate_queue(game._state, game.registry, queue, game.ruleset.max_resolution_steps)
    if any(p.kind == CardType.SPELL and not p.spell_acceptance_closed
           for p in game._state.play_history) and game._state.status == 'playing' and game._frame is None:
        raise ValueError('Active spell acceptance requires a suspended frame')


def validate_terminal_queue(r, queue):
    from .spell_cost_proof import validate_hand_cost_proof_live
    for work in queue:
        if type(work) is FinishSpellAcceptance:
            validate_hand_cost_proof_live(work.cost_proof, r.game)
    validate_queue(r.state, r.registry, queue, r.rules.max_resolution_steps, terminal=True)


def finish(r, work):
    from .spell_cost_proof import validate_hand_cost_proof_live
    validate_hand_cost_proof_live(work.cost_proof, r.game)
    validate_queue(r.state, r.registry, r._work_queue, r.rules.max_resolution_steps, closing=work)
    play = _bind_live(r.state, work, r.registry)
    if (work.resolution is None or not play.completed or play.interrupted or
            play.spell_acceptance_closed or
            any(w.play_id == play.id for w in r.state.action_windows)):
        raise ResolutionError('Spell acceptance closed before its completed root')
    validate_history(r.state, r.registry)
    _validate_cast_progress(r.state, play, allocated=True)
    if any(not c.completed for c in r.state.cast_history if c.play_id == play.id):
        raise ResolutionError('Spell acceptance closed before its actual casts')
    if any(not o.finished for o in r.state.rewind_outcomes if o.play_id == play.id):
        raise ResolutionError('Spell acceptance closed before retained outcomes')
    if any(_belongs_to_play(w, play, r.state) for w in r._work_queue):
        raise ResolutionError('Spell acceptance closed before its tagged root work')
    if any(type(w) is FinishSpellAcceptance and w.play_id > play.id for w in r._work_queue):
        raise ResolutionError('Spell acceptance closed before its nested hand play')
    r.state.play_history[play.id - 1] = replace(play, spell_acceptance_closed=True)


def register(mechanics):
    mechanics.register(FinishSpellAcceptance, finish)
