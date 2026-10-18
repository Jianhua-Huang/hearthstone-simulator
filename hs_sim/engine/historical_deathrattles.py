"""Replay printed minion Deathrattles through private, non-summoned carriers.

Selection is over immutable friendly death occurrences. The base body is a new
physical source, never a fabricated death or a grant to the issuing spell.
RNG/order, silence and base-memory policies remain explicit CN calibration items.
"""
from dataclasses import dataclass
from random import Random

from .effects import Effect, _integer, _player
from .model import CardType, Event, Zone

ROOT = 'historical_deathrattles_selected'
START = 'historical_deathrattle_started'
DONE = 'historical_deathrattle_finished'
CLOSED = 'historical_deathrattles_finished'
POLICY = 'printed_death_occurrences_v1'


def eligible_deaths(state, registry, player_id, *, prefix=None):
    _player(player_id)
    rows = state.death_history if prefix is None else state.death_history[:prefix]
    return tuple(d for d in rows if d.controller == player_id and d.zone == Zone.BOARD
                 and registry.card(d.card_id).kind == CardType.MINION
                 and registry.card(d.card_id).deathrattle is not None)


def _select(rng, candidates, count):
    remaining = list(candidates)
    return tuple(remaining.pop(rng.randrange(len(remaining)))
                 for _ in range(min(count, len(remaining))))


@dataclass(frozen=True)
class TriggerHistoricalDeathrattles(Effect):
    player_id: int
    count: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.count, 'historical minion count', 1)
        _integer(self.source_id, 'historical trigger source', 1)


@dataclass(frozen=True)
class StartHistoricalDeathrattle(Effect):
    root: Event
    index: int

    def __post_init__(self):
        if type(self.root) is not Event or self.root.kind != ROOT:
            raise ValueError('Historical Deathrattle requires its selection event')
        _integer(self.index, 'historical selected index', 0)


@dataclass(frozen=True)
class FinishHistoricalDeathrattle(Effect):
    root: Event
    index: int
    group_id: int | None

    def __post_init__(self):
        StartHistoricalDeathrattle(self.root, self.index)
        if self.group_id is not None:
            _integer(self.group_id, 'historical Deathrattle group', 1)


@dataclass(frozen=True)
class FinishHistoricalDeathrattles(Effect):
    root: Event

    def __post_init__(self):
        StartHistoricalDeathrattle(self.root, 0)


def validate_root(state, registry, root):
    if type(root) is not Event or root.kind != ROOT or root.source_id not in state.entities:
        raise ValueError('Historical selection lost its original issuer')
    data = dict(root.data)
    keys = {'policy', 'count', 'death_prefix', 'candidates', 'selected', 'carriers',
            'abilities', 'turn', 'issuer_card_id', 'rng_before', 'rng_after'}
    if set(data) != keys or data['policy'] != POLICY:
        raise ValueError('Historical selection changed its complete policy or fields')
    _player(root.player_id)
    _integer(data['count'], 'historical count', 1)
    _integer(data['death_prefix'], 'historical death prefix', 0)
    _integer(data['turn'], 'historical turn', 1)
    if (data['death_prefix'] > len(state.death_history) or data['turn'] > state.turn
            or root.action > state.action_number or root.target_id is not None or root.amount != 0):
        raise ValueError('Historical selection has invalid chronology')
    registry.card(data['issuer_card_id'])
    for field in ('candidates', 'selected', 'carriers', 'abilities'):
        if type(data[field]) is not tuple:
            raise ValueError('Historical selection requires frozen ordered inventories')
    for field in ('candidates', 'selected'):
        for identity in data[field]:
            _integer(identity, 'historical death occurrence', 1)
    expected = tuple(d.id for d in eligible_deaths(state, registry, root.player_id,
                                                  prefix=data['death_prefix']))
    if data['candidates'] != expected:
        raise ValueError('Historical selection lost its complete death candidates')
    rng = Random()
    rng.setstate(data['rng_before'])
    if _select(rng, expected, data['count']) != data['selected'] or rng.getstate() != data['rng_after']:
        raise ValueError('Historical selection differs from its original random draw')
    carriers, abilities = data['carriers'], data['abilities']
    if (len(carriers) != len(data['selected']) or len(set(carriers)) != len(carriers)
            or len(abilities) != len(carriers)):
        raise ValueError('Historical selection changed its physical carrier inventory')
    for carrier, ids in zip(carriers, abilities):
        _integer(carrier, 'historical carrier', 1)
        if carrier not in state.entities or type(ids) is not tuple or not ids or len(set(ids)) != len(ids):
            raise ValueError('Historical selection lost its base carrier or printed ability')
        for identity in ids:
            _integer(identity, 'historical printed ability', 1)
            if identity >= state.next_attachment_id:
                raise ValueError('Historical ability exceeds the attachment inventory')
    return data


