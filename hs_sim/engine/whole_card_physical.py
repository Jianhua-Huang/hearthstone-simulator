"""Generated whole physical bodies with their own activation provenance.

The explicit generated_after_install_v1 profile accepts current payloads after
the common installation/entry work and its reactions finish. It executes one
whole primary body; summon-quantity extra deliveries use the common summon
contract. It creates no hand submission, payment, counter window or PlayRecord.
All supported physical profiles bind actual Battlecry/Combo identities; only
their explicitly selected families accept repetition policies. Exact CN timing
and other producers remain separate requirements.
"""
from copy import deepcopy
from dataclasses import dataclass, fields, replace
import json
from types import SimpleNamespace

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .automatic_targets import (AutomaticTargetSelection, automatic_target_partition,
    select_automatic_target, selection_from_dict)
from .effects import Effect
from .errors import ResolutionError
from .generated_activation_receipts import GeneratedActivationReceipt
from .generated_battlecry_repeats import GeneratedBattlecryAcceptance
from .generated_retained_acceptance import GeneratedRetainedAcceptance
from .generated_body_targets import GeneratedBodyTargetAcceptance
from .generated_choose_one import GeneratedChooseOneReceipt, GeneratedChooseOneProof
from .generated_activation_receipts import RETAINED_PROFILE
from .lifecycle import active_abilities
from .model import BattlecryPayload, CardDefinition, CardType, ComboPayload, ComboAcceptanceReceipt, GameState, Zone
from .rules import Ruleset
from .whole_card_history import integer
from .whole_card_replay_ledger import ReplayChildStatus, top_root, with_root


PROFILE = 'generated_after_install_v1'
KINDS = (CardType.MINION, CardType.WEAPON, CardType.LOCATION, CardType.HERO)


@dataclass(frozen=True)
class PhysicalReplayProgress:
    child_id: int
    player_id: int
    card_id: str
    kind: CardType
    source: SourceAllocationFact | None = None
    summon_root_id: int | None = None
    phase: str = 'installing'
    failure: str | None = None
    selection: AutomaticTargetSelection | None = None
    on_play: tuple[str, ...] = ()
    battlecries: tuple[BattlecryPayload, ...] = ()
    combos: tuple[ComboPayload, ...] = ()
    combo: bool = False
    outcast: bool = False
    finale: bool = False
    quickdraw: bool = False
    manathirst: bool = False
    cursor: int = 0
    active_battlecry_id: int | None = None
    battlecry_ids: tuple[int, ...] = ()
    activation: GeneratedActivationReceipt | None = None
    battlecry_repeat_acceptance: GeneratedBattlecryAcceptance | None = None
    combo_repeat_acceptance: ComboAcceptanceReceipt | None = None
    active_combo_id: int | None = None
    combo_ids: tuple[int, ...] = ()
    retained_acceptance: GeneratedRetainedAcceptance | None = None
    outcome_id: int | None = None
    body_targets: GeneratedBodyTargetAcceptance | None = None
    choose_one: GeneratedChooseOneReceipt | None = None

    def __post_init__(self):
        integer(self.child_id, 'actual physical replay child')
        integer(self.cursor, 'physical body cursor', 0)
        if (type(self.player_id) is not int or self.player_id not in (1, 2)
                or type(self.card_id) is not str or not self.card_id
                or type(self.kind) is not CardType or self.kind not in KINDS
                or self.phase not in ('installing', 'running', 'completed')):
            raise ValueError('Physical body lost its typed primary activation')
        for name in ('combo', 'outcast', 'finale', 'quickdraw', 'manathirst'):
            if type(getattr(self, name)) is not bool: raise ValueError('Physical conditions require booleans')
        if self.outcast or self.finale or self.quickdraw:
            raise ValueError('Generated physical activation has no paid-hand conditions')
        if self.source is not None:
            if type(self.source) is not SourceAllocationFact: raise ValueError('Physical source lost its allocation')
            self.source.__post_init__()
            if (self.source.card_id, self.source.kind, self.source.controller) != (self.card_id, self.kind, self.player_id):
                raise ValueError('Physical primary source differs from its original installed face')
        for name in ('summon_root_id', 'active_battlecry_id', 'active_combo_id', 'outcome_id'):
            if getattr(self, name) is not None: integer(getattr(self, name), name)
        if self.summon_root_id is not None and self.kind != CardType.MINION:
            raise ValueError('Only a minion installation binds a common summon root')
        if (type(self.on_play) is not tuple or any(type(b) is not str or not b for b in self.on_play)
                or type(self.battlecries) is not tuple or any(type(b) is not BattlecryPayload for b in self.battlecries)
                or type(self.combos) is not tuple or any(type(b) is not ComboPayload for b in self.combos)
                or type(self.battlecry_ids) is not tuple or len(set(self.battlecry_ids)) != len(self.battlecry_ids)
                or type(self.combo_ids) is not tuple or len(set(self.combo_ids)) != len(self.combo_ids)):
            raise ValueError('Physical body lost its complete immutable ordered payloads')
        for b in (*self.battlecries, *self.combos): b.__post_init__()
        for value in self.battlecry_ids: integer(value, 'actual physical Battlecry')
        for value in self.combo_ids: integer(value, 'actual physical Combo')
        if self.selection is not None:
            if type(self.selection) is not AutomaticTargetSelection: raise ValueError('Physical target lost its typed receipt')
            self.selection.__post_init__()
            if self.source is None or self.selection.partition.source_id != self.source.entity_id:
                raise ValueError('Physical target source differs from its actual installation')
        if self.failure is not None and self.failure not in ('board_full', 'stale_installation', 'no_target'):
            raise ValueError('Unknown explicit physical activation failure')
        if self.phase == 'running' and (self.source is None or self.selection is None or self.failure is not None):
            raise ValueError('Running physical body requires its real source and target acceptance')
        if self.cursor > segment_count(self) or self.phase == 'completed' and self.failure is None and self.cursor != segment_count(self):
            raise ValueError('Physical completion cannot abandon an accepted payload')
        if self.phase != 'running' and (self.active_battlecry_id is not None or self.active_combo_id is not None):
            raise ValueError('Settled physical body cannot owe a Battlecry completion')
        if self.activation is not None:
            if type(self.activation) is not GeneratedActivationReceipt:
                raise ValueError('Physical body lost its typed generated activation')
            self.activation.__post_init__()
            if (self.source != self.activation.source or self.child_id != self.activation.child_id
                    or self.player_id != self.activation.player_id or self.selection is None
                    or self.selection.target_id != self.activation.target_id
                    or (self.combo, self.manathirst) != (self.activation.combo, self.activation.manathirst)):
                raise ValueError('Physical body changed its independent original acceptance')
        if (self.phase == 'running' or self.phase == 'completed' and self.failure is None) != (self.activation is not None):
            raise ValueError('Only an accepted executable physical body has an activation receipt')
        from .generated_battlecry_repeats import PROFILE as repeat_profile
        expected_repeat = self.activation is not None and self.activation.profile_id in (repeat_profile, 'generated_family_repeat_after_install_v1', 'generated_retained_family_after_install_v1') and bool(self.battlecries)
        if expected_repeat != (self.battlecry_repeat_acceptance is not None):
            raise ValueError('Physical body lost or fabricated its declared Battlecry repeat acceptance')
        if self.battlecry_repeat_acceptance is not None:
            if type(self.battlecry_repeat_acceptance) is not GeneratedBattlecryAcceptance:
                raise ValueError('Physical body requires a concrete Battlecry family acceptance')
            self.battlecry_repeat_acceptance.__post_init__()
        from .generated_combo_repeats import PROFILES as combo_profiles
        expected_combo = (self.activation is not None and
            self.activation.profile_id in combo_profiles and
            self.kind in (CardType.MINION, CardType.WEAPON, CardType.HERO))
        if expected_combo != (self.combo_repeat_acceptance is not None):
            raise ValueError('Physical body lost or fabricated its independent Combo acceptance')
        if self.combo_repeat_acceptance is not None:
            if type(self.combo_repeat_acceptance) is not ComboAcceptanceReceipt:
                raise ValueError('Generated Combo requires its concrete family acceptance')
            self.combo_repeat_acceptance.__post_init__()
            if ((self.combo_repeat_acceptance.recipient.carrier_id,
                    self.combo_repeat_acceptance.recipient.card_id, self.combo_repeat_acceptance.recipient.kind) !=
                    (self.source.entity_id, self.source.card_id, self.source.kind) or
                    self.combo_repeat_acceptance.player_id != self.player_id):
                raise ValueError('Generated Combo changed its original actual recipient')
        elif self.combo_ids or self.active_combo_id is not None:
            raise ValueError('Unsupported body cannot fabricate actual generated Combo identities')
        if self.retained_acceptance is not None:
            if type(self.retained_acceptance) is not GeneratedRetainedAcceptance:
                raise ValueError('Physical retained acceptance requires its full concrete type')
            self.retained_acceptance.__post_init__()
            receipt = self.retained_acceptance
            if (self.activation is None or self.activation.profile_id != RETAINED_PROFILE
                    or receipt.activation != self.activation or
                    (receipt.on_play, receipt.battlecries, receipt.combos) != (self.on_play, self.battlecries, self.combos)
                    or (receipt.status == 'retained') != (self.outcome_id is not None)
                    or self.outcome_id is not None and self.outcome_id != receipt.before_outcome_id):
                raise ValueError('Physical retained progress changed its original accepted body or quota')
        elif self.outcome_id is not None:
            raise ValueError('Physical result root lost its complete retained acceptance')
        if self.body_targets is not None:
            if type(self.body_targets) is not GeneratedBodyTargetAcceptance or self.activation is None:
                raise ValueError('Generated body targets require their actual accepted activation')
            self.body_targets.__post_init__()
        if self.choose_one is not None:
            if type(self.choose_one) is not GeneratedChooseOneReceipt or self.kind != CardType.MINION:
                raise ValueError('Generated Choose One requires its typed physical minion receipt')
            self.choose_one.__post_init__()
            if (self.choose_one.child_id, self.choose_one.player_id, self.choose_one.card_id) != (self.child_id, self.player_id, self.card_id):
                raise ValueError('Physical body borrowed another generated branch')
            if self.activation is not None and (self.choose_one.profile_id != self.activation.profile_id or
                    (self.choose_one.turn, self.choose_one.action) > (self.activation.turn, self.activation.action)):
                raise ValueError('Generated branch changed its independent source or acceptance chronology')


