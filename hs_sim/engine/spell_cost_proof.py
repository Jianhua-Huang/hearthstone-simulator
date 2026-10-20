"""Physical paid Spell quote and payment origin proofs.

These states explain payment before the two existing repeat acceptance windows.
No quote, projection or validator executes a handler, event or checkpoint.
"""
from copy import deepcopy
from dataclasses import dataclass, replace

from .model import CardType, GameState, HandPlayCostReceipt, PlayRecord, Zone
from .rewind import HandSpellRewindAnchor


@dataclass(frozen=True)
class HandPlayCostProof:
    payment_state: GameState
    prepared_play: PlayRecord
    rewind_anchor: HandSpellRewindAnchor | None = None
    rewind_session: HandSpellRewindAnchor | None = None

    def __post_init__(self):
        if type(self.payment_state) is not GameState or type(self.prepared_play) is not PlayRecord:
            raise ValueError('Spell cost proof requires complete typed prepayment state and play')
        play = self.prepared_play
        play.__post_init__()
        if (play.kind != CardType.SPELL or play.submitted_cost is None or
                play.countered or play.completed or play.interrupted or
                play.spell_submission is not None or play.spell_payload is not None or play.spell_acceptance_closed):
            raise ValueError('Spell cost proof requires the original next prepared paid Spell')
        if self.rewind_anchor is not None:
            if type(self.rewind_anchor) is not HandSpellRewindAnchor:
                raise ValueError('Spell cost proof requires a typed real retry anchor')
            self.rewind_anchor.__post_init__()
            if self.rewind_anchor.attempt < 1:
                raise ValueError('A submitted retry quote requires an actual later attempt')
        if self.rewind_session is not None:
            if type(self.rewind_session) is not HandSpellRewindAnchor:
                raise ValueError('Spell retained origin requires the complete real typed session')
            self.rewind_session.__post_init__()
            expected = self.rewind_session if self.rewind_session.attempt > 0 else None
            if self.rewind_anchor != expected:
                raise ValueError('Spell cost retry anchor and actual Rewind session differ')
        elif self.rewind_anchor is not None:
            raise ValueError('Spell retry quote lost its complete actual session')

    @property
    def quote_state(self):
        return self.payment_state if self.rewind_anchor is None else self.rewind_anchor.before


def capture_hand_cost_proof(r, prepared_play, quote):
    return _capture_hand_cost_proof(r, prepared_play, quote, HandPlayCostProof)


def _capture_hand_cost_proof(r, prepared_play, quote, proof_type):
    from .costs import capture_cost_input, capture_quote_fact, cost_quote_from_fact
    from .rewind import capture_hand_spell_session
    if type(prepared_play) is not PlayRecord or (proof_type is HandPlayCostProof) != (prepared_play.kind == CardType.SPELL):
        raise ValueError('Prepared paid hand kind differs from its registered proof family')
    payment_state = deepcopy(r.state)
    session = capture_hand_spell_session(r, prepared_play.source_id)
    anchor = session if session is not None and session.attempt > 0 else None
    quote_state = payment_state if anchor is None else anchor.before
    source = quote_state.entities[prepared_play.source_id]
    fact = capture_quote_fact(quote_state, r.registry, capture_cost_input(source))
    if cost_quote_from_fact(fact) != quote:
        raise ValueError('Real payment quote differs from its complete original quote fact')
    receipt = HandPlayCostReceipt('current_hand' if anchor is None else 'rewind_root',
        quote_state.turn, quote_state.action_number, source.hand_entry_id, source.zone_epoch,
        r.registry.card(source.card_id).cost, fact)
    play = replace(prepared_play, submitted_cost=receipt)
    proof = proof_type(payment_state, play, anchor, session)
    _validate_hand_cost_proof(proof, r.registry, proof_type=proof_type)
    from .cost_presence import note_paid as note_controlled_price
    note_controlled_price(r,play,fact)
    from .adjoining_spells import note_paid as note_adjoining_paid
    note_adjoining_paid(r,play,quote_state)
    return play, proof


def validate_hand_cost_proof(proof, registry, *, submission_state=None):
    return _validate_hand_cost_proof(proof, registry, submission_state=submission_state)


