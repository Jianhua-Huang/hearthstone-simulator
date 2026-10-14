"""Shared automatic target preference, selection receipts and original target proofs.

Uses the existing automatic eligibility contract. Its inherited protection and
choice policies remain local prototype rules pending CN calibration. The
candidate partition is diagnostic evidence, not a signed original-state proof.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
import json
from random import Random
from types import SimpleNamespace
from enum import Enum

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, Entity, TargetMode
from hs_sim.engine.targeting import accepts_target, effect_target_context, target_spec
from hs_sim.engine.model import GameState
from hs_sim.engine.rules import Ruleset


class AutomaticTargetPreference(str, Enum):
    ANY = 'any'
    ENEMY_IF_AVAILABLE = 'enemy_if_available'


@dataclass(frozen=True)
class AutomaticTargetPartition:
    source_id: int
    source_controller: int
    definition_id: str
    preference: AutomaticTargetPreference
    mode: TargetMode | None
    excluded_ids: tuple[int, ...]
    legal_ids: tuple[int, ...]
    enemy_ids: tuple[int, ...]
    selection_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.source_id) is not int or self.source_id < 1:
            raise ValueError('Target preference needs a physical source identity')
        if type(self.source_controller) is not int or self.source_controller not in (1, 2):
            raise ValueError('Target preference needs the actual source controller')
        if type(self.definition_id) is not str or not self.definition_id:
            raise ValueError('Target preference needs the effective registered definition')
        if type(self.preference) is not AutomaticTargetPreference:
            raise ValueError('Target preference must be an explicit typed policy')
        if self.mode is not None and type(self.mode) is not TargetMode:
            raise ValueError('Target preference has an unknown target mode')
        for label in ('excluded_ids', 'legal_ids', 'enemy_ids', 'selection_ids'):
            ids = getattr(self, label)
            if type(ids) is not tuple or any(type(i) is not int or i < 1 for i in ids):
                raise ValueError('Target preference needs complete typed ' + label)
            if ids != tuple(sorted(set(ids))):
                raise ValueError('Target preference IDs must be unique and ordered')
        if set(self.legal_ids) & set(self.excluded_ids):
            raise ValueError('Excluded target entered the legal partition')
        if not set(self.enemy_ids).issubset(self.legal_ids):
            raise ValueError('Enemy target entered from outside the legal partition')
        expected = (self.enemy_ids if self.preference is AutomaticTargetPreference.ENEMY_IF_AVAILABLE
                    and self.enemy_ids else self.legal_ids)
        if self.selection_ids != expected:
            raise ValueError('Target preference changed its complete selection domain')
        if self.mode is None and (self.legal_ids or self.enemy_ids or self.selection_ids):
            raise ValueError('Untargeted text cannot acquire target candidates')


def automatic_target_partition(r, source, definition, *,
                               preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE,
                               excluded_ids=(), context_factory=None):
    """Construct one complete domain through the shared automatic predicate.

    This is a trusted resolver component. Player predicates receive the existing
    detached player DTO. No candidate IDs or partition are returned to a player.
    """
    if type(source) is not Entity or r.state.entities.get(source.id) is not source:
        raise ValueError('Target preference requires the current physical source')
    if type(definition) is not CardDefinition:
        raise ValueError('Target preference requires an effective CardDefinition')
    r.registry.card(definition.id)
    if type(preference) is not AutomaticTargetPreference:
        raise ValueError('Target preference must be an explicit typed policy')
    if type(excluded_ids) is not tuple or any(type(i) is not int or i < 1 for i in excluded_ids):
        raise ValueError('Target exclusions must be an immutable tuple of identities')
    if len(set(excluded_ids)) != len(excluded_ids):
        raise ValueError('Target exclusions cannot repeat an identity')
    if any(i not in r.state.entities for i in excluded_ids):
        raise ValueError('Target exclusions contain an unknown physical identity')
    excluded = tuple(sorted(excluded_ids))
    spec = target_spec(definition)
    context = context_factory or effect_target_context(r, source)
    legal = (tuple(i for i in sorted(r.state.entities) if i not in excluded
                   and accepts_target(r.state, r.registry, source, definition, i,
                                      context_factory=context, automatic=True))
             if spec is not None else ())
    enemies = tuple(i for i in legal if r.state.entities[i].controller != source.controller)
    selected = enemies if preference is AutomaticTargetPreference.ENEMY_IF_AVAILABLE and enemies else legal
    return AutomaticTargetPartition(source.id, source.controller, definition.id, preference,
                                    spec.mode if spec is not None else None, excluded,
                                    legal, enemies, selected)


def select_automatic_target(r, source, definition, *,
                            preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE,
                            excluded_ids=()):
    """Accept one choice at the caller's current activation window.

    There is one RNG owner and one choice, including a singleton domain, matching
    existing random activation. Empty domains consume no RNG; only REQUIRED
    returns no_target. An accepted ID must not be silently reselected after wait.
    """
    partition = automatic_target_partition(r, source, definition, preference=preference,
                                           excluded_ids=excluded_ids)
    if partition.selection_ids:
        return r.game._rng.choice(partition.selection_ids), None, partition
    failure = 'no_target' if partition.mode is TargetMode.REQUIRED else None
    return None, failure, partition


@dataclass(frozen=True)
class AutomaticTargetSelection:
    partition: AutomaticTargetPartition
    target_id: int | None
    failure: str | None
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        from .whole_card_history import rng_state
        if type(self.partition) is not AutomaticTargetPartition:
            raise ValueError('Automatic selection lost its complete original target partition')
        self.partition.__post_init__(); rng_state(self.rng_before); rng_state(self.rng_after)
        if self.target_id is not None and (type(self.target_id) is not int or self.target_id < 1):
            raise ValueError('Automatic target identity must be a positive integer')
        rng = Random(0); rng.setstate(self.rng_before)
        target = rng.choice(self.partition.selection_ids) if self.partition.selection_ids else None
        failure = ('no_target' if not self.partition.selection_ids and self.partition.mode is TargetMode.REQUIRED else None)
        if (self.target_id, self.failure, self.rng_after) != (target, failure, rng.getstate()):
            raise ValueError('Automatic target or RNG differs from its one original selection')


@dataclass(frozen=True)
class AutomaticTargetProof:
    before_state: GameState
    rules: Ruleset
    effective_definition: CardDefinition
    selection: AutomaticTargetSelection
    cast_id: int
    information_json: str | None

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset
                or type(self.effective_definition) is not CardDefinition
                or type(self.selection) is not AutomaticTargetSelection
                or type(self.cast_id) is not int or self.cast_id < 1
                or self.information_json is not None and type(self.information_json) is not str):
            raise ValueError('Automatic target proof lost its complete original acceptance')
        self.selection.__post_init__(); self.rules.__post_init__()
        if self.information_json is not None and type(json.loads(self.information_json)) is not dict:
            raise ValueError('Original player target information must be a strict knowledge object')


def select_target_with_proof(r, source, definition, preference, *, excluded_ids=()):
    """The shared CAST window owns exactly one selection and its original proof."""
    information = None
    if r.registry.target_visibility(definition.target_rule) == 'player':
        r.game._information.sync(r.game)
        information = json.dumps(r.game._information.to_dict(), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    before = deepcopy(r.state)
    rng_before = r.game._rng.getstate()
    target, failure, partition = select_automatic_target(r, source, definition,
        preference=preference, excluded_ids=excluded_ids)
    selection = AutomaticTargetSelection(partition, target, failure, rng_before, r.game._rng.getstate())
    proof = AutomaticTargetProof(before, r.rules, definition, selection, len(before.cast_history) + 1, information)
    return target, failure, proof


def validate_proof(proof, registry):
    """Recompute the complete legal partition at the original host/player window."""
    proof.__post_init__()
    selection = proof.selection; state = deepcopy(proof.before_state)
    if proof.cast_id != len(state.cast_history) + 1 or state.status != 'playing':
        raise ValueError('Target proof lost its genuine pre-allocation cast window')
    source = state.entities.get(selection.partition.source_id)
    if source is None or source.card_id != proof.effective_definition.id:
        raise ValueError('Target proof lost its actual current casting carrier')
    player_predicate = registry.target_visibility(proof.effective_definition.target_rule) == 'player'
    if player_predicate != (proof.information_json is not None):
        raise ValueError('Target proof changed its original predicate visibility')
    game = SimpleNamespace(_state=state, registry=registry, ruleset=proof.rules)
    if player_predicate:
        from .information import Information
        game._information = Information.from_dict(json.loads(proof.information_json), game)
    probe = SimpleNamespace(state=state, registry=registry, game=game)
    actual = automatic_target_partition(probe, source, proof.effective_definition,
        preference=selection.partition.preference, excluded_ids=selection.partition.excluded_ids)
    if actual != selection.partition:
        raise ValueError('Automatic target partition differs from its complete original legal window')


def validate_cast_proof(proof, cast, registry):
    validate_proof(proof, registry)
    from .spell_casts import CONDITIONS, effective_definition
    from .choose_one import effective as branch_definition
    from .play_history import played_cards
    definition = registry.card(cast.card_id)
    state = proof.before_state
    actual_conditions = dict(combo=bool(played_cards(state, cast.player_id, turn=state.turn)),
        outcast=False, finale=False, quickdraw=False, manathirst=definition.manathirst is not None
        and state.players[cast.player_id].max_mana >= definition.manathirst)
    if any(getattr(cast, key) != actual_conditions[key] for key in CONDITIONS):
        raise ValueError('Automatic target proof differs from its original condition clocks')
    interval = state.owner_turn_history[-1].id if state.owner_turn_history else None
    if cast.owner_turn_id != interval:
        raise ValueError('Automatic target proof lost its original owner interval')
    expected = branch_definition(effective_definition(definition,
        {key: getattr(cast, key) for key in CONDITIONS}), cast.branch_id)
    if (proof.cast_id != cast.id or proof.effective_definition != expected
            or cast.target_selection != proof.selection or cast.source_id != proof.selection.partition.source_id
            or cast.player_id != proof.selection.partition.source_controller
            or (cast.turn, cast.action) != (proof.before_state.turn, proof.before_state.action_number)):
        raise ValueError('Automatic cast differs from its original complete target acceptance')


def selection_from_dict(value):
    def row(data, kind):
        if type(data) is not dict or set(data) != {f.name for f in fields(kind)}:
            raise ValueError('Automatic target wire fields differ from their declared type')
        return dict(data)
    data = row(value, AutomaticTargetSelection); part = row(data['partition'], AutomaticTargetPartition)
    part['preference'] = AutomaticTargetPreference(part['preference'])
    if part['mode'] is not None: part['mode'] = TargetMode(part['mode'])
    for name in ('excluded_ids', 'legal_ids', 'enemy_ids', 'selection_ids'):
        if type(part[name]) is not list: raise ValueError('Automatic target wire domain requires an array')
        part[name] = tuple(part[name])
    data['partition'] = AutomaticTargetPartition(**part)
    for name in ('rng_before', 'rng_after'):
        value = data[name]
        if type(value) is not list or len(value) != 3 or type(value[1]) is not list:
            raise ValueError('Automatic target RNG wire state requires its complete array')
        data[name] = (value[0], tuple(value[1]), value[2])
    return AutomaticTargetSelection(**data)


def register_payloads(mechanics):
    for kind in (AutomaticTargetPreference, AutomaticTargetPartition, AutomaticTargetSelection, AutomaticTargetProof, Ruleset):
        if kind not in mechanics.payload_types: mechanics.register_payload_type(kind)

