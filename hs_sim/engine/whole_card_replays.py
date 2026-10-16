"""Whole-card interpreter: automatic spell and installed physical bodies.

The explicit generated_after_install_v1 profile handles physical occurrences;
the default route remains spell-only. Per-source repeats, retained outcomes,
and safe natural end-turn requests remain required integration work. Original
proofs validate consistency, not authenticity of an unsigned imported save.
"""
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace

from .effects import Effect
from .errors import ResolutionError
from .model import CardType, GameState, SpellCastRecord
from .automatic_targets import AutomaticTargetPreference, AutomaticTargetProof, validate_cast_proof
from .whole_card_history import (HistorySelectionPolicy, WholeCardHistoryQuery,
    capture_history_frontier, integer, select_history_occurrences)
from .whole_card_replay_ledger import (ReplayAncestorPolicy, ReplayChildStatus,
    WholeCardReplayRoot, accept_replay_root, begin_replay_child, bind_replay_spell,
    finish_replay_child, finish_replay_root, root_record, top_root)
from .whole_card_physical import (PROFILE, FinishReplayPhysical, PreparePhysicalBody,
    AdvancePhysicalBody, FinishPhysicalBody, validate_physical_queue, validate_physical_history)
from .generated_battlecry_repeats import PROFILE as BATTLECRY_REPEAT_PROFILE
from .generated_combo_repeats import PROFILE as FAMILY_REPEAT_PROFILE
from .generated_activation_receipts import RETAINED_PROFILE


@dataclass(frozen=True)
class ReplayWholeCards(Effect):
    player_id: int
    source_id: int
    query: WholeCardHistoryQuery
    selection: HistorySelectionPolicy = HistorySelectionPolicy()
    ancestors: ReplayAncestorPolicy = ReplayAncestorPolicy.EXCLUDE_ACTIVE_SUBMISSIONS
    choices: str = 'random'
    target_preference: AutomaticTargetPreference = AutomaticTargetPreference.ANY
    physical_profile: str | None = None
    body_target_profile_id: str | None = None
    body_target_id: int | None = None
    physical_branch_id: str | None = None
    physical_branch_policy: str = 'current'
    spell_branch_policy: str = 'current'

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Whole-card executor requires an explicit player seat')
        integer(self.source_id, 'actual whole-card caster')
        if (type(self.query) is not WholeCardHistoryQuery
                or type(self.selection) is not HistorySelectionPolicy
                or type(self.ancestors) is not ReplayAncestorPolicy
                or type(self.target_preference) is not AutomaticTargetPreference
                or self.choices not in ('player', 'random') or self.physical_profile not in (None, PROFILE, BATTLECRY_REPEAT_PROFILE, FAMILY_REPEAT_PROFILE, RETAINED_PROFILE)):
            raise ValueError('Whole-card request lost its typed policies')
        self.query.__post_init__(); self.selection.__post_init__()
        if type(self.spell_branch_policy) is not str or self.spell_branch_policy not in ('current', 'inherit'):
            raise ValueError('Unknown whole-card spell branch policy')
        from .effects import _behavior, _source
        if self.body_target_profile_id is not None:
            _behavior(self.body_target_profile_id)
            if self.physical_profile is None: raise ValueError('Generated body target profile requires physical whole-card execution')
        _source(self.body_target_id)
        if self.body_target_id is not None and self.body_target_profile_id is None:
            raise ValueError('Explicit generated body target requires its own origin profile')
        if type(self.physical_branch_policy) is not str or self.physical_branch_policy not in ('current', 'inherit'):
            raise ValueError('Unknown physical branch policy')
        if self.physical_branch_policy == 'inherit' and (self.physical_profile is None or self.physical_branch_id is not None):
            raise ValueError('Branch inheritance requires a physical profile and cannot override with another request')
        if self.physical_branch_id is not None:
            _behavior(self.physical_branch_id)
            if self.physical_profile is None:
                raise ValueError('Physical Choose One requires its own generated source profile')


@dataclass(frozen=True)
class ReplayAcceptanceProof:
    request: ReplayWholeCards
    before_state: GameState
    root: WholeCardReplayRoot

    def __post_init__(self):
        if (type(self.request) is not ReplayWholeCards or type(self.before_state) is not GameState
                or type(self.root) is not WholeCardReplayRoot):
            raise ValueError('Whole-card acceptance lost its complete original window')
        self.request.__post_init__(); self.root.__post_init__()