def _validate_hand_cost_proof(proof, registry, *, submission_state=None, proof_type=HandPlayCostProof):
    """Requote the correct true origin, then compare exact shared payment writes."""
    from .costs import capture_cost_input, capture_quote_fact, cost_quote_from_fact
    from .payment_projection import validate_cost_source_history, validate_spell_payment_submission
    from .play_history import prepare_play
    from .rewind import normalized_hand_spell_retry, normalized_hand_play_retry
    if type(proof) is not proof_type:
        raise ValueError('Expected complete hand Spell cost proof')
    proof.__post_init__()
    before, play, origin = proof.payment_state, proof.prepared_play, proof.quote_state
    source = before.entities.get(play.source_id)
    quoted = origin.entities.get(play.source_id)
    if (before.status != 'playing' or source is None or quoted is None or
            source.kind != play.kind or quoted.kind != play.kind or
            source.zone != Zone.HAND or quoted.zone != Zone.HAND or
            source.controller != play.player_id or quoted.controller != play.player_id or
            source.id not in before.players[play.player_id].hand or quoted.id not in origin.players[play.player_id].hand or
            play.id != len(before.play_history) + 1 or (play.turn, play.action) != (before.turn, before.action_number)):
        raise ValueError('Spell cost proof lost its actual next physical hand payment')
    if any(not registry.card(e.card_id).hand_playable or
            not registry.card(e.card_id).manual_playable for e in (source, quoted)):
        raise ValueError('Hand cost proof lost original manual play permission')
    from .play_requirements import manual_requirement_error
    if manual_requirement_error(before, registry, source):
        raise ValueError('Hand cost proof lost its original manual play prerequisite')
    from .player_effects import manual_play_allowed
    if not manual_play_allowed(before, registry, play.player_id, source.kind):
        raise ValueError('Hand cost proof lost original current-turn type permission')
    if proof.rewind_anchor is not None:
        anchor = proof.rewind_anchor
        if (anchor.action.entity_id, anchor.action.player_id, anchor.action.target_id,
                anchor.action.position, anchor.action.branch_id, anchor.action.board_player_id) != (
                play.source_id, play.player_id, play.target_id, play.position, play.branch_id, play.board_player_id):
            raise ValueError('Spell retry cost proof changed the real root action')
        normalize = normalized_hand_spell_retry if proof_type is HandPlayCostProof else normalized_hand_play_retry
        if normalize(anchor, registry, before) != before:
            raise ValueError('Spell retry payment is not the normalized actual before/face/cursor state')
    elif origin is not before:
        raise ValueError('Ordinary hand payment cannot borrow another quote state')
    if proof.rewind_session is not None:
        session = proof.rewind_session
        saved = session.before.entities.get(play.source_id)
        from .model import Keyword
        if ((session.action.entity_id, session.action.player_id, session.action.target_id,
                session.action.position, session.action.branch_id, session.action.board_player_id) !=
                (play.source_id, play.player_id, play.target_id, play.position, play.branch_id, play.board_player_id) or
                saved is None or saved.zone != Zone.HAND or saved.controller != play.player_id or
                Keyword.REWIND not in saved.keywords or registry.card(saved.card_id).rewind is None or
                session.attempt > registry.card(saved.card_id).rewind.retries or
                session.attempt == 0 and session.before != before):
            raise ValueError('Spell cost proof changed its original complete Rewind activation session')
    fact = capture_quote_fact(origin, registry, capture_cost_input(quoted))
    expected_receipt = HandPlayCostReceipt('current_hand' if proof.rewind_anchor is None else 'rewind_root',
        origin.turn, origin.action_number, quoted.hand_entry_id, quoted.zone_epoch,
        registry.card(quoted.card_id).cost, fact)
    if play.submitted_cost != expected_receipt:
        raise ValueError('Spell submitted cost rewrote its complete original input or contributions')
    quote = cost_quote_from_fact(fact)
    body_receipt = None
    if play.body_targets is not None:
        from .paid_body_targets import capture as capture_paid_body_targets
        body_receipt = capture_paid_body_targets(before, registry, play.body_targets.action, quote,
            rewind_session=proof.rewind_session,
            player_observation=play.body_targets.origin.observation,
            retry_observation=None if play.body_targets.retry_root is None else play.body_targets.retry_root.origin.observation)
        if proof.rewind_session is not None:
            from .paid_body_retries import retry_action
            expected_action = proof.rewind_session.action if proof.rewind_session.attempt == 0 else retry_action(
                before, registry, proof.rewind_session.action)
            if expected_action != body_receipt.action:
                raise ValueError('Body targets changed the actual original Rewind selection')
    from .magnetic import host_at_position
    host = host_at_position(before, registry, source, play.position)
    if play.magnetic_target_id != (None if host is None else host.id):
        raise ValueError('Original hand payment changed its position-selected magnetic host')
    expected_play = prepare_play(before, registry, source, play.target_id, quote,
        position=play.position, magnetic_target_id=play.magnetic_target_id, branch_id=play.branch_id,
        body_targets=body_receipt, board_player_id=play.board_player_id)
    if replace(expected_play, submitted_cost=expected_receipt) != play:
        raise ValueError('Spell cost proof changed the complete prepared play or hand acquisition')
    validate_cost_source_history(origin, before, registry)
    if submission_state is not None:
        if type(submission_state) is not GameState:
            raise ValueError('Spell payment projection requires its actual submission state')
        validate_spell_payment_submission(before, quote, play, submission_state, registry)
        validate_cost_source_history(before, submission_state, registry)


