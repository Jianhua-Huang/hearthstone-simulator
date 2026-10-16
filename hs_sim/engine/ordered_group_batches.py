"""Whole ordered group roots and their independently accepted entry children.

This unexecuted draft uses an explicit internal member/extra ordering policy.
All child quantities and strengths keep their existing later acceptance windows.
"""
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
import json

from .effects import Effect, _integer
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import GameState
from .ordered_summon_groups import (GroupSummonEntryLink, OrderedGroupMember,
    OrderedGroupSelection, OrderedSummonGroupSpec, SelectedGroupOccurrence,
    from_dict as value_from_dict, select, validate_selection)
from .producer_amounts import (AcceptedProducerAmount, capture_group,
    validate as validate_amount)
from .summon_quantities import (SummonByCard, SummonCause, SummonEntryMaterial,
    accept as accept_entry, validate_cause, validate_material)


@dataclass(frozen=True)
class SummonOrderedGroup(Effect):
    group: OrderedSummonGroupSpec
    producer_profile_id: str | None = None
    bonus_effects: bool = False

    def __post_init__(self):
        if type(self.group) is not OrderedSummonGroupSpec:
            raise ValueError('A whole group requires its complete ordered request')
        self.group.__post_init__()
        if type(self.bonus_effects) is not bool:
            raise ValueError('Whole group bonus policy requires bool')
        if self.producer_profile_id is not None and (type(self.producer_profile_id) is not str or not self.producer_profile_id):
            raise ValueError('Whole group amount requires an explicit named logical profile')


def request_profile(registry, request):
    if request.producer_profile_id is None:
        return None
    profile = registry.summon_producer_profile(request.producer_profile_id)
    if profile.mode != 'ordered_board_group':
        raise ValueError('Whole group requires its own explicit logical producer mode')
    return profile


def validate_request(state, registry, request, *, closed=False):
    request.__post_init__()
    request_profile(registry, request)
    validate_cause(state, registry, request.group.cause, closed=closed)
    for member in request.group.members:
        validate_material(registry, member.material)


@dataclass(frozen=True)
class OrderedGroupRecord:
    id: int
    event_cursor: int
    turn: int
    action: int
    request: SummonOrderedGroup
    selection: OrderedGroupSelection
    producer_amount: AcceptedProducerAmount | None = None
    entry_root_ids: tuple[int, ...] = ()
    status: str = 'active'
    bonus_receipts: tuple = ()

    def __post_init__(self):
        for name in ('id', 'turn'):
            _integer(getattr(self, name), 'Whole group acceptance ' + name, 1)
        for name in ('event_cursor', 'action'):
            _integer(getattr(self, name), 'Whole group acceptance ' + name, 0)
        if type(self.request) is not SummonOrderedGroup or type(self.selection) is not OrderedGroupSelection:
            raise ValueError('Whole group must keep its typed original request and selection')
        self.request.__post_init__()
        self.selection.__post_init__()
        if self.selection.spec != self.request.group:
            raise ValueError('Whole group selection borrowed another original request')
        if (self.request.producer_profile_id is None) != (self.producer_amount is None):
            raise ValueError('Whole group lost or borrowed its accepted logical amount')
        additional = 0
        fact = self.producer_amount
        if fact is not None:
            if type(fact) is not AcceptedProducerAmount:
                raise ValueError('Typed whole group amount fact required')
            fact.__post_init__()
            if (fact.family != 'ordered_group' or fact.profile.id != self.request.producer_profile_id or
                    fact.base_count != len(self.request.group.members) or fact.cause != self.request.group.cause or
                    fact.recipient_id != self.request.group.player_id or
                    (fact.batch_id, fact.event_cursor, fact.turn, fact.action) !=
                    (self.id, self.event_cursor, self.turn, self.action)):
                raise ValueError('Whole group amount changed family, request or original window')
            additional = fact.total - fact.base_count
        if self.selection.additional != additional:
            raise ValueError('Whole group extras differ from their original accepted amount')
        if type(self.entry_root_ids) is not tuple or len(self.entry_root_ids) > len(self.selection.occurrences):
            raise ValueError('Complete typed actual group child prefix required')
        for child in self.entry_root_ids:
            _integer(child, 'Actual whole group child', 1)
        if list(self.entry_root_ids) != sorted(set(self.entry_root_ids)):
            raise ValueError('Repeated or reordered whole group child identities')
        if self.status not in ('active', 'completed', 'interrupted'):
            raise ValueError('Unknown whole group root status')
        if self.status == 'completed' and len(self.entry_root_ids) != len(self.selection.occurrences):
            raise ValueError('Completed whole group omitted an original owed occurrence')