def validate_capture(state, registry, capture):
    data = validate_root(state, registry, capture.historical_root)
    if capture.carrier_id not in data['carriers']:
        raise ValueError('Historical invocation changed its accepted carrier')
    index = data['carriers'].index(capture.carrier_id)
    death = state.death_history[data['selected'][index] - 1]
    definition = registry.card(death.card_id)
    a = capture.ability
    if ((capture.player_id, capture.card_id, capture.kind, capture.trigger_source_id,
         capture.trigger_source_card_id) !=
            (capture.historical_root.player_id, death.card_id, CardType.MINION,
             capture.historical_root.source_id, data['issuer_card_id'])
            or capture.turn < data['turn'] or capture.action < capture.historical_root.action
            or a.id not in data['abilities'][index] or a.origin != 'printed'
            or a.behavior_id != definition.deathrattle or a.source_id != capture.carrier_id
            or a.deathrattle_inherited_from is not None):
        raise ValueError('Historical invocation differs from its selected printed minion')


def validate_context(context, registry, batch):
    capture = context.deathrattle
    validate_capture(context.state, registry, capture)
    data = dict(capture.historical_root.data)
    source = context.source
    if (context.event != capture.historical_root or context.death is not None
            or source.zone != Zone.SETASIDE or source.card_id != capture.card_id
            or source.controller != capture.player_id):
        raise ValueError('Historical callback lost its private base acceptance view')
    from .lifecycle import active_abilities
    abilities = tuple(active_abilities(source, 'deathrattle'))
    if (batch.abilities != abilities or tuple(a.id for a in abilities) !=
            data['abilities'][data['carriers'].index(source.id)]):
        raise ValueError('Historical callback changed its complete printed payload')


def accept(r, effect):
    effect.__post_init__()
    issuer = r.state.entities[effect.source_id]
    candidates = tuple(d.id for d in eligible_deaths(r.state, r.registry, effect.player_id))
    before = r.game._rng.getstate()
    selected = _select(r.game._rng, candidates, effect.count)
    after = r.game._rng.getstate()
    carriers, abilities = [], []
    from .lifecycle import active_abilities
    for death_id in selected:
        death = r.state.death_history[death_id - 1]
        body = r.create_entity(effect.player_id, death.card_id, Zone.SETASIDE)
        carriers.append(body.id)
        abilities.append(tuple(a.id for a in active_abilities(body, 'deathrattle')))
    root = r.emit(ROOT, source_id=effect.source_id, player_id=effect.player_id, _capture=False,
                  policy=POLICY, count=effect.count, death_prefix=len(r.state.death_history),
                  candidates=candidates, selected=selected, carriers=tuple(carriers), abilities=tuple(abilities),
                  turn=r.state.turn, issuer_card_id=issuer.card_id, rng_before=before, rng_after=after)
    validate_root(r.state, r.registry, root)
    return [*(StartHistoricalDeathrattle(root, i) for i in range(len(selected))),
            FinishHistoricalDeathrattles(root)]


def start(r, work):
    work.__post_init__()
    data = validate_root(r.state, r.registry, work.root)
    if work.index >= len(data['carriers']):
        raise ValueError('Historical invocation exceeds its selected inventory')
    carrier = data['carriers'][work.index]
    body = r.state.entities[carrier]
    death = r.state.death_history[data['selected'][work.index] - 1]
    if (body.zone, body.card_id, body.controller) != (Zone.SETASIDE, death.card_id, work.root.player_id):
        raise ValueError('Historical execution lost its original private base body')
    from .lifecycle import active_abilities
    from .deathrattles import schedule_group
    first = r.state.next_deathrattle_id
    invocations = schedule_group(r, carrier, work.root.player_id,
        tuple(active_abilities(body, 'deathrattle')), event=work.root,
        trigger_source_id=work.root.source_id, origin='history', historical_root=work.root)
    group = first if invocations else None
    r.emit(START, source_id=carrier, player_id=work.root.player_id, _capture=False,
           root=work.root.sequence, index=work.index, group=group)
    return [*invocations, FinishHistoricalDeathrattle(work.root, work.index, group)]


def finish(r, work):
    work.__post_init__()
    data = validate_root(r.state, r.registry, work.root)
    if work.group_id is not None:
        rows = [d for d in r.state.deathrattle_history if d.capture.group_id == work.group_id]
        if not rows or any(not d.completed or d.interrupted or d.capture.historical_root != work.root
                           or d.capture.carrier_id != data['carriers'][work.index] for d in rows):
            raise ValueError('Historical minion has not finished its accepted Deathrattle group')
    r.emit(DONE, source_id=data['carriers'][work.index], player_id=work.root.player_id, _capture=False,
           root=work.root.sequence, index=work.index, group=work.group_id)


def finish_root(r, work):
    work.__post_init__()
    validate_root(r.state, r.registry, work.root)
    _validate_inventory(r.state, r.registry, r.game._events, r._work_queue, closing=work.root)
    r.emit(CLOSED, source_id=work.root.source_id, player_id=work.root.player_id,
           _capture=False, root=work.root.sequence)


