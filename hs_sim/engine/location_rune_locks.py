"""One finite in-play Rune gate, independent of ordinary location cooldown."""
from dataclasses import dataclass, fields, replace

from .model import CardType, Zone, _int, _name

RULE = 'location.runes-after-entry-v1'
BIRTH = 'location_rune_lock_entered'
PROGRESS = 'location_rune_lock_progress'


@dataclass(frozen=True)
class LocationRuneStep:
    play_id: int
    controller: int
    player_id: int
    runes: tuple[int, int, int]

    def __post_init__(self):
        _int(self.play_id, 'location Rune original play', 1)
        for pid in (self.controller, self.player_id):
            _int(pid, 'location Rune player', 1)
            if pid not in (1, 2): raise ValueError('Invalid location Rune player')
        if type(self.runes) is not tuple or len(self.runes) != 3:
            raise ValueError('Location Rune step requires all three original Rune counts')
        for value in self.runes: _int(value, 'original printed Rune count', 0)


@dataclass(frozen=True)
class LocationRuneLock:
    entity_id: int
    card_id: str
    zone_epoch: int
    entry_order: int
    start_play_id: int
    controller_at_entry: int
    steps: tuple[LocationRuneStep, ...] = ()

    def __post_init__(self):
        for name in ('entity_id', 'entry_order', 'start_play_id'): _int(getattr(self, name), 'location lock '+name, 1)
        _int(self.zone_epoch, 'location lock epoch', 0); _name(self.card_id, 'location lock original card')
        _int(self.controller_at_entry, 'location lock original controller', 1)
        if self.controller_at_entry not in (1, 2): raise ValueError('Invalid original location lock controller')
        if type(self.steps) is not tuple or any(type(s) is not LocationRuneStep for s in self.steps):
            raise ValueError('Location lock requires complete immutable original play steps')
        for step in self.steps: step.__post_init__()
        if tuple(s.play_id for s in self.steps) != tuple(range(self.start_play_id, self.start_play_id+len(self.steps))):
            raise ValueError('Location lock lost or duplicated an original in-play hand root')
        seen = [False, False, False]
        for step in self.steps:
            if all(seen): raise ValueError('A completed first-use lock cannot keep accepting plays')
            if step.player_id == step.controller:
                seen = [old or value > 0 for old, value in zip(seen, step.runes)]

    @property
    def origin(self):
        return (self.entity_id, self.card_id, self.zone_epoch, self.entry_order,
            self.start_play_id, self.controller_at_entry)

    @property
    def open(self): return unlocked(self.steps)


def unlocked(steps):
    return all(any(s.player_id == s.controller and s.runes[i] > 0 for s in steps) for i in range(3))


def original_runes(record, controller):
    metadata = record.played_face.metadata
    if metadata is None:
        if record.player_id != controller: return (0, 0, 0)
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Original played Rune metadata is unknown for an in-play location lock')
    return (0, 0, 0) if metadata.runes is None else (
        metadata.runes.blood, metadata.runes.frost, metadata.runes.unholy)


def initialize(state, registry, entity):
    entity.location_lock = None
    if entity.zone == Zone.BOARD and entity.kind == CardType.LOCATION and registry.card(entity.card_id).use_rule == RULE:
        entity.location_lock = LocationRuneLock(entity.id, entity.card_id, entity.zone_epoch,
            entity.entered_order, len(state.play_history)+1, entity.controller)


def publish_birth(r, entity):
    lock = entity.location_lock
    if lock is not None:
        r.emit(BIRTH, source_id=entity.id, target_id=entity.id, player_id=entity.controller,
            origin=lock.origin, _capture=False)


def note_play(state, record):
    updates = []
    for entity in state.entities.values():
        lock = entity.location_lock
        if entity.zone != Zone.BOARD or lock is None or lock.open: continue
        step = LocationRuneStep(record.id, entity.controller, record.player_id, original_runes(record, entity.controller))
        entity.location_lock = replace(lock, steps=(*lock.steps, step))
        updates.append((entity.location_lock.origin, step))
    return tuple(updates)


def publish_progress(r, record, updates):
    if not updates: return
    from .remaining_mana_numbers import payment_window
    # These synchronous admission notifications precede physical hand exit.
    # Preserve the accepted source's numbers just as in the original debit.
    with payment_window(r, record.source_id):
        for origin, step in updates:
            r.emit(PROGRESS, source_id=record.source_id, target_id=origin[0], player_id=record.player_id,
                origin=origin, step=(step.play_id, step.controller, step.player_id, *step.runes), _capture=False)
            entity = r.state.entities[origin[0]]
            if entity.location_lock.open and not entity.location_cooldown and entity.durability > 0 and not entity.doomed:
                r.emit('location_opened', source_id=entity.id, target_id=entity.id,
                    player_id=entity.controller, reason='runes_completed', cooldown=0)


