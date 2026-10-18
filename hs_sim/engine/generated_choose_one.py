"""Generated physical Choose One: branch before installation, targets after.

The compact receipt owns its actual child and source profile, not a paid/cast
identity. Full pre-child state remains only in the pending preparation/Finish
proof. Unsigned compact receipts prove consistency, not external authenticity.
"""
from dataclasses import dataclass
import json
import random

from .choose_one import DISPATCH, branch, branches, combined_sources, effective
from .choose_policies import ChooseBothModifier, ChoosePolicyProof
from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import _behavior, _player
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import CardType, GameState, Zone
from .serialization import canonical_hash, entity_from_dict, entity_to_dict, state_to_dict
from .whole_card_history import integer, rng_state


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class GeneratedChooseOneReceipt:
    root_id: int
    child_id: int
    occurrence_id: int
    profile_id: str
    card_id: str
    player_id: int
    turn: int
    action: int
    owner_turn_id: int
    next_entity_id: int
    next_attachment_id: int
    original_state_hash: str
    original_board_json: tuple[str, ...]
    combined_source_ids: tuple[int, ...]
    original_player_modifiers: tuple[ChooseBothModifier, ...]
    policy_receipt_id: int | None
    options: tuple[str, ...]
    request_branch_id: str | None
    branch_id: str
    rng_before: tuple
    rng_after: tuple
    branch_policy: str = 'current'
    inherited_branch_id: str | None = None

    def __post_init__(self):
        from .generated_combo_repeats import PROFILES
        if type(self.branch_policy) is not str or self.branch_policy not in ('current', 'inherit', 'offered'):
            raise ValueError('Unknown generated branch inheritance policy')
        if ((self.branch_policy == 'inherit' and self.inherited_branch_id is None)
                or (self.branch_policy == 'current' and self.inherited_branch_id is not None)):
            raise ValueError('Generated inheritance lost or invented its original branch')
        if self.inherited_branch_id is not None: _behavior(self.inherited_branch_id)
        if self.branch_policy == 'inherit' and self.request_branch_id is not None:
            raise ValueError('Inherited generated branch cannot also prescribe a new branch')
        if self.profile_id not in PROFILES:
            raise ValueError('Generated Choose One requires an actual physical origin')
        _player(self.player_id); _behavior(self.card_id); _behavior(self.branch_id)
        if self.request_branch_id is not None: _behavior(self.request_branch_id)
        for name in ('root_id', 'child_id', 'occurrence_id', 'turn', 'owner_turn_id',
                'next_entity_id', 'next_attachment_id'):
            integer(getattr(self, name), 'generated branch ' + name)
        integer(self.action, 'generated branch action', 0)
        if (type(self.original_state_hash) is not str or len(self.original_state_hash) != 64 or
                any(c not in '0123456789abcdef' for c in self.original_state_hash) or
                type(self.original_board_json) is not tuple or
                any(type(s) is not str for s in self.original_board_json)):
            raise ValueError('Generated branch requires its compact original board and hash')
        if (type(self.combined_source_ids) is not tuple or len(set(self.combined_source_ids)) != len(self.combined_source_ids)):
            raise ValueError('Generated combined policy requires its complete ordered identities')
        for identity in self.combined_source_ids: integer(identity, 'accepted combined source')
        if (type(self.original_player_modifiers) is not tuple or
                any(type(m) is not ChooseBothModifier for m in self.original_player_modifiers)):
            raise ValueError('Generated branch requires complete original player policies')
        for modifier in self.original_player_modifiers: modifier.__post_init__()
        if self.policy_receipt_id is not None: integer(self.policy_receipt_id, 'generated player Choose policy')
        if (type(self.options) is not tuple or not self.options or len(set(self.options)) != len(self.options)):
            raise ValueError('Generated branch requires its complete ordered options')
        for option in self.options: _behavior(option)
        if self.branch_id not in self.options:
            raise ValueError('Generated branch is outside its accepted policy')
        rng_state(self.rng_before); rng_state(self.rng_after)
        probe = random.Random(); probe.setstate(self.rng_before)
        if self.request_branch_id is not None:
            expected = self.request_branch_id
        else:
            expected = self.options[0] if len(self.options) == 1 else probe.choice(self.options)
        if self.branch_id != expected or self.rng_after != probe.getstate():
            raise ValueError('Generated branch changed its original request or random draw')


