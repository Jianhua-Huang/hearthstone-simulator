"""Pure, complete plans for several distinct spell arrows in one window.

These plans are inputs to an activation consumer, not accepted plays or casts.
The consumer must bind the count policy and effective definition at its actual
window. No payment, random draw, target replacement or payload runs here.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from itertools import permutations
import json
import re

from hs_sim.targets import canonical_digest
from .allocation_facts import SourceAllocationFact
from .effects import _integer, _player
from .model import BoardPresenceReference, CardDefinition, CardType, Zone


@dataclass(frozen=True)
class SpellTargetGroupProfile:
    card_id: str
    version: str
    count: int = 2
    shortfall: str = 'reject'

    def __post_init__(self):
        from .model import _name
        _name(self.card_id, 'spell target-group card')
        _name(self.version, 'spell target-group policy')
        _integer(self.count, 'distinct spell target count', 2)
        if self.count != 2:
            raise ValueError('Current paid group consumer supports the two real spell arrows only')
        if self.shortfall not in ('reject', 'available'):
            raise ValueError('Spell target shortage requires an explicit policy')


def validate_profile(registry, profile):
    profile.__post_init__()
    card = registry.card(profile.card_id)
    from .model import TargetMode
    if (card.kind != CardType.SPELL or card.targeting is None or
            card.targeting.mode != TargetMode.REQUIRED or card.target_condition is not None or
            card.choose_one is not None or registry.target_visibility(card.target_rule) != 'builtin' or
            not set(card.targeting.zones).issubset({Zone.HERO, Zone.BOARD}) or
            not set(card.targeting.kinds).issubset({CardType.HERO, CardType.MINION})):
        raise ValueError('Paid target groups currently require a fixed ordinary spell target domain')


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
    board_presences: tuple[BoardPresenceReference, ...] = ()

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
        if (type(self.board_presences) is not tuple or any(type(x) is not BoardPresenceReference for x in self.board_presences) or
                tuple(x.entity_id for x in self.board_presences) != tuple(x.entity_id for x in self.candidates
                    if x.kind == CardType.MINION and x.zone == Zone.BOARD)):
            raise ValueError('Spell target plan lost its complete original board residences')
        for ref in self.board_presences:
            ref.__post_init__()
            if ref.presence_id >= self.source.next_order:
                raise ValueError('Spell target residence exceeds its original allocation window')

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
        state.turn, state.action_number, candidates, tuple(BoardPresenceReference.capture(state, x.entity_id)
            for x in candidates if x.kind == CardType.MINION and x.zone == Zone.BOARD))


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


def hand_plan(state, registry, source):
    profile = registry.spell_target_group_profiles.get(source.card_id)
    if profile is None:
        return None
    validate_profile(registry, profile)
    from .model import Zone
    if source.zone != Zone.HAND or source.id not in state.players[source.controller].hand:
        raise ValueError('Paid target groups require their actual owned hand source')
    plan = prepare_spell_target_group(state, registry, source.id, source.controller,
        min_count=profile.count, max_count=profile.count)
    count = min(profile.count, len(plan.candidates)) if profile.shortfall == 'available' else profile.count
    if count and count != profile.count:
        from dataclasses import replace
        plan = replace(plan, min_count=count, max_count=count)
    return plan


def hand_selection(state, registry, source, target_ids):
    plan = hand_plan(state, registry, source)
    if plan is None:
        if target_ids:
            raise ValueError('This card has no declared spell target group')
        return None
    return SpellTargetGroupSelection(plan, target_ids)


def validate_prepared(state, registry, source, selection):
    ids = () if selection is None else selection.target_ids
    expected = hand_selection(state, registry, source, ids)
    if selection != expected:
        raise ValueError('Paid spell target group differs from its actual prepayment window')


def validate_record_material(record, *, cast=False):
    group = record.spell_target_group
    if group is None:
        return
    if type(group) is not SpellTargetGroupSelection:
        raise ValueError('A paid spell group requires its typed complete original selection')
    group.__post_init__()
    plan = group.plan
    from .model import Zone
    primary = (record.spell_target_receipt.primary_target_id if cast and record.spell_target_receipt is not None else group.target_ids[0])
    if ((plan.source.entity_id, plan.source.card_id, plan.player_id, plan.turn, primary) !=
            (record.source_id, record.card_id, record.player_id, record.turn, record.target_id) or
            plan.automatic or plan.source.zone != Zone.HAND or
            (plan.action > record.action if cast else plan.action != record.action) or
            not cast and record.kind != CardType.SPELL or cast and record.origin not in ('hand', 'repeat')):
        raise ValueError('Spell group borrowed another original paid activation')


def plan_from_dict(value):
    from .serialization import _row, _list
    from .allocation_facts import allocation_from_dict
    plan = _row(value, SpellTargetGroupPlan)
    plan['source'] = allocation_from_dict(plan['source'])
    plan['candidates'] = tuple(allocation_from_dict(x) for x in _list(plan['candidates'], 'spell group candidates'))
    plan['board_presences'] = tuple(BoardPresenceReference(**_row(x, BoardPresenceReference))
        for x in _list(plan['board_presences'], 'original spell target board residences'))
    return SpellTargetGroupPlan(**plan)


def selection_from_dict(value):
    if value is None:
        return None
    from .serialization import _row, _list
    row = _row(value, SpellTargetGroupSelection)
    row['plan'] = plan_from_dict(row['plan'])
    row['target_ids'] = tuple(_list(row['target_ids'], 'original spell group target IDs'))
    return SpellTargetGroupSelection(**row)


def receipt(selection):
    return json.dumps(asdict(selection), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def note_submission(r, play):
    if play.spell_target_group is not None:
        r.emit('spell_target_group_submitted', source_id=play.source_id, player_id=play.player_id,
            play_id=play.id, selection=receipt(play.spell_target_group), _capture=False)


def validate_boundary(game):
    state, registry = game._state, game.registry
    from .allocation_facts import validate_allocation
    from .hero_health_history import effective_events
    expected = {}
    for play in state.play_history:
        group = play.spell_target_group
        profile = registry.spell_target_group_profiles.get(play.card_id)
        if (group is None) != (profile is None):
            raise ValueError('A paid spell lost or invented its declared original target group')
        if group is None:
            continue
        validate_profile(registry, profile)
        validate_record_material(play)
        count = min(profile.count, len(group.plan.candidates)) if profile.shortfall == 'available' else profile.count
        if (group.plan.min_count, group.plan.max_count) != (count, count) or count < 1 or (
                group.plan.definition_digest != canonical_digest(asdict(registry.card(play.card_id)))):
            raise ValueError('Paid spell group changed its original registered count or target domain')
        for fact in (group.plan.source, *group.plan.candidates):
            validate_allocation(state, registry, fact)
        expected[play.id] = play
    seen = set()
    for event in effective_events(game._events):
        if event.kind != 'spell_target_group_submitted':
            continue
        data = dict(event.data); play = expected.get(data.get('play_id'))
        if (play is None or play.id in seen or set(data) != {'play_id', 'selection'} or
                (event.source_id, event.player_id, event.action) != (play.source_id, play.player_id, play.action) or
                data['selection'] != receipt(play.spell_target_group)):
            raise ValueError('Paid spell group differs from its unique actual submission receipt')
        seen.add(play.id)
    if seen != set(expected):
        raise ValueError('Paid spell group lost its actual private submission fact')
    for cast in state.cast_history:
        group = cast.spell_target_group
        if registry.spell_target_group_profiles.get(cast.card_id) is not None:
            if cast.play_id is not None and group != state.play_history[cast.play_id-1].spell_target_group:
                raise ValueError('Spell CAST lost its complete accepted paid target group')
            if cast.play_id is None and group is not None:
                raise ValueError('An automatic CAST cannot invent paid target input')
        elif group is not None:
            raise ValueError('An undeclared CAST invented a spell target group')
    from .spell_group_targets import validate_boundary as validate_actual_groups
    validate_actual_groups(game)
    from .automatic_spell_groups import validate_boundary as validate_automatic_groups
    validate_automatic_groups(game)


def adjacent_target_ids(context,registry):
    """Local policy: replace the actual primary arrow, retain the other inputs.

    This is a derived execution subset, never a new group submission or CAST.
    Original receipts and the accepted adjacent slot remain its only inputs.
    """
    from .next_spell_bodies import adjacent_body_index,body_target,presence
    from .spell_group_targets import _live_fact
    from .targeting import accepts_target
    cast=context.cast;receipt=cast.spell_target_receipt
    profile=registry.spell_target_group_profiles.get(cast.card_id)
    if (profile is None or profile.count!=2 or cast.completed or cast.interrupted or
            adjacent_body_index(registry,cast)is None or
            (context.source_id,context.player_id)!=(cast.source_id,cast.player_id)):
        raise ValueError('Adjacent target vector lost its actual registered running body')
    neighbor=body_target(registry,cast);source=context.state.entities[cast.source_id]
    target=context.state.entities.get(None if neighbor is None else neighbor.entity_id)
    definition=registry.card(cast.card_id)
    if (neighbor is None or context.target_id!=neighbor.entity_id or target is None or
            presence(SourceAllocationFact.capture(context.state,target))!=presence(neighbor)or
            not accepts_target(context.state,registry,source,definition,neighbor.entity_id,automatic=False)):
        raise ValueError('Adjacent target vector changed its original valid primary neighbor')
    primary=next((i for i,f in enumerate(receipt.targets)if f is not None and f.entity_id==cast.target_id),None)
    if primary is None:raise ValueError('Adjacent target vector lost its original actual primary alias')
    result=[]
    for index,(fact,residence)in enumerate(zip(receipt.targets,receipt.presences)):
        if index==primary:current=neighbor
        else:current=None if fact is None else _live_fact(context.state,fact,residence)
        if (current is None or current.entity_id in result or
                not accepts_target(context.state,registry,source,definition,current.entity_id,automatic=False)):
            continue
        result.append(current.entity_id)
    return tuple(result)


def target_ids(context,registry=None):
    """Live deliveries of the original paid group; a re-entry is a new residence."""
    cast = context.cast
    if (cast is None or not cast.payload_started or
            cast.failure is not None or context.state.cast_history[cast.id-1] != cast):
        raise ValueError('Group target delivery requires its actual accepted physical CAST')
    if cast.spell_target_receipt is None or not cast.spell_target_receipt.closed:
        raise ValueError('Group target delivery lost its actual accepted target phase')
    if cast.next_spell_body_board is not None and cast.next_spell_body_cursor%2:
        if registry is None:raise ValueError('Grouped extra body delivery requires its original registered profile')
        from .next_spell_bodies import adjacent_body_index
        if adjacent_body_index(registry,cast)is not None:
            return adjacent_target_ids(context,registry)
    from .spell_group_targets import _live_fact
    return tuple(f.entity_id for f, presence in zip(cast.spell_target_receipt.targets, cast.spell_target_receipt.presences)
        if f is not None and _live_fact(context.state, f, presence) is not None)


def register(mechanics):
    mechanics.register_payload_type(SpellTargetGroupPlan)
    mechanics.register_payload_type(SpellTargetGroupSelection)
    from .spell_group_targets import register as register_actual_spell_groups
    register_actual_spell_groups(mechanics)
    from .automatic_spell_groups import register_payloads
    register_payloads(mechanics)
