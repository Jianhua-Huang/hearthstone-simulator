"""Nonmoving original-hand deadlines, counted by genuine owner natural ends.

The clock, guarded card identity and non-death removal remain shared. Private
acceptance receipts are not player events; only remaining end counts are shown.
"""
from dataclasses import dataclass, fields, is_dataclass, replace

from .effects import Effect, Summon, _integer, _player, _source
from .errors import ResolutionError
from .model import GameState, Zone
from .nondeath_removal import RemoveFromGame, remove_from_game
from .zones import CardReference, HAND_TYPES, DestroyStoredCard, DiscardCard, destruction_result


@dataclass(frozen=True)
class ScheduleHandRemoval(Effect):
    player_id: int
    owner_ends: int
    source_id: int | None = None
    retirement: str = 'remove'
    cards: tuple[CardReference, ...] | None = None

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.owner_ends, 'hand deadline owner ends', 1)
        _source(self.source_id)
        if self.retirement not in ('remove', 'destroy', 'discard_copy'):
            raise ValueError('Unknown hand deadline retirement')
        if self.retirement == 'discard_copy' and (self.source_id is None or self.cards is None or len(self.cards) != 1):
            raise ValueError('Discard-copy deadline requires one explicit hand card and its minion source')
        if self.cards is not None:
            if type(self.cards) is not tuple or any(type(card) is not CardReference for card in self.cards):
                raise ValueError('Bound hand deadline needs immutable physical references')
            for card in self.cards:
                card.__post_init__()
                if card.zone != Zone.HAND or card.player_id != self.player_id:
                    raise ValueError('Bound deadline references require the original target hand')
            if len({card.entity_id for card in self.cards}) != len(self.cards):
                raise ValueError('Bound hand deadline cannot repeat a physical target')


@dataclass(frozen=True)
class HandDeadlineRecord:
    id: int
    request: ScheduleHandRemoval
    targets: tuple[CardReference, ...]
    source_card_id: str | None
    turn: int
    action: int
    owner_ends_at_accept: int
    created_event: int
    owner_end_event: int | None = None
    removal_event: int | None = None
    expired_event: int | None = None
    removed: tuple[int, ...] = ()
    destruction_started_event: int | None = None
    destruction_cursor: int = 0
    destruction_events: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.request) is not ScheduleHandRemoval:
            raise ValueError('Hand deadline requires its original typed request')
        self.request.__post_init__()
        for name in ('id', 'turn', 'created_event'):
            _integer(getattr(self, name), name, 1)
        for name in ('action', 'owner_ends_at_accept'):
            _integer(getattr(self, name), name, 0)
        if (self.request.source_id is None) != (self.source_card_id is None):
            raise ValueError('Hand deadline lost its original source face')
        if self.source_card_id is not None and (type(self.source_card_id) is not str or not self.source_card_id):
            raise ValueError('Hand deadline needs a known source face')
        if type(self.targets) is not tuple or any(type(t) is not CardReference for t in self.targets):
            raise ValueError('Hand deadline needs immutable original card references')
        for target in self.targets:
            target.__post_init__()
            if target.player_id != self.request.player_id or target.zone != Zone.HAND:
                raise ValueError('Hand deadline targets must belong to its original hand')
        if len({t.entity_id for t in self.targets}) != len(self.targets):
            raise ValueError('Hand deadline cannot repeat a physical target')
        if self.request.cards is not None and self.targets != self.request.cards:
            raise ValueError('Hand deadline replaced its complete explicit target inventory')
        if type(self.removed) is not tuple or any(type(i) is not int or i < 1 for i in self.removed):
            raise ValueError('Hand deadline needs immutable removed identities')
        if tuple(t.entity_id for t in self.targets if t.entity_id in self.removed) != self.removed:
            raise ValueError('Removed identities must be an ordered original subset')
        _integer(self.destruction_cursor, 'hand destruction cursor', 0)
        if self.destruction_cursor > len(self.targets):
            raise ValueError('Hand destruction exceeds its original inventory')
        if type(self.destruction_events) is not tuple:
            raise ValueError('Hand destruction needs immutable event identities')
        if self.request.retirement == 'remove':
            if self.destruction_started_event is not None or self.destruction_cursor or self.destruction_events:
                raise ValueError('Non-death hand removal cannot claim destruction progress')
        elif self.destruction_started_event is None:
            if self.owner_end_event is not None or self.removal_event is not None or self.removed or self.destruction_cursor or self.destruction_events or self.expired_event is not None:
                raise ValueError('Unstarted hand destruction cannot claim a result')
        else:
            _integer(self.owner_end_event, 'hand destruction owner end', self.created_event + 1)
            _integer(self.destruction_started_event, 'hand destruction start', self.owner_end_event + 1)
            if self.removal_event is not None or len(self.destruction_events) != len(self.removed) or len(self.removed) > self.destruction_cursor:
                raise ValueError('Hand destruction lost its actual per-card outcomes')
            previous = self.destruction_started_event
            for event in self.destruction_events:
                _integer(event, 'hand destruction event', previous + 1); previous = event
            if any(t.entity_id in self.removed for t in self.targets[self.destruction_cursor:]):
                raise ValueError('Hand destruction claims an unprocessed original target')
            if self.expired_event is not None and (self.destruction_cursor != len(self.targets) or self.expired_event <= previous):
                raise ValueError('Hand destruction closes before its complete original inventory')
        if self.expired_event is None and self.request.retirement == 'remove':
            if self.owner_end_event is not None or self.removal_event is not None or self.removed:
                raise ValueError('Unexpired hand deadline cannot claim a result')
        elif self.expired_event is not None:
            _integer(self.owner_end_event, 'hand deadline natural end event', self.created_event + 1)
            _integer(self.expired_event, 'hand deadline expiry event', self.owner_end_event + 1)
            if self.request.retirement == 'remove' and bool(self.removed) != (self.removal_event is not None):
                raise ValueError('Hand deadline removal lost its original event')
            if self.removal_event is not None:
                _integer(self.removal_event, 'hand deadline removal event', self.owner_end_event + 1)
                if self.removal_event >= self.expired_event:
                    raise ValueError('Removal must precede deadline closure')