@dataclass(frozen=True)
class GeneratedChooseOneProof:
    before_state: GameState
    receipt: GeneratedChooseOneReceipt
    policy_proof: ChoosePolicyProof | None = None

    def __post_init__(self):
        if type(self.before_state) is not GameState or type(self.receipt) is not GeneratedChooseOneReceipt:
            raise ValueError('Generated branch lost its full original pre-child proof')
        self.receipt.__post_init__()
        if self.policy_proof is not None:
            if type(self.policy_proof) is not ChoosePolicyProof:
                raise ValueError('Generated player policy needs its original typed proof')
            self.policy_proof.__post_init__()


def board_json(state, player_id):
    return tuple(canonical(entity_to_dict(state.entities[i])) for i in state.players[player_id].board)


def capture(r, acceptance, child, before):
    card = r.registry.card(child.card_id)
    requested = acceptance.request.physical_branch_id
    if card.choose_one is None:
        if requested is not None:
            raise ResolutionError('Physical branch request requires a Choose One child')
        return None
    if type(before) is not GameState:
        raise ResolutionError('Generated Choose One lost its original pre-installation window')
    from .choose_one import automatic_branch
    # Child allocation changes only the ledger; options use the earlier board.
    from types import SimpleNamespace
    probe = SimpleNamespace(state=before, game=r.game)
    rng_before = r.game._rng.getstate()
    from .choose_branch_state import history_selection
    selection = history_selection(acceptance.before_state, r.registry, child, acceptance.request.physical_branch_policy,
        source_selection=acceptance.root.selection)
    entity = SimpleNamespace(choose_branch=selection)
    selected = automatic_branch(probe, card, acceptance.request.player_id, requested, origin='physical', entity=entity)
    from .choose_policies import capture as capture_policy
    policy_proof = capture_policy(before, r.registry, card.id, acceptance.request.player_id,
        'physical', child.id, 'physical', selected, profile_id=acceptance.request.physical_profile)
    from .owner_turns import current_owner_turn
    receipt = GeneratedChooseOneReceipt(acceptance.root.id, child.id, child.occurrence_id,
        acceptance.request.physical_profile, child.card_id, acceptance.request.player_id,
        before.turn, before.action_number, current_owner_turn(before).id,
        before.next_entity_id, before.next_attachment_id, canonical_hash(state_to_dict(before)),
        board_json(before, acceptance.request.player_id), combined_sources(before, acceptance.request.player_id),
        tuple(before.players[acceptance.request.player_id].choose_both_modifiers),
        None if policy_proof is None else policy_proof.receipt.id,
        branches(before, card, acceptance.request.player_id, origin='physical', entity=entity), requested, selected,
        rng_before, r.game._rng.getstate(), acceptance.request.physical_branch_policy,
        None if selection is None else selection.branch_id)
    proof = GeneratedChooseOneProof(before, receipt, policy_proof)
    validate_proof(proof, acceptance, r.registry)
    return proof


