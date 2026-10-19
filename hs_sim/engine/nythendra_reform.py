"""Nythendra's finite native forms and ordinary, resumable beetle operations.

Attack-based splitting and count-based native reformation are explicit local
policies pending CN calibration. No alternate death or summon executor lives here.
Private receipts bind interpreter tails; they do not authenticate unsigned saves.
"""
from dataclasses import dataclass, fields, is_dataclass, replace
import json

from .effects import Effect, _integer
from .model import CardType, Event, Zone
from .sacrifice import MinionReference, live_minion
from .summon_quantities import (SummonByCard, SummonCause, SummonEntryMaterial,
    FinishCardSummon, accept as accept_summon, record as summon_record, validate_cause)

ROOT = 'EDR_818'
BEETLE = 'EDR_818t'
FORMS = {n: ROOT if n == 7 else 'nythendra.reformed.' + str(n) for n in range(1, 8)}
SPLIT_BODY = 'cards.nythendra.split'
REFORM_BODY = 'cards.nythendra.reform'
SPLIT_START = 'nythendra_split_started'
SPLIT_STEP = 'nythendra_split_step'
SPLIT_DONE = 'nythendra_split_finished'
REFORM_START = 'nythendra_reform_started'
REFORM_CHILD = 'nythendra_reform_summon'
REFORM_DONE = 'nythendra_reform_finished'


@dataclass(frozen=True)
class SplitNythendra(Effect):
    deathrattle_id: int
    cause: SummonCause
    position: int | None = None
    ordinal: int = 0

    def __post_init__(self):
        _integer(self.deathrattle_id, 'original split Deathrattle', 1)
        if type(self.cause) is not SummonCause: raise ValueError('Split requires its original card cause')
        self.cause.__post_init__()
        if self.position is not None: _integer(self.position, 'original split position', 0)
        _integer(self.ordinal, 'completed split units', 0)


@dataclass(frozen=True)
class ReformNythendra(Effect):
    source: MinionReference
    cause: SummonCause
    event: Event

    def __post_init__(self):
        if type(self.source) is not MinionReference or type(self.cause) is not SummonCause or type(self.event) is not Event:
            raise ValueError('Reform requires its physical beetle, cause and original start event')
        self.source.__post_init__(); self.cause.__post_init__()
        if (self.source.card_id != BEETLE or self.event.kind != 'turn_started' or
                self.event.player_id != self.source.player_id or self.cause.player_id != self.source.player_id or
                self.event.action != self.cause.action or
                dict(self.event.data).get('turn') != self.cause.turn or
                (self.cause.source.entity_id, self.cause.source.card_id, self.cause.source.zone_epoch,
                 self.cause.source.entered_order, self.cause.source.controller, self.cause.source.zone) !=
                (self.source.entity_id, BEETLE, self.source.zone_epoch, self.source.entered_order,
                 self.source.player_id, Zone.BOARD)):
            raise ValueError('Reform changed its original own-turn physical source')


@dataclass(frozen=True)
class FinishNythendraReform(Effect):
    request: ReformNythendra
    selected: tuple[MinionReference, ...]
    form_id: str
    position: int
    root_id: int | None = None

    def __post_init__(self):
        if type(self.request) is not ReformNythendra: raise ValueError('Reform tail requires its original request')
        self.request.__post_init__()
        if (type(self.selected) is not tuple or not 1 <= len(self.selected) <= 7 or
                any(type(x) is not MinionReference for x in self.selected)):
            raise ValueError('Reform requires its complete finite physical beetle group')
        for x in self.selected: x.__post_init__()
        if (len({x.entity_id for x in self.selected}) != len(self.selected) or
                any(x.card_id != BEETLE or x.player_id != self.request.source.player_id for x in self.selected) or
                self.request.source not in self.selected or self.form_id != FORMS[len(self.selected)]):
            raise ValueError('Reform form differs from its original beetle count')
        _integer(self.position, 'original leftmost reform slot', 0)
        if self.root_id is not None: _integer(self.root_id, 'original reform summon', 1)


def _codec(game):
    from .continuations import FrameCodec
    return FrameCodec(game.mechanics, game.registry)


def _dump(game, work):
    return json.dumps(_codec(game).encode(work), sort_keys=True, separators=(',', ':'))


