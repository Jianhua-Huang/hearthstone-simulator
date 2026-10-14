"""U65 independent replay root/child ledger component, not a kernel installer.

All transitions return immutable new values. No GameState, paid-hand history,
events or RNG are modified. Finish calls are trusted component inputs; the
future interpreter must establish actual body completion and parent tails.
This codec proves structural consistency, never unsigned-origin authenticity.
"""
from dataclasses import asdict, dataclass, fields, replace
from enum import StrEnum
import json

from hs_sim.engine.model import CardType, Entity, GameState, Zone
from .whole_card_history import (
    HistorySelectionReceipt, integer, unique_ids, rng_state,
    selection_from_dict, validate_frontier_registry, verify_frontier_origin)


class ReplayRootStatus(StrEnum):
    RUNNING = 'running'
    FINISHED = 'finished'
    INTERRUPTED = 'interrupted'


class ReplayChildStatus(StrEnum):
    RUNNING = 'running'
    FINISHED = 'finished'
    FAILED = 'failed'
    INTERRUPTED = 'interrupted'


class ReplayAncestorPolicy(StrEnum):
    ALLOW = 'allow'
    EXCLUDE_ACTIVE_SUBMISSIONS = 'exclude_active_submissions'


@dataclass(frozen=True)
class ReplayCasterFact:
    entity_id: int
    card_id: str
    kind: CardType
    owner: int
    controller: int
    zone: Zone
    zone_epoch: int

    def __post_init__(self):
        integer(self.entity_id, 'replay caster identity')
        integer(self.zone_epoch, 'caster zone epoch', 0)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Caster requires its explicit accepted card face')
        if type(self.kind) is not CardType or type(self.zone) is not Zone:
            raise ValueError('Caster requires typed accepted kind/zone')
        for name in ('owner', 'controller'):
            if type(getattr(self, name)) is not int or getattr(self, name) not in (1, 2):
                raise ValueError('Caster owner/controller requires a player seat')


@dataclass(frozen=True)
class WholeCardReplayRoot:
    id: int
    player_id: int
    caster: ReplayCasterFact
    accepted_turn: int
    accepted_action: int
    owner_turn_id: int
    selection: HistorySelectionReceipt
    ancestor_policy: ReplayAncestorPolicy
    accepted_after_child_id: int
    parent_child_id: int | None = None
    cursor: int = 0
    active_child_id: int | None = None
    status: ReplayRootStatus = ReplayRootStatus.RUNNING
    runtime_route: str | None = None
    spell_branch_policy: str = 'current'

    def __post_init__(self):
        for name in ('id', 'accepted_turn', 'owner_turn_id'):
            integer(getattr(self, name), name)
        integer(self.accepted_action, 'accepted action', 0)
        integer(self.accepted_after_child_id, 'original child allocation frontier', 0)
        integer(self.cursor, 'replay cursor', 0)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Replay executor requires its own explicit player seat')
        if type(self.caster) is not ReplayCasterFact or type(self.selection) is not HistorySelectionReceipt:
            raise ValueError('Replay root lost its original caster or complete selection')
        self.caster.__post_init__()
        self.selection.__post_init__()
        if type(self.ancestor_policy) is not ReplayAncestorPolicy or type(self.status) is not ReplayRootStatus:
            raise ValueError('Replay root requires typed lifecycle and recursion policies')
        if self.runtime_route not in (None, 'spells_v1', 'cards_v1'):
            raise ValueError('Unknown whole-card runtime route')
        if type(self.spell_branch_policy) is not str or self.spell_branch_policy not in ('current', 'inherit'):
            raise ValueError('Unknown whole-card spell branch policy')
        for name in ('parent_child_id', 'active_child_id'):
            if getattr(self, name) is not None:
                integer(getattr(self, name), name)
        frontier = self.selection.frontier
        if ((frontier.captured_turn, frontier.captured_action) != (self.accepted_turn, self.accepted_action)
                or self.owner_turn_id > frontier.owner_turn_size or self.cursor > len(self.selection.selected_ids)):
            raise ValueError('Replay root differs from its exact original acceptance window')
        if self.status != ReplayRootStatus.RUNNING and self.active_child_id is not None:
            raise ValueError('Settled roots cannot retain active children')
        if self.status == ReplayRootStatus.FINISHED and self.cursor != len(self.selection.selected_ids):
            raise ValueError('Finished replay root lost accepted selected occurrences')