@dataclass(frozen=True)
class StartOrderedGroupEntry(Effect):
    group_id: int
    index: int

    def __post_init__(self):
        _integer(self.group_id, 'Whole group start identity', 1)
        _integer(self.index, 'Whole group start index', 0)


@dataclass(frozen=True)
class FinishOrderedGroup(Effect):
    group_id: int

    def __post_init__(self):
        _integer(self.group_id, 'Whole group finish identity', 1)


CONTROL = (StartOrderedGroupEntry, FinishOrderedGroup)


def record(state, group_id):
    value = next((root for root in state.ordered_group_history if root.id == group_id), None)
    if value is None:
        raise ValueError('Unknown whole ordered group root')
    return value


def update(state, old, **changes):
    value = replace(old, **changes)
    state.ordered_group_history[state.ordered_group_history.index(old)] = value
    return value


def emit(r, kind, root):
    r.emit(kind, source_id=root.request.group.cause.source.entity_id,
        player_id=root.request.group.player_id,
        amount=len(root.selection.occurrences) if kind == 'ordered_group_accepted' else len(root.entry_root_ids),
        group_id=root.id, root=json.dumps(asdict(root), ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        _capture=False)


def child_request(root, index):
    member = root.selection.occurrences[index]
    return SummonByCard(root.request.group.player_id, (member.material,), root.request.group.cause,
        position=member.position, capacity='preselected_attempt', producer_link=GroupSummonEntryLink(root.id, index))


def accept(r, effect):
    validate_request(r.state, r.registry, effect)
    if len(effect.group.members) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Original whole group exceeds engineering budget')
    amount = capture_group(r, effect)
    count = len(effect.group.members) if amount is None else amount.total
    if count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Derived whole group exceeds engineering budget')
    additional = 0 if amount is None else amount.total - amount.base_count
    selection = select(r.registry, effect.group, additional, r.game._rng)
    root = OrderedGroupRecord(r.state.next_ordered_group_id, len(r.game._events), r.state.turn,
                              r.state.action_number, effect, selection, amount)
    r.state.next_ordered_group_id += 1
    r.state.ordered_group_history.append(root)
    emit(r, 'ordered_group_accepted', root)
    return ((StartOrderedGroupEntry(root.id, 0),) if selection.occurrences else ()) + (FinishOrderedGroup(root.id),)


def start_entry(r, effect):
    root = record(r.state, effect.group_id)
    if root.status != 'active' or effect.index != len(root.entry_root_ids) or effect.index >= len(root.selection.occurrences):
        raise ResolutionError('Out-of-order whole group child acceptance')
    if root.entry_root_ids and next(c for c in r.state.card_summon_history if c.id == root.entry_root_ids[-1]).status == 'active':
        raise ResolutionError('Whole group child preceded completion of the previous child')
    continuation = accept_entry(r, child_request(root, effect.index))
    child_id = r.state.card_summon_history[-1].id
    update(r.state, root, entry_root_ids=(*root.entry_root_ids, child_id))
    if effect.index + 1 < len(root.selection.occurrences):
        continuation = (*continuation, StartOrderedGroupEntry(root.id, effect.index + 1))
    return continuation


def finish(r, effect):
    root = record(r.state, effect.group_id)
    if root.status != 'active' or len(root.entry_root_ids) != len(root.selection.occurrences):
        raise ResolutionError('Whole group Finish omitted owed original occurrences')
    if any(next(c for c in r.state.card_summon_history if c.id == i).status == 'active' for i in root.entry_root_ids):
        raise ResolutionError('Whole group Finish preceded child completion')
    if root.request.bonus_effects:
        from .group_bonus import reward_next
        reward = reward_next(r, root)
        if reward is not None:
            return reward
    emit(r, 'ordered_group_finished', update(r.state, root, status='completed'))


def interrupt(r):
    for root in tuple(r.state.ordered_group_history):
        if root.status == 'active':
            emit(r, 'ordered_group_finished', update(r.state, root, status='interrupted'))


def validate_link(state, child, *, closed=False):
    link = child.request.producer_link
    if type(link) is not GroupSummonEntryLink:
        raise ValueError('Typed distinct whole group child link required')
    link.__post_init__()
    if link.group_id >= state.next_ordered_group_id:
        raise ValueError('Future whole group child link')
    parent = next((root for root in state.ordered_group_history if root.id == link.group_id), None)
    if parent is None:
        if closed:
            return
        raise ValueError('Whole group child lost its original parent')
    if (link.index >= len(parent.entry_root_ids) or parent.entry_root_ids[link.index] != child.id or
            child.request != child_request(parent, link.index)):
        raise ValueError('Child borrowed another group, occurrence, recipient, cause or recipe')


def validate_record(state, registry, root, *, closed=False, children=None):
    root.__post_init__()
    validate_request(state, registry, root.request, closed=closed)
    validate_selection(registry, root.selection)
    if root.id >= state.next_ordered_group_id or root.turn > state.turn or root.action > state.action_number:
        raise ValueError('Future whole group acceptance')
    cause = root.request.group.cause
    if cause.turn > root.turn or cause.action > root.action:
        raise ValueError('Whole group cause is newer than its original root')
    fact = root.producer_amount
    if fact is not None:
        validate_amount(registry, fact)
        if (fact.next_entity_id > state.next_entity_id or fact.next_attachment_id > state.next_attachment_id or
                fact.next_order > state.next_order):
            raise ValueError('Whole group amount carries future original allocation counters')
    if not closed and root.status == 'interrupted' and state.status == 'playing':
        raise ValueError('Playing whole group cannot be terminal interrupted')
    children = {c.id: c for c in state.card_summon_history} if children is None else children
    for index, child_id in enumerate(root.entry_root_ids):
        child = children.get(child_id)
        if child is None or child.request != child_request(root, index) or child.event_cursor <= root.event_cursor:
            raise ValueError('Whole group lost or changed an actual original child window')
    from .group_bonus import validate as validate_bonus
    validate_bonus(root, state, closed=closed, children=children)


def validate_history(state, registry):
    _integer(state.next_ordered_group_id, 'Next whole group root', 1)
    if type(state.ordered_group_history) is not list:
        raise ValueError('Typed complete whole group history required')
    for root in state.ordered_group_history:
        if type(root) is not OrderedGroupRecord:
            raise ValueError('Typed whole group record required')
        validate_record(state, registry, root)
    ids = [root.id for root in state.ordered_group_history]
    if ids != sorted(set(ids)):
        raise ValueError('Whole group root identities are repeated or reordered')


def validate_queue(state, registry, queue):
    from .summon_quantities import FinishCardSummon
    for work in queue:
        if type(work) in CONTROL and record(state, work.group_id).status != 'active':
            raise ValueError('Settled or orphan whole group control')
    for root in state.ordered_group_history:
        controls = [w for w in queue if type(w) in CONTROL and w.group_id == root.id]
        if root.status != 'active':
            if controls:
                raise ValueError('Completed whole group retains owed control')
            continue
        expected = ((StartOrderedGroupEntry(root.id, len(root.entry_root_ids)),)
                    if len(root.entry_root_ids) < len(root.selection.occurrences) else ()) + (FinishOrderedGroup(root.id),)
        if tuple(controls) != expected:
            raise ValueError('Whole group lost or changed its complete owed continuation')
        if root.entry_root_ids:
            child = next(c for c in state.card_summon_history if c.id == root.entry_root_ids[-1])
            if child.status == 'active':
                tail = next((w for w in queue if type(w) is FinishCardSummon and w.root_id == child.id), None)
                if tail is None or queue.index(tail) > queue.index(controls[0]):
                    raise ValueError('Whole group advances before its current child Finish')


def reject_choice_control(options):
    from .summon_quantities import walk_work
    if any(type(w) in CONTROL for w in walk_work(options)):
        raise ValueError('Choice cannot inject whole group control')


def validate_frame_references(state, registry, value):
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item, scope, depth):
        if depth > FrameCodec.MAX_DEPTH:
            raise ValueError('Whole group frame depth exceeded')
        if type(item) is SummonOrderedGroup:
            validate_request(scope, registry, item)
            return
        if type(item) is SummonCause:
            validate_cause(scope, registry, item)
            return
        if type(item) is OrderedGroupSelection:
            validate_selection(registry, item)
            validate_cause(scope, registry, item.spec.cause)
            return
        if type(item) in CONTROL:
            if record(scope, item.group_id).status != 'active':
                raise ValueError('Stale whole group control')
            return
        if type(item) is RuleContext:
            for field in fields(item):
                if field.name != 'state':
                    visit(getattr(item, field.name), item.state, depth + 1)
            return
        if type(item) is PaidHandChoiceBoundaryProof:
            validate_queue(item.state, registry, item.work)
            visit(item.work, item.state, depth + 1)
            return
        if type(item) is GameState:
            return
        if type(item) in (tuple, list):
            for child in item:
                visit(child, scope, depth + 1)
        elif is_dataclass(item):
            for field in fields(item):
                visit(getattr(item, field.name), scope, depth + 1)
    visit(value, state, 0)