@dataclass(frozen=True)
class ExpireHandDeadline(Effect):
    deadline_id: int
    owner_end_event: int

    def __post_init__(self):
        _integer(self.deadline_id, 'hand deadline identity', 1)
        _integer(self.owner_end_event, 'hand deadline natural end event', 1)


@dataclass(frozen=True)
class CompleteHandDeadlineDestruction(Effect):
    deadline_id: int
    owner_end_event: int
    index: int
    step_event: int

    def __post_init__(self):
        _integer(self.deadline_id, 'hand deadline ID', 1)
        _integer(self.owner_end_event, 'hand deadline owner end event', 1)
        _integer(self.index, 'hand destruction index', 0)
        _integer(self.step_event, 'hand destruction step event', self.owner_end_event + 1)


@dataclass(frozen=True)
class SummonHandDeadlineCopy(CompleteHandDeadlineDestruction):
    """Private successful-discard continuation; the ordinary summon owns entry."""


def copy_receipt(root, work, discard_event, entity_id, board_full):
    return dict(deadline_id=root.id, owner_end_event=work.owner_end_event, index=work.index,
        step_event=work.step_event, discard_event=discard_event, card_id=root.source_card_id,
        entity_id=entity_id, board_full=board_full)


def copy_work(r, work):
    root = expiry_root(r.state, work)
    if not r.ending_turn or root.request.retirement != 'discard_copy' or root.destruction_cursor != work.index:
        raise ResolutionError('Hand deadline copy requires its original successful discard step')
    step = next((e for e in r.game._events if e.sequence == work.step_event), None)
    if step is None or dict(step.data) != destruction_step_data(root,work.index,True):
        raise ResolutionError('Hand deadline copy lost its original step')
    discarded = matching_destructions(r.game._events,root,work.index,work.step_event,state=r.state)
    if len(discarded) != 1 or any(e.kind == 'hand_deadline_copy_accepted' and
            dict(e.data).get('deadline_id') == root.id for e in r.game._events):
        raise ResolutionError('Hand deadline copy lost or repeated its successful discard')
    r.emit('hand_deadline_copy_accepted',source_id=root.request.source_id,player_id=root.request.player_id,
        **copy_receipt(root,work,discarded[0].sequence,r.state.next_entity_id,
            len(r.player(root.request.player_id).board) >= r.rules.max_board))
    return (Summon(root.request.player_id,root.source_card_id),)