def validate_hand_cost_proof_live(proof, game):
    """A retry cannot replace its true anchor with a new ordinary hand quote."""
    from .actions import PlayCard
    from .rewind import RewindSession, validate_hand_spell_anchor_live
    proof.__post_init__()
    session = game._rewind
    real_session = (type(session) is RewindSession and type(session.action) is PlayCard and
        session.action.entity_id == proof.prepared_play.source_id and
        session.action.player_id == proof.prepared_play.player_id)
    if real_session != (proof.rewind_session is not None):
        raise ValueError('Spell cost origin lost or invented its actual complete Rewind session')
    real_retry = real_session and session.attempt > 0
    if real_retry != (proof.rewind_anchor is not None):
        raise ValueError('Spell cost origin lost or invented its actual Rewind retry')
    validate_hand_spell_anchor_live(proof.rewind_session, game)


def validate_cost_fact_identity(state, registry, fact, *, play=None):
    """Compact frozen identity checks. Never requery live prices or eligibility."""
    from .repeat_matching import validate_cost_quote_fact
    from .repeat_provenance import checked_live_attachments, _static_compatible
    validate_cost_quote_fact(registry, fact)
    from .intrinsic_costs import validate_intrinsic_history_prefix
    validate_intrinsic_history_prefix(fact.intrinsic, state, registry)
    value = fact.quote_input
    if value.source_id not in state.entities or value.player_id not in state.players:
        raise ValueError('Historical quote has no physical source or payer')
    if play is not None and (value.source_id, value.player_id, value.kind) != (
            play.source_id, play.player_id, play.kind):
        raise ValueError('Historical hand quote borrowed another physical subject')
    live = checked_live_attachments(state)
    for contribution in fact.contributions:
        from .costs import validate_first_play_cost_prefix
        validate_first_play_cost_prefix(state, registry, contribution.first_play)
        if contribution.enchantment is not None:
            family, carrier, old = 'enchantment', contribution.carrier_id, contribution.enchantment
        elif contribution.modifier is not None:
            family, carrier, old = 'cost_modifiers', contribution.player_id, contribution.modifier
        else:
            family, carrier, old = 'ability', contribution.carrier_id, contribution.ability
        if old.id >= state.next_attachment_id or carrier not in (state.players if family == 'cost_modifiers' else state.entities):
            raise ValueError('Historical quote references an unallocated or missing cost carrier')
        current = live.get(old.id)
        if current is not None and (current[:2] != (family, carrier) or
                not _static_compatible(family, old, current[2])):
            raise ValueError('Historical cost contribution changed global family or physical identity')


def validate_compact_spell_costs(state, registry, play):
    if play.kind != CardType.SPELL:
        raise ValueError('Spell compact validation requires its Spell root')
    return validate_compact_hand_costs(state, registry, play)