@dataclass(frozen=True)
class WholeCardReplayChild:
    id: int
    root_id: int
    slot: int
    occurrence_id: int
    card_id: str
    kind: CardType
    status: ReplayChildStatus = ReplayChildStatus.RUNNING
    failure: str | None = None
    spell_cast_id: int | None = None
    physical: object | None = None
    spell_branch: object | None = None

    def __post_init__(self):
        for name in ('id', 'root_id', 'occurrence_id'):
            integer(getattr(self, name), name)
        integer(self.slot, 'selected occurrence slot', 0)
        if self.spell_cast_id is not None:
            integer(self.spell_cast_id, 'actual whole-card spell invocation')
            if self.kind != CardType.SPELL or self.failure == 'ancestor_excluded':
                raise ValueError('Only an actually attempted spell child may bind a cast')
        if self.physical is not None:
            from .whole_card_physical import PhysicalReplayProgress
            if (type(self.physical) is not PhysicalReplayProgress or self.kind == CardType.SPELL
                    or self.spell_cast_id is not None or self.failure == 'ancestor_excluded'):
                raise ValueError('Physical replay child requires its concrete independent activation')
            self.physical.__post_init__()
            if (self.physical.child_id, self.physical.card_id, self.physical.kind) != (self.id, self.card_id, self.kind):
                raise ValueError('Physical activation borrowed another selected child')
        if self.spell_branch is not None:
            from .history_branch_replays import SpellReplayBranchReceipt
            if (type(self.spell_branch) is not SpellReplayBranchReceipt or self.kind != CardType.SPELL
                    or self.spell_cast_id is None or self.failure == 'ancestor_excluded'):
                raise ValueError('Only an actual spell child may carry its own branch selection')
            self.spell_branch.__post_init__()
            if (self.spell_branch.root_id, self.spell_branch.child_id, self.spell_branch.occurrence_id,
                    self.spell_branch.card_id, self.spell_branch.cast_id) != (self.root_id, self.id,
                    self.occurrence_id, self.card_id, self.spell_cast_id):
                raise ValueError('Spell branch selection borrowed another replay child')
        if (type(self.card_id) is not str or not self.card_id.strip() or type(self.kind) is not CardType
                or self.kind == CardType.HERO_POWER or type(self.status) is not ReplayChildStatus):
            raise ValueError('Replay child requires original hand-card face/type and typed status')
        if self.status == ReplayChildStatus.FAILED:
            if type(self.failure) is not str or not self.failure.strip():
                raise ValueError('Failed child requires an explicit outcome reason')
        elif self.failure is not None:
            raise ValueError('Only failed children may carry failure reasons')


