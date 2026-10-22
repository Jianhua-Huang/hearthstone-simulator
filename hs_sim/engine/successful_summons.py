"""Immutable successful minion entries, published by the original interpreter.

The original minion_summoned event is authoritative, including an ordinary
minion play. Producer acceptance/attempts and initial scenario boards are not
occurrences. Queries never scan the host log or maintain a player counter.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .model import CardType, DeathRecord, Event, Keyword, TribeChangeSpec, Zone, _int
from .tribes import TribeState, apply_change, tribe_changes, tribe_state_for
from .effects import Effect

ENTRY_STATS_KEY = '_entry_stats'
ENTRY_DEATHRATTLES_KEY = '_entry_deathrattles'


def publication_stats(state,entity_id,data):
    """Freeze actual board-entry attributes at the original publication point."""
    if ENTRY_STATS_KEY in data or ENTRY_DEATHRATTLES_KEY in data:
        raise ValueError('Entry stats belong to the original summon publisher')
    entity=state.entities.get(entity_id)
    if entity is None or entity.kind!=CardType.MINION or entity.zone!=Zone.BOARD:
        raise ValueError('Entry stats require an actual original board minion')
    return {ENTRY_STATS_KEY:(entity.attack,entity.health,entity.max_health),
        ENTRY_DEATHRATTLES_KEY:tuple(a.id for a in entity.abilities if a.kind=='deathrattle' and not a.consumed)}


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
    entry_attack: int
    entry_health: int
    entry_max_health: int
    reborn_death_id: int | None = None
    deathrattle_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.deathrattle_ids)is not tuple or len(set(self.deathrattle_ids))!=len(self.deathrattle_ids):
            raise ValueError('Successful entry requires its distinct original Deathrattle declarations')
        for identity in self.deathrattle_ids:_int(identity,'original entry Deathrattle',1)
        _int(self.entry_attack,'actual entry Attack',0)
        _int(self.entry_max_health,'actual entry maximum Health')
        _int(self.entry_health,'actual entry remaining Health')
        if self.entry_health>self.entry_max_health:
            raise ValueError('Entry remaining Health exceeds its original maximum')
        if self.reborn_death_id is not None:
            _int(self.reborn_death_id, 'original successful Reborn death', 1)
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


def _validate_reborn_death(row, death):
    if type(death) is not DeathRecord:
        raise ValueError('Successful Reborn lost its actual original death')
    death.__post_init__()
    if (row.reborn_death_id != death.id or death.zone != Zone.BOARD or
            death.card_id != row.card_id or death.controller != row.player_id or
            row.minion.owner != row.player_id or Keyword.REBORN not in death.keywords or
            death.turn > row.turn or death.entity_id >= row.entity_id or
            death.cause.target_entered_order >= row.minion.entered_order):
        raise ValueError('Successful Reborn changed its original death or returned body')


def validate_state(state, registry=None):
    rows = state.successful_summon_history
    _int(state.next_successful_summon_id, 'next successful summon ID', 1)
    if type(rows) is not list or state.next_successful_summon_id != len(rows) + 1:
        raise ValueError('Successful summon history lost its complete allocation cursor')
    last_turn = last_action = last_event = 0
    seen = set()
    deaths = None
    for index, row in enumerate(rows, 1):
        if type(row) is not SuccessfulSummonRecord:
            raise ValueError('Successful summon history requires immutable typed occurrences')
        row.__post_init__()
        if any(identity>=state.next_attachment_id for identity in row.deathrattle_ids):
            raise ValueError("Successful entry borrowed a future Deathrattle allocation")
        if row.reborn_death_id is not None:
            if deaths is None:
                deaths = {d.id: d for d in state.death_history}
            _validate_reborn_death(row, deaths.get(row.reborn_death_id))
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


def successful_reborns(state, player_id):
    """Original successful Reborn entries for their original receiving player."""
    return tuple(row for row in summoned_minions(state, player_id) if row.reborn_death_id is not None)


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
    data = dict(event.data)
    original=data.get(ENTRY_DEATHRATTLES_KEY)
    if type(original)not in(tuple,list)or tuple(original)!=row.deathrattle_ids or any(type(i)is not int for i in original):
        raise ValueError('Successful entry changed its original published Deathrattle declarations')
    stats=data.get(ENTRY_STATS_KEY)
    if (type(stats)not in(tuple,list)or len(stats)!=3 or any(type(v)is not int for v in stats)or
            tuple(stats)!=(row.entry_attack,row.entry_health,row.entry_max_health)):
        raise ValueError('Successful summon changed its original published entry stats')
    if 'reborn_from' in data:
        _int(data['reborn_from'], 'original Reborn parent', 1)
        _int(data.get('death_id'), 'original Reborn death', 1)
        if ('copied_from' in data or 'resurrected_from' in data or
                row.reborn_death_id != data['death_id']):
            raise ValueError('Successful Reborn changed its original publication kind')
    elif row.reborn_death_id is not None:
        raise ValueError('An ordinary successful summon cannot claim Reborn')


def commit(r, event):
    """One hook after the original successful event, before listener capture.

This records success and the entry stats frozen by the original publisher; it
does not create/move a minion, resolve a body or introduce a checkpoint. Failed/canceled paths stay owned
by their original executors.
"""
    state = r.state
    data = dict(event.data)
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
        tribe_state_for(r.registry, entity.card_id, tribe_changes(entity)),
        entity.attack, entity.health, entity.max_health,
        data.get('death_id') if 'reborn_from' in data else None,
        tuple(a.id for a in entity.abilities if a.kind=='deathrattle' and not a.consumed))
    _validate_event(row, event)
    if row.reborn_death_id is not None:
        death = next((d for d in state.death_history if d.id == row.reborn_death_id), None)
        _validate_reborn_death(row, death)
        if data['reborn_from'] != death.entity_id or entity.origin_entity_id != death.entity_id:
            raise ValueError('Successful Reborn borrowed another original minion')
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
    timeline = tuple(effective_events(game._events))
    events = tuple(e for e in timeline if e.kind == 'minion_summoned')
    if len(events) != len(state.successful_summon_history):
        raise ValueError('Successful summon history lost its complete original event inventory')
    for row, event in zip(state.successful_summon_history, events):
        _validate_event(row, event)
    reborns = tuple(row for row in state.successful_summon_history if row.reborn_death_id is not None)
    actual = tuple(event for event in timeline if event.kind == 'minion_reborn')
    if len(reborns) != len(actual):
        raise ValueError('Successful Reborn lost its complete actual event inventory')
    deaths = {d.id: d for d in state.death_history} if reborns else {}
    original_events = {event.sequence: event for event in events} if reborns else {}
    for row, event in zip(reborns, actual):
        death = deaths[row.reborn_death_id]
        if ((event.source_id, event.target_id, event.player_id, event.action, dict(event.data).get('death_id')) !=
                (death.entity_id, row.entity_id, row.player_id, row.action, row.reborn_death_id) or
                event.sequence <= row.event_sequence):
            raise ValueError('Successful Reborn changed its original returned-body event')
        original = original_events[row.event_sequence]
        if dict(original.data)['reborn_from'] != death.entity_id:
            raise ValueError('Successful Reborn changed its original parent death')


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
    row['deathrattle_ids'] = tuple(_list(row['deathrattle_ids'],'original entry Deathrattles'))
    return SuccessfulSummonRecord(**row)


def rows_from_dict(value):
    from .serialization import _list, _integer
    _integer(value['next_successful_summon_id'], 'next successful summon ID', 1)
    value['successful_summon_history'] = [record_from_dict(item)
        for item in _list(value['successful_summon_history'], 'successful summon history')]
