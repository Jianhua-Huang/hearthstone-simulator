"""Dormancy lifecycle and serializable countdown work (provisional R-040/041)."""
from dataclasses import dataclass, replace

from .effects import Buff, Effect, _integer, _source
from .errors import ResolutionError
from .lifecycle import active_abilities, attachment_id
from .model import CardType, DormancyState, Zone
from .sacrifice import MinionReference, reference_value, same_instance


@dataclass(frozen=True)
class MakeDormant(Effect):
    target_id: int
    turns: int | None
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _source(self.source_id)
        if self.turns is not None:
            _integer(self.turns, 'turns', 1)


@dataclass(frozen=True)
class AwakenMinion(Effect):
    target_id: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _source(self.source_id)


@dataclass(frozen=True)
class AwakenCapturedMinion(Effect):
    reference: MinionReference
    dormancy_id: int
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.reference)
        _integer(self.dormancy_id,'original dormancy instance',1)
        _source(self.source_id)


@dataclass(frozen=True)
class GrowDormantMinion(Effect):
    """Self-growth belonging to one captured physical dormancy interval."""
    reference: MinionReference
    dormancy_id: int
    attack: int
    health: int

    def __post_init__(self):
        reference_value(self.reference)
        _integer(self.dormancy_id, 'original dormancy instance', 1)
        _integer(self.attack, 'dormant attack growth', 0)
        _integer(self.health, 'dormant health growth', 0)
        if not (self.attack or self.health):
            raise ValueError('Dormant self-growth requires a positive stat delta')


@dataclass(frozen=True)
class AdvanceDormancy(Effect):
    target_id: int
    turns: int = 1
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.turns, 'turns', 1)
        _source(self.source_id)


@dataclass(frozen=True)
class AdvanceCapturedDormancy(Effect):
    """Advance only the original physical receiver's accepted dormancy."""
    reference: MinionReference
    dormancy_id: int
    turns: int = 1
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.reference)
        _integer(self.dormancy_id, 'original dormancy instance', 1)
        _integer(self.turns, 'captured countdown turns', 1)
        _source(self.source_id)


@dataclass(frozen=True)
class TickDormancy(Effect):
    target_id: int
    dormancy_id: int
    player_id: int

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.dormancy_id, 'dormancy_id', 1)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid countdown player')


def _target(r, effect, *, dormant):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Dormancy effect source does not exist')
    entity = r.state.entities.get(effect.target_id)
    if (entity is None or entity.zone != Zone.BOARD or entity.starship_building or
            (entity.dormancy is not None) != dormant):
        r.stale(effect, effect.target_id)
        return None
    if entity.kind != CardType.MINION:
        raise ResolutionError('Dormancy requires a minion')
    if not dormant and (entity.doomed or entity.health <= 0):
        r.stale(effect, entity.id)
        return None
    return entity


def make_dormant(r, effect, *, deathrattle_memory=None):
    entity = _target(r, effect, dormant=False)
    if entity is None:
        return
    entity.dormancy = DormancyState(attachment_id(r.state), effect.turns, r.state.turn)
    if deathrattle_memory is not None:
        from .deathrattle_memory import remember_dormancy
        remember_dormancy(r,deathrattle_memory,entity)
    r.refresh_auras()
    r.emit('minion_dormant', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller, remaining_turns=effect.turns)


def awaken(r, effect):
    entity = _target(r, effect, dormant=True)
    if entity is None:
        return
    if entity.dormancy.permanent:
        r.stale(effect, entity.id)
        return
    entity.dormancy = None
    # Awakening grants no new entity, summon, battlecry, or attack allowance.
    entity.summoned_turn = r.state.turn
    r.refresh_auras()
    event = r.emit('minion_awakened', source_id=effect.source_id, target_id=entity.id,
                   player_id=entity.controller)
    return [r.call(a.behavior_id, entity.id, entity.controller, event=event)
            for a in active_abilities(entity, 'on_awaken')]