def copy_outcome(state, events, root, work, discard_event, *, before=None, require=False):
    accepts = [e for e in events if e.kind == 'hand_deadline_copy_accepted' and
        dict(e.data).get('deadline_id') == root.id and (before is None or e.sequence < before)]
    if root.request.retirement != 'discard_copy' or discard_event is None:
        if accepts:raise ValueError('Hand deadline copy has no actual original discard')
        return None,False
    if len(accepts) > 1 or require and not accepts:
        raise ValueError('Hand deadline lost or repeated its copy acceptance')
    if not accepts:return None,False
    event=accepts[0];d=dict(event.data)
    _integer(d.get('entity_id'),'hand deadline copy allocation',1)
    if type(d.get('board_full')) is not bool or d['entity_id'] > state.next_entity_id:
        raise ValueError('Hand deadline copy has an impossible allocation')
    if ((event.source_id,event.player_id)!=(root.request.source_id,root.request.player_id) or
        event.sequence <= discard_event or d != copy_receipt(root,work,discard_event,d['entity_id'],d['board_full'])):
        raise ValueError('Hand deadline copy changed its original recipe or discard')
    later=[e for e in events if e.sequence > event.sequence and (before is None or e.sequence < before)]
    if d['board_full']:
        results=[e for e in later if e.kind=='summon_failed' and e.player_id==root.request.player_id and
            dict(e.data)==dict(card_id=root.source_card_id,reason='board_full')]
    else:
        known={x.event_sequence for x in state.successful_summon_history if
            x.entity_id==d['entity_id'] and x.minion.card_id==root.source_card_id and x.player_id==root.request.player_id}
        results=[e for e in later if e.sequence in known]
    if not d['board_full'] and len(results)>1 or require and not results:
        raise ValueError('Hand deadline copy lost its actual ordinary summon result')
    return event,bool(results)


def ended_count(state, player_id, *, before_event=None):
    return sum(row.player_id == player_id and row.end_event is not None and
        (before_event is None or row.end_event < before_event) for row in state.owner_turn_history)


def same_hand(state, reference):
    entity = state.entities.get(reference.entity_id)
    return entity is not None and (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) == (
        reference.player_id, Zone.HAND, reference.card_id, reference.zone_epoch) and entity.id in state.players[reference.player_id].hand


def begin_data(root):
    return dict(deadline_id=root.id, turn=root.turn, owner_ends=root.request.owner_ends,
        owner_ends_at_accept=root.owner_ends_at_accept, source_card_id=root.source_card_id,
        targets=tuple(reference_data(t) for t in root.targets), retirement=root.request.retirement,
        target_scope='hand' if root.request.cards is None else 'captured')


def finish_data(root):
    data = dict(deadline_id=root.id, owner_end_event=root.owner_end_event,
        removal_event=root.removal_event, removed=root.removed)
    if root.request.retirement != 'remove':
        data.update(destruction_started_event=root.destruction_started_event, destruction_events=root.destruction_events)
    return data


def reference_data(card):
    return (card.entity_id, card.player_id, card.zone.value, card.card_id, card.zone_epoch)


def destruction_start_data(root):
    return dict(deadline_id=root.id, owner_end_event=root.owner_end_event,
        targets=tuple(reference_data(t) for t in root.targets))


def destruction_step_data(root, index, available):
    return dict(deadline_id=root.id, owner_end_event=root.owner_end_event, index=index,
        original_card=reference_data(root.targets[index]), available=available)


def matching_destructions(events, root, index, after, before=None, *, state=None):
    if root.request.retirement == 'discard_copy':
        target = root.targets[index]
        sequences = {row.event_sequence for row in state.discard_history
            if row.source_id == root.request.source_id and
            (row.card.entity_id,row.player_id,row.card.card_id,row.card.zone_epoch) ==
            (target.entity_id,target.player_id,target.card_id,target.zone_epoch)}
        return tuple(e for e in events if e.sequence in sequences and e.sequence > after and
            (before is None or e.sequence < before))
    return tuple(e for e in events if e.sequence > after and (before is None or e.sequence < before)
        and e.kind == 'card_destroyed_in_hand' and e.source_id == root.request.source_id
        and destruction_result(e).card == root.targets[index])