def validate_boundary(game):
    frame = game._frame
    queue = (*frame.prefix, *frame.continuation) if frame else ()
    validate_queue(game._state, game.registry, queue)
    if frame:
        reject_choice_control(frame.options)
        validate_frame_references(game._state, game.registry, frame)
        proof = frame.paid_hand_choice_boundary
        if proof.state.ordered_group_history != game._state.ordered_group_history:
            raise ValueError('Whole group history differs from its complete choice boundary')
        controls = lambda work: tuple(w for w in work if type(w) in CONTROL)
        if controls(queue) != controls(proof.work):
            raise ValueError('Whole group changed its original owed choice continuation')


def validate_closed_events(game):
    from .summon_quantities import CardSummonRecord, from_dict as child_from_dict
    state, registry, events = game._state, game.registry, game._events
    children = {c.id: c for c in state.card_summon_history}
    for event in events:
        if event.kind == 'card_summon_accepted':
            child = child_from_dict(CardSummonRecord, json.loads(dict(event.data)['root']))
            children.setdefault(child.id, child)
    current = {root.id: root for root in state.ordered_group_history}
    accepted, closed, rewarded = {}, {}, {}
    for event in events:
        if event.kind not in ('ordered_group_accepted', 'ordered_group_finished', 'ordered_group_rewarded'):
            continue
        data = dict(event.data)
        if set(data) != {'group_id', 'root'} or type(data['root']) is not str:
            raise ValueError('Complete private original whole group event required')
        root = from_dict(OrderedGroupRecord, json.loads(data['root']))
        validate_record(state, registry, root, closed=True, children=children)
        if (data['group_id'] != root.id or root.action > event.action or root.event_cursor >= event.sequence or
                (event.source_id, event.player_id) != (root.request.group.cause.source.entity_id, root.request.group.player_id)):
            raise ValueError('Whole group event changed original producer and event window')
        if event.kind == 'ordered_group_accepted':
            if (root.id in accepted or root.status != 'active' or root.entry_root_ids or root.bonus_receipts or
                    root.event_cursor != event.sequence - 1 or event.amount != len(root.selection.occurrences)):
                raise ValueError('Duplicate or invalid original whole group acceptance')
            accepted[root.id] = root
        elif event.kind == 'ordered_group_rewarded':
            previous = rewarded.get(root.id)
            prefix = () if previous is None else previous.bonus_receipts
            if (root.status != 'active' or not root.request.bonus_effects or root.id in closed or
                    len(root.entry_root_ids) != len(root.selection.occurrences) or
                    len(root.bonus_receipts) != len(prefix) + 1 or root.bonus_receipts[:-1] != prefix or
                    event.amount != len(root.entry_root_ids) or
                    replace(root, entry_root_ids=(), bonus_receipts=(), status='active') != accepted.get(root.id) or
                    previous is not None and root.entry_root_ids != previous.entry_root_ids):
                raise ValueError('Whole group changed or duplicated its original bonus prefix')
            rewarded[root.id] = root
        else:
            if (root.id in closed or root.status == 'active' or event.amount != len(root.entry_root_ids) or
                    replace(root, entry_root_ids=(), bonus_receipts=(), status='active') != accepted.get(root.id) or
                    root.bonus_receipts != (() if root.id not in rewarded else rewarded[root.id].bonus_receipts)):
                raise ValueError('Whole group close changed the original plan or selection')
            closed[root.id] = root
        if root.id not in current and not any(e.kind == 'timeline_rewound' and e.sequence > event.sequence and
                type(dict(e.data).get('event_start')) is int and dict(e.data)['event_start'] <= root.event_cursor for e in events):
            raise ValueError('Whole group vanished without a later actual Retry')
    for root in current.values():
        if (replace(root, entry_root_ids=(), bonus_receipts=(), status='active') != accepted.get(root.id) or
                root.bonus_receipts != (() if root.id not in rewarded else rewarded[root.id].bonus_receipts) or
                root.status != 'active' and closed.get(root.id) != root):
            raise ValueError('Current whole group differs from its original private event proof')
    parents = {**closed, **current}
    for child in children.values():
        link = child.request.producer_link
        if type(link) is not GroupSummonEntryLink:
            continue
        parent = parents.get(link.group_id)
        if parent is None or link.index >= len(parent.entry_root_ids) or parent.entry_root_ids[link.index] != child.id:
            raise ValueError('Actual whole group child lost complete original parent ownership')