def awaken_captured(r,effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Captured awakening source does not exist')
    entity=same_instance(r.state,effect.reference)
    if entity is None or entity.dormancy is None or entity.dormancy.id!=effect.dormancy_id:
        r.stale(effect,effect.reference.entity_id)
        return ()
    return awaken(r,AwakenMinion(entity.id,effect.source_id))


def grow_dormant(r, effect):
    effect.__post_init__()
    entity = same_instance(r.state, effect.reference)
    if (entity is None or entity.starship_building or entity.dormancy is None or
            entity.dormancy.id != effect.dormancy_id):
        r.stale(effect, effect.reference.entity_id)
        return ()
    # Ordinary Buff deliberately rejects dormant targets. This finite self
    # entry only bypasses that eligibility gate; attachment/stat/lifecycle and
    # stats_changed reactions remain owned by the ordinary installer.
    from .resolver import _buff_to
    _buff_to(r, Buff(entity.id, effect.attack, effect.health, entity.id), entity)


def advance(r, effect):
    entity = _target(r, effect, dormant=True)
    if entity is None:
        return
    remaining = entity.dormancy.remaining_turns
    if remaining is None:
        return
    if effect.turns >= remaining:
        # Transition now, so a countdown reaction cannot accidentally awaken a
        # newly installed dormancy instance using an old queued AwakenMinion.
        return awaken(r, AwakenMinion(entity.id, effect.source_id))
    entity.dormancy = replace(entity.dormancy, remaining_turns=remaining - effect.turns)
    r.emit('dormancy_progressed', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller, remaining_turns=entity.dormancy.remaining_turns)


def tick(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if (entity is None or entity.zone != Zone.BOARD or entity.controller != effect.player_id or
            entity.dormancy is None or entity.dormancy.id != effect.dormancy_id):
        return
    return advance(r, AdvanceDormancy(entity.id))


def advance_captured(r, effect):
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Captured countdown source does not exist')
    entity = same_instance(r.state, effect.reference)
    if entity is None or entity.dormancy is None or entity.dormancy.id != effect.dormancy_id:
        r.stale(effect, effect.reference.entity_id)
        return ()
    return advance(r, AdvanceDormancy(entity.id, effect.turns, effect.source_id))


def turn_countdowns(r, player):
    # Freeze eligibility before turn-start callbacks. New or replaced dormancy
    # instances in those callbacks wait until a later controller turn.
    return [TickDormancy(i, r.state.entities[i].dormancy.id, player.id)
            for i in r.rules.entity_order(r.state, player.board)
            if r.state.entities[i].dormancy is not None and
            r.state.entities[i].dormancy.remaining_turns is not None]


def validate_board_full_carrier(registry, card_id, kind, abilities):
    rows = tuple(a for a in abilities if a.kind == 'board_full_awaken')
    if rows and (kind != CardType.MINION or not registry.card(card_id).dormant_board_full):
        raise ValueError('Full-board awakening borrowed an undeclared printed carrier')
    for ability in rows:
        ability.__post_init__()


def capture_board_full(r):
    """Accept one existing awaken request per original physical dormancy.

    Pending work already carries the receipt through choices and snapshots;
    no extra unsaved set or event-name subscription matrix is required.
    """
    candidates = []
    for player in r.state.players.values():
        if len(player.board) < r.rules.max_board:
            continue
        for entity_id in player.board:
            entity = r.state.entities[entity_id]
            if (entity.kind != CardType.MINION or entity.dormancy is None or entity.dormancy.permanent or
                    entity.health <= 0 or entity.doomed or not active_abilities(entity, 'board_full_awaken')):
                continue
            candidates.append(entity.id)
    if not candidates:
        return ()
    pending = {(x.reference.entity_id, x.dormancy_id)
        for x in (*r._captured, *getattr(r, '_work_queue', ())) if type(x) is AwakenCapturedMinion}
    result = []
    for entity_id in r.rules.entity_order(r.state, candidates):
        entity = r.state.entities[entity_id]
        key = (entity.id, entity.dormancy.id)
        if key not in pending:
            result.append(AwakenCapturedMinion(MinionReference.capture(entity), entity.dormancy.id, entity.id))
            pending.add(key)
    return tuple(result)


def register_dormancy(mechanics):
    for kind, handler in ((MakeDormant, make_dormant), (AwakenMinion, awaken),
                          (AwakenCapturedMinion, awaken_captured),
                          (GrowDormantMinion, grow_dormant),
                          (AdvanceCapturedDormancy, advance_captured),
                          (AdvanceDormancy, advance), (TickDormancy, tick)):
        mechanics.register(kind, handler)
