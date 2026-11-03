"""Complete automatic spell arrows at the existing physical CAST window.

Automatic casts retain the ordinary automatic target policy: no manual target
reaction window is invented. Random arrows share one state and exclude earlier
selected identities. History can instead retain the full original residences;
native repetition reuses the accepted group without another selection.
"""
from .runtime_copy import deepcopy
from dataclasses import asdict, dataclass
import json
from random import Random
from types import SimpleNamespace

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .automatic_targets import (AutomaticTargetPreference, AutomaticTargetSelection,
    select_automatic_target, selection_from_dict, validate_preferred_source)
from .effects import _integer
from .errors import ResolutionError
from .model import BoardPresenceReference, CardType, GameState, Zone
from .rules import Ruleset
from .spell_group_targets import _facts, _presences, _live_fact
from .spell_target_groups import (SpellTargetGroupPlan, plan_from_dict,
    prepare_spell_target_group, validate_profile)
from hs_sim.targets import canonical_digest

ACCEPTED = 'automatic_spell_target_group_accepted'


@dataclass(frozen=True)
class AutomaticSpellTargets:
    cast_id: int
    plan: SpellTargetGroupPlan
    targeting: str
    submitted_ids: tuple[int | None, ...]
    targets: tuple[SourceAllocationFact | None, ...]
    presences: tuple[BoardPresenceReference | None, ...]
    selections: tuple[AutomaticTargetSelection, ...] = ()
    retained_cast_id: int | None = None
    failure: str | None = None

    def __post_init__(self):
        _integer(self.cast_id, 'automatic target group accepting cast', 1)
        if type(self.plan) is not SpellTargetGroupPlan:
            raise ValueError('Automatic spell group requires its complete original target plan')
        self.plan.__post_init__()
        if (not self.plan.automatic or self.source.zone != Zone.GRAVEYARD or
                self.source.controller != self.player_id or self.targeting not in ('random', 'explicit', 'original')):
            raise ValueError('Automatic spell group lost its actual physical cast source or target policy')
        if type(self.submitted_ids) is not tuple or any(x is not None and (type(x) is not int or x < 1)
                for x in self.submitted_ids):
            raise ValueError('Automatic spell targets require complete ordered typed input')
        count = len(self.targets)
        if not 1 <= count <= self.plan.max_count:
            raise ValueError('Automatic spell group changed its declared arrow count')
        _facts(self.targets, count); _presences(self.targets, self.presences)
        inventory = {x.entity_id:x for x in self.plan.candidates}
        residences = {x.entity_id:x for x in self.plan.board_presences}
        if any(f is not None and (inventory.get(f.entity_id) != f or p != residences.get(f.entity_id))
                for f,p in zip(self.targets,self.presences)):
            raise ValueError('Automatic spell group lost its actual candidate material or residence')
        if self.failure not in (None, 'no_target', 'invalid_target'):
            raise ValueError('Invalid automatic spell group failure')
        if self.failure == 'invalid_target' and self.targeting != 'explicit':
            raise ValueError('Only an explicit group can reject a prescribed target')
        if (not any(self.targets)) != (self.failure == 'no_target') and self.failure != 'invalid_target':
            raise ValueError('Automatic spell group failure differs from its accepted actual targets')
        if type(self.selections) is not tuple or any(type(x) is not AutomaticTargetSelection for x in self.selections):
            raise ValueError('Automatic spell group requires immutable complete selections')
        if self.targeting == 'original':
            _integer(self.retained_cast_id, 'retained complete original cast', 1)
            if self.retained_cast_id >= self.cast_id or self.selections or len(self.submitted_ids) != count:
                raise ValueError('Retained target group must refer to an earlier complete cast')
        elif self.retained_cast_id is not None:
            raise ValueError('A fresh target group cannot borrow an original cast')
        if self.targeting == 'explicit':
            if (any(x is None for x in self.submitted_ids) or len(set(self.submitted_ids)) != len(self.submitted_ids)
                    or self.selections or self.submitted_ids and len(self.submitted_ids) != count or
                    not self.submitted_ids and any(self.targets)):
                raise ValueError('Explicit automatic spell arrows require complete distinct input')
        if self.targeting == 'random':
            if self.submitted_ids or len(self.selections) != self.plan.max_count or count != self.plan.max_count:
                raise ValueError('Random automatic spell arrows lost a position or added explicit input')
            chosen = set(); previous = None; preference = None
            candidates = {x.entity_id:x for x in self.plan.candidates}
            for index, selection in enumerate(self.selections):
                selection.__post_init__(); part = selection.partition
                if index == 0: preference = part.preference
                if (part.source_id != self.source.entity_id or part.source_controller != self.player_id or
                        part.definition_id != self.source.card_id or part.preference != preference or
                        part.excluded_ids != tuple(sorted(chosen)) or
                        part.legal_ids != tuple(i for i in self.plan.target_ids if i not in chosen) or
                        previous is not None and selection.rng_before != previous.rng_after or
                        self.targets[index] != candidates.get(selection.target_id)):
                    raise ValueError('Automatic spell arrows lost their shared complete window or RNG chain')
                if selection.target_id is not None: chosen.add(selection.target_id)
                previous = selection

    @property
    def source(self): return self.plan.source

    @property
    def player_id(self): return self.plan.player_id

    @property
    def closed(self): return True

    @property
    def primary_target_id(self): return next((x.entity_id for x in self.targets if x is not None), None)