def _load(game, value):
    if type(value) is not str: raise ValueError('Native beetle receipt lost its original typed work')
    return _codec(game).decode(json.loads(value))


def _split_total(state, registry, work):
    from .deathrattles import record
    work.__post_init__(); validate_cause(state, registry, work.cause)
    row = record(state, work.deathrattle_id)
    c = row.capture
    if (c.kind != CardType.MINION or c.ability.behavior_id != SPLIT_BODY or row.source_attack is None or
            row.execution_order is None or (c.player_id, c.carrier_id) !=
            (work.cause.player_id, work.cause.source.entity_id) or work.ordinal > row.source_attack):
        raise ValueError('Split lost its actual executing Deathrattle Attack')
    return row.source_attack


def _child(work, card_id, position):
    return SummonByCard(work.cause.player_id, (SummonEntryMaterial(card_id),), work.cause, position=position)


def split(r, work):
    total = _split_total(r.state, r.registry, work)
    starts, reforms = _receipts(r.game)
    saved = starts.get(work.deathrattle_id)
    if work.ordinal == 0:
        if saved is not None: raise ValueError('Split invocation was already accepted')
        r.emit(SPLIT_START, source_id=work.cause.source.entity_id, player_id=work.cause.player_id,
               work=_dump(r.game, work), amount=total, _capture=False)
    elif saved is None or saved['request'] != replace(work, ordinal=0) or saved['done'] or len(saved['roots']) != work.ordinal:
        raise ValueError('Split skipped or duplicated an original unit')
    if saved is not None and saved['roots'] and summon_record(r.state, saved['roots'][-1]).status == 'active':
        raise ValueError('Split advanced before its original summon completed')
    full = len(r.state.players[work.cause.player_id].board) >= r.rules.max_board
    if work.ordinal == total or full:
        r.emit(SPLIT_DONE, source_id=work.cause.source.entity_id, deathrattle_id=work.deathrattle_id,
               ordinal=work.ordinal, reason='exhausted' if work.ordinal == total else 'board_full', _capture=False)
        return ()
    position = None if work.position is None else work.position + work.ordinal
    entry = accept_summon(r, _child(work, BEETLE, position))
    root_id = next(x.root_id for x in entry if type(x) is FinishCardSummon)
    r.emit(SPLIT_STEP, source_id=work.cause.source.entity_id, deathrattle_id=work.deathrattle_id,
           ordinal=work.ordinal, root_id=root_id, _capture=False)
    return (*entry, replace(work, ordinal=work.ordinal + 1))


def _validate_reform(game, work):
    from .hero_health_history import effective_events
    work.__post_init__(); validate_cause(game._state, game.registry, work.cause)
    if work.event not in effective_events(game._events) or work.cause.turn > game._state.turn:
        raise ValueError('Reform borrowed an unknown or future turn-start event')


def reform(r, work):
    _validate_reform(r.game, work)
    if live_minion(r.state, work.source) is None:
        r.stale(work, work.source.entity_id); return ()
    board = r.state.players[work.cause.player_id].board
    selected = tuple(MinionReference.capture(e) for eid in board for e in (r.state.entities[eid],)
                     if e.kind == CardType.MINION and e.card_id == BEETLE and e.active and e.health > 0 and not e.doomed)
    if len(selected) not in FORMS: raise ValueError('Unsupported experimental beetle group outside native board capacity')
    tail = FinishNythendraReform(work, selected, FORMS[len(selected)], board.index(selected[0].entity_id))
    r.emit(REFORM_START, source_id=work.source.entity_id, player_id=work.cause.player_id,
           work=_dump(r.game, tail), _capture=False)
    from .nondeath_removal import RemoveFromGame
    return (RemoveFromGame(selected, work.source.entity_id), tail)


def finish_reform(r, work):
    work.__post_init__()
    _, groups = _receipts(r.game)
    key = _key(work.request)
    saved = groups.get(key)
    if saved is None or saved['done'] or replace(work, root_id=None) != saved['work'] or work.root_id != saved['root']:
        raise ValueError('Reform changed its complete originally accepted continuation')
    if work.root_id is None:
        _removed(r.game, saved)
        entry = accept_summon(r, _child(work.request, work.form_id, work.position))
        root_id = next(x.root_id for x in entry if type(x) is FinishCardSummon)
        r.emit(REFORM_CHILD, source_id=work.request.source.entity_id, key=key, root_id=root_id, _capture=False)
        return (*entry, replace(work, root_id=root_id))
    if summon_record(r.state, work.root_id).status == 'active': raise ValueError('Reform preceded its original entry')
    r.emit(REFORM_DONE, source_id=work.request.source.entity_id, key=key, root_id=work.root_id, _capture=False)
    return ()