def _validate_inventory(state, registry, events, queue, *, closing=None):
    from .hero_health_history import effective_events
    events = tuple(effective_events(events))
    roots = {e.sequence: e for e in events if e.kind == ROOT}
    starts, finishes, closed = {}, {}, set()
    for event in events:
        if event.kind not in (START, DONE, CLOSED):
            continue
        data = dict(event.data)
        root = roots.get(data.get('root'))
        if root is None or event.player_id != root.player_id or event.sequence <= root.sequence:
            raise ValueError('Historical progress lost its actual selection event')
        if event.kind == CLOSED:
            if root.sequence in closed or set(data) != {'root'} or event.source_id != root.source_id:
                raise ValueError('Historical root has duplicate or mismatched completion')
            closed.add(root.sequence)
            continue
        if set(data) != {'root', 'index', 'group'} or root.sequence in closed:
            raise ValueError('Historical progress changed its fields or followed completion')
        index = data['index']
        _integer(index, 'historical progress index', 0)
        if data['group'] is not None:
            _integer(data['group'], 'historical accepted group', 1)
        root_data = dict(root.data)
        if index >= len(root_data['carriers']) or event.source_id != root_data['carriers'][index]:
            raise ValueError('Historical progress changed its selected carrier')
        key = root.sequence, index
        inventory = starts if event.kind == START else finishes
        if key in inventory or event.kind == DONE and starts.get(key) != data['group']:
            raise ValueError('Historical progress duplicated or changed its accepted group')
        if event.kind == DONE and key not in starts:
            raise ValueError('Historical completion lacks its actual start')
        if event.kind == START:
            previous = [i for seq, i in starts if seq == root.sequence]
            if index != len(previous) or index and (root.sequence, index - 1) not in finishes:
                raise ValueError('Historical minions must execute in their accepted selected order')
        inventory[key] = data['group']
    for work in queue:
        if type(work) in (StartHistoricalDeathrattle, FinishHistoricalDeathrattle, FinishHistoricalDeathrattles):
            if roots.get(work.root.sequence) != work.root:
                raise ValueError('Historical continuation changed its original selection event')
    root_proofs = [w.root for w in queue if type(w) is FinishHistoricalDeathrattles]
    if closing is not None:
        root_proofs.append(closing)
    pending_starts = [(w.root.sequence, w.index) for w in queue if type(w) is StartHistoricalDeathrattle]
    pending_finishes = [(w.root.sequence, w.index, w.group_id) for w in queue
                        if type(w) is FinishHistoricalDeathrattle]
    expected_starts, expected_finishes, open_roots = [], [], []
    for root in roots.values():
        data = validate_root(state, registry, root)
        if root.sequence not in closed and state.status == 'playing':
            open_roots.append(root)
        for index in range(len(data['selected'])):
            key = root.sequence, index
            if key not in starts:
                if root.sequence in closed:
                    raise ValueError('Historical root completed without its selected minions')
                if state.status == 'playing':
                    expected_starts.append(key)
            elif key not in finishes:
                if root.sequence in closed:
                    raise ValueError('Historical root completed before its selected minion')
                if state.status == 'playing':
                    expected_finishes.append((*key, starts[key]))
        queued = [w for w in queue if type(w) in (StartHistoricalDeathrattle, FinishHistoricalDeathrattle,
                                                FinishHistoricalDeathrattles) and w.root == root]
        if queued:
            if type(queued[-1]) is not FinishHistoricalDeathrattles:
                raise ValueError('Historical root completion must follow all selected minions')
            indices = [w.index for w in queued if type(w) is StartHistoricalDeathrattle]
            if indices != sorted(indices):
                raise ValueError('Historical continuation changed its accepted selected order')
    if (sorted(root_proofs, key=lambda e: e.sequence) != sorted(open_roots, key=lambda e: e.sequence)
            or sorted(pending_starts) != sorted(expected_starts)
            or sorted(pending_finishes) != sorted(expected_finishes)):
        raise ValueError('Historical selection lost its complete pending continuation inventory')
    for row in state.deathrattle_history:
        capture = row.capture
        if capture.origin == 'history':
            root = roots.get(capture.historical_root.sequence)
            if root != capture.historical_root:
                raise ValueError('Historical invocation lost its actual original selection')
            data = dict(root.data)
            key = root.sequence, data['carriers'].index(capture.carrier_id)
            if starts.get(key) != capture.group_id:
                raise ValueError('Historical invocation changed its actual accepted group')


def validate_boundary(game):
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    _validate_inventory(game._state, game.registry, game._events, queue)


def register(mechanics):
    for effect, handler in ((TriggerHistoricalDeathrattles, accept), (StartHistoricalDeathrattle, start),
                            (FinishHistoricalDeathrattle, finish), (FinishHistoricalDeathrattles, finish_root)):
        mechanics.register(effect, handler)
