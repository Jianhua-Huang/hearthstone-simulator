"""Immutable successful minion entries, published by the original interpreter.

The original minion_summoned event is authoritative, including an ordinary
minion play. Producer acceptance/attempts and initial scenario boards are not
occurrences. Queries never scan the host log or maintain a player counter.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .model import CardType, Event, Keyword, TribeChangeSpec, Zone, _int
from .tribes import TribeState, apply_change, tribe_changes, tribe_state_for
from .effects import Effect


@dataclass(frozen=True)
class BuffSummonedMinion(Effect):
    """Reward the original successful entry, never a later reused entity ID."""
    player_id: int
    summon_id: int
    source_id: int
    attack: int = 0
    health: int = 0

    def __post_init__(self):
        for name in ('player_id','summon_id','source_id'):_int(getattr(self,name),'summon reward '+name,1)
        if self.player_id not in(1,2):raise ValueError('Invalid original summon reward player')
        _int(self.attack,'summon reward attack',0);_int(self.health,'summon reward health',0)

    def validate_in_state(self,state):
        self.__post_init__()
        if self.source_id not in state.entities:raise ValueError('Summon reward has an unknown original source')
        if self.summon_id>len(state.successful_summon_history):raise ValueError('Summon reward has an unknown original entry')
        row=state.successful_summon_history[self.summon_id-1];row.__post_init__()
        if(row.id,row.player_id)!=(self.summon_id,self.player_id)or row.turn>state.turn or row.action>state.action_number:
            raise ValueError('Summon reward changed its original entry or player')


def buff_summoned_minion(r,effect):
    from .effects import Buff
    from .resolver import buff
    target=original_recipient(r,effect)
    if target is None:
        r.stale(effect,r.state.successful_summon_history[effect.summon_id-1].entity_id);return ()
    buff(r,Buff(target.id,effect.attack,effect.health,effect.source_id))
    return ()


def original_recipient(r,effect):
    from .board_presence import resolve_board_presence
    from .model import BoardPresenceReference
    effect.validate_in_state(r.state)
    row=r.state.successful_summon_history[effect.summon_id-1]
    validate_allocation(r.state,r.registry,row.minion)
    target=resolve_board_presence(r.state,BoardPresenceReference(row.entity_id,row.minion.entered_order))
    if target is None or not target.active or target.health<=0 or target.doomed:
        return None
    return target


@dataclass(frozen=True)
class GrantSummonedKeyword(Effect):
    player_id:int
    summon_id:int
    source_id:int
    keyword:Keyword

    def __post_init__(self):
        BuffSummonedMinion(self.player_id,self.summon_id,self.source_id).__post_init__()
        if type(self.keyword)is not Keyword or self.keyword not in(Keyword.RUSH,Keyword.REBORN):
            raise ValueError('Original summon keyword reward supports Rush or Reborn')

    def validate_in_state(self,state):
        self.__post_init__();BuffSummonedMinion(self.player_id,self.summon_id,self.source_id).validate_in_state(state)


def grant_summoned_keyword(r,effect):
    from .effects import GrantKeyword
    from .resolver import grant_ability
    target=original_recipient(r,effect)
    if target is None:
        r.stale(effect,r.state.successful_summon_history[effect.summon_id-1].entity_id);return ()
    grant_ability(r,GrantKeyword(target.id,effect.keyword,effect.source_id))
    return ()


@dataclass(frozen=True)
class DamageSummonedMinion(Effect):
    player_id:int
    summon_id:int
    source_id:int
    amount:int

    def __post_init__(self):
        BuffSummonedMinion(self.player_id,self.summon_id,self.source_id).__post_init__()
        _int(self.amount,'original summon damage amount',0)

    def validate_in_state(self,state):
        self.__post_init__();BuffSummonedMinion(self.player_id,self.summon_id,self.source_id).validate_in_state(state)
        if state.entities[self.source_id].kind!=CardType.MINION:raise ValueError('Original summon damage requires a minion ability source')


def damage_summoned_minion(r,effect):
    from .effects import Damage
    from .model import DamageKind
    target=original_recipient(r,effect)
    if target is None:
        r.stale(effect,r.state.successful_summon_history[effect.summon_id-1].entity_id);return()
    return(Damage(target.id,effect.amount,effect.source_id,DamageKind.MINION_ABILITY),)


@dataclass(frozen=True)
class SuccessfulSummonRecord:
    id: int
    player_id: int
    active_player: int
    turn: int
    action: int
    event_sequence: int
    minion: SourceAllocationFact
    printed_tribes: TribeState | None
    tribe_changes: tuple[TribeChangeSpec, ...]
    tribes: TribeState | None

    def __post_init__(self):
        for name in ('id', 'player_id', 'active_player', 'turn', 'event_sequence'):
            _int(getattr(self, name), 'successful summon ' + name, 1)
        _int(self.action, 'successful summon action', 0)
        if self.player_id not in (1, 2) or self.active_player not in (1, 2):
            raise ValueError('Successful summon requires its original players')
        if type(self.minion) is not SourceAllocationFact:
            raise ValueError('Successful summon requires its complete physical allocation')
        self.minion.__post_init__()
        if (self.minion.kind, self.minion.zone, self.minion.controller) != (
                CardType.MINION, Zone.BOARD, self.player_id) or self.minion.entered_order < 1:
            raise ValueError('Successful summon belongs to its original board controller')
        for tribes in (self.printed_tribes, self.tribes):
            if tribes is not None:
                if type(tribes) is not TribeState:
                    raise ValueError('Successful summon requires frozen known or unknown tribes')
                tribes.__post_init__()
        if type(self.tribe_changes) is not tuple or any(type(c) is not TribeChangeSpec for c in self.tribe_changes):
            raise ValueError('Successful summon requires its ordered original tribe declarations')
        current = self.printed_tribes
        for change in self.tribe_changes:
            change.__post_init__()
            current = apply_change(current, change)
        if current != self.tribes:
            raise ValueError('Successful summon changed its complete original tribe basis')

    @property
    def entity_id(self):
        return self.minion.entity_id

    @property
    def card_id(self):
        return self.minion.card_id


def validate_state(state, registry=None):
    rows = state.successful_summon_history
    _int(state.next_successful_summon_id, 'next successful summon ID', 1)
    if type(rows) is not list or state.next_successful_summon_id != len(rows) + 1:
        raise ValueError('Successful summon history lost its complete allocation cursor')
    last_turn = last_action = last_event = 0
    seen = set()
    for index, row in enumerate(rows, 1):
        if type(row) is not SuccessfulSummonRecord:
            raise ValueError('Successful summon history requires immutable typed occurrences')
        row.__post_init__()
        allocation = row.minion
        if (row.id != index or not last_turn <= row.turn <= state.turn or
                not last_action <= row.action <= state.action_number or row.event_sequence <= last_event):
            raise ValueError('Successful summon history changed its original chronology')
        identity = (row.entity_id, allocation.zone_epoch, allocation.entered_order)
        if identity in seen:
            raise ValueError('A physical entry cannot publish two successful summons')
        if registry is not None:
            validate_allocation(state, registry, allocation)
            if tribe_state_for(registry, row.card_id, basis='printed') != row.printed_tribes:
                raise ValueError('Successful summon changed its pinned original printed tribes')
        else:
            entity = state.entities.get(row.entity_id)
            if (entity is None or entity.owner != allocation.owner or
                    allocation.next_entity_id > state.next_entity_id or allocation.next_order > state.next_order or
                    allocation.zone_epoch > entity.zone_epoch):
                raise ValueError('Successful summon borrowed an unknown or future physical allocation')
        seen.add(identity)
        last_turn, last_action, last_event = row.turn, row.action, row.event_sequence


def summoned_minions(state, player_id, *, tribes=(), basis='current', turn=None):
    """Ordered actual entries for their original board controller, not the actor.