def validate_card_scope(state, registry, request):
    request.__post_init__()
    if request.source_id is not None and request.source_id not in state.entities:
        raise ValueError('Hand deadline source does not exist')
    for target in request.cards or ():
        entity = state.entities.get(target.entity_id)
        card = registry.card(target.card_id)
        if entity is None or target.zone_epoch > entity.zone_epoch:
            raise ValueError('Bound deadline requires an existing physical card and known epoch')
        if card.kind not in HAND_TYPES or card.kind.name == 'HERO' and not card.hero_card:
            raise ValueError('Bound deadline requires a playable physical hand definition')


def schedule(r, request):
    request.__post_init__()
    validate_card_scope(r.state, r.registry, request)
    source = None if request.source_id is None else r.state.entities.get(request.source_id)
    if request.source_id is not None and source is None:
        raise ResolutionError('Hand deadline source does not exist')
    if request.retirement == 'discard_copy':
        if source.kind.name != 'MINION':
            raise ResolutionError('Discard-copy deadline requires its actual minion source')
        if any(row.request.retirement == 'discard_copy' and row.expired_event is None and
               any(t == request.cards[0] for t in row.targets) for row in r.state.hand_deadlines):
            raise ResolutionError('A physical hand residence cannot be ignited twice')
    targets = tuple(CardReference.capture(r.state.entities[i]) for i in r.player(request.player_id).hand) if request.cards is None else request.cards
    RemoveFromGame(targets, request.source_id).__post_init__()
    for target in targets:
        card = r.registry.card(target.card_id)
        if card.kind not in HAND_TYPES or (card.kind.name == 'HERO' and not card.hero_card):
            raise ResolutionError('Hand deadline requires playable hand cards')
    root = HandDeadlineRecord(len(r.state.hand_deadlines) + 1, request, targets,
        None if source is None else source.card_id, r.state.turn, r.state.action_number,
        ended_count(r.state, request.player_id), len(r.game._events) + 1)
    r.state.hand_deadlines.append(root)
    r.emit('hand_deadline_armed', source_id=request.source_id, player_id=request.player_id, **begin_data(root))


def due_before_end(state, player_id):
    following = ended_count(state, player_id) + 1
    return tuple(root.id for root in state.hand_deadlines if root.expired_event is None and
        root.request.player_id == player_id and following >= root.owner_ends_at_accept + root.request.owner_ends)


def expiry_root(state, work):
    work.__post_init__()
    if work.deadline_id > len(state.hand_deadlines):
        raise ResolutionError('Unknown hand deadline expiry')
    root = state.hand_deadlines[work.deadline_id - 1]
    if root.expired_event is not None:
        raise ResolutionError('Hand deadline was already consumed')
    if root.owner_end_event is not None and root.owner_end_event != work.owner_end_event:
        raise ResolutionError('Hand destruction borrowed another accepted natural end')
    matches = [row for row in state.owner_turn_history if row.player_id == root.request.player_id and row.end_event == work.owner_end_event]
    if len(matches) != 1 or state.active_player != root.request.player_id or matches[0].turn != state.turn:
        raise ResolutionError('Hand deadline expiry requires its current genuine owner end')
    count = ended_count(state, root.request.player_id, before_event=work.owner_end_event + 1)
    if count != root.owner_ends_at_accept + root.request.owner_ends:
        raise ResolutionError('Hand deadline expiry differs from its accepted end count')
    return root