def validate_receipt(state, registry, receipt, root, child):
    if type(receipt) is not GeneratedChooseOneReceipt:
        raise ValueError('Missing actual generated branch receipt')
    receipt.__post_init__()
    if ((receipt.root_id, receipt.child_id, receipt.occurrence_id, receipt.card_id, receipt.player_id) !=
            (root.id, child.id, child.occurrence_id, child.card_id, root.player_id) or
            child.kind != CardType.MINION or root.runtime_route != 'cards_v1' or
            not root.accepted_turn <= receipt.turn <= state.turn or
            not root.accepted_action <= receipt.action <= state.action_number or
            not root.owner_turn_id <= receipt.owner_turn_id <= len(state.owner_turn_history) or
            receipt.next_entity_id > state.next_entity_id or receipt.next_attachment_id > state.next_attachment_id):
        raise ValueError('Generated branch borrowed another child, player, origin or window')
    interval = state.owner_turn_history[receipt.owner_turn_id - 1]
    if (interval.turn != receipt.turn or receipt.action < interval.start_action or
            interval.closed_action is not None and receipt.action > interval.closed_action):
        raise ValueError('Generated branch lost its actual owner interval')
    card = registry.card(receipt.card_id)
    if card.choose_one is None: raise ValueError('Generated branch requires its original Choose One definition')
    branch(card, receipt.branch_id)
    originals = []; identities = set(); attachments = set()
    for raw in receipt.original_board_json:
        entity = entity_from_dict(json.loads(raw))
        if (canonical(entity_to_dict(entity)) != raw or entity.id in identities or
                entity.id >= receipt.next_entity_id or entity.controller != receipt.player_id or
                entity.zone != Zone.BOARD or entity.kind not in (CardType.MINION, CardType.LOCATION)):
            raise ValueError('Generated branch changed its canonical original board')
        definition = registry.card(entity.card_id)
        if definition.kind != entity.kind: raise ValueError('Generated branch board lost its original card kind')
        validate_allocation(state, registry, SourceAllocationFact.capture(state, entity))
        for item in (*entity.abilities, *entity.enchantments):
            item.__post_init__()
            if item.id in attachments or item.id >= receipt.next_attachment_id:
                raise ValueError('Generated branch reused or invented an original attachment')
            attachments.add(item.id)
        for ability in active_abilities(entity, 'choose_both'):
            if ability.origin == 'printed' and not definition.choose_both:
                raise ValueError('Generated branch fabricated a printed combined declaration')
        originals.append(entity); identities.add(entity.id)
    sources = tuple(a.id for entity in originals for a in active_abilities(entity, 'choose_both'))
    modifiers = tuple(m for m in receipt.original_player_modifiers if card.kind in m.kinds and
        'physical' in m.origins and (m.expires_turn is None or receipt.turn <= m.expires_turn))
    if any(m.player_id != receipt.player_id or m.created_turn > receipt.turn or m.id >= receipt.next_attachment_id
           for m in receipt.original_player_modifiers):
        raise ValueError('Generated branch changed its original player policy allocation')
    if bool(modifiers) != (receipt.policy_receipt_id is not None):
        raise ValueError('Generated branch lost or fabricated its player policy receipt')
    if receipt.policy_receipt_id is not None:
        if receipt.policy_receipt_id <= len(state.choose_policy_receipts):
            policy = state.choose_policy_receipts[receipt.policy_receipt_id - 1]
            if ((policy.root_kind, policy.root_id, policy.card_id, policy.player_id, policy.branch_id,
                    policy.profile_id, policy.original_board_json, policy.original_modifiers, policy.modifier_ids) !=
                    ('physical', child.id, receipt.card_id, receipt.player_id, receipt.branch_id, receipt.profile_id,
                     receipt.original_board_json, receipt.original_player_modifiers, tuple(m.id for m in modifiers))):
                raise ValueError('Generated branch borrowed another player policy acceptance')
        elif receipt.policy_receipt_id != len(state.choose_policy_receipts) + 1:
            raise ValueError('Generated branch policy cannot skip its next real acceptance')
    from .choose_branch_state import options as selection_options, history_selection
    selection = history_selection(state, registry, child, receipt.branch_policy, source_selection=root.selection)
    if receipt.inherited_branch_id != (None if selection is None else selection.branch_id):
        raise ValueError('Generated inheritance changed its original committed branch')
    options = selection_options(card, bool(sources or modifiers), 'physical', selection)
    if (sources, options) != (receipt.combined_source_ids, receipt.options):
        raise ValueError('Generated branch changed its complete original combination policy')


