"""Fresh physical turn queries and an original forced-attack reward continuation."""
from dataclasses import dataclass

from .effects import Effect, _integer
from .errors import ResolutionError
from .model import BoardPresenceReference, CardType, DamageKind, Zone
from .sacrifice import BuffCapturedMinion, MinionReference, live_minion
from .summon_quantities import SummonCause, validate_cause


def validate_source(state, registry, source):
    if type(source) is not MinionReference:
        raise ValueError('Native turn query requires its original minion source')
    source.__post_init__()
    entity = state.entities.get(source.entity_id)
    if (entity is None or registry.card(source.card_id).kind != CardType.MINION or
            source.zone_epoch > entity.zone_epoch or source.entered_order >= state.next_order):
        raise ValueError('Native turn query borrowed an unknown or future source')


@dataclass(frozen=True)
class ResurrectFriendlyTurnDeaths(Effect):
    source: MinionReference
    cause: SummonCause

    def __post_init__(self):
        if type(self.source) is not MinionReference or type(self.cause) is not SummonCause:
            raise ValueError('Turn resurrection requires its typed original source and cause')
        self.source.__post_init__(); self.cause.__post_init__()
        if (self.cause.origin != 'card_effect' or self.cause.source.kind != CardType.MINION or
                (self.cause.source.entity_id, self.cause.player_id) != (self.source.entity_id, self.source.player_id)):
            raise ValueError('Turn resurrection changed its original source or actor')

    def validate_in_state(self, state, registry):
        self.__post_init__(); validate_source(state, registry, self.source); validate_cause(state, registry, self.cause)


def resurrect_turn(r, effect):
    from .summon_sources import DeathQuery, Resurrect, death_candidates
    effect.validate_in_state(r.state, r.registry)
    if live_minion(r.state, effect.source) is None: return ()
    query = DeathQuery(min_turn=r.state.turn, max_turn=r.state.turn)
    ids = tuple(d.id for d in death_candidates(r.state, r.registry, effect.source.player_id, query, effect.source.entity_id))
    if not ids: return ()
    return (Resurrect(effect.source.player_id, len(ids), query=query, selection='first',
        source_id=effect.source.entity_id, cause=effect.cause, death_ids=ids),)


def attacked_this_residence(state, entity):
    """Completed manual and forced combat, independent of available-attack use."""
    ref = BoardPresenceReference.capture(state, entity.id)
    return any(row.turn == state.turn and row.declaration.source_id == entity.id and
        row.declaration.attack_source_presence == ref and row.combat is not None and
        row.terminal is not None and row.terminal.status == 'completed'
        for row in state.character_attack_history)


@dataclass(frozen=True)
class BuffUnattackedOtherMinions(Effect):
    source: MinionReference

    def __post_init__(self):
        if type(self.source) is not MinionReference: raise ValueError('Unattacked reward requires its original minion')
        self.source.__post_init__()

    def validate_in_state(self, state, registry):
        self.__post_init__(); validate_source(state, registry, self.source)


def buff_unattacked(r, effect):
    effect.validate_in_state(r.state, r.registry)
    if live_minion(r.state, effect.source) is None: return ()
    units = tuple(r.state.entities[i] for i in r.player(effect.source.player_id).board)
    return tuple(BuffCapturedMinion(BoardPresenceReference.capture(r.state, e.id), 2, 2, effect.source.entity_id)
        for e in units if e.id != effect.source.entity_id and e.kind == CardType.MINION and e.active and
        not e.doomed and e.health > 0 and not attacked_this_residence(r.state, e))


@dataclass(frozen=True)
class EatOpponentDeckMinion(Effect):
    source: MinionReference

    def __post_init__(self):
        if type(self.source) is not MinionReference: raise ValueError('Deck meal requires its original minion')
        self.source.__post_init__()

    def validate_in_state(self, state, registry):
        self.__post_init__(); validate_source(state, registry, self.source)


def eat_deck_minion(r, effect):
    from .pools import PoolQuery
    from .zones import DestroyStoredCard, zone_candidates
    effect.validate_in_state(r.state, r.registry)
    if live_minion(r.state, effect.source) is None: return ()
    candidates = zone_candidates(r, 3-effect.source.player_id, Zone.DECK,
        PoolQuery(kinds=(CardType.MINION,)), effect.source.player_id, effect.source.entity_id)
    if not candidates: return ()
    original = r.game._rng.choice(candidates)
    reward = BuffCapturedMinion(effect.source, 2, 2, effect.source.entity_id)
    return (DestroyStoredCard(original, effect.source.entity_id, on_destroy=(reward,)),)