@dataclass(frozen=True)
class AutomaticSpellGroupProof:
    before_state: GameState
    rules: Ruleset
    receipt: AutomaticSpellTargets

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset or
                type(self.receipt) is not AutomaticSpellTargets):
            raise ValueError('Automatic spell group proof requires its original complete cast window')
        self.rules.__post_init__(); self.receipt.__post_init__()


def _retained(state, cast_id, card_id):
    if type(cast_id) is not int or not 1 <= cast_id <= len(state.cast_history):
        raise ValueError('Retained spell targets require their original existing cast')
    original = state.cast_history[cast_id-1]
    if original.card_id != card_id:
        raise ValueError('Retained targets borrowed another spell identity')
    if original.spell_target_receipt is not None:
        return original.spell_target_receipt.targets, original.spell_target_receipt.presences
    # A countered hand attempt still has its complete submitted physical group.
    if original.spell_target_group is not None:
        group = original.spell_target_group
        refs = {x.entity_id:x for x in group.plan.board_presences}
        return group.targets, tuple(refs.get(i) for i in group.target_ids)
    raise ValueError('Historical targeting lost the complete original spell group')


def _build(r, source, definition, targeting, submitted_ids, preference=None, retained_cast_id=None):
    profile = r.registry.spell_target_group_profiles[source.card_id]
    validate_profile(r.registry, profile)
    if definition != r.registry.card(source.card_id):
        raise ResolutionError('Automatic spell group requires its declared fixed effective domain')
    plan = prepare_spell_target_group(r.state, r.registry, source.id, source.controller,
        min_count=profile.count, max_count=profile.count, automatic=True, definition=definition)
    candidates = {x.entity_id:x for x in plan.candidates}
    refs = {x.entity_id:x for x in plan.board_presences}
    selections = []; targets = []; presences = []; failure = None
    if targeting == 'random':
        chosen = set()
        for _ in range(profile.count):
            before = r.game._rng.getstate()
            target, _, partition = select_automatic_target(r, source, definition,
                preference=preference or AutomaticTargetPreference.ANY, excluded_ids=tuple(sorted(chosen)))
            selections.append(AutomaticTargetSelection(partition, target,
                'no_target' if target is None else None, before, r.game._rng.getstate()))
            targets.append(candidates.get(target)); presences.append(refs.get(target))
            if target is not None: chosen.add(target)
    elif targeting == 'original':
        old, old_refs = _retained(r.state, retained_cast_id, source.card_id)
        submitted_ids = tuple(None if x is None else x.entity_id for x in old)
        for fact, presence in zip(old, old_refs):
            live = _live_fact(r.state, fact, presence)
            accepted = live if live is not None and live.entity_id in candidates else None
            targets.append(accepted); presences.append(presence if accepted is not None else None)
    else:
        available = min(profile.count, len(plan.candidates)) if profile.shortfall == 'available' else profile.count
        if submitted_ids and len(submitted_ids) != available:
            raise ResolutionError('Explicit multi-target cast requires every declared arrow')
        for target in submitted_ids or (None,)*profile.count:
            targets.append(candidates.get(target)); presences.append(refs.get(target))
        if submitted_ids and any(x is None for x in targets): failure = 'invalid_target'
    if failure is None and not any(targets): failure = 'no_target'
    return AutomaticSpellTargets(len(r.state.cast_history)+1, plan, targeting, submitted_ids,
        tuple(targets), tuple(presences), tuple(selections), retained_cast_id, failure)