def validate_proof(proof, acceptance, registry):
    proof.__post_init__(); before = proof.before_state; receipt = proof.receipt
    from .whole_card_replays import current_root
    from .whole_card_replay_ledger import begin_replay_child, ReplayChildStatus
    root = current_root(before, registry, acceptance)
    if root.active_child_id is not None:
        raise ValueError('Generated branch must precede its actual child installation')
    ledger, identity = begin_replay_child(before.whole_card_replay_ledger, root.id)
    child = ledger.children[identity - 1]
    if child.status == ReplayChildStatus.FAILED:
        raise ValueError('Excluded child cannot fabricate a generated branch')
    validate_receipt(before, registry, receipt, root, child)
    from .owner_turns import current_owner_turn
    if ((receipt.profile_id, receipt.request_branch_id, receipt.branch_policy) !=
            (acceptance.request.physical_profile, acceptance.request.physical_branch_id, acceptance.request.physical_branch_policy) or
            (receipt.turn, receipt.action, receipt.owner_turn_id, receipt.next_entity_id, receipt.next_attachment_id) !=
                (before.turn, before.action_number, current_owner_turn(before).id, before.next_entity_id, before.next_attachment_id) or
            receipt.original_state_hash != canonical_hash(state_to_dict(before)) or
            receipt.original_board_json != board_json(before, receipt.player_id) or
            receipt.original_player_modifiers != tuple(before.players[receipt.player_id].choose_both_modifiers)):
        raise ValueError('Generated branch differs from its complete original pre-installation state')
    from .choose_branch_state import history_selection
    selection = history_selection(acceptance.before_state, registry, child, receipt.branch_policy,
        source_selection=acceptance.root.selection)
    if receipt.inherited_branch_id != (None if selection is None else selection.branch_id):
        raise ValueError('Generated branch differs from its original accepted historical root')
    from .choose_policies import capture as capture_policy, validate_proof as validate_policy_proof
    expected = capture_policy(before, registry, receipt.card_id, receipt.player_id, 'physical',
        child.id, 'physical', receipt.branch_id, profile_id=receipt.profile_id)
    if proof.policy_proof != expected:
        raise ValueError('Generated branch lost its complete original player policy proof')
    if expected is not None: validate_policy_proof(proof.policy_proof, registry)


def definition(registry, card, receipt):
    if card.choose_one is None:
        if receipt is not None: raise ValueError('Ordinary generated card cannot borrow a Choose One receipt')
        return card
    if type(receipt) is not GeneratedChooseOneReceipt or receipt.card_id != card.id:
        raise ValueError('Generated Choose One lost its own accepted branch')
    receipt.__post_init__()
    return effective(card, receipt.branch_id)


def dispatch(registry, context):
    from .whole_card_physical import PhysicalReplayProgress, child_for, segment_at
    progress = context.physical
    if (type(progress) is not PhysicalReplayProgress or progress.phase != 'running' or
            progress.source.entity_id != context.source_id or progress.player_id != context.player_id or
            progress.choose_one is None or context.battlecry is not None or context.combo is not None or
            progress.cursor < 1 or segment_at(progress, progress.cursor - 1) != ('on_play', DISPATCH) or
            child_for(context.state, progress.child_id).physical != progress):
        raise ResolutionError('Generated Choose One dispatch requires its actual accepted ordinary body')
    selected = branch(registry.card(progress.card_id), progress.choose_one.branch_id)
    return registry.behavior(selected.behavior_id)(context)


def receipt_from_dict(value):
    from .serialization import _row, _list, rng_from_json
    data = _row(value, GeneratedChooseOneReceipt)
    for name in ('original_board_json', 'combined_source_ids', 'options'):
        data[name] = tuple(_list(data[name], 'generated branch ' + name))
    from .choose_policies import modifier_from_dict
    data['original_player_modifiers'] = tuple(modifier_from_dict(m)
        for m in _list(data['original_player_modifiers'], 'generated original player policies'))
    for name in ('rng_before', 'rng_after'): data[name] = rng_from_json(data[name])
    return GeneratedChooseOneReceipt(**data)


def register(mechanics):
    mechanics.register_payload_type(GeneratedChooseOneReceipt)
    mechanics.register_payload_type(GeneratedChooseOneProof)
