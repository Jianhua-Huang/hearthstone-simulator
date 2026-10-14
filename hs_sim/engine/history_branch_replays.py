"""Each whole-card spell selects at its own CAST window from its original Play.

Compact receipts preserve branch provenance and RNG. Pending target proofs own
the full original state for pool recomputation; closed receipts are consistency
evidence, not authentication of an unsigned imported history.
"""
from dataclasses import dataclass, fields
from random import Random

from .effects import _behavior, _player
from .whole_card_history import integer, rng_state


@dataclass(frozen=True)
class SpellReplayBranchReceipt:
    root_id: int
    child_id: int
    occurrence_id: int
    cast_id: int
    card_id: str
    player_id: int
    policy: str
    inherited_branch_id: str | None
    options: tuple[str, ...]
    branch_id: str
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        for name in ('root_id', 'child_id', 'occurrence_id', 'cast_id'):
            integer(getattr(self, name), 'spell branch ' + name)
        _behavior(self.card_id); _player(self.player_id); _behavior(self.branch_id)
        if type(self.policy) is not str or self.policy not in ('current', 'inherit'):
            raise ValueError('Unknown replay spell branch policy')
        if (self.policy == 'inherit') != (self.inherited_branch_id is not None):
            raise ValueError('Spell replay erased or invented its inherited branch')
        if self.inherited_branch_id is not None: _behavior(self.inherited_branch_id)
        if (type(self.options) is not tuple or not self.options or len(set(self.options)) != len(self.options)):
            raise ValueError('Spell replay requires the complete ordered branch options')
        for option in self.options: _behavior(option)
        rng_state(self.rng_before); rng_state(self.rng_after)
        probe = Random(); probe.setstate(self.rng_before)
        selected = self.options[0] if len(self.options) == 1 else probe.choice(self.options)
        if (self.branch_id, self.rng_after) != (selected, probe.getstate()):
            raise ValueError('Spell replay branch changed its original random selection')


def capture(root, child, cast, target_proof, registry, rng_before):
    card = registry.card(child.card_id)
    if card.choose_one is None: return None
    from .choose_one import branches
    entity = target_proof.before_state.entities[cast.source_id]
    inherited = None if root.spell_branch_policy == 'current' else entity.choose_branch.branch_id
    return SpellReplayBranchReceipt(root.id, child.id, child.occurrence_id, cast.id, child.card_id,
        root.player_id, root.spell_branch_policy, inherited,
        branches(target_proof.before_state, card, root.player_id, origin='cast_effect', entity=entity),
        cast.branch_id, rng_before, target_proof.selection.rng_before)


def validate_receipt(state, registry, root, child, cast):
    card = registry.card(child.card_id)
    receipt = child.spell_branch
    if card.choose_one is None:
        if receipt is not None: raise ValueError('Unbranched spell fabricated a branch receipt')
        return
    if type(receipt) is not SpellReplayBranchReceipt:
        raise ValueError('Replay spell lost its actual branch receipt')
    receipt.__post_init__()
    from .choose_one import branch
    for selected in (*receipt.options, receipt.branch_id): branch(card, selected)
    from .choose_branch_state import history_selection
    selection = history_selection(state, registry, child, root.spell_branch_policy, origin='cast_effect')
    ordinary = tuple(b.id for b in card.choose_one.branches)
    permitted = (ordinary, (card.choose_one.combined.id,)) if selection is None else (
        (selection.branch_id,), (card.choose_one.combined.id,))
    if receipt.options not in permitted:
        raise ValueError('Replay spell invented a branch option or changed declared order')
    if (receipt.root_id, receipt.child_id, receipt.occurrence_id, receipt.cast_id, receipt.card_id,
            receipt.player_id, receipt.policy, receipt.branch_id, receipt.inherited_branch_id) != (
            root.id, child.id, child.occurrence_id, cast.id, cast.card_id, cast.player_id,
            root.spell_branch_policy, cast.branch_id, None if selection is None else selection.branch_id):
        raise ValueError('Replay spell branch lost its own original occurrence or request')
    if cast.target_selection is None or cast.target_selection.rng_before != receipt.rng_after:
        raise ValueError('Replay spell target must follow its own branch selection RNG')


def validate_proof(proof, registry):
    state = proof.accepted_state
    child = state.whole_card_replay_ledger.children[proof.child_id - 1]
    root = state.whole_card_replay_ledger.roots[child.root_id - 1]
    cast = proof.cast
    validate_receipt(state, registry, root, child, cast)
    from .choose_branch_state import history_selection
    expected = history_selection(proof.acceptance.before_state, registry, child,
        proof.acceptance.request.spell_branch_policy, origin='cast_effect')
    before = proof.target_proof.before_state
    from .whole_card_replays import current_root
    original_root = current_root(before, registry, proof.acceptance)
    original_child = before.whole_card_replay_ledger.children[child.id - 1]
    from dataclasses import replace
    if (original_root.active_child_id != child.id or
            original_child != replace(child, spell_cast_id=None, spell_branch=None)):
        raise ValueError('Spell branch lost its actual pre-cast child allocation window')
    carrier = before.entities[cast.source_id]
    if carrier.choose_branch != expected or state.entities[cast.source_id].choose_branch is not None:
        raise ValueError('Replay spell borrowed or erased a historical branch recipe')
    if child.spell_branch is not None:
        actual = capture(root, child, cast, proof.target_proof, registry, child.spell_branch.rng_before)
        if child.spell_branch != actual:
            raise ValueError('Replay spell branch options differ from its complete original CAST window')


def receipt_from_dict(value):
    if type(value) is not dict or set(value) != {f.name for f in fields(SpellReplayBranchReceipt)}:
        raise ValueError('Spell replay branch receipt fields do not match')
    row = dict(value)
    if type(row['options']) is not list: raise ValueError('Spell branch options require an array')
    row['options'] = tuple(row['options'])
    from .serialization import rng_from_json
    row['rng_before'] = rng_from_json(row['rng_before']); row['rng_after'] = rng_from_json(row['rng_after'])
    return SpellReplayBranchReceipt(**row)


def register(mechanics):
    mechanics.register_payload_type(SpellReplayBranchReceipt)