def accept(r, source, definition, effect, *, retained_cast_id=None):
    submitted = effect.target_ids
    if retained_cast_id is None and effect.targeting == 'explicit' and effect.target_id is not None and not submitted:
        raise ResolutionError('A scalar target cannot replace a complete automatic spell group')
    before = deepcopy(r.state)
    receipt = _build(r, source, definition, 'original' if retained_cast_id is not None else effect.targeting,
        submitted, getattr(effect, 'target_preference', None), retained_cast_id)
    return receipt, AutomaticSpellGroupProof(before, r.rules, receipt)


def validate_proof(proof, registry):
    proof.__post_init__(); value = proof.receipt; state = proof.before_state
    if (state.status != 'playing' or value.cast_id != len(state.cast_history)+1 or
            (value.plan.turn, value.plan.action) != (state.turn, state.action_number)):
        raise ValueError('Automatic spell group proof lost its actual pre-allocation cast window')
    source = state.entities.get(value.source.entity_id)
    if source is None or SourceAllocationFact.capture(state, source) != value.source:
        raise ValueError('Automatic spell group changed its original physical carrier')
    rng = Random(0)
    if value.selections: rng.setstate(value.selections[0].rng_before)
    probe = SimpleNamespace(state=state, registry=registry, rules=proof.rules,
        game=SimpleNamespace(_rng=rng, ruleset=proof.rules))
    preference = value.selections[0].partition.preference if value.selections else None
    expected = _build(probe, source, registry.card(source.card_id), value.targeting,
        value.submitted_ids, preference, value.retained_cast_id)
    if expected != value:
        raise ValueError('Automatic spell group differs from its complete original target acceptance')


def validate_material(record):
    value = record.spell_target_receipt
    if type(value) is not AutomaticSpellTargets:
        raise ValueError('Automatic spell group requires its typed complete target receipt')
    value.__post_init__()
    native = record.origin == 'native_repeat'
    root = record.recast_id if native else record.id
    if (record.play_id is not None or record.spell_target_group is not None or record.target_selection is not None or
            record.origin not in ('effect', 'draw', 'history', 'native_repeat') or value.cast_id != root or
            (value.source.entity_id, value.source.card_id, value.player_id, value.primary_target_id, value.failure) !=
            (record.source_id, record.card_id, record.player_id, record.target_id, record.failure) or
            not native and (value.plan.turn, value.plan.action) != (record.turn, record.action) or
            value.retained_cast_id is not None and (record.origin not in ('history', 'native_repeat') or
                not native and value.retained_cast_id != record.recast_id)):
        raise ValueError('Automatic spell group borrowed another actual physical CAST')


def validate_finish(proof, record, registry, state=None):
    value = record.spell_target_receipt
    if type(value) is not AutomaticSpellTargets or record.origin == 'native_repeat':
        if proof is not None: raise ValueError('CAST borrowed an unrelated automatic group proof')
        return
    if type(proof) is not AutomaticSpellGroupProof or proof.receipt != value:
        raise ValueError('Automatic target group lost its one original Finish proof')
    validate_proof(proof, registry)
    before = proof.before_state
    from .spell_casts import CONDITIONS, automatic_conditions
    definition = registry.card(record.card_id)
    conditions = automatic_conditions(before, definition, record.player_id)
    if any(getattr(record, key) != conditions[key] for key in CONDITIONS):
        raise ValueError('Automatic spell group changed its original cast conditions')
    interval = before.owner_turn_history[-1].id if before.owner_turn_history else None
    if record.owner_turn_id != interval:
        raise ValueError('Automatic spell group changed its original owner interval')
    if value.selections:
        validate_preferred_source(value.selections[0].partition.preference, record.caster_id, before)
    if state is not None:
        from .spell_acceptance import _bind_prefix_and_references
        _bind_prefix_and_references(before, state, registry)
        from .spell_casts import bind_cast_prefix
        bind_cast_prefix(before, state)