def expire(r, work):
    root = expiry_root(r.state, work)
    if not r.ending_turn:
        raise ResolutionError('Hand deadline expiry is private natural-end work')
    if any(type(item) is ExpireHandDeadline and item.deadline_id == root.id for item in r._work_queue):
        raise ResolutionError('Hand deadline expiry cannot be injected ahead of its original work')
    if root.request.retirement != 'remove':
        if root.destruction_started_event is None:
            root = replace(root, owner_end_event=work.owner_end_event, destruction_started_event=len(r.game._events)+1)
            r.state.hand_deadlines[root.id-1] = root
            r.emit('hand_deadline_destruction_started', source_id=root.request.source_id,
                player_id=root.request.player_id, **destruction_start_data(root))
        if root.destruction_cursor == len(root.targets):
            root = replace(root, expired_event=len(r.game._events)+1)
            r.state.hand_deadlines[root.id-1] = root
            r.emit('hand_deadline_expired', source_id=root.request.source_id, player_id=root.request.player_id, **finish_data(root))
            return ()
        index = root.destruction_cursor; target = root.targets[index]
        available = same_hand(r.state, target)
        event = r.emit('hand_deadline_destruction_step', source_id=root.request.source_id,
            player_id=root.request.player_id, **destruction_step_data(root, index, available))
        complete = CompleteHandDeadlineDestruction(root.id, work.owner_end_event, index, event.sequence)
        if not available:
            return (complete,)
        if root.request.retirement == 'discard_copy':
            followup = SummonHandDeadlineCopy(root.id, work.owner_end_event, index, event.sequence)
            return (DiscardCard(target, root.request.source_id, on_success=(followup,)), complete)
        return (DestroyStoredCard(target, root.request.source_id, reveal=False), complete)
    removed = tuple(t.entity_id for t in root.targets if same_hand(r.state, t))
    first_event = len(r.game._events)
    remove_from_game(r, RemoveFromGame(root.targets, root.request.source_id))
    receipts = [e for e in r.game._events[first_event:] if e.kind == 'cards_removed_from_game']
    if len(receipts) != bool(removed):
        raise ResolutionError('Hand deadline removal lacks its original receipt')
    closed = replace(root, owner_end_event=work.owner_end_event,
        removal_event=receipts[0].sequence if receipts else None,
        expired_event=len(r.game._events) + 1, removed=removed)
    r.state.hand_deadlines[root.id - 1] = closed
    r.emit('hand_deadline_expired', source_id=root.request.source_id, player_id=root.request.player_id, **finish_data(closed))


def complete_destruction(r, work):
    root = expiry_root(r.state, work)
    if not r.ending_turn or root.request.retirement == 'remove' or root.destruction_started_event is None or root.destruction_cursor != work.index:
        raise ResolutionError('Hand destruction continuation lost its original step')
    step = next((e for e in r.game._events if e.sequence == work.step_event), None)
    if step is None or step.kind != 'hand_deadline_destruction_step' or (step.source_id, step.player_id) != (root.request.source_id, root.request.player_id) or dict(step.data) != destruction_step_data(root, work.index, dict(step.data).get('available')) or type(dict(step.data).get('available')) is not bool:
        raise ResolutionError('Hand destruction continuation changed its original step receipt')
    matches = matching_destructions(r.game._events, root, work.index, work.step_event, state=r.state)
    if len(matches) > 1 or not matches and same_hand(r.state, root.targets[work.index]):
        raise ResolutionError('Hand destruction skipped an owed physical target')
    result = matches[0].sequence if matches else None
    copy_outcome(r.state,r.game._events,root,work,result,require=True)
    root = replace(root, destruction_cursor=work.index+1,
        destruction_events=root.destruction_events + (() if result is None else (result,)),
        removed=root.removed + (() if result is None else (root.targets[work.index].entity_id,)))
    r.state.hand_deadlines[root.id-1] = root
    r.emit('hand_deadline_destruction_step_finished', source_id=root.request.source_id, player_id=root.request.player_id,
        deadline_id=root.id, owner_end_event=work.owner_end_event, index=work.index,
        step_event=work.step_event, destruction_event=result)
    return (ExpireHandDeadline(root.id, work.owner_end_event),)


def public_countdowns(state, entity):
    if entity.zone != Zone.HAND:
        return []
    count = ended_count(state, entity.controller)
    return [max(0, root.owner_ends_at_accept + root.request.owner_ends - count)
        for root in state.hand_deadlines if root.expired_event is None and
        any(t.entity_id == entity.id and same_hand(state, t) for t in root.targets)]