@dataclass(frozen=True)
class PhysicalBodyProof:
    acceptance: object
    before_state: GameState
    rules: Ruleset
    definition: CardDefinition
    accepted: PhysicalReplayProgress
    information_json: str | None
    choose_proof: GeneratedChooseOneProof | None = None

    def __post_init__(self):
        from .whole_card_replays import ReplayAcceptanceProof
        if (type(self.acceptance) is not ReplayAcceptanceProof or type(self.before_state) is not GameState
                or type(self.rules) is not Ruleset or type(self.definition) is not CardDefinition
                or type(self.accepted) is not PhysicalReplayProgress or self.accepted.phase != 'running'
                or self.information_json is not None and type(self.information_json) is not str):
            raise ValueError('Physical body proof lost its actual complete acceptance window')
        self.acceptance.__post_init__(); self.accepted.__post_init__(); self.rules.__post_init__()
        if (self.accepted.choose_one is not None) != (self.choose_proof is not None):
            raise ValueError('Physical body lost or invented its original generated branch proof')
        if self.choose_proof is not None:
            if type(self.choose_proof) is not GeneratedChooseOneProof or self.choose_proof.receipt != self.accepted.choose_one:
                raise ValueError('Physical branch proof differs from its actual receipt')
            self.choose_proof.__post_init__()


@dataclass(frozen=True)
class PreparePhysicalBody(Effect):
    acceptance: object
    child_id: int
    choose_proof: GeneratedChooseOneProof | None = None


@dataclass(frozen=True)
class AdvancePhysicalBody(Effect):
    proof: PhysicalBodyProof


@dataclass(frozen=True)
class FinishPhysicalBody(Effect):
    proof: PhysicalBodyProof


@dataclass(frozen=True)
class FinishReplayPhysical(Effect):
    proof: object
    child_id: int


def segments(progress):
    return tuple(segment_at(progress, index) for index in range(segment_count(progress)))


def bc_repetitions(progress):
    return 1 if progress.battlecry_repeat_acceptance is None else progress.battlecry_repeat_acceptance.plan.repetitions


def combo_repetitions(progress):
    accepted = progress.combo_repeat_acceptance
    return 1 if accepted is None or accepted.plan is None else accepted.plan.repetitions


def combo_start(progress):
    return len(progress.on_play) + len(progress.battlecries) * bc_repetitions(progress)


def combo_repetition_at(progress, index):
    index = index % result_segment_count(progress) - combo_start(progress)
    if index < 0 or index >= len(progress.combos) * combo_repetitions(progress):
        raise ValueError('Physical cursor does not identify an accepted Combo segment')
    return index % combo_repetitions(progress) + 1