def is_locked(entity):
    return entity.location_lock is not None and not entity.location_lock.open


def register_rule(registry):
    registry.register_use_rule(RULE, lambda c: c.source['location']['open'], visibility='player')


def from_dict(value):
    if value is None: return None
    if type(value) is not dict or set(value) != {f.name for f in fields(LocationRuneLock)}:
        raise ValueError('Location lock requires its complete original fields')
    row = dict(value)
    if type(row['steps']) is not list: raise ValueError('Location lock steps must be an encoded list')
    steps = []
    for raw in row['steps']:
        if type(raw) is not dict or set(raw) != {f.name for f in fields(LocationRuneStep)} or type(raw['runes']) is not list:
            raise ValueError('Location lock lost a complete original Rune step')
        steps.append(LocationRuneStep(raw['play_id'], raw['controller'], raw['player_id'], tuple(raw['runes'])))
    row['steps'] = tuple(steps)
    return LocationRuneLock(**row)


def validate_step(state, step):
    step.__post_init__()
    if step.play_id > len(state.play_history): raise ValueError('Location lock borrowed a future hand root')
    record = state.play_history[step.play_id-1]
    if (step.player_id, step.runes) != (record.player_id, original_runes(record, step.controller)):
        raise ValueError('Location lock changed its original frozen played Rune face')


def validate_state(state, registry):
    for entity in state.entities.values():
        lock = entity.location_lock
        required = entity.zone == Zone.BOARD and entity.kind == CardType.LOCATION and registry.card(entity.card_id).use_rule == RULE
        if lock is None:
            if required: raise ValueError('Native Rune-locked location lost its original in-play lock')
            continue
        if not required or type(lock) is not LocationRuneLock: raise ValueError('Location lock escaped its original declared board carrier')
        lock.__post_init__()
        if (lock.entity_id, lock.card_id, lock.zone_epoch) != (entity.id, entity.card_id, entity.zone_epoch):
            raise ValueError('Location lock borrowed another original incarnation')
        if lock.entry_order > entity.entered_order or lock.entry_order >= state.next_order or lock.start_play_id > len(state.play_history)+1:
            raise ValueError('Location lock borrowed a future entry or history cursor')
        for step in lock.steps: validate_step(state, step)
        if not lock.open and lock.start_play_id+len(lock.steps) != len(state.play_history)+1:
            raise ValueError('Incomplete original Rune lock omitted an accepted hand root')


def validate_boundary(game):
    state, registry = game._state, game.registry
    births = {}; steps = {}
    for event in game._events:
        if event.kind not in (BIRTH, PROGRESS): continue
        data = dict(event.data)
        if set(data) != ({'origin'} if event.kind == BIRTH else {'origin', 'step'}):
            raise ValueError('Location Rune event lost its complete private receipt')
        origin = data['origin']
        if type(origin) not in (tuple, list) or len(origin) != 6: raise ValueError('Location lock event lost its original entry')
        lock = LocationRuneLock(*origin); key = lock.origin
        if (lock.entity_id not in state.entities or lock.entry_order >= state.next_order or
                lock.start_play_id > len(state.play_history)+1 or
                lock.zone_epoch > state.entities[lock.entity_id].zone_epoch or registry.card(lock.card_id).use_rule != RULE):
            raise ValueError('Location lock event borrowed an undeclared or future source')
        if event.kind == BIRTH:
            if key in births or (event.source_id, event.target_id, event.player_id) != (lock.entity_id, lock.entity_id, lock.controller_at_entry):
                raise ValueError('Location lock entry receipt was duplicated or rebound')
            if event.action == 0 and lock.start_play_id != 1:
                raise ValueError('Initial scenario location invented pre-entry hand history')
            births[key] = event.sequence; steps[key] = []
        else:
            if key not in births or event.sequence <= births[key]: raise ValueError('Location Rune progress lost its original entry receipt')
            raw = data['step']
            if type(raw) not in (tuple, list) or len(raw) != 6: raise ValueError('Location Rune progress lost its original hand root')
            step = LocationRuneStep(*raw[:3], tuple(raw[3:])); validate_step(state, step)
            record = state.play_history[step.play_id-1]
            if (event.source_id, event.target_id, event.player_id, event.action) != (
                    record.source_id, lock.entity_id, record.player_id, record.action):
                raise ValueError('Location Rune receipt changed its actual paid hand envelope')
            steps[key].append(step); LocationRuneLock(*origin, tuple(steps[key]))
    for entity in state.entities.values():
        lock = entity.location_lock
        if lock is not None and (lock.origin not in births or tuple(steps[lock.origin]) != lock.steps):
            raise ValueError('Location lock changed or lost its original entry/progress receipts')