@dataclass(frozen=True)
class ReplaySpellProof:
    acceptance: ReplayAcceptanceProof
    child_id: int
    accepted_state: GameState
    cast: SpellCastRecord
    behavior_ids: tuple[str, ...]
    target_proof: AutomaticTargetProof

    def __post_init__(self):
        integer(self.child_id, 'actual replay child')
        if (type(self.acceptance) is not ReplayAcceptanceProof or type(self.accepted_state) is not GameState
                or type(self.cast) is not SpellCastRecord or type(self.behavior_ids) is not tuple
                or type(self.target_proof) is not AutomaticTargetProof
                or any(type(b) is not str or not b for b in self.behavior_ids)):
            raise ValueError('Whole-card spell proof lost its actual original invocation')
        self.acceptance.__post_init__(); self.cast.__post_init__()


@dataclass(frozen=True)
class AdvanceReplayRoot(Effect):
    proof: ReplayAcceptanceProof


@dataclass(frozen=True)
class BeginReplaySpell(Effect):
    proof: ReplayAcceptanceProof
    slot: int

    def __post_init__(self):
        integer(self.slot, 'accepted replay slot', 0)


@dataclass(frozen=True)
class FinishReplaySpell(Effect):
    proof: ReplaySpellProof


@dataclass(frozen=True)
class FinishReplayRoot(Effect):
    proof: ReplayAcceptanceProof


CONTROL = (AdvanceReplayRoot, BeginReplaySpell, FinishReplaySpell, FinishReplayPhysical, FinishReplayRoot)
PHYSICAL_CONTROL = (PreparePhysicalBody, AdvancePhysicalBody, FinishPhysicalBody)
DIAGNOSTIC_CONTROL = (AdvanceReplayRoot, FinishReplaySpell, FinishReplayPhysical, FinishReplayRoot, FinishPhysicalBody)


def validate_acceptance(proof, registry):
    proof.__post_init__()
    request, before, root = proof.request, proof.before_state, proof.root
    if (root.selection.frontier.query != request.query or root.selection.policy != request.selection
            or root.ancestor_policy != request.ancestors or root.player_id != request.player_id
            or root.caster.entity_id != request.source_id or root.spell_branch_policy != request.spell_branch_policy):
        raise ValueError('Replay root differs from its complete original request')
    accepted, root_id = accept_replay_root(before.whole_card_replay_ledger, before, registry,
        root.selection, request.player_id, request.source_id, request.ancestors,
        shared_rng_state=root.selection.rng_after, parent_child_id=root.parent_child_id,
        runtime_route='cards_v1' if request.physical_profile is not None else 'spells_v1',
        spell_branch_policy=request.spell_branch_policy)
    if root_id != root.id or accepted.roots[-1] != root:
        raise ValueError('Replay root differs from its original acceptance proof')


def same_root(current, accepted):
    return replace(current, cursor=0, active_child_id=None, status=accepted.status) == accepted


def current_root(state, registry, proof):
    validate_acceptance(proof, registry)
    root = root_record(state.whole_card_replay_ledger, proof.root.id)
    if not same_root(root, proof.root):
        raise ValueError('Replay progress changed an accepted request, source or occurrence batch')
    return root