def result_segment_count(progress):
    return combo_start(progress) + len(progress.combos) * combo_repetitions(progress)


def result_total(progress):
    return 1 if progress.retained_acceptance is None else progress.retained_acceptance.total


def segment_count(progress):
    return result_segment_count(progress) * result_total(progress)


def iteration_at(progress, index):
    base = result_segment_count(progress)
    if type(index) is not int or not 0 <= index < segment_count(progress) or base == 0:
        raise ValueError('Physical result position lies outside its complete accepted body')
    return index // base + 1


def battlecry_repetition_at(progress, index):
    index = index % result_segment_count(progress) - len(progress.on_play)
    if not 0 <= index < len(progress.battlecries) * bc_repetitions(progress):
        raise ValueError('Physical position is not an accepted Battlecry segment')
    return index % bc_repetitions(progress) + 1


def started_family_count(progress, offset, size):
    base = result_segment_count(progress)
    if base == 0:
        return 0
    complete, position = divmod(progress.cursor, base)
    return complete * size + max(0, min(position - offset, size))


def started_battlecry_count(progress):
    return started_family_count(progress, len(progress.on_play), len(progress.battlecries) * bc_repetitions(progress))


def started_combo_count(progress):
    return started_family_count(progress, combo_start(progress), len(progress.combos) * combo_repetitions(progress))