def _key(work):
    return (work.event.sequence, work.source.entity_id, work.source.zone_epoch, work.source.entered_order)


def _removed(game, saved):
    from .nondeath_removal import removal_result
    from .hero_health_history import effective_events
    work = saved['work']
    expected = tuple((x.entity_id, x.player_id, Zone.BOARD.value, BEETLE) for x in work.selected)
    matches = [e for e in effective_events(game._events) if e.sequence > saved['event'].sequence and
               e.source_id == work.request.source.entity_id and e.kind == 'cards_removed_from_game' and
               removal_result(e) == (expected, False)]
    if len(matches) != 1: raise ValueError('Reform lost its original simultaneous nondeath removal')
    if saved['root'] is not None:
        child = summon_record(game._state, saved['root'])
        if matches[0].sequence > child.event_cursor: raise ValueError('Reform summoned before original beetles retired')


def _receipts(game):
    from .hero_health_history import effective_events
    splits, groups, used_roots = {}, {}, set()
    for event in effective_events(game._events):
        data = dict(event.data)
        if event.kind == SPLIT_START:
            work = _load(game, data.get('work'))
            if type(work) is not SplitNythendra or work.ordinal or work.deathrattle_id in splits:
                raise ValueError('Split lost its unique original acceptance')
            if (event.amount != _split_total(game._state, game.registry, work) or
                    (event.source_id,event.player_id)!=(work.cause.source.entity_id,work.cause.player_id)):
                raise ValueError('Split changed original Attack or source')
            splits[work.deathrattle_id] = {'request':work, 'roots':[], 'done':False}
        elif event.kind in (SPLIT_STEP, SPLIT_DONE):
            saved = splits.get(data.get('deathrattle_id'))
            if saved is None or saved['done'] or data.get('ordinal') != len(saved['roots']): raise ValueError('Split receipt order changed')
            if event.kind == SPLIT_STEP:
                root_id = data.get('root_id'); child = summon_record(game._state, root_id); work = saved['request']
                pos = None if work.position is None else work.position + len(saved['roots'])
                if (root_id in used_roots or child.request != _child(work, BEETLE, pos) or child.event_cursor >= event.sequence or
                        len(saved['roots']) >= _split_total(game._state, game.registry, work)):
                    raise ValueError('Split borrowed another summon or exceeded original Attack')
                if saved['roots'] and summon_record(game._state, saved['roots'][-1]).status == 'active':
                    raise ValueError('Split overlapped unfinished original units')
                saved['roots'].append(root_id); used_roots.add(root_id)
            else:
                total = _split_total(game._state, game.registry, saved['request'])
                if (data.get('reason') not in ('exhausted','board_full') or
                        (data['reason'] == 'exhausted') != (len(saved['roots']) == total) or
                        any(summon_record(game._state, x).status == 'active' for x in saved['roots'])):
                    raise ValueError('Split lost its original stop obligation')
                saved['done'] = True
        elif event.kind == REFORM_START:
            work = _load(game, data.get('work'))
            if type(work) is not FinishNythendraReform or work.root_id is not None: raise ValueError('Invalid original reform acceptance')
            _validate_reform(game, work.request); work.__post_init__(); key = _key(work.request)
            if key in groups or (event.source_id,event.player_id)!=(work.request.source.entity_id,work.request.cause.player_id):
                raise ValueError('Reform duplicated or changed its original source')
            for ref in work.selected:
                e = game._state.entities.get(ref.entity_id)
                if e is None or ref.zone_epoch > e.zone_epoch or ref.entered_order >= game._state.next_order:
                    raise ValueError('Reform selected an unknown or future physical allocation')
            groups[key] = {'work':work, 'event':event, 'root':None, 'done':False}
        elif event.kind in (REFORM_CHILD, REFORM_DONE):
            saved = groups.get(tuple(data.get('key', ())))
            if saved is None or saved['done']: raise ValueError('Reform lost its original acceptance')
            root_id = data.get('root_id'); child = summon_record(game._state, root_id); work = saved['work']
            if child.request != _child(work.request, work.form_id, work.position): raise ValueError('Reform changed its native entry')
            if event.kind == REFORM_CHILD:
                if saved['root'] is not None or root_id in used_roots or child.event_cursor >= event.sequence:
                    raise ValueError('Reform duplicated or borrowed another original summon')
                saved['root'] = root_id; used_roots.add(root_id)
            else:
                if saved['root'] != root_id or child.status == 'active': raise ValueError('Reform finished before its complete entry')
                saved['done'] = True
    # A genuine executing split and its actual plain child entries cannot lose
    # the entire private producer ledger while the generic histories survive.
    for row in game._state.deathrattle_history:
        if row.capture.ability.behavior_id == SPLIT_BODY and row.completed and row.capture.id not in splits:
            raise ValueError('Completed split lost its original acceptance')
    for child in game._state.card_summon_history:
        m=child.request.materials
        native=(len(m)==1 and type(m[0]) is SummonEntryMaterial and
                (m[0].card_id==BEETLE and child.request.cause.source.card_id in FORMS.values() or
                 m[0].card_id in FORMS.values() and child.request.cause.source.card_id==BEETLE))
        if native and child.id not in used_roots:
            raise ValueError('Native beetle summon lost its original producer receipt')
    return splits, groups