def from_dict(cls, value):
    from .serialization import _list, _row
    from .producer_amounts import from_dict as amount_from_dict
    if cls is SummonOrderedGroup:
        row = _row(value, cls)
        row['group'] = value_from_dict(OrderedSummonGroupSpec, row['group'])
    elif cls is OrderedGroupRecord:
        row = _row(value, cls)
        row['request'] = from_dict(SummonOrderedGroup, row['request'])
        row['selection'] = value_from_dict(OrderedGroupSelection, row['selection'])
        row['producer_amount'] = None if row['producer_amount'] is None else amount_from_dict(row['producer_amount'])
        row['entry_root_ids'] = tuple(_list(row['entry_root_ids'], 'Whole group child prefix'))
        from .group_bonus import from_dict as bonus_from_dict
        row['bonus_receipts'] = tuple(bonus_from_dict(x) for x in _list(row['bonus_receipts'], 'Original group bonus prefix'))
    else:
        raise ValueError('Unknown whole group record codec type')
    return cls(**row)


def rows_from_dict(value):
    from .serialization import _list
    value['ordered_group_history'] = [from_dict(OrderedGroupRecord, x)
                                    for x in _list(value['ordered_group_history'], 'Whole group history')]


def register(mechanics):
    from .group_bonus import GroupBonusFact
    mechanics.register_payload_type(GroupBonusFact)
    for cls in (OrderedGroupMember, OrderedSummonGroupSpec, SelectedGroupOccurrence,
                OrderedGroupSelection, GroupSummonEntryLink, OrderedGroupRecord):
        mechanics.register_payload_type(cls)
    for cls, handler in ((SummonOrderedGroup, accept), (StartOrderedGroupEntry, start_entry), (FinishOrderedGroup, finish)):
        mechanics.register(cls, handler)