Unknown tribes are valid facts. A filtered query cannot silently treat them as
nonmatches; unrelated players/turns are outside that query's matching scope.
"""
    _int(player_id, 'successful summon query player', 1)
    if player_id not in (1, 2):
        raise ValueError('Invalid successful summon query player')
    TribeChangeSpec('set', tribes).__post_init__()
    if type(basis) is not str or basis not in ('printed', 'current'):
        raise ValueError('Successful summon query requires an explicit tribe basis')
    if turn is not None:
        _int(turn, 'successful summon query turn', 1)
    validate_state(state)
    return _matching_rows(state.successful_summon_history, player_id, tribes, basis, turn)


def _matching_rows(records, player_id, tribes, basis, turn):
    """Shared selection after the caller validates its State or frozen operand."""
    result = []
    for row in records:
        if row.player_id != player_id or turn is not None and row.turn != turn:
            continue
        captured = row.tribes if basis == 'current' else row.printed_tribes
        if tribes:
            if captured is None:
                from .registry import UnsupportedDefinitionError
                raise UnsupportedDefinitionError('Unknown original ' + basis + ' summon tribes: ' + row.card_id)
            if not captured.matches_any(tribes):
                continue
        result.append(row)
    return tuple(result)


def summon_count(state, player_id, *, tribes=(), basis='current', turn=None):
    return len(summoned_minions(state, player_id, tribes=tribes, basis=basis, turn=turn))


def _validate_event(row, event):
    if type(event) is not Event:
        raise ValueError('Successful summon requires its original event')
    for name in ('sequence', 'source_id', 'target_id', 'player_id'):
        _int(getattr(event, name), 'successful summon event ' + name, 1)
    for name in ('action', 'amount'):
        _int(getattr(event, name), 'successful summon event ' + name, 0)
    if (event.kind, event.sequence, event.action,
            event.source_id, event.target_id, event.player_id, event.amount) != (
            'minion_summoned', row.event_sequence, row.action,
            row.entity_id, row.entity_id, row.player_id, 0):
        raise ValueError('Successful summon differs from its original physical publication')


def commit(r, event):
    """One hook after the original successful event, before listener capture.

