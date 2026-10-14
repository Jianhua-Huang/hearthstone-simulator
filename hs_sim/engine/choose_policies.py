"""Player Choose Both policies, accepted once per real qualifying root.

Legality is pure. Policies declare kinds and origins explicitly; a paid card's
repeated payloads reuse its root, while a new automatic attempt owns a new use.
Full pending proofs bind the original window, and compact receipts retain
consistency after closure. They do not authenticate unsigned external saves.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
import json

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import attachment_id, active_abilities
from .model import CardType, GameState, Zone, _name
from .serialization import canonical_hash, entity_from_dict, entity_to_dict, state_to_dict


KINDS = (CardType.MINION, CardType.SPELL, CardType.HERO_POWER)
ORIGINS = ('hand', 'cast_effect', 'cast_draw', 'cast_history', 'physical',
           'power_manual', 'power_effect')


def declaration(kinds, origins):
    if (type(kinds) is not tuple or not kinds or len(set(kinds)) != len(kinds) or
            any(type(k) is not CardType or k not in KINDS for k in kinds) or
            type(origins) is not tuple or not origins or len(set(origins)) != len(origins) or
            any(type(o) is not str or o not in ORIGINS for o in origins)):
        raise ValueError('Choose Both policies require explicit unique kinds and origins')
    for origin in origins:
        permitted = ((CardType.MINION, CardType.SPELL) if origin == 'hand' else
                     (CardType.MINION,) if origin == 'physical' else
                     (CardType.HERO_POWER,) if origin.startswith('power_') else (CardType.SPELL,))
        if not set(kinds) & set(permitted):
            raise ValueError('Choose Both policy origin cannot match any declared kind')


@dataclass(frozen=True)
class ChooseBothModifier:
    id: int
    player_id: int
    source_id: int | None
    source_card_id: str | None
    created_turn: int
    uses_remaining: int | None = None
    expires_turn: int | None = None
    kinds: tuple[CardType, ...] = (CardType.MINION, CardType.SPELL)
    origins: tuple[str, ...] = ('hand',)

    def __post_init__(self):
        _integer(self.id, 'Choose Both policy identity', 1); _player(self.player_id)
        _source(self.source_id); _integer(self.created_turn, 'Choose Both creation turn', 1)
        if (self.source_id is None) != (self.source_card_id is None):
            raise ValueError('Choose Both source requires its original card identity')
        if self.source_card_id is not None: _name(self.source_card_id, 'Choose Both source card')
        if self.uses_remaining is not None: _integer(self.uses_remaining, 'Choose Both uses', 1)
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'Choose Both expiry', self.created_turn)
        declaration(self.kinds, self.origins)


@dataclass(frozen=True)
class AddChooseBothModifier(Effect):
    player_id: int
    source_id: int | None = None
    uses: int | None = None
    expires_turn: int | None = None
    kinds: tuple[CardType, ...] = (CardType.MINION, CardType.SPELL)
    origins: tuple[str, ...] = ('hand',)

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if self.uses is not None: _integer(self.uses, 'Choose Both uses', 1)
        if self.expires_turn is not None: _integer(self.expires_turn, 'Choose Both expiry', 1)
        declaration(self.kinds, self.origins)


@dataclass(frozen=True)
class RemoveChooseBothModifier(Effect):
    player_id: int
    modifier_id: int

    def __post_init__(self):
        _player(self.player_id); _integer(self.modifier_id, 'Choose Both modifier', 1)


def public_modifier(modifier, *, remaining=None, used=False):
    return dict(kinds=[k.value for k in modifier.kinds], origins=list(modifier.origins),
                uses_remaining=remaining if used else modifier.uses_remaining,
                expires_turn=modifier.expires_turn)


def emit(r, kind, modifier, remaining=None):
    r.emit(kind, player_id=modifier.player_id, **public_modifier(modifier,
        remaining=remaining, used=kind == 'choose_both_modifier_used'))


def add(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__(); validate_attachment_source(r, effect.source_id, effect.expires_turn)
    source = r.state.entities.get(effect.source_id)
    modifier = ChooseBothModifier(attachment_id(r.state), effect.player_id, effect.source_id,
        source.card_id if source is not None else None, r.state.turn, effect.uses,
        effect.expires_turn, effect.kinds, effect.origins)
    r.player(effect.player_id).choose_both_modifiers.append(modifier)
    emit(r, 'choose_both_modifier_added', modifier)


def remove(r, effect):
    player = r.player(effect.player_id)
    modifier = next((m for m in player.choose_both_modifiers if m.id == effect.modifier_id), None)
    if modifier is not None:
        player.choose_both_modifiers.remove(modifier)
        emit(r, 'choose_both_modifier_removed', modifier)


def matching(state, definition, player_id, origin):
    if origin not in ORIGINS: raise ValueError('Unknown Choose One root origin')
    if definition.choose_one is None: return ()
    return tuple(m for m in state.players[player_id].choose_both_modifiers
                 if definition.kind in m.kinds and origin in m.origins and
                 (m.expires_turn is None or state.turn <= m.expires_turn))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def board_json(state, player_id):
    return tuple(canonical(entity_to_dict(state.entities[i])) for i in state.players[player_id].board)


@dataclass(frozen=True)
class ChoosePolicyReceipt:
    id: int
    root_kind: str
    root_id: int
    origin: str
    profile_id: str | None
    card_id: str
    player_id: int
    source_id: int | None
    turn: int
    action: int
    next_entity_id: int
    next_attachment_id: int
    original_state_hash: str
    original_board_json: tuple[str, ...]
    board_source_ids: tuple[int, ...]
    original_modifiers: tuple[ChooseBothModifier, ...]
    modifier_ids: tuple[int, ...]
    branch_id: str
    closed_action: int | None = None
    interrupted: bool = False

    def __post_init__(self):
        for name in ('id', 'root_id', 'turn', 'next_entity_id', 'next_attachment_id'):
            _integer(getattr(self, name), 'Choose policy ' + name, 1)
        _integer(self.action, 'Choose policy action', 0); _player(self.player_id); _source(self.source_id)
        _name(self.card_id, 'Choose policy card'); _name(self.branch_id, 'Choose policy branch')
        expected = {'play': ('hand',), 'cast': ('cast_effect', 'cast_draw', 'cast_history'),
                    'power': ('power_manual', 'power_effect'), 'physical': ('physical',)}
        if self.root_kind not in expected or self.origin not in expected[self.root_kind]:
            raise ValueError('Choose policy root differs from its declared origin')
        if self.root_kind == 'physical':
            from .generated_combo_repeats import PROFILES
            if self.profile_id not in PROFILES or self.source_id is not None:
                raise ValueError('Physical Choose policy requires its actual profile and pre-install window')
        elif self.profile_id is not None or self.source_id is None:
            raise ValueError('Nonphysical Choose policy requires its own actual entity')
        if (type(self.original_state_hash) is not str or len(self.original_state_hash) != 64 or
                any(c not in '0123456789abcdef' for c in self.original_state_hash) or
                type(self.original_board_json) is not tuple or any(type(s) is not str for s in self.original_board_json) or
                type(self.original_modifiers) is not tuple or any(type(m) is not ChooseBothModifier for m in self.original_modifiers)):
            raise ValueError('Choose policy requires its complete compact original facts')
        for modifier in self.original_modifiers: modifier.__post_init__()
        ids = tuple(m.id for m in self.original_modifiers)
        if ids != tuple(sorted(set(ids))): raise ValueError('Choose policies require original acquisition order')
        for values in (self.board_source_ids, self.modifier_ids):
            if type(values) is not tuple or len(values) != len(set(values)):
                raise ValueError('Choose policy requires unique complete identities')
            for identity in values: _integer(identity, 'Choose policy accepted identity', 1)
        if not self.modifier_ids or any(i not in ids for i in self.modifier_ids):
            raise ValueError('Player Choose receipt requires actual qualifying policies')
        if type(self.interrupted) is not bool or self.interrupted and self.closed_action is not None:
            raise ValueError('Choose policy cannot close and interrupt together')
        if self.closed_action is not None: _integer(self.closed_action, 'Choose policy close', self.action)


@dataclass(frozen=True)
class ChoosePolicyProof:
    before_state: GameState
    receipt: ChoosePolicyReceipt

    def __post_init__(self):
        if type(self.before_state) is not GameState or type(self.receipt) is not ChoosePolicyReceipt:
            raise ValueError('Choose policy needs its full typed original window')
        self.receipt.__post_init__()
        if self.receipt.closed_action is not None or self.receipt.interrupted:
            raise ValueError('Original Choose policy proof cannot be already settled')


@dataclass(frozen=True)
class FinishChoosePolicy(Effect):
    proof: ChoosePolicyProof

    def __post_init__(self):
        if type(self.proof) is not ChoosePolicyProof: raise ValueError('Choose policy Finish needs its original proof')
        self.proof.__post_init__()


def capture(before, registry, card_id, player_id, root_kind, root_id, origin, branch_id,
            *, source_id=None, profile_id=None):
    card = registry.card(card_id)
    modifiers = matching(before, card, player_id, origin)
    if not modifiers: return None
    history = {'play': before.play_history, 'cast': before.cast_history, 'power': before.hero_power_history,
               'physical': before.whole_card_replay_ledger.children}.get(root_kind)
    if history is None or root_id != len(history) + 1:
        raise ValueError('Choose policy must capture the actual next root in its original window')
    if branch_id != card.choose_one.combined.id:
        raise ResolutionError('Player Choose Both policy requires its combined branch')
    from .choose_one import combined_sources
    receipt = ChoosePolicyReceipt(len(before.choose_policy_receipts) + 1, root_kind, root_id,
        origin, profile_id, card_id, player_id, source_id, before.turn, before.action_number,
        before.next_entity_id, before.next_attachment_id, canonical_hash(state_to_dict(before)),
        board_json(before, player_id), combined_sources(before, player_id),
        tuple(before.players[player_id].choose_both_modifiers), tuple(m.id for m in modifiers), branch_id)
    return ChoosePolicyProof(before, receipt)


def validate_proof(proof, registry):
    proof.__post_init__(); old = proof.receipt
    expected = capture(proof.before_state, registry, old.card_id, old.player_id, old.root_kind,
        old.root_id, old.origin, old.branch_id, source_id=old.source_id, profile_id=old.profile_id)
    if expected is None or expected.receipt != old:
        raise ValueError('Choose policy differs from its complete original acceptance window')


def accept(r, proof):
    if proof is None: return ()
    validate_proof(proof, r.registry); receipt = proof.receipt
    if receipt.id != len(r.state.choose_policy_receipts) + 1 or any(
            (x.root_kind, x.root_id) == (receipt.root_kind, receipt.root_id) for x in r.state.choose_policy_receipts):
        raise ResolutionError('Choose policy root can accept only once')
    player = r.player(receipt.player_id)
    originals = {m.id: m for m in receipt.original_modifiers if m.id in receipt.modifier_ids}
    current = {m.id: m for m in player.choose_both_modifiers}
    if any(current.get(i) != m for i, m in originals.items()):
        raise ResolutionError('Choose policy changed before original consumption')
    changes = []; updated = []
    for modifier in player.choose_both_modifiers:
        if modifier.id not in originals or modifier.uses_remaining is None:
            updated.append(modifier); continue
        remaining = modifier.uses_remaining - 1
        if remaining: updated.append(replace(modifier, uses_remaining=remaining))
        changes.append((modifier, remaining))
    player.choose_both_modifiers = updated
    r.state.choose_policy_receipts.append(receipt)
    for modifier, remaining in changes: emit(r, 'choose_both_modifier_used', modifier, remaining)
    return (FinishChoosePolicy(proof),)


def bind_root(state, registry, receipt, *, settled=False):
    if receipt.root_kind == 'physical':
        from .whole_card_physical import child_for
        child = child_for(state, receipt.root_id)
        root = state.whole_card_replay_ledger.roots[child.root_id - 1]
        progress = child.physical
        if (progress is None or progress.choose_one is None or
                progress.choose_one.policy_receipt_id != receipt.id or
                (progress.player_id, progress.card_id, progress.choose_one.branch_id,
                 progress.choose_one.profile_id) != (receipt.player_id, receipt.card_id, receipt.branch_id, receipt.profile_id)):
            raise ValueError('Choose policy borrowed another actual physical child')
        if root.player_id != receipt.player_id: raise ValueError('Choose policy changed physical owner')
        if settled and child.status.value in ('running', 'pending'):
            raise ValueError('Choose policy closed before its actual physical root')
        return
    collection = {'play': state.play_history, 'cast': state.cast_history, 'power': state.hero_power_history}[receipt.root_kind]
    if receipt.root_id > len(collection): raise ValueError('Choose policy lost its real root')
    record = collection[receipt.root_id - 1]
    origin = ('hand' if receipt.root_kind == 'play' else 'cast_' + record.origin
              if receipt.root_kind == 'cast' else 'power_' + record.origin)
    if ((record.source_id, record.player_id, record.card_id, record.branch_id, record.turn, record.action, origin) !=
            (receipt.source_id, receipt.player_id, receipt.card_id, receipt.branch_id, receipt.turn, receipt.action, receipt.origin)):
        raise ValueError('Choose policy borrowed another root, branch, player or window')
    if settled and not (record.completed or record.interrupted):
        raise ValueError('Choose policy closed before its actual root')


def validate_history(state, registry):
    from .repeat_provenance import checked_live_attachments, accepted_repeat_source_references
    from .allocation_facts import SourceAllocationFact, validate_allocation
    if type(state.choose_policy_receipts) is not list:
        raise ValueError('Choose policies require typed ordered history')
    if not state.choose_policy_receipts and not any(p.choose_both_modifiers for p in state.players.values()):
        if any(child.physical is not None and child.physical.choose_one is not None and
               child.physical.choose_one.policy_receipt_id is not None for child in state.whole_card_replay_ledger.children):
            raise ValueError('Actual generated branch lost its player policy history')
        return
    live = checked_live_attachments(state); roots = set(); previous = (0, 0); seen = {}
    other_historical_ids = {reference.identity for reference in accepted_repeat_source_references(state).values()}
    if any(m.id in other_historical_ids for p in state.players.values() for m in p.choose_both_modifiers):
        raise ValueError('Choose policy reused another historical attachment family')
    for index, receipt in enumerate(state.choose_policy_receipts, 1):
        if type(receipt) is not ChoosePolicyReceipt: raise ValueError('Invalid Choose policy history')
        receipt.__post_init__(); key = (receipt.root_kind, receipt.root_id)
        if (receipt.id != index or key in roots or not previous <= (receipt.turn, receipt.action) <= (state.turn, state.action_number) or
                receipt.closed_action is not None and receipt.closed_action > state.action_number or
                receipt.interrupted and state.status == 'playing' or
                receipt.next_entity_id > state.next_entity_id or receipt.next_attachment_id > state.next_attachment_id):
            raise ValueError('Invalid Choose policy history order or allocation window')
        bind_root(state, registry, receipt, settled=receipt.closed_action is not None)
        card = registry.card(receipt.card_id)
        if card.choose_one is None or receipt.branch_id != card.choose_one.combined.id:
            raise ValueError('Choose policy requires its declared combined branch')
        identities = set(); attachments = set(); board_sources = []
        for raw in receipt.original_board_json:
            entity = entity_from_dict(json.loads(raw))
            if (canonical(entity_to_dict(entity)) != raw or entity.id in identities or entity.id >= receipt.next_entity_id or
                    entity.controller != receipt.player_id or entity.zone != Zone.BOARD or entity.kind not in (CardType.MINION, CardType.LOCATION)):
                raise ValueError('Choose policy changed its original board facts')
            validate_allocation(state, registry, SourceAllocationFact.capture(state, entity))
            definition = registry.card(entity.card_id)
            for attachment in (*entity.abilities, *entity.enchantments):
                if attachment.id in attachments or attachment.id >= receipt.next_attachment_id:
                    raise ValueError('Choose policy fabricated original board attachments')
                attachments.add(attachment.id)
            for ability in active_abilities(entity, 'choose_both'):
                if ability.origin == 'printed' and not definition.choose_both:
                    raise ValueError('Choose policy fabricated a printed board source')
                board_sources.append(ability.id)
            identities.add(entity.id)
        expected = tuple(m.id for m in receipt.original_modifiers if card.kind in m.kinds and receipt.origin in m.origins and
                         (m.expires_turn is None or receipt.turn <= m.expires_turn))
        if expected != receipt.modifier_ids or tuple(board_sources) != receipt.board_source_ids:
            raise ValueError('Choose policy changed its complete original source set')
        for modifier in receipt.original_modifiers:
            if (modifier.player_id != receipt.player_id or modifier.created_turn > receipt.turn or
                    modifier.id >= receipt.next_attachment_id or modifier.id in attachments or modifier.id in other_historical_ids or
                    modifier.source_id is not None and (modifier.source_id not in state.entities or modifier.source_id >= receipt.next_entity_id)):
                raise ValueError('Choose policy changed its original player or source allocation')
            if modifier.source_card_id is not None: registry.card(modifier.source_card_id)
            current = live.get(modifier.id)
            if current is not None and (current[:2] != ('choose_both_modifiers', modifier.player_id) or
                    replace(current[2], uses_remaining=modifier.uses_remaining) != modifier):
                raise ValueError('Choose policy identity conflicts with a live attachment')
            if modifier.id in seen:
                old, remaining = seen[modifier.id]
                if replace(modifier, uses_remaining=old.uses_remaining) != old or modifier.uses_remaining != remaining:
                    raise ValueError('Choose policy rewrote or resurrected consumed uses')
            remaining = modifier.uses_remaining
            if modifier.id in receipt.modifier_ids and remaining is not None: remaining -= 1
            seen[modifier.id] = (modifier, remaining)
        roots.add(key); previous = (receipt.turn, receipt.action)
    for identity, (modifier, remaining) in seen.items():
        current = live.get(identity)
        if current is not None and current[2].uses_remaining != remaining:
            raise ValueError('Choose policy live uses differ from accepted consumption')
    for child in state.whole_card_replay_ledger.children:
        selection = None if child.physical is None else child.physical.choose_one
        if selection is not None and selection.policy_receipt_id is not None:
            if selection.policy_receipt_id > len(state.choose_policy_receipts):
                raise ValueError('Actual generated branch lost its player policy history')
            row = state.choose_policy_receipts[selection.policy_receipt_id - 1]
            if (row.root_kind, row.root_id) != ('physical', child.id):
                raise ValueError('Actual generated branch borrowed a sibling policy')


def validate_prefix(before, state):
    if len(before.choose_policy_receipts) > len(state.choose_policy_receipts):
        raise ValueError('Original Choose policy history was truncated')
    for old, new in zip(before.choose_policy_receipts, state.choose_policy_receipts):
        if replace(new, closed_action=old.closed_action, interrupted=old.interrupted) != old or (
                old.closed_action is not None and new.closed_action != old.closed_action or old.interrupted and not new.interrupted or
                old.closed_action is None and new.closed_action is not None and new.closed_action < before.action_number):
            raise ValueError('Original Choose policy acceptance was rewritten')


def related_work(state, receipt, work):
    """Only concrete work identities, never a callback predicate or live query."""
    context = getattr(work, 'context', None)
    if context is not None:
        record = getattr(context, {'play': 'play', 'cast': 'cast', 'power': 'power', 'physical': 'physical'}[receipt.root_kind], None)
        identity = None if record is None else getattr(record, 'child_id' if receipt.root_kind == 'physical' else 'id', None)
        if identity == receipt.root_id: return True
        if receipt.root_kind == 'play' and context.cast is not None and context.cast.play_id == receipt.root_id: return True
        event = context.event
        if event is not None and receipt.source_id is not None and event.source_id == receipt.source_id:
            key = {'play': 'play_id', 'cast': 'cast_id', 'power': 'power_id'}.get(receipt.root_kind)
            if key is not None and dict(event.data).get(key) == receipt.root_id: return True
    if receipt.root_kind == 'play':
        if getattr(work, 'play_id', None) == receipt.root_id: return True
        window_id = getattr(work, 'window_id', None)
        if window_id is not None:
            return any(window.id == window_id and window.play_id == receipt.root_id for window in state.action_windows)
    elif receipt.root_kind == 'cast':
        return getattr(work, 'cast_id', None) == receipt.root_id
    elif receipt.root_kind == 'power':
        from .hero_powers import FinishHeroPower
        return type(work) is FinishHeroPower and work.record_id == receipt.root_id
    else:
        return getattr(work, 'child_id', None) == receipt.root_id
    return False


def validate_queue(state, registry, queue, *, closing=None):
    tails = [(index, work) for index, work in enumerate(queue) if type(work) is FinishChoosePolicy]
    if closing is not None: tails.append((-1, closing))
    owed = [row for row in state.choose_policy_receipts if row.closed_action is None and not row.interrupted]
    if sorted(work.proof.receipt.id for _, work in tails) != [row.id for row in owed]:
        raise ValueError('Choose policy queue lost or duplicated an original completion proof')
    positions = {work.proof.receipt.id: index for index, work in tails}
    for tail_index, work in tails:
        validate_proof(work.proof, registry); old = work.proof.receipt
        if state.choose_policy_receipts[old.id - 1] != old:
            raise ValueError('Choose policy completion changed its accepted receipt')
        validate_prefix(work.proof.before_state, state)
        bind_root(state, registry, old)
        if any(index > tail_index and type(other) is not FinishChoosePolicy and related_work(state, old, other)
               for index, other in enumerate(queue)):
            raise ValueError('Choose policy completion precedes its original root work')
        for parent in work.proof.before_state.choose_policy_receipts:
            if parent.closed_action is None and not parent.interrupted and parent.id in positions and positions[parent.id] <= tail_index:
                raise ValueError('Nested Choose policies must finish in actual inner-first order')
    return tuple(row.id for row in owed)


def finish(r, effect):
    validate_queue(r.state, r.registry, r._work_queue, closing=effect)
    receipt = effect.proof.receipt
    bind_root(r.state, r.registry, receipt, settled=True)
    r.state.choose_policy_receipts[receipt.id - 1] = replace(receipt, closed_action=r.state.action_number)


def boundary(game):
    frame = game._frame
    queue = () if frame is None else (*frame.prefix, *frame.continuation)
    if frame is not None: reject_choice_control(frame.options)
    validate_queue(game._state, game.registry, queue)


def interrupt(r, queue):
    validate_queue(r.state, r.registry, queue)
    r.state.choose_policy_receipts = [replace(row, interrupted=True)
        if row.closed_action is None and not row.interrupted else row for row in r.state.choose_policy_receipts]


def expire(r, turn):
    changes = []
    for player in r.state.players.values():
        keep = []
        for modifier in player.choose_both_modifiers:
            if modifier.expires_turn is not None and modifier.expires_turn <= turn: changes.append(modifier)
            else: keep.append(modifier)
        player.choose_both_modifiers = keep
    # All expirations precede reactions, matching the existing global clock.
    for modifier in changes: emit(r, 'choose_both_modifier_expired', modifier)
    return bool(changes)


def reject_choice_control(options):
    from .effects import RequestChoice
    for option in options:
        for effect in option.effects:
            if type(effect) is FinishChoosePolicy:
                raise ValueError('Choice options cannot own Choose policy completion control')
            if type(effect) is RequestChoice: reject_choice_control(effect.options)


def modifier_from_dict(value):
    from .serialization import _row, _list
    row = _row(value, ChooseBothModifier)
    row['kinds'] = tuple(CardType(k) for k in _list(row['kinds'], 'Choose policy kinds'))
    row['origins'] = tuple(_list(row['origins'], 'Choose policy origins'))
    return ChooseBothModifier(**row)


def receipt_from_dict(value):
    from .serialization import _row, _list
    row = _row(value, ChoosePolicyReceipt)
    row['original_modifiers'] = tuple(modifier_from_dict(v) for v in _list(row['original_modifiers'], 'original Choose policies'))
    for name in ('original_board_json', 'board_source_ids', 'modifier_ids'):
        row[name] = tuple(_list(row[name], name))
    return ChoosePolicyReceipt(**row)


def register(mechanics):
    for effect, handler in ((AddChooseBothModifier, add), (RemoveChooseBothModifier, remove), (FinishChoosePolicy, finish)):
        mechanics.register(effect, handler)
    for kind in (ChooseBothModifier, ChoosePolicyReceipt, ChoosePolicyProof): mechanics.register_payload_type(kind)