@dataclass(frozen=True)
class WholeCardReplayLedger:
    roots: tuple[WholeCardReplayRoot, ...] = ()
    children: tuple[WholeCardReplayChild, ...] = ()
    stack: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.roots) is not tuple or type(self.children) is not tuple:
            raise ValueError('Replay ledgers require immutable complete histories')
        unique_ids(self.stack, 'active replay root stack')
        for index, root in enumerate(self.roots, 1):
            if type(root) is not WholeCardReplayRoot:
                raise ValueError('Replay roots require typed immutable entries')
            root.__post_init__()
            if root.id != index:
                raise ValueError('Replay roots require monotonic dense independent identities')
            if (root.accepted_after_child_id > len(self.children) or index > 1
                    and root.accepted_after_child_id < self.roots[index - 2].accepted_after_child_id):
                raise ValueError('Root child allocation frontiers must be known and monotonic')
        for index, child in enumerate(self.children, 1):
            if type(child) is not WholeCardReplayChild:
                raise ValueError('Replay children require typed immutable entries')
            child.__post_init__()
            if child.id != index or not 1 <= child.root_id <= len(self.roots):
                raise ValueError('Replay child identity or parent root is unknown')
            root = self.roots[child.root_id - 1]
            if (child.id <= root.accepted_after_child_id or child.slot >= len(root.selection.selected_ids)
                    or child.occurrence_id != root.selection.selected_ids[child.slot]):
                raise ValueError('Replay child differs from its exact accepted occurrence slot')
            face = root.selection.frontier.rows[child.occurrence_id - 1].occurrence.face
            if (child.card_id, child.kind) != (face.card_id, face.kind):
                raise ValueError('Replay child face differs from its frozen original submission')
        running = tuple(r.id for r in self.roots if r.status == ReplayRootStatus.RUNNING)
        if set(self.stack) != set(running) or any(i > len(self.roots) for i in self.stack):
            raise ValueError('Active stack differs from the complete running root histories')
        for root in self.roots:
            children = tuple(c for c in self.children if c.root_id == root.id)
            if tuple(c.slot for c in children) != tuple(range(len(children))):
                raise ValueError('Each accepted selected occurrence has one ordered independent child')
            settled = tuple(c for c in children if c.status in (ReplayChildStatus.FINISHED, ReplayChildStatus.FAILED))
            if root.cursor != len(settled) or any(c.slot >= root.cursor for c in settled):
                raise ValueError('Root cursor differs from its complete settled child prefix')
            active = tuple(c for c in children if c.status == ReplayChildStatus.RUNNING)
            if active:
                if (len(active) != 1 or active[0].id != root.active_child_id
                        or active[0].slot != root.cursor or root.status != ReplayRootStatus.RUNNING):
                    raise ValueError('Root active child differs from its unique current occurrence')
            elif root.active_child_id is not None:
                raise ValueError('Active replay child identity is absent from the ledger')
            interrupted = tuple(c for c in children if c.status == ReplayChildStatus.INTERRUPTED)
            if interrupted and (len(interrupted) != 1 or interrupted[0].slot != root.cursor
                                or root.status != ReplayRootStatus.INTERRUPTED):
                raise ValueError('Interrupted child requires its retained interrupted root frontier')
            if root.status == ReplayRootStatus.RUNNING and len(children) != root.cursor + int(bool(active)):
                raise ValueError('Running root lost or preallocated selected children')
            if root.parent_child_id is not None:
                if not 1 <= root.parent_child_id <= len(self.children):
                    raise ValueError('Nested replay root references an unknown parent child')
                if root.parent_child_id > root.accepted_after_child_id:
                    raise ValueError('Nested root cannot borrow a future parent invocation')
                parent = self.children[root.parent_child_id - 1]
                parent_root = self.roots[parent.root_id - 1]
                if (parent_root.id >= root.id or root.accepted_action < parent_root.accepted_action
                        or root.accepted_turn < parent_root.accepted_turn):
                    raise ValueError('Nested replay root lost its earlier real parent invocation')
                if root.status == ReplayRootStatus.RUNNING and parent.status != ReplayChildStatus.RUNNING:
                    raise ValueError('Running nested root requires its still-active parent child')
        for index, root_id in enumerate(self.stack):
            root = self.roots[root_id - 1]
            if index == 0:
                if root.parent_child_id is not None:
                    raise ValueError('Top-level replay root cannot borrow a parent invocation')
            else:
                previous = self.roots[self.stack[index - 1] - 1]
                if root.parent_child_id is None or previous.active_child_id is None or root.parent_child_id != previous.active_child_id:
                    raise ValueError('Replay stack lost the exact nested parent invocation order')


def checked(ledger):
    if type(ledger) is not WholeCardReplayLedger:
        raise ValueError('Expected a typed independent replay ledger')
    ledger.__post_init__()
    return ledger


def root_record(ledger, root_id):
    checked(ledger)
    integer(root_id, 'replay root reference')
    if not 1 <= root_id <= len(ledger.roots):
        raise ValueError('Unknown independent replay root')
    return ledger.roots[root_id - 1]


def top_root(ledger, root_id):
    root = root_record(ledger, root_id)
    if not ledger.stack or ledger.stack[-1] != root_id or root.status != ReplayRootStatus.RUNNING:
        raise ValueError('Replay work must belong to the current active root')
    return root


def with_root(ledger, root, *, children=None, stack=None):
    return WholeCardReplayLedger(ledger.roots[:root.id - 1] + (root,) + ledger.roots[root.id:],
        ledger.children if children is None else children, ledger.stack if stack is None else stack)