def rows_from_dict(value):
    from .serialization import _list, _row
    result = []
    for raw in _list(value['hand_deadlines'], 'hand deadline history'):
        row = _row(raw, HandDeadlineRecord)
        request = _row(row['request'], ScheduleHandRemoval)
        if request['cards'] is not None:
            cards = []
            for item in _list(request['cards'], 'bound hand deadline references'):
                card = _row(item, CardReference); card['zone'] = Zone(card['zone'])
                cards.append(CardReference(**card))
            request['cards'] = tuple(cards)
        row['request'] = ScheduleHandRemoval(**request)
        targets = []
        for item in _list(row['targets'], 'original deadline hand'):
            target = _row(item, CardReference)
            target['zone'] = Zone(target['zone'])
            targets.append(CardReference(**target))
        row['targets'] = tuple(targets)
        row['removed'] = tuple(_list(row['removed'], 'removed deadline targets'))
        row['destruction_events'] = tuple(_list(row['destruction_events'], 'deadline destruction events'))
        result.append(HandDeadlineRecord(**row))
    value['hand_deadlines'] = result


def validate_shape(state, registry):
    if type(state.hand_deadlines) is not list:
        raise ValueError('Hand deadline history requires its complete list')
    last_turn = last_action = last_event = 0
    for index, root in enumerate(state.hand_deadlines, 1):
        if type(root) is not HandDeadlineRecord:
            raise ValueError('Hand deadline history requires original typed records')
        root.__post_init__()
        if root.id != index or not last_turn <= root.turn <= state.turn or not last_action <= root.action <= state.action_number or root.created_event <= last_event:
            raise ValueError('Hand deadline changed its original order or identity')
        if ended_count(state, root.request.player_id, before_event=root.created_event) != root.owner_ends_at_accept:
            raise ValueError('Hand deadline changed its original owner-end clock')
        if root.request.source_id is not None:
            if root.request.source_id not in state.entities:
                raise ValueError('Hand deadline has an unknown original source')
            registry.card(root.source_card_id)
        if root.request.retirement == 'discard_copy' and registry.card(root.source_card_id).kind.name != 'MINION':
            raise ValueError('Discard-copy deadline lost its original minion recipe')
        for target in root.targets:
            entity = state.entities.get(target.entity_id)
            card = registry.card(target.card_id)
            if entity is None or target.zone_epoch > entity.zone_epoch or card.kind not in HAND_TYPES or (card.kind.name == 'HERO' and not card.hero_card):
                raise ValueError('Hand deadline has an unknown or impossible original card')
        if root.owner_end_event is not None:
            ends = [row for row in state.owner_turn_history if row.end_event == root.owner_end_event and row.player_id == root.request.player_id]
            if len(ends) != 1 or ended_count(state, root.request.player_id, before_event=root.owner_end_event + 1) != root.owner_ends_at_accept + root.request.owner_ends:
                raise ValueError('Hand deadline closure lost its original natural end')
        last_turn, last_action, last_event = root.turn, root.action, root.created_event