def family_position(progress, ordinal, payloads, repetitions):
    width = len(payloads) * repetitions
    if width == 0 or not 0 <= ordinal < width * result_total(progress):
        raise ValueError('Actual generated family identity lies outside its accepted result groups')
    group, index = divmod(ordinal, width)
    return payloads[index // repetitions], index % repetitions + 1, group + 1


def segment_at(progress, index):
    index %= result_segment_count(progress)
    if index < len(progress.on_play): return 'on_play', progress.on_play[index]
    index -= len(progress.on_play); count = bc_repetitions(progress)
    if index < len(progress.battlecries) * count: return 'battlecry', progress.battlecries[index // count]
    index -= len(progress.battlecries) * count
    return 'combo', progress.combos[index // combo_repetitions(progress)]


def child_for(state, child_id):
    integer(child_id, 'physical child reference')
    if child_id > len(state.whole_card_replay_ledger.children): raise ValueError('Unknown actual physical child')
    return state.whole_card_replay_ledger.children[child_id - 1]


def put(state, progress):
    progress.__post_init__()
    ledger = state.whole_card_replay_ledger; child = child_for(state, progress.child_id)
    root = top_root(ledger, child.root_id)
    if root.active_child_id != child.id or child.status != ReplayChildStatus.RUNNING:
        raise ValueError('Physical body cannot replace another active replay invocation')
    if (child.card_id, child.kind, root.player_id) != (progress.card_id, progress.kind, progress.player_id):
        raise ValueError('Physical body differs from its original selected occurrence')
    child = replace(child, physical=progress)
    state.whole_card_replay_ledger = with_root(ledger, root,
        children=ledger.children[:child.id - 1] + (child,) + ledger.children[child.id:])


def install(r, acceptance, child, *, choose_before=None):
    from .whole_card_replays import current_root
    root = current_root(r.state, r.registry, acceptance)
    card = r.registry.card(child.card_id)
    from .generated_body_targets import selected_binding
    selected_binding(r.registry,card.id,acceptance.request)
    if card.kind not in KINDS or not card.hand_playable: raise ResolutionError('Unsupported physical hand-card definition')
    from .generated_choose_one import capture as capture_branch
    choose_proof = capture_branch(r, acceptance, child, choose_before)
    from .choose_policies import accept as accept_choose_policy
    choose_tail = accept_choose_policy(r, None if choose_proof is None else choose_proof.policy_proof)
    progress = PhysicalReplayProgress(child.id, root.player_id, child.card_id, child.kind,
        choose_one=None if choose_proof is None else choose_proof.receipt)
    work = ()
    if child.kind == CardType.MINION:
        from .summon_quantities import SummonByCard, SummonCause, accept as accept_summon
        from .replay_entry_material import PhysicalReplayEntryMaterial
        cause = SummonCause(SourceAllocationFact.capture(r.state, r.state.entities[root.caster.entity_id]),
            root.player_id, r.state.turn, r.state.action_number)
        work = accept_summon(r, SummonByCard(root.player_id, (PhysicalReplayEntryMaterial(card.id, root.id, child.id),), cause))
        # The common acceptor returns the actual typed root. No entity cursor guessing.
        progress = replace(progress, summon_root_id=work[0].root_id)
    elif child.kind in (CardType.WEAPON, CardType.LOCATION):
        from .generated_placement import InstallGeneratedPlacement, install_generated_placement
        result = install_generated_placement(r, InstallGeneratedPlacement(root.player_id, card.id, root.caster.entity_id))
        progress = replace(progress, source=result.installation, failure=result.failure,
            phase='completed' if result.failure else 'installing')
    else:
        from .generated_heroes import InstallGeneratedHeroCard, install_generated_hero_card
        result = install_generated_hero_card(r, InstallGeneratedHeroCard(root.player_id, card.id, root.caster.entity_id))
        progress = replace(progress, source=SourceAllocationFact.capture(r.state, r.state.entities[result.hero_id]))
    if progress.source is not None:
        r.state.entities[progress.source.entity_id].origin_entity_id = root.caster.entity_id
    put(r.state, progress)
    return (*work, PreparePhysicalBody(acceptance, child.id, choose_proof), FinishReplayPhysical(acceptance, child.id), *choose_tail)


def current_source(state, progress):
    fact = progress.source
    if fact is None: return False
    entity = state.entities[fact.entity_id]
    if not entity.active or entity.doomed: return False
    if progress.kind in (CardType.MINION, CardType.HERO) and entity.health <= 0: return False
    if progress.kind in (CardType.WEAPON, CardType.LOCATION) and entity.durability <= 0: return False
    if ((entity.card_id, entity.kind, entity.owner, entity.controller, entity.zone, entity.zone_epoch, entity.entered_order)
            != (fact.card_id, fact.kind, fact.owner, fact.controller, fact.zone, fact.zone_epoch, fact.entered_order)):
        return False
    player = state.players[progress.player_id]
    return (entity.id in player.board if progress.kind in (CardType.MINION, CardType.LOCATION)
        else player.weapon_id == entity.id if progress.kind == CardType.WEAPON else player.hero_id == entity.id)


def original_body(state, registry, progress):
    from .battlecries import capture as capture_bc
    from .combos import capture as capture_combo
    from .play_history import played_cards
    from .spell_casts import effective_definition
    entity = state.entities[progress.source.entity_id]
    card = registry.card(progress.card_id)
    from .generated_choose_one import definition as branch_definition
    card = branch_definition(registry, card, progress.choose_one)
    conditions = dict(combo=bool(played_cards(state, progress.player_id, turn=state.turn)),
        outcast=False, finale=False, quickdraw=False,
        manathirst=card.manathirst is not None and state.players[progress.player_id].max_mana >= card.manathirst)
    return (effective_definition(card, conditions), conditions,
        tuple(a.behavior_id for a in active_abilities(entity, 'on_play')), capture_bc(entity),
        capture_combo(entity) if conditions['combo'] else ())


def prepare(r, effect):
    from .whole_card_replays import current_root
    root = current_root(r.state, r.registry, effect.acceptance)
    child = child_for(r.state, effect.child_id); progress = child.physical
    if progress is None or root.active_child_id != child.id: raise ResolutionError('Physical preparation lost its original installation')
    if progress.phase == 'completed': return ()
    if progress.phase != 'installing': raise ResolutionError('Physical body was already prepared')
    if progress.summon_root_id is not None:
        from .summon_quantities import record
        summon = record(r.state, progress.summon_root_id)
        if summon.status not in ('completed', 'skipped'): raise ResolutionError('Physical minion body precedes its common entry completion')
        fact = summon.deliveries[0].entity if summon.deliveries else None
        # CardSummonDelivery uses the original physical fact, including quantity extras.
        if fact is None:
            put(r.state, replace(progress, phase='completed', failure='board_full')); return ()
        progress = replace(progress, source=fact)
        r.state.entities[fact.entity_id].origin_entity_id = root.caster.entity_id
        put(r.state, progress)
    if not current_source(r.state, progress):
        put(r.state, replace(progress, phase='completed', failure='stale_installation')); return ()
    definition, conditions, bodies, battlecries, combos = original_body(r.state, r.registry, progress)
    from .generated_body_targets import selected_binding, capture as capture_body_targets
    binding=selected_binding(r.registry,progress.card_id,effect.acceptance.request)
    information = None
    if binding is None and r.registry.target_visibility(definition.target_rule) == 'player':
        r.game._information.sync(r.game)
        information = json.dumps(r.game._information.to_dict(), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    before = deepcopy(r.state); rng_before = r.game._rng.getstate()
    from .generated_activation_receipts import capture as capture_activation
    body_targets=None
    if binding is not None:
        initial=capture_activation(before,r.registry,root,child,progress.source,None,effect.acceptance.request.physical_profile)
        definition,body_targets=capture_body_targets(r,binding,initial,effect.acceptance.request)
        selection=body_targets.root;target=selection.target_id;failure=None
    else:
        target, failure, partition = select_automatic_target(r, r.state.entities[progress.source.entity_id], definition,
            preference=effect.acceptance.request.target_preference)
        selection = AutomaticTargetSelection(partition, target, failure, rng_before, r.game._rng.getstate())
    activation = None if failure else capture_activation(before, r.registry, root, child, progress.source, target,
        effect.acceptance.request.physical_profile)
    from .generated_battlecry_repeats import capture as capture_bc_repeat, consume as consume_bc_repeat
    bc_repeat = None if failure else capture_bc_repeat(before, r.registry, progress.source.entity_id, progress.player_id,
        battlecries, effect.acceptance.request.physical_profile)
    from .generated_combo_repeats import capture as capture_combo_repeat
    combo_repeat, combo_policy = (None, None) if failure else capture_combo_repeat(before, r.registry,
        activation, effect.acceptance.request.physical_profile)
    combo_count = 1 if combo_repeat is None or combo_repeat.plan is None else combo_repeat.plan.repetitions
    bc_count = 1 if bc_repeat is None else bc_repeat.plan.repetitions
    if len(battlecries) * bc_count + len(bodies) + len(combos) * combo_count > r.rules.max_resolution_steps:
        from .errors import ResolutionLimitExceeded
        raise ResolutionLimitExceeded('Complete generated Battlecry body exceeds resolution budget')
    progress = replace(progress, **conditions, selection=selection, on_play=bodies, battlecries=battlecries, combos=combos,
        phase='completed' if failure else 'running', failure=failure, activation=activation,
        battlecry_repeat_acceptance=bc_repeat, combo_repeat_acceptance=combo_repeat,body_targets=body_targets)
    if not failure and activation.profile_id == RETAINED_PROFILE:
        from .generated_retained_acceptance import capture_from_state
        retained = capture_from_state(before, r.registry, progress, r.rules.max_resolution_steps)
        progress = replace(progress, retained_acceptance=retained,
            outcome_id=retained.before_outcome_id if retained.status == 'retained' else None)
    put(r.state, progress)
    if failure: return ()
    from .generated_combo_repeats import install_policy, consume as consume_combo_repeat
    install_policy(r.state, progress, combo_policy)
    from .generated_retained_outcomes import install as install_retained
    install_retained(r, progress)
    consume_bc_repeat(r, progress)
    consume_combo_repeat(r, progress)
    proof = PhysicalBodyProof(effect.acceptance, before, r.rules, definition, progress, information, effect.choose_proof)
    if progress.outcome_id is not None:
        from .rewind_outcomes import StartRewindOutcome, FinishRewindOutcomes
        return (StartRewindOutcome(progress.outcome_id), FinishRewindOutcomes(progress.outcome_id), FinishPhysicalBody(proof))
    return (AdvancePhysicalBody(proof), FinishPhysicalBody(proof))


def validate_body_proof(proof, registry):
    from .whole_card_replays import current_root
    proof.__post_init__(); state = proof.before_state; accepted = proof.accepted
    if proof.choose_proof is not None:
        from .generated_choose_one import validate_proof as validate_branch_proof
        validate_branch_proof(proof.choose_proof, proof.acceptance, registry)
    root = current_root(state, registry, proof.acceptance)
    prior = child_for(state, accepted.child_id).physical
    if prior is None or root.active_child_id != accepted.child_id or not current_source(state, prior):
        raise ValueError('Physical proof lost its real installed primary source')
    definition, conditions, bodies, battlecries, combos = original_body(state, registry, prior)
    from .generated_body_targets import selected_binding,root_definition,validate as validate_body_targets
    binding=selected_binding(registry,prior.card_id,proof.acceptance.request)
    if (binding is not None)!=(accepted.body_targets is not None):
        raise ValueError('Physical proof erased or invented independent generated target acceptance')
    from .generated_activation_receipts import capture as capture_activation
    activation = capture_activation(state, registry, root, child_for(state, accepted.child_id), prior.source,
        accepted.selection.target_id, proof.acceptance.request.physical_profile)
    if binding is not None:
        if accepted.body_targets.binding!=binding: raise ValueError('Generated targets borrowed another source binding')
        definition=root_definition(registry,binding,activation,bodies,prior.choose_one)
        validate_body_targets(state,registry,accepted,proof.acceptance.request,before=state)
    from .generated_battlecry_repeats import capture as capture_bc_repeat
    bc_repeat = capture_bc_repeat(state, registry, prior.source.entity_id, prior.player_id, battlecries,
        proof.acceptance.request.physical_profile)
    from .generated_combo_repeats import capture as capture_combo_repeat
    combo_repeat, _ = capture_combo_repeat(state, registry, activation, proof.acceptance.request.physical_profile)
    combo_count = 1 if combo_repeat is None or combo_repeat.plan is None else combo_repeat.plan.repetitions
    bc_count = 1 if bc_repeat is None else bc_repeat.plan.repetitions
    if len(battlecries) * bc_count + len(bodies) + len(combos) * combo_count > proof.rules.max_resolution_steps:
        raise ValueError('Physical proof exceeds its original generated Battlecry resolution budget')
    expected = replace(prior, **conditions, selection=accepted.selection, on_play=bodies,
        battlecries=battlecries, combos=combos, phase='running', activation=activation,
        battlecry_repeat_acceptance=bc_repeat, combo_repeat_acceptance=combo_repeat,body_targets=accepted.body_targets)
    if activation.profile_id == RETAINED_PROFILE:
        from .generated_retained_acceptance import capture_from_state
        retained = capture_from_state(state, registry, expected, proof.rules.max_resolution_steps)
        expected = replace(expected, retained_acceptance=retained,
            outcome_id=retained.before_outcome_id if retained.status == 'retained' else None)
    if accepted != expected or proof.definition != definition:
        raise ValueError('Physical body changed its original current payloads or conditions')
    if binding is not None:
        if proof.information_json is not None: raise ValueError('Generated independent targets use their own original player input')
        return
    player_predicate = registry.target_visibility(definition.target_rule) == 'player'
    if player_predicate != (proof.information_json is not None): raise ValueError('Physical target proof changed predicate visibility')
    game = SimpleNamespace(_state=deepcopy(state), registry=registry, ruleset=proof.rules)
    if player_predicate:
        from .information import Information
        game._information = Information.from_dict(json.loads(proof.information_json), game)
    probe = SimpleNamespace(state=game._state, registry=registry, game=game)
    partition = automatic_target_partition(probe, game._state.entities[accepted.source.entity_id], definition,
        preference=proof.acceptance.request.target_preference)
    if partition != accepted.selection.partition: raise ValueError('Physical target differs from its complete original window')


def same_progress(current, accepted):
    return replace(current, phase=accepted.phase, cursor=0, active_battlecry_id=None, battlecry_ids=(),
        active_combo_id=None, combo_ids=()) == accepted


def advance(r, effect):
    proof = effect.proof; validate_body_proof(proof, r.registry)
    progress = child_for(r.state, proof.accepted.child_id).physical
    if not same_progress(progress, proof.accepted) or progress.phase != 'running':
        raise ResolutionError('Physical body lost its original invocation')
    if progress.active_battlecry_id is not None:
        b = r.state.battlecry_history[progress.active_battlecry_id - 1]
        if not b.completed or b.interrupted: raise ResolutionError('Physical continuation precedes actual Battlecry completion')
        progress = replace(progress, active_battlecry_id=None)
        put(r.state, progress)
    if progress.active_combo_id is not None:
        combo = r.state.combo_history[progress.active_combo_id - 1]
        if not combo.completed or combo.interrupted:
            raise ResolutionError('Physical continuation precedes actual Combo completion')
        progress = replace(progress, active_combo_id=None)
        put(r.state, progress)
    limit = segment_count(progress)
    if progress.outcome_id is not None:
        from .generated_retained_outcomes import record_for, validate_original_binding
        retained = record_for(r.state, progress)
        if not retained.running:
            raise ResolutionError('Physical continuation cannot execute outside its actual running result')
        validate_original_binding(r.state, r.registry, proof)
        limit = (retained.completed + 1) * result_segment_count(progress)
    if progress.cursor > limit:
        raise ResolutionError('Physical continuation crossed its owed result boundary')
    if progress.cursor == limit: return ()
    kind, payload = segment_at(progress, progress.cursor)
    progress = replace(progress, cursor=progress.cursor + 1)
    put(r.state, progress)
    if kind == 'battlecry':
        from .battlecry_sources import BeginIndirectBattlecry, begin
        # Full-card target accepted once; each declared BC validates that target
        # through its existing indirect route, not a fake paid activation.
        from .generated_body_targets import target_for
        result = begin(r, BeginIndirectBattlecry(progress.source.entity_id, progress.player_id, progress.card_id,
            payload, caster_id=proof.acceptance.root.caster.entity_id, target_id=target_for(progress,payload,'battlecry'),
            targeting='explicit', choices=proof.acceptance.request.choices, physical_child_id=progress.child_id,
            outcome_id=progress.outcome_id, iteration=iteration_at(progress, progress.cursor - 1),
            repeat_index=battlecry_repetition_at(progress, progress.cursor - 1)
                if progress.activation.profile_id == RETAINED_PROFILE else 1))
    elif kind == 'combo':
        from .generated_combo_repeats import BeginGeneratedCombo, begin as begin_generated_combo
        result = begin_generated_combo(r, BeginGeneratedCombo(progress.child_id, payload,
            combo_repetition_at(progress, progress.cursor - 1)))
    else:
        behavior = payload
        target=progress.selection.target_id
        from .generated_body_targets import root_failure_for
        failure=root_failure_for(r,progress) if progress.body_targets is not None else None
        if failure:
            r.emit('body_target_skipped',source_id=progress.source.entity_id,target_id=target,
                player_id=progress.player_id,physical_child_id=progress.child_id,family=kind,reason=failure)
            result=()
        else: result = (r.call(behavior, progress.source.entity_id, progress.player_id,target, physical=progress),)
    return (*result, AdvancePhysicalBody(proof))


def bind_actual_battlecry(r, request, record):
    """Bind before start listeners capture the current actual generated body."""
    progress = child_for(r.state, request.physical_child_id).physical
    from .generated_body_targets import target_for
    from .whole_card_replay_ledger import root_record
    root = root_record(r.state.whole_card_replay_ledger, child_for(r.state, request.physical_child_id).root_id)
    proof = next((w.proof for w in r._work_queue if type(w) is FinishPhysicalBody
        and w.proof.accepted.child_id == progress.child_id), None)
    if (proof is None or not same_progress(progress, proof.accepted) or progress.phase != 'running'
            or progress.cursor < 1 or progress.active_battlecry_id is not None
            or segment_at(progress, progress.cursor - 1) != ('battlecry', request.payload)
            or (request.source_id, request.player_id, request.card_id, request.caster_id, request.target_id, request.choices) !=
                (progress.source.entity_id, progress.player_id, progress.card_id, root.caster.entity_id,
                    target_for(progress,request.payload,'battlecry'), proof.acceptance.request.choices)
            or request.origin != 'effect' or request.targeting != 'explicit' or request.history_id is not None
            or request.history_play_id is not None or request.exclude_source_target or request.controller_policy != 'captured'):
        raise ResolutionError('Physical Battlecry lost its unique original owed invocation')
    count = started_battlecry_count(progress)
    expected_repeat = (battlecry_repetition_at(progress, progress.cursor - 1)
        if progress.activation.profile_id == RETAINED_PROFILE else 1)
    if (request.outcome_id, request.iteration, request.repeat_index) != (
            progress.outcome_id, iteration_at(progress, progress.cursor - 1), expected_repeat):
        raise ResolutionError('Generated Battlecry changed its actual result or repetition position')
    if len(progress.battlecry_ids) != count - 1:
        raise ResolutionError('Physical Battlecry reused or abandoned its real invocation identity')
    put(r.state, replace(progress, active_battlecry_id=record.id, battlecry_ids=(*progress.battlecry_ids, record.id)))


def finish_body(r, effect):
    proof = effect.proof; validate_body_proof(proof, r.registry)
    progress = child_for(r.state, proof.accepted.child_id).physical
    if (not same_progress(progress, proof.accepted) or progress.cursor != segment_count(progress)
            or progress.active_battlecry_id is not None or progress.active_combo_id is not None or progress.phase != 'running'):
        raise ResolutionError('Physical body Finish abandoned accepted payload work')
    if progress.outcome_id is not None:
        from .generated_retained_outcomes import record_for
        retained = record_for(r.state, progress)
        if not retained.finished or retained.interrupted:
            raise ResolutionError('Physical Finish precedes its complete retained-result group')
    put(r.state, replace(progress, phase='completed'))


def finish_child(r, effect):
    from .whole_card_replays import current_root
    from .whole_card_replay_ledger import finish_replay_child
    root = current_root(r.state, r.registry, effect.proof)
    child = child_for(r.state, effect.child_id)
    if root.active_child_id != child.id or child.physical is None or child.physical.phase != 'completed':
        raise ResolutionError('Physical replay child cannot finish before its full actual body')
    r.state.whole_card_replay_ledger = finish_replay_child(r.state.whole_card_replay_ledger,
        child.id, failure=child.physical.failure)


def automatic_choice(r, choice, options, on_select):
    for root_id in reversed(r.state.whole_card_replay_ledger.stack):
        root = r.state.whole_card_replay_ledger.roots[root_id - 1]
        if root.active_child_id is None: continue
        progress = child_for(r.state, root.active_child_id).physical
        if progress is None or progress.phase != 'running' or progress.source.entity_id != choice.source_id or progress.player_id != choice.player_id:
            continue
        # Read the actual root Finish proof owning this body, not another actor.
        from .whole_card_replays import FinishReplayRoot
        closer = next(w for w in r._work_queue if type(w) is FinishReplayRoot and w.proof.root.id == root.id)
        if closer.proof.request.choices != 'random': return None
        from .choices import random_choice_effects
        return random_choice_effects(r, choice, options, on_select, 'physical_choice_automatic', child_id=progress.child_id)
    return None


def active_progress(state, source_id, player_id):
    for root_id in reversed(state.whole_card_replay_ledger.stack):
        root = state.whole_card_replay_ledger.roots[root_id - 1]
        if root.active_child_id is None: continue
        progress = child_for(state, root.active_child_id).physical
        if (progress is not None and progress.phase == 'running' and progress.source.entity_id == source_id
                and progress.player_id == player_id):
            return progress
    return None


def validate_physical_history(state, registry):
    from .generated_body_targets import target_for
    used_sources = set(); used_summons = set(); used_battlecries = set()
    for child in state.whole_card_replay_ledger.children:
        root = state.whole_card_replay_ledger.roots[child.root_id - 1]
        progress = child.physical
        if child.kind == CardType.SPELL or child.failure == 'ancestor_excluded':
            if progress is not None: raise ValueError('Spell/excluded child cannot borrow a physical activation')
            continue
        if root.runtime_route != 'cards_v1':
            if progress is not None: raise ValueError('Fixture/legacy root cannot fabricate a physical runtime')
            continue
        if progress is None: raise ValueError('Actual physical child lost its real installed-body binding')
        progress.__post_init__()
        from .generated_choose_one import validate_receipt as validate_branch_receipt
        if (registry.card(child.card_id).choose_one is not None) != (progress.choose_one is not None):
            raise ValueError('Physical history lost or invented its actual generated branch')
        if progress.choose_one is not None:
            validate_branch_receipt(state, registry, progress.choose_one, root, child)
        from .generated_body_targets import validate as validate_body_targets
        bound=any(card==progress.card_id for card,_ in registry.generated_whole_target_bindings)
        if progress.activation is not None and bound and progress.body_targets is None:
            raise ValueError('Generated source erased its independent target acceptance')
        validate_body_targets(state,registry,progress)
        if progress.activation is not None:
            from .generated_activation_receipts import validate as validate_activation
            validate_activation(state, registry, progress.activation, root, child)
        from .generated_battlecry_repeats import validate as validate_bc_repeat
        validate_bc_repeat(state, registry, progress)
        from .generated_retained_outcomes import validate_progress
        validate_progress(state, registry, progress)
        from .generated_combo_repeats import validate_physical_progress
        validate_physical_progress(state, registry, progress)
        if (progress.player_id, progress.card_id, progress.kind) != (root.player_id, child.card_id, child.kind):
            raise ValueError('Physical activation changed its accepted executor or original card')
        if progress.source is not None:
            validate_allocation(state, registry, progress.source)
            if progress.source.entity_id in used_sources: raise ValueError('Physical child reused another primary carrier')
            used_sources.add(progress.source.entity_id)
            if state.entities[progress.source.entity_id].origin_entity_id != root.caster.entity_id:
                raise ValueError('Physical installation lost its original actual issuer')
        if progress.summon_root_id is not None:
            from .summon_quantities import record
            summon = record(state, progress.summon_root_id)
            if (summon.id in used_summons or summon.request.player_id != root.player_id
                    or summon.request.cause.source.entity_id != root.caster.entity_id
                    or summon.request.cause.action < root.accepted_action
                    or tuple(m.card_id for m in summon.request.materials) != (child.card_id,)):
                raise ValueError('Physical minion lost its unique original common summon root')
            used_summons.add(summon.id)
            if progress.source is not None and (not summon.deliveries or summon.deliveries[0].entity != progress.source):
                raise ValueError('Physical body substituted an extra or unrelated summon carrier')
        elif child.kind == CardType.MINION:
            raise ValueError('Actual physical minion erased its attributed entry root')
        if child.status in (ReplayChildStatus.FINISHED, ReplayChildStatus.FAILED):
            if progress.phase != 'completed' or child.failure != progress.failure:
                raise ValueError('Settled physical child lost its complete actual body outcome')
        accepted_bc_count = started_battlecry_count(progress)
        if accepted_bc_count != len(progress.battlecry_ids): raise ValueError('Physical body erased accepted Battlecry attempts')
        for index, b_id in enumerate(progress.battlecry_ids):
            payload, repeated, iteration = family_position(progress, index, progress.battlecries, bc_repetitions(progress))
            if b_id > len(state.battlecry_history) or b_id in used_battlecries:
                raise ValueError('Physical body lost a unique actual Battlecry invocation')
            used_battlecries.add(b_id); b = state.battlecry_history[b_id - 1]
            if (b.origin != 'effect' or b.source_id != progress.source.entity_id
                    or b.player_id != root.player_id or b.card_id != child.card_id or b.payload != payload
                    or b.caster_id != root.caster.entity_id or b.target_id != target_for(progress,payload,'battlecry')
                    or b.play_id is not None or b.physical_child_id != progress.child_id
                    or b.outcome_id != progress.outcome_id or b.iteration != iteration
                    or b.repeat_index != (repeated if progress.activation.profile_id == RETAINED_PROFILE else 1)):
                raise ValueError('Physical Battlecry differs from its independent actual source')
            if progress.phase == 'completed' and (not b.completed or b.interrupted):
                raise ValueError('Physical body completed before its actual Battlecry')
        for behavior in progress.on_play: registry.behavior(behavior)
        for payload in (*progress.battlecries, *progress.combos):
            registry.behavior(payload.behavior_id)
            field = 'battlecry' if type(payload) is BattlecryPayload else 'combo'
            if getattr(registry.card(payload.card_id), field) != payload.behavior_id:
                raise ValueError('Physical body lost a registered declaration')


def validate_physical_control(state, registry, work):
    from .whole_card_replays import current_root
    if type(work) is PreparePhysicalBody:
        root = current_root(state, registry, work.acceptance)
        child = child_for(state, work.child_id)
        if root.active_child_id != child.id or child.physical is None:
            raise ValueError('Physical preparation belongs to another current child')
        if (child.physical.choose_one is not None) != (work.choose_proof is not None):
            raise ValueError('Physical preparation lost or invented its generated branch proof')
        if work.choose_proof is not None:
            from .generated_choose_one import validate_proof as validate_branch_proof
            validate_branch_proof(work.choose_proof, work.acceptance, registry)
            if work.choose_proof.receipt != child.physical.choose_one:
                raise ValueError('Preparation changed its accepted generated branch')
    elif type(work) in (AdvancePhysicalBody, FinishPhysicalBody):
        validate_body_proof(work.proof, registry)
        root = current_root(state, registry, work.proof.acceptance)
        progress = child_for(state, work.proof.accepted.child_id).physical
        if root.active_child_id != work.proof.accepted.child_id or not same_progress(progress, work.proof.accepted):
            raise ValueError('Physical continuation changed its accepted body')
        from .generated_combo_repeats import validate_original_binding
        validate_original_binding(state, registry, work.proof)
        from .generated_retained_outcomes import validate_original_binding as validate_retained_binding
        validate_retained_binding(state, registry, work.proof)


def validate_physical_queue(state, registry, closer, queue):
    progress = child_for(state, closer.child_id).physical
    if progress is None: raise ValueError('Physical Finish lost its real installation progress')
    own = tuple(w for w in queue if (type(w) is PreparePhysicalBody and w.child_id == closer.child_id
        or type(w) in (AdvancePhysicalBody, FinishPhysicalBody) and w.proof.accepted.child_id == closer.child_id))
    if progress.phase == 'installing':
        if (len(own) != 1 or type(own[0]) is not PreparePhysicalBody or
                own[0].acceptance != closer.proof or own[0].child_id != closer.child_id):
            raise ValueError('Physical installation lost its exact original body preparation')
        validate_physical_control(state, registry, own[0])
        if progress.summon_root_id is not None:
            from .summon_quantities import FinishCardSummon, record
            summon = record(state, progress.summon_root_id)
            if summon.status == 'active':
                end = FinishCardSummon(summon.id)
                if end not in queue or queue.index(end) > queue.index(own[0]):
                    raise ValueError('Physical body preparation precedes its owed attributed entry')
    elif progress.phase == 'running':
        if not own or type(own[-1]) is not FinishPhysicalBody:
            raise ValueError('Physical body lost its complete original Finish')
        proof = own[-1].proof; validate_body_proof(proof, registry)
        expected_types = (AdvancePhysicalBody, FinishPhysicalBody)
        if progress.outcome_id is not None:
            from .generated_retained_outcomes import record_for, validate_original_binding as validate_retained_binding
            from .rewind_outcomes import StartRewindOutcome, FinishRewindOutcome, FinishRewindOutcomes
            retained = record_for(state, progress)
            expected_types = (AdvancePhysicalBody, FinishPhysicalBody) if retained.running else (FinishPhysicalBody,)
            group_end = FinishRewindOutcomes(retained.id)
            if not retained.finished:
                if group_end not in queue or queue.index(group_end) >= queue.index(own[-1]):
                    raise ValueError('Physical body lost its complete retained-group Finish')
                marker = FinishRewindOutcome(retained.id) if retained.running else StartRewindOutcome(retained.id)
                if marker not in queue or queue.index(marker) >= queue.index(group_end):
                    raise ValueError('Physical retained body lost its actual result continuation')
                if retained.running and queue.index(own[0]) >= queue.index(marker):
                    raise ValueError('Physical advance cannot cross its actual retained-result Finish')
            validate_retained_binding(state, registry, proof)
        if tuple(type(w) for w in own) != expected_types or any(w.proof != proof for w in own) or not same_progress(progress, proof.accepted):
            raise ValueError('Physical body tails changed original payloads or result position')
        if progress.active_battlecry_id is not None:
            from .battlecries import FinishBattlecry
            b = state.battlecry_history[progress.active_battlecry_id - 1]
            end = FinishBattlecry(b.id)
            if not b.completed and (end not in queue or queue.index(end) > queue.index(own[0])):
                raise ValueError('Physical body advance abandoned its actual pending Battlecry')
        if progress.active_combo_id is not None:
            from .combos import FinishCombo
            combo = state.combo_history[progress.active_combo_id - 1]
            end = FinishCombo(combo.id)
            if not combo.completed and (end not in queue or queue.index(end) > queue.index(own[0])):
                raise ValueError('Physical body advance abandoned its actual pending Combo')
        from .generated_combo_repeats import validate_original_binding
        validate_original_binding(state, registry, proof)
    elif own not in ((), (PreparePhysicalBody(closer.proof, closer.child_id),)):
        raise ValueError('Settled physical body retained or injected executable payload tails')
    if any(queue.index(w) > queue.index(closer) for w in own):
        raise ValueError('Physical child completes before its complete owed body')


def progress_from_dict(value):
    if type(value) is not dict or set(value) != {f.name for f in fields(PhysicalReplayProgress)}:
        raise ValueError('Physical activation wire fields differ from its concrete type')
    data = dict(value); data['kind'] = CardType(data['kind'])
    if data['source'] is not None: data['source'] = allocation_from_dict(data['source'])
    if data['selection'] is not None: data['selection'] = selection_from_dict(data['selection'])
    if data['body_targets'] is not None:
        from .generated_body_targets import acceptance_from_dict
        data['body_targets']=acceptance_from_dict(data['body_targets'])
    if data['choose_one'] is not None:
        from .generated_choose_one import receipt_from_dict
        data['choose_one'] = receipt_from_dict(data['choose_one'])
    if data['activation'] is not None:
        from .generated_activation_receipts import receipt_from_dict
        data['activation'] = receipt_from_dict(data['activation'])
    if data['battlecry_repeat_acceptance'] is not None:
        from .generated_battlecry_repeats import acceptance_from_dict
        data['battlecry_repeat_acceptance'] = acceptance_from_dict(data['battlecry_repeat_acceptance'])
    if data['retained_acceptance'] is not None:
        from .generated_retained_acceptance import receipt_from_dict
        data['retained_acceptance'] = receipt_from_dict(data['retained_acceptance'])
    if data['combo_repeat_acceptance'] is not None:
        from .serialization import _combo_acceptance_from_dict
        data['combo_repeat_acceptance'] = _combo_acceptance_from_dict(data['combo_repeat_acceptance'])
    for name in ('on_play', 'battlecries', 'combos', 'battlecry_ids', 'combo_ids'):
        if type(data[name]) is not list: raise ValueError('Physical activation requires complete ordered arrays')
        data[name] = tuple(data[name])
    data['battlecries'] = tuple(BattlecryPayload(**p) for p in data['battlecries'])
    data['combos'] = tuple(ComboPayload(**p) for p in data['combos'])
    return PhysicalReplayProgress(**data)


def register(mechanics):
    from .generated_placement import register as register_placement
    from .generated_heroes import register as register_heroes
    register_placement(mechanics); register_heroes(mechanics)
    from .generated_retained_outcomes import register as register_retained
    register_retained(mechanics)
    from .generated_body_targets import register as register_body_targets
    register_body_targets(mechanics)
    from .generated_choose_one import register as register_branches
    register_branches(mechanics)
    from .battlecry_policy_uses import BattlecryPolicyUseReceipt
    for kind in (BattlecryPolicyUseReceipt, GeneratedBattlecryAcceptance, GeneratedActivationReceipt,
            PhysicalReplayProgress, PhysicalBodyProof): mechanics.register_payload_type(kind)
    for kind, handler in ((PreparePhysicalBody, prepare), (AdvancePhysicalBody, advance),
            (FinishPhysicalBody, finish_body), (FinishReplayPhysical, finish_child)):
        mechanics.register(kind, handler)


def validate_generated_battlecry(state, registry, record, *, before_binding=False):
    from .generated_retained_outcomes import validate_actual_iteration
    from .generated_body_targets import target_for,validate_failure
    progress = child_for(state, record.physical_child_id).physical
    if progress is None or progress.source is None or progress.activation is None:
        raise ValueError('Generated Battlecry lost its actual independent physical body')
    child = child_for(state, progress.child_id)
    root = state.whole_card_replay_ledger.roots[child.root_id - 1]
    if (record.origin != 'effect' or record.play_id is not None or record.batch_id is not None
            or record.payload not in progress.battlecries or
            (record.source_id, record.player_id, record.card_id, record.target_id, record.caster_id) !=
                (progress.source.entity_id, progress.player_id, progress.card_id, target_for(progress,record.payload,'battlecry'), root.caster.entity_id)
            or (record.turn, record.action) < (progress.activation.turn, progress.activation.action)
            or (record.turn, record.action) > (state.turn, state.action_number)
            or not before_binding and record.id not in progress.battlecry_ids):
        raise ValueError('Generated Battlecry changed its actual original carrier, body or source')
    validate_failure(progress,record.payload,'battlecry',record.failure)
    validate_actual_iteration(state, progress, record.outcome_id, record.iteration)
    if before_binding:
        if progress.cursor < 1 or segment_at(progress, progress.cursor - 1) != ('battlecry', record.payload):
            raise ValueError('Generated Battlecry borrowed an unowed original body segment')
        iteration = iteration_at(progress, progress.cursor - 1)
        repeated = battlecry_repetition_at(progress, progress.cursor - 1)
    else:
        ordinal = progress.battlecry_ids.index(record.id)
        payload, repeated, iteration = family_position(progress, ordinal, progress.battlecries, bc_repetitions(progress))
        if payload != record.payload:
            raise ValueError('Generated Battlecry erased or reordered its accepted complete bodies')
    if (record.iteration != iteration or record.repeat_index !=
            (repeated if progress.activation.profile_id == RETAINED_PROFILE else 1)):
        raise ValueError('Generated Battlecry changed its actual result or repetition identity')