def accept_replay_root(ledger, state, registry, selection, player_id, caster_id,
                       ancestor_policy, *, shared_rng_state, parent_child_id=None, runtime_route=None,
                       spell_branch_policy='current'):
    checked(ledger)
    if type(state) is not GameState or type(selection) is not HistorySelectionReceipt:
        raise ValueError('Replay acceptance requires actual typed state and original selection')
    selection.__post_init__()
    rng_state(shared_rng_state)
    if shared_rng_state != selection.rng_after:
        raise ValueError('Replay root selection differs from the actual supplied post-selection RNG')
    verify_frontier_origin(selection.frontier, state, registry)
    if state.status != 'playing' or not state.owner_turn_history or state.owner_turn_history[-1].closed:
        raise ValueError('Replay acceptance requires its actual open owner interval')
    integer(caster_id, 'actual replay caster')
    source = state.entities.get(caster_id)
    if type(source) is not Entity:
        raise ValueError('Replay caster is absent from the original window')
    definition = registry.card(source.card_id)
    if definition.kind != source.kind:
        raise ValueError('Replay caster differs from its current pinned physical kind')
    if ledger.stack:
        parent = ledger.roots[ledger.stack[-1] - 1]
        if parent_child_id is None or parent_child_id != parent.active_child_id:
            raise ValueError('Nested replay requires the exact current parent child')
    elif parent_child_id is not None:
        raise ValueError('Top-level replay cannot invent a parent invocation')
    fact = ReplayCasterFact(source.id, source.card_id, source.kind, source.owner, source.controller,
                            source.zone, source.zone_epoch)
    root = WholeCardReplayRoot(len(ledger.roots) + 1, player_id, fact, state.turn, state.action_number,
        state.owner_turn_history[-1].id, selection, ancestor_policy, len(ledger.children),
        parent_child_id=parent_child_id, runtime_route=runtime_route, spell_branch_policy=spell_branch_policy)
    return WholeCardReplayLedger(ledger.roots + (root,), ledger.children, ledger.stack + (root.id,)), root.id


def begin_replay_child(ledger, root_id):
    root = top_root(ledger, root_id)
    if root.active_child_id is not None or root.cursor == len(root.selection.selected_ids):
        raise ValueError('Root has an active child or no accepted occurrences left')
    occurrence_id = root.selection.selected_ids[root.cursor]
    face = root.selection.frontier.rows[occurrence_id - 1].occurrence.face
    ancestors = tuple(ledger.children[ledger.roots[i - 1].active_child_id - 1].occurrence_id
        for i in ledger.stack[:-1] if ledger.roots[i - 1].active_child_id is not None)
    excluded = root.ancestor_policy == ReplayAncestorPolicy.EXCLUDE_ACTIVE_SUBMISSIONS and occurrence_id in ancestors
    child = WholeCardReplayChild(len(ledger.children) + 1, root.id, root.cursor, occurrence_id, face.card_id, face.kind,
        ReplayChildStatus.FAILED if excluded else ReplayChildStatus.RUNNING,
        'ancestor_excluded' if excluded else None)
    root = replace(root, cursor=root.cursor + int(excluded), active_child_id=None if excluded else child.id)
    return with_root(ledger, root, children=ledger.children + (child,)), child.id


def finish_replay_child(ledger, child_id, *, failure=None):
    checked(ledger)
    integer(child_id, 'replay child completion')
    if child_id > len(ledger.children):
        raise ValueError('Unknown replay child completion')
    child = ledger.children[child_id - 1]
    root = top_root(ledger, child.root_id)
    if child.status != ReplayChildStatus.RUNNING or root.active_child_id != child.id:
        raise ValueError('Replay child is already settled or not the accepted active invocation')
    status = ReplayChildStatus.FINISHED if failure is None else ReplayChildStatus.FAILED
    child = replace(child, status=status, failure=failure)
    children = ledger.children[:child.id - 1] + (child,) + ledger.children[child.id:]
    return with_root(ledger, replace(root, cursor=root.cursor + 1, active_child_id=None), children=children)