def validate_spell_proof(proof, registry):
    from .lifecycle import active_abilities
    proof.__post_init__(); validate_acceptance(proof.acceptance, registry)
    validate_cast_proof(proof.target_proof, proof.cast, registry)
    if proof.target_proof.selection.partition.preference != proof.acceptance.request.target_preference:
        raise ValueError('Replay spell changed its original root target preference')
    state, cast = proof.accepted_state, proof.cast
    root = current_root(state, registry, proof.acceptance)
    child = state.whole_card_replay_ledger.children[proof.child_id - 1]
    entity = state.entities.get(cast.source_id)
    if (root.active_child_id != child.id or child.root_id != root.id
            or child.spell_cast_id != cast.id or child.status != ReplayChildStatus.RUNNING
            or cast.id > len(state.cast_history) or state.cast_history[cast.id - 1] != cast
            or cast.origin != 'effect' or cast.play_id is not None or cast.from_zone is not None
            or cast.caster_id != root.caster.entity_id or cast.player_id != root.player_id
            or cast.card_id != child.card_id or cast.choices != proof.acceptance.request.choices
            or cast.payload_started or cast.interrupted or entity is None
            or entity.card_id != cast.card_id or entity.origin_entity_id != cast.caster_id
            or entity.controller != cast.player_id
            or proof.behavior_ids != tuple(a.behavior_id for a in active_abilities(entity, 'on_play'))):
        raise ValueError('Replay spell proof differs from its actual allocated full body')
    for behavior in proof.behavior_ids: registry.behavior(behavior)
    from .history_branch_replays import validate_proof as validate_branch
    validate_branch(proof, registry)


def same_cast(current, accepted):
    return replace(current, payload_started=accepted.payload_started,
        completed=accepted.completed, interrupted=accepted.interrupted,
        native_spell_value=accepted.native_spell_value) == accepted


def accept(r, request):
    request.__post_init__()
    before = deepcopy(r.state)
    frontier = capture_history_frontier(before, r.registry, request.query)
    selection = select_history_occurrences(frontier, request.selection, r.game._rng)
    # Refuse unsupported selected types before allocating an execution root.
    # No occurrence is silently removed from the accepted pool or run as blank.
    if request.physical_profile is None and any(frontier.rows[i - 1].occurrence.face.kind != CardType.SPELL for i in selection.selected_ids):
        raise ResolutionError('Whole-card replay physical full-body routes are not installed')
    ledger = before.whole_card_replay_ledger
    parent_child = ledger.roots[ledger.stack[-1] - 1].active_child_id if ledger.stack else None
    ledger, root_id = accept_replay_root(ledger, before, r.registry, selection,
        request.player_id, request.source_id, request.ancestors,
        shared_rng_state=r.game._rng.getstate(), parent_child_id=parent_child,
        runtime_route='cards_v1' if request.physical_profile is not None else 'spells_v1',
        spell_branch_policy=request.spell_branch_policy)
    r.state.whole_card_replay_ledger = ledger
    proof = ReplayAcceptanceProof(request, before, ledger.roots[root_id - 1])
    return (AdvanceReplayRoot(proof), FinishReplayRoot(proof))


def advance(r, work):
    root = top_root(r.state.whole_card_replay_ledger, work.proof.root.id)
    if root.active_child_id is not None:
        raise ResolutionError('Whole-card advance cannot abandon its active body')
    if root.cursor == len(root.selection.selected_ids): return ()
    return (BeginReplaySpell(work.proof, root.cursor), AdvanceReplayRoot(work.proof))