This records success; it does not create/move a minion, resolve a body, change
the event payload or introduce a checkpoint. Failed/canceled paths stay owned
by their original executors.
"""
    state = r.state
    entity = state.entities.get(event.target_id)
    if (entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or
            entity.id not in state.players[entity.controller].board or
            event.sequence != len(r.game._events) + 1 or
            state.next_successful_summon_id != len(state.successful_summon_history) + 1):
        raise ValueError('Successful summon lost its original committed board entry')
    row = SuccessfulSummonRecord(state.next_successful_summon_id, event.player_id,
        state.active_player, state.turn, state.action_number, event.sequence,
        SourceAllocationFact.capture(state, entity), tribe_state_for(r.registry, entity.card_id, basis='printed'),
        tuple(change.tribe_change for change in tribe_changes(entity)),
        tribe_state_for(r.registry, entity.card_id, tribe_changes(entity)))
    _validate_event(row, event)
    identity = (row.entity_id, row.minion.zone_epoch, row.minion.entered_order)
    if any((old.entity_id, old.minion.zone_epoch, old.minion.entered_order) == identity
            for old in state.successful_summon_history):
        raise ValueError('A physical entry cannot publish two successful summons')
    state.successful_summon_history.append(row)
    state.next_successful_summon_id += 1


def validate_boundary(game):
    state = game._state
    validate_state(state, game.registry)
    from .hero_health_history import effective_events
    events = tuple(e for e in effective_events(game._events) if e.kind == 'minion_summoned')
    if len(events) != len(state.successful_summon_history):
        raise ValueError('Successful summon history lost its complete original event inventory')
    for row, event in zip(state.successful_summon_history, events):
        _validate_event(row, event)


def _tribes_from_dict(value):
    if value is None:
        return None
    from .serialization import _row, _list
    row = _row(value, TribeState)
    for name in ('members', 'excluded'):
        row[name] = tuple(_list(row[name], 'original summon tribes ' + name))
    return TribeState(**row)


def record_from_dict(value):
    from .serialization import _row, _list
    row = _row(value, SuccessfulSummonRecord)
    row['minion'] = allocation_from_dict(row['minion'])
    row['printed_tribes'] = _tribes_from_dict(row['printed_tribes'])
    row['tribes'] = _tribes_from_dict(row['tribes'])
    changes = []
    for item in _list(row['tribe_changes'], 'original summon tribe declarations'):
        change = _row(item, TribeChangeSpec)
        change['tribes'] = tuple(_list(change['tribes'], 'original summon change tribes'))
        changes.append(TribeChangeSpec(**change))
    row['tribe_changes'] = tuple(changes)
    return SuccessfulSummonRecord(**row)


def rows_from_dict(value):
    from .serialization import _list, _integer
    _integer(value['next_successful_summon_id'], 'next successful summon ID', 1)
    value['successful_summon_history'] = [record_from_dict(item)
        for item in _list(value['successful_summon_history'], 'successful summon history')]
