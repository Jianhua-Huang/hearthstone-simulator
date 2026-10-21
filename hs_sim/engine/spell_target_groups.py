"""Pure, complete plans for several distinct spell arrows in one window.

These plans are inputs to an activation consumer, not accepted plays or casts.
The consumer must bind the count policy and effective definition at its actual
window. No payment, random draw, target replacement or payload runs here.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from itertools import permutations
import re

from hs_sim.targets import canonical_digest
from .allocation_facts import SourceAllocationFact
from .effects import _integer, _player
from .model import CardDefinition, CardType


@dataclass(frozen=True)
class SpellTargetGroupPlan:
    source: SourceAllocationFact
    player_id: int
    definition_digest: str
    min_count: int
    max_count: int
    automatic: bool
    turn: int
    action: int
    candidates: tuple[SourceAllocationFact, ...]

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact:
            raise ValueError('Spell arrows require their original physical source')
        self.source.__post_init__()
        _player(self.player_id)
        _integer(self.min_count, 'minimum spell arrows', 1)
        _integer(self.max_count, 'maximum spell arrows', self.min_count)
        _integer(self.turn, 'original spell target turn', 1)
        _integer(self.action, 'original spell target action', 0)
        if (self.source.kind != CardType.SPELL or type(self.automatic) is not bool or
                not self.automatic and self.player_id != self.source.controller):
            raise ValueError('Manual spell arrows require the actual physical controller')
        if type(self.definition_digest) is not str or not re.fullmatch('[0-9a-f]{64}', self.definition_digest):
            raise ValueError('Spell arrows require the complete effective definition digest')
        if type(self.candidates) is not tuple or any(type(x) is not SourceAllocationFact for x in self.candidates):
            raise ValueError('Spell arrows require an immutable complete candidate inventory')
        ids = []
        for fact in self.candidates:
            fact.__post_init__()
            if (fact.next_entity_id, fact.next_order) != (self.source.next_entity_id, self.source.next_order):
                raise ValueError('Spell arrows borrowed another allocation window')
            ids.append(fact.entity_id)
        if ids != sorted(set(ids)):
            raise ValueError('Spell target inventory must be unique and ordered')

    @property
    def target_ids(self):
        return tuple(x.entity_id for x in self.candidates)


@dataclass(frozen=True)
class SpellTargetGroupSelection:
    plan: SpellTargetGroupPlan
    target_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.plan) is not SpellTargetGroupPlan:
            raise ValueError('Spell selection requires its complete original plan')
        self.plan.__post_init__()
        if type(self.target_ids) is not tuple:
            raise ValueError('Spell arrows require an immutable ordered target vector')
        for target in self.target_ids:
            _integer(target, 'spell arrow target', 1)
        if (not self.plan.min_count <= len(self.target_ids) <= self.plan.max_count or
                len(set(self.target_ids)) != len(self.target_ids) or
                not set(self.target_ids) <= set(self.plan.target_ids)):
            raise ValueError('Spell selection violates its original count, domain or distinctness')

    @property
    def targets(self):
        by_id = {x.entity_id: x for x in self.plan.candidates}
        return tuple(by_id[i] for i in self.target_ids)


def prepare_spell_target_group(state, registry, source_id, player_id, *, min_count, max_count,
                               automatic=False, definition=None, context_factory=None):
    """Read the whole shared target domain once; no per-arrow state advances.

    Counts and an optional effective definition are trusted producer inputs.
    They are deliberately not inferred from card text or the available count.
    Manual protections and automatic eligibility remain in accepts_target.
    """
    from .targeting import accepts_target, effective_target_spec
    _integer(source_id, 'physical spell source', 1)
    _player(player_id)
    _integer(min_count, 'minimum spell arrows', 1)
    _integer(max_count, 'maximum spell arrows', min_count)
    if type(automatic) is not bool:
        raise ValueError('Spell arrow activation mode must be explicit')
    source = state.entities.get(source_id)
    if source is None or source.kind != CardType.SPELL:
        raise ValueError('Spell target planning requires an existing physical spell')
    original = registry.card(source.card_id)
    definition = original if definition is None else definition
    if (type(definition) is not CardDefinition or
            (definition.id, definition.kind) != (source.card_id, CardType.SPELL)):
        raise ValueError('Spell target planning borrowed another effective definition')
    if not automatic and source.controller != player_id:
        raise ValueError('A manual target group cannot borrow another controller')
    actor = deepcopy(source)
    actor.controller = player_id
    if effective_target_spec(state, registry, actor, definition) is None:
        raise ValueError('A targetless spell cannot acquire invented arrows')
    candidates = tuple(SourceAllocationFact.capture(state, state.entities[i])
        for i in sorted(state.entities) if accepts_target(state, registry, actor, definition, i,
            context_factory=context_factory, automatic=automatic))
    return SpellTargetGroupPlan(SourceAllocationFact.capture(state, source), player_id,
        canonical_digest(asdict(definition)), min_count, max_count, automatic,
        state.turn, state.action_number, candidates)


def spell_target_group_selections(plan):
    """Lazy ordered submissions; every arrow is distinct within this one group."""
    if type(plan) is not SpellTargetGroupPlan:
        raise ValueError('Spell group enumeration requires its complete typed plan')
    plan.__post_init__()
    for count in range(plan.min_count, min(plan.max_count, len(plan.candidates)) + 1):
        for ids in permutations(plan.target_ids, count):
            yield SpellTargetGroupSelection(plan, ids)


def validate_spell_target_group(state, registry, selection, source_id, player_id, *, min_count,
                                max_count, automatic=False, definition=None, context_factory=None):
    """Recompute in the original window using independent producer inputs.

    Never validate a historical accepted group against a later changed board.
    Shape alone cannot certify that a supplied inventory was complete.
    """
    if type(selection) is not SpellTargetGroupSelection:
        raise ValueError('Spell group validation requires its typed original submission')
    selection.__post_init__()
    expected = prepare_spell_target_group(state, registry, source_id, player_id,
        min_count=min_count, max_count=max_count, automatic=automatic,
        definition=definition, context_factory=context_factory)
    if selection.plan != expected:
        raise ValueError('Spell group differs from its actual complete original window')
    return selection