def _encoded(codec, value):
    return json.dumps(codec.encode(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def note(r, record):
    if type(record.spell_target_receipt) is AutomaticSpellTargets:
        from .continuations import FrameCodec
        r.emit(ACCEPTED, source_id=record.source_id, player_id=record.player_id, target_id=record.target_id,
            cast_id=record.id, receipt=_encoded(FrameCodec(r.game.mechanics, r.registry), record.spell_target_receipt),
            _capture=False)


def validate_boundary(game):
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    codec = FrameCodec(game.mechanics, game.registry); seen = set()
    for event in effective_events(game._events):
        if event.kind != ACCEPTED: continue
        data = dict(event.data); cast_id = data.get('cast_id')
        if type(cast_id) is not int or not 1 <= cast_id <= len(game._state.cast_history):
            raise ValueError('Automatic group receipt refers to an absent actual CAST')
        record = game._state.cast_history[cast_id-1]
        if (cast_id in seen or set(data) != {'cast_id', 'receipt'} or record.origin == 'native_repeat' or
                type(record.spell_target_receipt) is not AutomaticSpellTargets or
                _encoded(codec, record.spell_target_receipt) != data['receipt'] or
                event.sequence <= record.recorded_event or
                (event.source_id, event.player_id, event.target_id, event.action) !=
                (record.source_id, record.player_id, record.target_id, record.action)):
            raise ValueError('Automatic target group lost its unique original private acceptance event')
        seen.add(cast_id)
    expected = set()
    for record in game._state.cast_history:
        profile = game.registry.spell_target_group_profiles.get(record.card_id)
        if record.play_id is not None: continue
        value = record.spell_target_receipt
        if (value is None) != (profile is None):
            raise ValueError('An automatic CAST lost or invented its declared complete target group')
        if value is None: continue
        validate_material(record); validate_profile(game.registry, profile)
        if ((value.plan.min_count, value.plan.max_count) != (profile.count, profile.count) or
                value.plan.definition_digest != canonical_digest(asdict(game.registry.card(record.card_id)))):
            raise ValueError('Automatic target group changed its registered arrow count')
        for fact in (value.source, *value.plan.candidates, *value.targets):
            if fact is not None: validate_allocation(game._state, game.registry, fact)
        if record.origin == 'native_repeat':
            parent = game._state.cast_history[record.recast_id-1]
            if value != parent.spell_target_receipt:
                raise ValueError('Native repetition changed its accepted complete original targets')
        else: expected.add(record.id)
    if seen != expected:
        raise ValueError('Automatic CAST groups and actual acceptance facts differ')


def receipt_from_dict(value):
    if value is None or 'play_id' in value:
        from .spell_group_targets import receipt_from_dict as paid
        return paid(value)
    from .serialization import _row, _list
    row = _row(value, AutomaticSpellTargets); row['plan'] = plan_from_dict(row['plan'])
    row['submitted_ids'] = tuple(_list(row['submitted_ids'], 'automatic group input'))
    row['targets'] = tuple(None if x is None else allocation_from_dict(x)
        for x in _list(row['targets'], 'actual automatic targets'))
    row['presences'] = tuple(None if x is None else BoardPresenceReference(**_row(x, BoardPresenceReference))
        for x in _list(row['presences'], 'automatic target residences'))
    row['selections'] = tuple(selection_from_dict(x) for x in _list(row['selections'], 'automatic group selections'))
    return AutomaticSpellTargets(**row)


def register_payloads(mechanics):
    for kind in (AutomaticSpellTargets, AutomaticSpellGroupProof): mechanics.register_payload_type(kind)