def begin_spell(r, work):
    from .spell_casts import CastSpell, automatic
    from .lifecycle import active_abilities
    from .model import Zone
    root = top_root(r.state.whole_card_replay_ledger, work.proof.root.id)
    if work.slot != root.cursor:
        raise ResolutionError('Replay spell lost its exact original ordered slot')
    face = root.selection.frontier.rows[root.selection.selected_ids[work.slot] - 1].occurrence.face
    card = r.registry.card(face.card_id)
    choose_before = deepcopy(r.state) if card.kind != CardType.SPELL and card.choose_one is not None else None
    ledger, child_id = begin_replay_child(r.state.whole_card_replay_ledger, root.id)
    r.state.whole_card_replay_ledger = ledger
    child = ledger.children[child_id - 1]
    if child.status == ReplayChildStatus.FAILED: return ()
    if child.kind != CardType.SPELL:
        from .whole_card_physical import install
        if work.proof.request.physical_profile not in (PROFILE, BATTLECRY_REPEAT_PROFILE, FAMILY_REPEAT_PROFILE, RETAINED_PROFILE):
            raise ResolutionError('Whole-card replay requires its declared physical source profile')
        return install(r, work.proof, child, choose_before=choose_before)
    # Allocation returns the real carrier; never infer it from an entity cursor.
    entity = r.create_entity(root.player_id, child.card_id, Zone.GRAVEYARD)
    entity.origin_entity_id = root.caster.entity_id
    from .native_spell_values import inherit_play
    inherit_play(r,entity,work.proof.before_state,child.occurrence_id)
    from .choose_branch_state import history_selection
    entity.choose_branch = history_selection(work.proof.before_state, r.registry, child,
        work.proof.request.spell_branch_policy, origin='cast_effect')
    cast_request = CastSpell(root.player_id, child.card_id, root.caster.entity_id,
        choices=work.proof.request.choices, target_preference=work.proof.request.target_preference)
    target_proofs = []
    branch_rng_before = r.game._rng.getstate()
    result = automatic(r, cast_request, entity, None, target_proofs=target_proofs)
    if len(target_proofs) != 1:
        raise ResolutionError('Whole-card replay lost its original automatic target proof')
    # Inheritance belongs to this invocation, not a lasting physical grant.
    # The original target proof preserves the transient pre-CAST recipe.
    entity.choose_branch = None
    cast = r.state.cast_history[-1]
    if cast.source_id != entity.id:
        raise ResolutionError('Replay spell lost its actual allocated cast')
    from .history_branch_replays import capture as capture_branch
    receipt = capture_branch(root, child, cast, target_proofs[0], r.registry, branch_rng_before)
    r.state.whole_card_replay_ledger = bind_replay_spell(r.state.whole_card_replay_ledger, child_id, cast.id,
        branch_receipt=receipt)
    proof = ReplaySpellProof(work.proof, child_id, deepcopy(r.state), cast,
        tuple(a.behavior_id for a in active_abilities(entity, 'on_play')), target_proofs[0])
    return (*result, FinishReplaySpell(proof))


def finish_spell(r, work):
    proof = work.proof; validate_spell_proof(proof, r.registry)
    child = r.state.whole_card_replay_ledger.children[proof.child_id - 1]
    cast = r.state.cast_history[proof.cast.id - 1]
    accepted_child = proof.accepted_state.whole_card_replay_ledger.children[proof.child_id - 1]
    if (child.spell_cast_id != cast.id or child.spell_branch != accepted_child.spell_branch
            or not same_cast(cast, proof.cast) or not cast.completed or cast.interrupted):
        raise ResolutionError('Replay child cannot finish before its actual full spell body')
    r.state.whole_card_replay_ledger = finish_replay_child(
        r.state.whole_card_replay_ledger, child.id, failure=cast.failure)


def finish_root(r, work):
    r.state.whole_card_replay_ledger = finish_replay_root(r.state.whole_card_replay_ledger, work.proof.root.id)


def validate_control_work(r, work):
    if type(work) in PHYSICAL_CONTROL:
        from .whole_card_physical import validate_physical_control
        validate_physical_control(r.state, r.registry, work)
        return
    if type(work) not in CONTROL: return
    proof = work.proof.acceptance if type(work) is FinishReplaySpell else work.proof
    root = current_root(r.state, r.registry, proof)
    if not r.state.whole_card_replay_ledger.stack or r.state.whole_card_replay_ledger.stack[-1] != root.id:
        raise ResolutionError('Stale or cross-parent whole-card control work')
    if type(work) is FinishReplaySpell:
        validate_spell_proof(work.proof, r.registry)
        if root.active_child_id != work.proof.child_id:
            raise ResolutionError('Replay Finish refers to another active child')