def validate_compact_hand_costs(state, registry, play):
    from .repeat_matching import validate_cost_quote_fact, validate_spell_cost_facts
    from .rewind import face_signature
    receipt = play.submitted_cost
    if receipt is None:
        if play.spell_submission is not None or play.completed:
            raise ValueError('Accepted paid Spell lost its original submitted cost fact')
        return
    receipt.__post_init__()
    validate_cost_quote_fact(registry, receipt.quote)
    from .model import HandOtherClassMatch
    conditions = receipt.quote.intrinsic.condition_facts
    if receipt.quote_origin == 'current_hand' and conditions and type(conditions[0]) is HandOtherClassMatch:
        rows = conditions[0].rows
        if (len(rows) != play.hand_size or
                (rows[play.hand_index].entity_id, rows[play.hand_index].card_id) !=
                (play.source_id,receipt.quote.quote_input.card_id)):
            raise ValueError('Hand class price lost the complete original submitted hand or subject position')
    validate_cost_fact_identity(state, registry, receipt.quote, play=play)
    original = registry.card(receipt.quote.quote_input.card_id)
    accepted = registry.card(play.card_id)
    if not original.hand_playable or not original.manual_playable:
        raise ValueError('Historical hand payment lost original manual play permission')
    if receipt.printed_cost != original.cost:
        raise ValueError('Historical submitted quote changed its printed original face')
    if receipt.quote_origin == 'rewind_root' and face_signature(original) != face_signature(accepted):
        raise ValueError('Historical retry quote changed its underlying face signature')
    matches = [row for row in state.cost_use_history if (row.turn, row.action, row.player_id, row.source_id, row.origin) ==
        (play.turn, play.action, play.player_id, play.source_id, 'payment')]
    # Prepayment detached proof has not installed this play; its original
    # submission has installed both the play and the actual cost-use record.
    if play in state.play_history:
        if len(matches) != 1:
            raise ValueError('Paid Spell cost fact lost its unique actual global cost-use record')
        row = matches[0]
        modifiers = tuple(c.modifier for c in receipt.quote.contributions if c.modifier is not None)
        if (row.source_card_id, row.amount, row.payment, row.modifier_ids, row.player_modifiers, row.consumable_ids) != (
                play.card_id, receipt.quote.amount, receipt.quote.payment, receipt.quote.modifier_ids, modifiers, receipt.quote.consumable_ids):
            raise ValueError('Submitted Spell quote differs from its actual cost-use clock entry')
        from .model import CurrentDeckCountMatch, PermanentManaMatch
        intrinsic = receipt.quote.intrinsic
        current_deck = (intrinsic.condition_facts[0] if intrinsic.condition_facts
            and type(intrinsic.condition_facts[0]) is CurrentDeckCountMatch else None)
        if row.current_deck != current_deck:
            raise ValueError('Submitted price changed its complete original deck condition retained by the actual cost-use receipt')
        permanent_mana = (intrinsic.condition_facts[0] if intrinsic.condition_facts
            and type(intrinsic.condition_facts[0]) is PermanentManaMatch else None)
        if row.permanent_mana != permanent_mana:
            raise ValueError('Submitted price changed its original permanent mana payment operand')
    for accepted_receipt in (play.spell_submission, play.spell_payload):
        if accepted_receipt is None or accepted_receipt.cost_facts is None:
            continue
        facts = accepted_receipt.cost_facts
        validate_spell_cost_facts(registry, facts)
        from .intrinsic_costs import validate_intrinsic_history_prefix
        validate_intrinsic_history_prefix(facts.intrinsic, state, registry)
        if (facts.cost_input.source_id, facts.cost_input.player_id, facts.cost_input.card_id, facts.cost_input.kind,
                facts.printed_cost) != (play.source_id, play.player_id, play.card_id, CardType.SPELL, accepted.cost):
            raise ValueError('Accepted Spell cost facts changed their original recipient face')
        if facts.cost_input.minimum_cost != receipt.quote.quote_input.minimum_cost:
            raise ValueError('Accepted Spell quote changed its original hand minimum')
        for fact in facts.window_quotes:
            validate_cost_fact_identity(state, registry, fact, play=play)