@dataclass(frozen=True)
class AttackRandomEnemyAndGrow(Effect):
    source: MinionReference

    def __post_init__(self):
        if type(self.source) is not MinionReference: raise ValueError('Native forced attack requires its original minion')
        self.source.__post_init__()

    def validate_in_state(self, state, registry):
        self.__post_init__(); validate_source(state, registry, self.source)


@dataclass(frozen=True)
class GrowAfterOriginalForcedAttack(Effect):
    window_id: int
    source: MinionReference

    def __post_init__(self):
        _integer(self.window_id, 'original native forced attack', 1)
        if type(self.source) is not MinionReference: raise ValueError('Attack reward requires its original minion')
        self.source.__post_init__()

    def validate_in_state(self, state, registry):
        from .character_attacks import record
        self.__post_init__(); validate_source(state, registry, self.source)
        row = record(state, self.window_id)
        if (not row.declaration.forced or row.source_kind != CardType.MINION or
                (row.declaration.source_id, row.declaration.player_id, row.source_card_id,
                    row.source_zone_epoch, row.source_entered_order) !=
                (self.source.entity_id, self.source.player_id, self.source.card_id,
                    self.source.zone_epoch, self.source.entered_order)):
            raise ValueError('Native kill reward borrowed another actual attack or source residence')
        return row


def attack_and_grow(r, effect):
    from .forced_attack_sequences import AttackRandomEnemyMinion, execute
    from .resolver import force_attack
    effect.validate_in_state(r.state, r.registry)
    source = live_minion(r.state, effect.source)
    if source is None: return ()
    selected = execute(r, AttackRandomEnemyMinion(BoardPresenceReference.capture(r.state, source.id),
        effect.source.player_id, source.id))
    if not selected: return ()
    # Existing selector and forced-combat acceptance run before any reaction body.
    # Capture the actual accepted window, never a predicted future/latest attack.
    before = len(r.state.character_attack_history)
    work = force_attack(r, selected[0])
    if not work: return ()
    if len(r.state.character_attack_history) != before+1:
        raise ResolutionError('Native forced attack lost its one actual accepted window')
    row = r.state.character_attack_history[-1]
    return (*work, GrowAfterOriginalForcedAttack(row.declaration.id, effect.source))


def original_combat_killed_minion(state, row):
    if row.combat is None or row.delivery is None or row.terminal is None or row.terminal.status != 'completed':
        return False
    target = state.entities[row.delivery.target_id]
    causes = ((target.death_cause,) if target.death_cause is not None else ()) + tuple(
        death.cause for death in state.death_history if death.entity_id == row.delivery.target_id)
    for cause in causes:
        result = cause.health_result
        if (cause.kind in ('damage','poison') and result is not None and result.target_kind == CardType.MINION.value and
                (cause.source_id,cause.source_card_id,cause.source_zone_epoch,cause.source_entered_order) ==
                (row.declaration.source_id,row.combat.source_card_id,row.combat.source_zone_epoch,row.combat.source_entered_order) and
                result.damage_kind == DamageKind.COMBAT.value and result.original_target_id == row.delivery.target_id and
                result.source_entered_order == row.combat.source_entered_order and
                row.combat.event_cursor < result.batch_id <= row.terminal.event_cursor):
            return True
    return False


def grow_after_attack(r, effect):
    row = effect.validate_in_state(r.state, r.registry)
    if live_minion(r.state, effect.source) is None or not original_combat_killed_minion(r.state, row): return ()
    return (BuffCapturedMinion(effect.source, 3, 3, effect.source.entity_id),)


def register(mechanics):
    for typ, handler in ((ResurrectFriendlyTurnDeaths,resurrect_turn),
            (BuffUnattackedOtherMinions,buff_unattacked), (EatOpponentDeckMinion,eat_deck_minion),
            (AttackRandomEnemyAndGrow,attack_and_grow), (GrowAfterOriginalForcedAttack,grow_after_attack)):
        mechanics.register(typ,handler)