def validate_boundary(game):
    if ROOT not in game.registry.cards and BEETLE not in game.registry.cards: return
    splits, groups = _receipts(game)
    frame = game._frame
    queue = (*frame.prefix, *frame.continuation) if frame else ()
    controls = tuple(w for w in queue if type(w) in (SplitNythendra, ReformNythendra, FinishNythendraReform))
    split_ids=[w.deathrattle_id for w in controls if type(w) is SplitNythendra]
    if len(split_ids)!=len(set(split_ids)): raise ValueError('Duplicate original split continuation')
    if frame:
        original = tuple(w for w in frame.paid_hand_choice_boundary.work if type(w) in (SplitNythendra, ReformNythendra, FinishNythendraReform))
        if controls != original: raise ValueError('Beetle work differs from its complete original choice boundary')
        def reject(value):
            if type(value) in (SplitNythendra, ReformNythendra, FinishNythendraReform): raise ValueError('Choice options cannot invent beetle control work')
            if type(value) in (tuple, list):
                for x in value: reject(x)
            elif is_dataclass(value):
                for f in fields(value): reject(getattr(value, f.name))
        reject(frame.options)
    for w in controls:
        if type(w) is SplitNythendra:
            _split_total(game._state, game.registry, w)
            saved = splits.get(w.deathrattle_id)
            if saved is None and w.ordinal: raise ValueError('Orphan split continuation')
            if saved is None:
                from .deathrattles import record
                row=record(game._state,w.deathrattle_id)
                if row.completed or row.interrupted:raise ValueError('Settled Deathrattle cannot start another split')
            if saved and (saved['done'] or replace(w, ordinal=0) != saved['request'] or w.ordinal != len(saved['roots'])):
                raise ValueError('Split continuation changed original units')
        elif type(w) is ReformNythendra: _validate_reform(game, w)
        else:
            saved = groups.get(_key(w.request))
            if saved is None or saved['done'] or w != replace(saved['work'], root_id=saved['root']):
                raise ValueError('Orphan or altered reform completion')
    terminal = game._state.status in ('finished', 'draw')
    for identity, saved in splits.items():
        owed = [w for w in controls if type(w) is SplitNythendra and w.deathrattle_id == identity]
        if (not saved['done'] and not terminal and len(owed) != 1) or (saved['done'] and owed): raise ValueError('Split lost its remaining original work')
    for key, saved in groups.items():
        if saved['root'] is not None or saved['done']: _removed(game, saved)
        owed = [w for w in controls if type(w) is FinishNythendraReform and _key(w.request) == key]
        if (not saved['done'] and not terminal and len(owed) != 1) or (saved['done'] and owed): raise ValueError('Reform lost its remaining original work')


def register(mechanics):
    mechanics.register(SplitNythendra, split)
    mechanics.register(ReformNythendra, reform)
    mechanics.register(FinishNythendraReform, finish_reform)