def bind_replay_spell(ledger, child_id, cast_id, *, branch_receipt=None):
    """Bind the interpreter's actual allocated cast, never a fabricated play."""
    checked(ledger)
    integer(child_id, 'replay child binding')
    integer(cast_id, 'actual replay spell cast')
    if child_id > len(ledger.children):
        raise ValueError('Unknown replay child binding')
    child = ledger.children[child_id - 1]
    root = top_root(ledger, child.root_id)
    if (child.status != ReplayChildStatus.RUNNING or root.active_child_id != child.id
            or child.kind != CardType.SPELL or child.spell_cast_id is not None
            or any(c.spell_cast_id == cast_id for c in ledger.children)):
        raise ValueError('Replay spell binding lost its unique active actual invocation')
    child = replace(child, spell_cast_id=cast_id, spell_branch=branch_receipt)
    children = ledger.children[:child.id - 1] + (child,) + ledger.children[child.id:]
    return with_root(ledger, root, children=children)


def finish_replay_root(ledger, root_id):
    root = top_root(ledger, root_id)
    if root.active_child_id is not None or root.cursor != len(root.selection.selected_ids):
        raise ValueError('Root completion lost an active or unattempted accepted occurrence')
    return with_root(ledger, replace(root, status=ReplayRootStatus.FINISHED), stack=ledger.stack[:-1])


def interrupt_replay_ledger(ledger, terminal_state):
    """Terminal marker is necessary; original queue/parent proof integration remains."""
    checked(ledger)
    if (type(terminal_state) is not GameState or terminal_state.status not in ('finished', 'draw')
            or any(root.accepted_action > terminal_state.action_number
                   or root.accepted_turn > terminal_state.turn for root in ledger.roots)):
        raise ValueError('Replay interruption requires a supplied actual terminal state and later clock')
    roots = tuple(replace(r, status=ReplayRootStatus.INTERRUPTED, active_child_id=None)
                  if r.status == ReplayRootStatus.RUNNING else r for r in ledger.roots)
    children = tuple(replace(c, status=ReplayChildStatus.INTERRUPTED)
                     if c.status == ReplayChildStatus.RUNNING else c for c in ledger.children)
    return WholeCardReplayLedger(roots, children, ())


def ledger_to_dict(ledger):
    checked(ledger)
    return json.loads(json.dumps(asdict(ledger)))


def row(value, cls):
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise ValueError(f'Invalid {cls.__name__} fields')
    return dict(value)


def array(value):
    if type(value) is not list:
        raise ValueError('Replay ledger codec requires an array')
    return value


def ledger_from_dict(value):
    data = row(value, WholeCardReplayLedger)
    roots = []
    for value in array(data['roots']):
        root = row(value, WholeCardReplayRoot)
        caster = row(root['caster'], ReplayCasterFact)
        caster['kind'] = CardType(caster['kind'])
        caster['zone'] = Zone(caster['zone'])
        root['caster'] = ReplayCasterFact(**caster)
        root['selection'] = selection_from_dict(root['selection'])
        root['ancestor_policy'] = ReplayAncestorPolicy(root['ancestor_policy'])
        root['status'] = ReplayRootStatus(root['status'])
        roots.append(WholeCardReplayRoot(**root))
    children = []
    for value in array(data['children']):
        child = row(value, WholeCardReplayChild)
        child['kind'] = CardType(child['kind'])
        child['status'] = ReplayChildStatus(child['status'])
        if child['physical'] is not None:
            from .whole_card_physical import progress_from_dict
            child['physical'] = progress_from_dict(child['physical'])
        if child['spell_branch'] is not None:
            from .history_branch_replays import receipt_from_dict
            child['spell_branch'] = receipt_from_dict(child['spell_branch'])
        children.append(WholeCardReplayChild(**child))
    return WholeCardReplayLedger(tuple(roots), tuple(children), tuple(array(data['stack'])))


def validate_ledger_registry(ledger, registry):
    checked(ledger)
    for root in ledger.roots:
        validate_frontier_registry(root.selection.frontier, registry)
        if registry.card(root.caster.card_id).kind != root.caster.kind:
            raise ValueError('Recorded replay caster differs from its pinned physical kind')