def validate_destruction_receipts(root, events, by_sequence, state):
    kinds = ('hand_deadline_destruction_started', 'hand_deadline_destruction_step', 'hand_deadline_destruction_step_finished')
    own = [e for e in events if e.kind in kinds and dict(e.data).get('deadline_id') == root.id]
    if root.request.retirement == 'remove' or root.destruction_started_event is None:
        if own:
            raise ValueError('Hand deadline has unexpected destruction receipts')
        return None
    starts = [e for e in own if e.kind == kinds[0]]
    steps = [e for e in own if e.kind == kinds[1]]
    finishes = [e for e in own if e.kind == kinds[2]]
    if len(starts) != 1 or starts[0].sequence != root.destruction_started_event or dict(starts[0].data) != destruction_start_data(root):
        raise ValueError('Hand destruction lost its complete original start')
    if len(finishes) != root.destruction_cursor or len(steps) not in (root.destruction_cursor, root.destruction_cursor+1) or len(steps) > len(root.targets):
        raise ValueError('Hand destruction lost its ordered per-card progress')
    for event in own:
        data = dict(event.data)
        _integer(data.get('deadline_id'), 'hand destruction receipt identity', 1)
        _integer(data.get('owner_end_event'), 'hand destruction receipt owner end', 1)
        if (event.source_id, event.player_id) != (root.request.source_id, root.request.player_id) or event.sequence <= root.owner_end_event:
            raise ValueError('Hand destruction receipt borrowed another source or end')
    results = []; last = root.destruction_started_event
    for index, step in enumerate(steps):
        data = dict(step.data); available = data.get('available')
        _integer(data.get('index'), 'hand destruction step index', 0)
        raw = data.get('original_card'); expected = reference_data(root.targets[index])
        if type(raw) not in (tuple, list) or len(raw) != len(expected) or any(type(a) is not type(z) for a,z in zip(raw,expected)):
            raise ValueError('Hand destruction step lost its typed original reference')
        if type(available) is not bool or data != destruction_step_data(root,index,available) or step.sequence <= last:
            raise ValueError('Hand destruction changed an original step')
        if index >= len(finishes):
            break
        finish = finishes[index]; outcome = dict(finish.data).get('destruction_event')
        if outcome is not None:
            _integer(outcome, 'hand destruction actual event', step.sequence+1)
        expected_finish = dict(deadline_id=root.id, owner_end_event=root.owner_end_event, index=index,
            step_event=step.sequence, destruction_event=outcome)
        matches = matching_destructions(events,root,index,step.sequence,finish.sequence,state=state)
        if dict(finish.data) != expected_finish or finish.sequence <= step.sequence or len(matches) != (outcome is not None) or matches and (matches[0].sequence != outcome or not available):
            raise ValueError('Hand destruction completion lost its actual stored outcome')
        copy_outcome(state,events,root,CompleteHandDeadlineDestruction(root.id,root.owner_end_event,index,step.sequence),outcome,before=finish.sequence,require=True)
        if outcome is not None:
            results.append((root.targets[index].entity_id,outcome))
        last = finish.sequence
    if root.removed != tuple(i for i,_ in results) or root.destruction_events != tuple(s for _,s in results):
        raise ValueError('Hand destruction truncated or replaced its actual results')
    if root.expired_event is not None and (len(steps) != root.destruction_cursor or root.expired_event <= last):
        raise ValueError('Hand destruction closes with an unfinished step')
    return steps[-1] if len(steps) > root.destruction_cursor else None