def validate_queue(state, registry, queue):
    ledger = state.whole_card_replay_ledger
    controls = tuple(w for w in queue if type(w) in CONTROL)
    closers = tuple(w for w in controls if type(w) is FinishReplayRoot)
    if tuple(w.proof.root.id for w in closers) != tuple(reversed(ledger.stack)):
        raise ValueError('Whole-card replay runtime queue/Finish integration is not installed: missing original root tail')
    if any((w.proof.acceptance if type(w) is FinishReplaySpell else w.proof).root.id not in ledger.stack for w in controls):
        raise ValueError('Stale or unknown whole-card control work at a public boundary')
    for root_id in ledger.stack:
        root = ledger.roots[root_id - 1]
        closer = next(w for w in closers if w.proof.root.id == root_id)
        current_root(state, registry, closer.proof)
        own = tuple(w for w in controls if (w.proof.acceptance if type(w) is FinishReplaySpell else w.proof).root.id == root_id)
        physical = root.active_child_id is not None and ledger.children[root.active_child_id - 1].kind != CardType.SPELL
        expected_types = (((FinishReplayPhysical,) if physical else (FinishReplaySpell,)) if root.active_child_id is not None else ())
        expected_types += ((AdvanceReplayRoot,) if root.cursor < len(root.selection.selected_ids) else ())
        expected_types += (FinishReplayRoot,)
        if tuple(type(w) for w in own) != expected_types:
            raise ValueError('Whole-card replay lost or injected child, ordered advance or root Finish work')
        for w in own:
            p = w.proof.acceptance if type(w) is FinishReplaySpell else w.proof
            if p != closer.proof:
                raise ValueError('Whole-card controls changed their shared original acceptance')
        if root.active_child_id is not None:
            child = ledger.children[root.active_child_id - 1]; fin = own[0]
            descendants = ledger.stack[ledger.stack.index(root_id) + 1:]
            if any(queue.index(c) > queue.index(fin) for c in closers if c.proof.root.id in descendants):
                raise ValueError('Parent replay child completion precedes an active nested root')
            if physical:
                if fin.child_id != child.id or fin.proof != closer.proof:
                    raise ValueError('Physical child completion lost its original accepted root')
                validate_physical_queue(state, registry, fin, queue)
                continue
            validate_spell_proof(fin.proof, registry)
            cast = state.cast_history[fin.proof.cast.id - 1]
            if (child.id != fin.proof.child_id or child.spell_cast_id != cast.id or not same_cast(cast, fin.proof.cast)
                    or child.spell_branch != fin.proof.accepted_state.whole_card_replay_ledger.children[child.id - 1].spell_branch):
                raise ValueError('Replay Finish lost its actual unique original spell invocation')
            from .spell_casts import ResolveAutomaticSpell, FinishSpellCast
            payloads = tuple(w for w in queue if type(w) is ResolveAutomaticSpell and w.cast_id == cast.id)
            finishes = tuple(w for w in queue if type(w) is FinishSpellCast and w.cast_id == cast.id)
            if payloads != (() if cast.payload_started or cast.completed else (ResolveAutomaticSpell(cast.id, fin.proof.behavior_ids),)):
                raise ValueError('Replay spell continuation changed its complete accepted body')
            if finishes != (() if cast.completed else (FinishSpellCast(cast.id, fin.proof.target_proof),)):
                raise ValueError('Replay spell continuation lost its actual cast completion')
            if any(queue.index(w) > queue.index(fin) for w in (*payloads, *finishes)):
                raise ValueError('Replay child completion precedes its owed full spell body')


def reject_choice_control(options):
    def visit(value):
        if type(value) in (*CONTROL, *PHYSICAL_CONTROL):
            raise ValueError('Choice branches cannot inject whole-card control work')
        if type(value) is GameState: return
        if type(value) in (tuple, list):
            for item in value: visit(item)
        elif is_dataclass(value):
            for f in fields(value): visit(getattr(value, f.name))
    visit(options)


def validate_boundary(game):
    frame = game._frame
    queue = (*frame.prefix, *frame.continuation) if frame is not None else ()
    validate_queue(game._state, game.registry, queue)
    if frame is not None:
        reject_choice_control(frame.options)
        original = frame.paid_hand_choice_boundary
        validate_queue(original.state, game.registry, original.work)
        if game._state.whole_card_replay_ledger != original.state.whole_card_replay_ledger:
            raise ValueError('Whole-card progress differs from its original genuine choice boundary')
        select = lambda seq: tuple(w for w in seq if type(w) in CONTROL)
        if select(queue) != select(original.work):
            raise ValueError('Whole-card tails differ from their complete original owed work')


def register(mechanics):
    from .history_branch_replays import register as register_branches
    register_branches(mechanics)
    from .whole_card_physical import register as register_physical
    register_physical(mechanics)
    for kind, handler in ((ReplayWholeCards, accept), (AdvanceReplayRoot, advance),
            (BeginReplaySpell, begin_spell), (FinishReplaySpell, finish_spell), (FinishReplayRoot, finish_root)):
        mechanics.register(kind, handler)
    for kind in (ReplayAcceptanceProof, ReplaySpellProof): mechanics.register_payload_type(kind)