def validate_boundary(game):
    state = game._state
    validate_shape(state, game.registry)
    if not state.hand_deadlines and not any(e.kind in ('hand_deadline_armed', 'hand_deadline_expired', 'hand_deadline_copy_accepted') for e in game._events):
        return
    from .hero_health_history import effective_events
    events = tuple(effective_events(game._events))
    by_sequence = {e.sequence: e for e in events}
    starts = [e for e in events if e.kind == 'hand_deadline_armed']
    finishes = [e for e in events if e.kind == 'hand_deadline_expired']
    destruction_pending = {}
    for event in events:
        if event.kind in ('hand_deadline_destruction_started','hand_deadline_destruction_step','hand_deadline_destruction_step_finished','hand_deadline_copy_accepted'):
            identity = dict(event.data).get('deadline_id')
            _integer(identity, 'hand destruction receipt identity', 1)
            if identity > len(state.hand_deadlines):
                raise ValueError('Unknown hand destruction receipt')
            if event.kind == 'hand_deadline_copy_accepted':
                original = state.hand_deadlines[identity-1]
                if original.request.retirement != 'discard_copy' or original.destruction_started_event is None:
                    raise ValueError('Hand deadline copy receipt has no original discard-copy step')
    if len(starts) != len(state.hand_deadlines) or len(finishes) != sum(r.expired_event is not None for r in state.hand_deadlines):
        raise ValueError('Hand deadlines lost their complete original receipts')
    for root, event in zip(state.hand_deadlines, starts):
        if (event.sequence, event.source_id, event.player_id, event.action, dict(event.data)) != (
            root.created_event, root.request.source_id, root.request.player_id, root.action, begin_data(root)):
            raise ValueError('Hand deadline changed its original acceptance')
        destruction_pending[root.id] = validate_destruction_receipts(root,events,by_sequence,state)
        if root.expired_event is None:
            continue
        closed = by_sequence.get(root.expired_event)
        end = by_sequence.get(root.owner_end_event)
        if closed is None or closed.kind != 'hand_deadline_expired' or (closed.source_id, closed.player_id, dict(closed.data)) != (
            root.request.source_id, root.request.player_id, finish_data(root)):
            raise ValueError('Hand deadline changed its original closure')
        if end is None or end.kind != 'turn_ended' or end.player_id != root.request.player_id or closed.action < end.action:
            raise ValueError('Hand deadline closure borrowed another end')
        if root.removal_event is not None:
            removed = by_sequence.get(root.removal_event)
            rows = tuple((t.entity_id, t.player_id, Zone.HAND.value, t.card_id) for t in root.targets if t.entity_id in root.removed)
            if removed is None or (removed.kind, removed.source_id, removed.amount, dict(removed.data)) != (
                'cards_removed_from_game', root.request.source_id, len(rows), dict(removed=rows, reveal=False)):
                raise ValueError('Hand deadline changed its original non-death removal')
    pending = [root for root in state.hand_deadlines if root.expired_event is None and
        ended_count(state, root.request.player_id) >= root.owner_ends_at_accept + root.request.owner_ends]
    if state.status != 'playing':
        return
    works, destroys, copies, summons, seen = [], [], [], [], set()
    def visit(value):
        if type(value) is ScheduleHandRemoval:
            validate_card_scope(state,game.registry,value)
        if type(value) in (ExpireHandDeadline,CompleteHandDeadlineDestruction):
            works.append(value)
        if type(value) in (DestroyStoredCard,DiscardCard):
            destroys.append(value)
        if type(value) is SummonHandDeadlineCopy:
            copies.append(value)
        if type(value) is Summon:
            summons.append(value)
        if value is None or type(value) is GameState or id(value) in seen:
            return
        if is_dataclass(value):
            seen.add(id(value))
            for field in fields(value):
                visit(getattr(value, field.name))
        elif type(value) in (tuple, list):
            seen.add(id(value))
            for child in value:
                visit(child)
    if game._frame is not None:
        visit(game._frame.prefix)
        visit(game._frame.continuation)
        accepted = (len(works),len(copies))
        visit(game._frame.options)
        if (len(works),len(copies)) != accepted:
            raise ValueError('Hand deadline expiry cannot be a choice option')
    if [w.deadline_id for w in works] != [r.id for r in pending]:
        raise ValueError('Hand deadline continuation lost or repeated accepted expiries')
    if any(c.deadline_id not in {r.id for r in pending if r.request.retirement=='discard_copy'} for c in copies):
        raise ValueError('Hand deadline copy has no currently owed original step')
    for work in works:
        root = expiry_root(state, work); step = destruction_pending[root.id]
        if step is None:
            if type(work) is not ExpireHandDeadline:
                raise ValueError('Hand deadline replaced its owed next original step')
        else:
            if type(work) is not CompleteHandDeadlineDestruction or (work.index,work.step_event) != (root.destruction_cursor,step.sequence):
                raise ValueError('Hand deadline lost its complete original target continuation')
            matching = [d for d in destroys if d.card == root.targets[work.index] and d.source_id == root.request.source_id]
            outcomes = matching_destructions(events,root,work.index,work.step_event,state=state)
            if root.request.retirement == 'discard_copy':
                followup=SummonHandDeadlineCopy(root.id,work.owner_end_event,work.index,work.step_event)
                accepting,done=copy_outcome(state,events,root,work,outcomes[0].sequence if outcomes else None)
                queued=[c for c in copies if c.deadline_id==root.id]
                if (accepting is None and dict(step.data)['available'] and len(queued)!=1 or accepting is not None and queued or
                    accepting is not None and not done and summons.count(Summon(root.request.player_id,root.source_card_id))!=1):
                    raise ValueError('Hand deadline lost or repeated its owed successful-discard copy')
                if queued and queued != [followup]:raise ValueError('Hand deadline copy borrowed another step')
                for d in matching:
                    if type(d) is not DiscardCard or d.on_success != (followup,) or not d.reveal:
                        raise ValueError('Hand deadline changed its actual discard and copy continuation')
            available = dict(step.data)['available']
            if len(matching) > 1 or not available and matching or outcomes and matching or available and not outcomes and same_hand(state,root.targets[work.index]) and len(matching) != 1:
                raise ValueError('Hand destruction lost or duplicated its owed physical movement')
    if works and (game._frame is None or not game._frame.ending_turn):
        raise ValueError('Hand deadline continuation is outside its natural end')


def register(mechanics):
    mechanics.register(ScheduleHandRemoval, schedule)
    mechanics.register(ExpireHandDeadline, expire)
    mechanics.register(CompleteHandDeadlineDestruction, complete_destruction)
    mechanics.register(SummonHandDeadlineCopy, copy_work)
