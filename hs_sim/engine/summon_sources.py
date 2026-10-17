"""Physical zone summons and non-consuming resurrection from immutable deaths."""
from dataclasses import dataclass, replace

from .effects import Effect, _player, _source, _integer, _behavior
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardClass, CardType, ResurrectionRecord, SummonStats, Zone, validate_summon_stats
from .pools import PoolQuery, matches_metadata
from .zones import CardReference, filter_value, source_exists, zone_candidates
from .sacrifice import MinionReference, reference_value, live_minion
from .card_conditions import has_battlecry


def minion_query(query):
    filter_value(query)
    if query.kinds and query.kinds != (CardType.MINION,):
        raise ValueError('Summon queries can only select minions')
    return replace(query, kinds=(CardType.MINION,))


def position_value(position):
    if position is not None:
        _integer(position, 'summon position', 0)


@dataclass(frozen=True)
class SummonFromZone(Effect):
    player_id: int
    count: int = 1
    owner_id: int | None = None
    zone: Zone = Zone.DECK
    query: PoolQuery = PoolQuery()
    selection: str = 'random'
    position: int | None = None
    source_id: int | None = None
    stats: SummonStats | None = None
    cause: object = None
    on_summon: str | None = None

    def __post_init__(self):
        if self.on_summon is not None:
            _behavior(self.on_summon)
            if self.cause is None: raise ValueError('Recruit followup requires original card attribution')
        if self.cause is not None:
            from .summon_quantities import SummonCause
            if type(self.cause)is not SummonCause:raise ValueError('Typed physical recruit cause required')
            self.cause.__post_init__()
        _player(self.player_id); _integer(self.count, 'summon count', 0); _source(self.source_id)
        validate_summon_stats(self.stats)
        if self.owner_id is not None: _player(self.owner_id)
        if type(self.zone) is not Zone or self.zone not in (Zone.HAND, Zone.DECK):
            raise ValueError('Physical summons require a hand or deck')
        minion_query(self.query); position_value(self.position)
        if self.selection not in ('random', 'first'):
            raise ValueError('Unknown zone summon selection policy')


def summon_from_zone(r, effect):
    if effect.cause is not None:
        from .recruit_summons import start
        return start(r,effect)
    from .summon_quantities import reject_ambiguous
    reject_ambiguous(r)
    effect.__post_init__(); source_exists(r, effect.source_id)
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Zone summons exceed resolution budget')
    if effect.count == 0 or len(r.player(effect.player_id).board) >= r.rules.max_board:
        return ()
    candidates = zone_candidates(r, effect.owner_id or effect.player_id, effect.zone,
        minion_query(effect.query), effect.player_id, effect.source_id)
    if not candidates: return ()
    selected = r.game._rng.choice(candidates) if effect.selection == 'random' else candidates[0]
    from .colossal import SummonStoredCard
    # Each movement, Colossal expansion and reaction finishes before re-querying.
    return (SummonStoredCard(selected, effect.player_id, effect.position, effect.stats),
            replace(effect, count=effect.count-1,
                    position=None if effect.position is None else effect.position+1))


@dataclass(frozen=True)
class SummonFromStoredCandidates(Effect):
    """Uniformly choose a supplied physical alternative, then move that card.

    Pure card rules build this inventory at their actual execution window. It is
    not a generated-card pool or a replacement for printed zone queries. Departed
    references never identify a later lifetime; repeated physical IDs are errors.
    """
    player_id: int
    cards: tuple[CardReference, ...]
    position: int | None = None
    stats: SummonStats | None = None
    cause: object = None

    def __post_init__(self):
        _player(self.player_id); position_value(self.position)
        validate_summon_stats(self.stats)
        if type(self.cards) is not tuple:
            raise ValueError('Stored candidates require an immutable reference inventory')
        for card in self.cards:
            from .zones import reference_value
            reference_value(card)
        if len({card.entity_id for card in self.cards}) != len(self.cards):
            raise ValueError('Duplicate physical summon candidate')
        if len({(card.player_id, card.zone) for card in self.cards}) > 1:
            raise ValueError('Stored candidates require one original physical zone')
        if self.cause is not None:
            from .summon_quantities import SummonCause
            if type(self.cause) is not SummonCause:
                raise ValueError('Typed stored candidate summon cause required')
            self.cause.__post_init__()


def validate_stored_candidates(state, registry, effect):
    effect.__post_init__()
    if effect.cause is not None:
        from .summon_quantities import validate_cause
        validate_cause(state, registry, effect.cause)
    # Validate even skipped attempts and pending work, without sampling or moving.
    for card in effect.cards:
        if registry.card(card.card_id).kind != CardType.MINION:
            raise ResolutionError('Stored summon candidates require minion definitions')


def summon_from_stored_candidates(r, effect):
    validate_stored_candidates(r.state, r.registry, effect)
    if effect.cause is None:
        from .summon_quantities import reject_ambiguous
        reject_ambiguous(r)
    candidates = []
    for card in effect.cards:
        entity = r.state.entities.get(card.entity_id)
        if entity is not None and (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) == (
                card.player_id, card.zone, card.card_id, card.zone_epoch):
            candidates.append(card)
    if not candidates or len(r.player(effect.player_id).board) >= r.rules.max_board:
        return ()
    selected = r.game._rng.choice(candidates)
    from .colossal import SummonStoredCard
    return (SummonStoredCard(selected, effect.player_id, effect.position, effect.stats, effect.cause),)


@dataclass(frozen=True)
class DeathQuery:
    side: str = 'friendly'
    cards: PoolQuery = PoolQuery()
    has_deathrattle: bool | None = None
    keywords_at_death: bool = False
    min_turn: int | None = None
    max_turn: int | None = None
    exclude_entity_ids: tuple[int, ...] = ()
    cost_extreme: str | None = None
    cost_basis: str = 'printed'
    deathrattle_basis: str = 'at_death'

    def __post_init__(self):
        if self.deathrattle_basis not in ('at_death', 'printed'):
            raise ValueError('Unknown deathrattle qualification basis')
        if self.cost_extreme not in (None, 'highest', 'lowest'):
            raise ValueError('Unknown death cost extreme')
        if self.cost_basis not in ('printed', 'local_at_death'):
            raise ValueError('Unknown death cost basis')
        if self.side not in ('friendly', 'enemy', 'both'):
            raise ValueError('Unknown death history side')
        minion_query(self.cards)
        if self.has_deathrattle is not None and type(self.has_deathrattle) is not bool:
            raise ValueError('Deathrattle predicate must be a boolean')
        if type(self.keywords_at_death) is not bool:
            raise ValueError('Death keyword policy must be a boolean')
        for value in (self.min_turn, self.max_turn):
            if value is not None: _integer(value, 'death turn bound', 1)
        if self.min_turn is not None and self.max_turn is not None and self.min_turn > self.max_turn:
            raise ValueError('Invalid death turn interval')
        if type(self.exclude_entity_ids) is not tuple or len(set(self.exclude_entity_ids)) != len(self.exclude_entity_ids):
            raise ValueError('Death exclusions require distinct immutable entity IDs')
        for entity_id in self.exclude_entity_ids: _integer(entity_id, 'excluded death entity', 1)


def death_candidates(state, registry, player_id, query=DeathQuery(), source_id=None):
    """Pure host query; friendly means controller at death, not original owner."""
    _player(player_id); _source(source_id)
    if type(query) is not DeathQuery: raise ValueError('Expected DeathQuery')
    query.__post_init__()
    if source_id is not None and source_id not in state.entities:
        raise ResolutionError('Death query source does not exist')
    card_query = minion_query(query.cards)
    current_class = state.players[player_id].hero_class
    if card_query.class_mode in ('current', 'other') and current_class in (None, CardClass.NEUTRAL):
        raise ResolutionError('Death query requires a known current hero class')
    return death_query_candidates(registry,player_id,query,state.death_history,current_class,None if source_id is None else state.entities[source_id].card_id)


def death_query_candidates(registry,player_id,query,records,current_class,source_card_id=None):
    """Shared pure evaluator for live and frozen original death inventories."""
    _player(player_id);query.__post_init__();card_query=minion_query(query.cards)
    if card_query.class_mode in ('current','other')and current_class in(None,CardClass.NEUTRAL):raise ResolutionError('Death query requires a known current hero class')
    excluded = set(card_query.exclude_card_ids)
    if card_query.exclude_source:
        if source_card_id is None: raise ResolutionError('Death source exclusion requires a source')
        excluded.add(source_card_id)
    from .costs import local_cost
    result = []; costs = {}
    for record in records:
        from .jade import printed_definition
        definition = printed_definition(registry, record)
        if definition.kind != CardType.MINION or record.zone != Zone.BOARD: continue
        if ((query.side == 'friendly' and record.controller != player_id) or
                (query.side == 'enemy' and record.controller == player_id) or
                record.entity_id in query.exclude_entity_ids or record.card_id in excluded or
                query.min_turn is not None and record.turn < query.min_turn or
                query.max_turn is not None and record.turn > query.max_turn):
            continue
        deathrattle = (definition.deathrattle is not None if query.deathrattle_basis == 'printed' else
                      any(a.kind == 'deathrattle' and not a.consumed for a in record.abilities))
        if query.has_deathrattle is not None and deathrattle != query.has_deathrattle: continue
        cost = definition.cost if query.cost_basis == 'printed' else local_cost(record)[0]
        if matches_metadata(card_query, card_id=record.card_id, kind=definition.kind,
                cost=cost, meta=definition.metadata, spell_school=None,
                keywords=record.keywords if query.keywords_at_death else definition.keywords,
                current_class=current_class,printed_battlecry=definition.battlecry is not None,
                current_battlecry=has_battlecry(record.abilities)):
            result.append(record); costs[record.id] = cost
    if result and query.cost_extreme is not None:
        extreme = (max if query.cost_extreme == 'highest' else min)(costs.values())
        result = [record for record in result if costs[record.id] == extreme]
    return tuple(result)


@dataclass(frozen=True)
class ResurrectMinion(Effect):
    player_id: int
    death_id: int
    position: int | None = None
    source_id: int | None = None
    stats: SummonStats | None = None
    on_summon: str | None = None
    cause: object = None
    producer_link: object = None

    def __post_init__(self):
        if self.cause is not None:
            from .summon_quantities import SummonCause
            if type(self.cause)is not SummonCause:raise ValueError('Typed original resurrection cause required')
            self.cause.__post_init__()
        if self.producer_link is not None:
            from .resurrection_summons import ResurrectionEntryLink
            if type(self.producer_link)is not ResurrectionEntryLink or self.cause is None:raise ValueError('Typed original death selection required')
            self.producer_link.__post_init__()
        _player(self.player_id); _integer(self.death_id, 'resurrection death ID', 1)
        position_value(self.position); _source(self.source_id)
        validate_summon_stats(self.stats)
        if self.on_summon is not None: _behavior(self.on_summon)


def death_record(state, death_id):
    record = next((d for d in state.death_history if d.id == death_id), None)
    if record is None: raise ResolutionError('Missing resurrection death record')
    return record


def resurrect_minion(r, effect):
    if effect.cause is not None:
        from .resurrection_summons import accept_entry
        return accept_entry(r,effect)
    from .summon_quantities import reject_ambiguous
    reject_ambiguous(r)
    effect.__post_init__(); source_exists(r, effect.source_id)
    if effect.on_summon is not None: r.registry.behavior(effect.on_summon)
    record = death_record(r.state, effect.death_id)
    if record.zone != Zone.BOARD or r.registry.card(record.card_id).kind != CardType.MINION:
        raise ResolutionError('Only a recorded minion death can be resurrected')
    if len(r.player(effect.player_id).board) >= r.rules.max_board:
        r.emit('resurrection_failed', player_id=effect.player_id, source_id=effect.source_id,
               reason='board_full', death_id=record.id)
        return ()
    entity = r.create_entity(effect.player_id, record.card_id, Zone.BOARD,
                             effect.position, components=record.components)
    entity.origin_entity_id = record.entity_id
    from .jade import inherit_printed
    inherit_printed(record, entity)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state, entity, effect.stats)
    history = ResurrectionRecord(len(r.state.resurrection_history)+1,
        record.id, entity.id, effect.player_id, r.state.turn, r.state.action_number, effect.source_id, effect.stats,
        entity.entered_order, entity.zone_epoch)
    r.state.resurrection_history.append(history)
    r.refresh_auras()
    from .colossal import enter_minion
    followup = (ContinueResurrectedMinion(history.id, MinionReference.capture(entity), effect.on_summon),) if effect.on_summon is not None else ()
    return (*enter_minion(r, entity, 'resurrect', origin_id=record.entity_id, death_id=record.id), *followup)


@dataclass(frozen=True)
class ContinueResurrectedMinion(Effect):
    resurrection_id: int
    beneficiary: MinionReference
    behavior_id: str

    def __post_init__(self):
        _integer(self.resurrection_id, 'resurrection ID', 1)
        reference_value(self.beneficiary); _behavior(self.behavior_id)


def followup_record(state, registry, effect):
    effect.__post_init__(); registry.behavior(effect.behavior_id)
    record = next((x for x in state.resurrection_history if x.id == effect.resurrection_id), None)
    if record is None or (record.entity_id, record.player_id) != (effect.beneficiary.entity_id, effect.beneficiary.player_id):
        raise ResolutionError('Resurrection continuation and successful subject disagree')
    death = death_record(state, record.death_id)
    if death.card_id != effect.beneficiary.card_id:
        raise ResolutionError('Resurrection continuation and death identity disagree')
    ref = effect.beneficiary
    if (ref.zone_epoch, ref.entered_order) != (record.zone_epoch, record.entered_order):
        raise ResolutionError('Resurrection continuation has invalid original entry provenance')
    return record, death


def continue_resurrected_minion(r, effect):
    record, death = followup_record(r.state, r.registry, effect)
    if live_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    # The body, never a last-board/last-history heuristic, is the callback target.
    # Summon reactions and Colossal expansion have finished before this capture.
    return (r.call(effect.behavior_id, record.source_id or r.player(record.player_id).hero_id,
                   record.player_id, target_id=record.entity_id, death=death),)


def validate_boundary(game):
    frame = game._frame
    if frame is None: return
    for work in (*frame.prefix, *frame.continuation):
        if type(work) is ContinueResurrectedMinion:
            followup_record(game._state, game.registry, work)


@dataclass(frozen=True)
class Resurrect(Effect):
    player_id: int
    count: int = 1
    query: DeathQuery = DeathQuery()
    distinct: str = 'death'
    selection: str = 'random'
    position: int | None = None
    source_id: int | None = None
    stats: SummonStats | None = None
    on_summon: str | None = None
    cause: object = None
    death_ids: tuple[int, ...] | None = None
    attack_after_all: bool = False

    def __post_init__(self):
        if type(self.attack_after_all) is not bool:
            raise ValueError('Resurrection group attack policy must be explicit')
        if self.death_ids is not None:
            if type(self.death_ids) is not tuple or len(set(self.death_ids)) != len(self.death_ids):
                raise ValueError('Exact resurrection deaths require distinct original identities')
            for identity in self.death_ids: _integer(identity, 'exact resurrection death', 1)
        if (self.death_ids is not None or self.attack_after_all) and self.cause is None:
            raise ValueError('Exact/group resurrection requires its attributed native batch')
        if self.cause is not None:
            from .summon_quantities import SummonCause
            if type(self.cause)is not SummonCause:raise ValueError('Typed original resurrection cause required')
            self.cause.__post_init__()
        _player(self.player_id); _integer(self.count, 'resurrection count', 0)
        position_value(self.position); _source(self.source_id)
        validate_summon_stats(self.stats)
        if self.on_summon is not None: _behavior(self.on_summon)
        if type(self.query) is not DeathQuery: raise ValueError('Expected DeathQuery')
        self.query.__post_init__()
        if self.distinct not in ('death', 'card') or self.selection not in ('random', 'first'):
            raise ValueError('Invalid resurrection selection policy')


@dataclass(frozen=True)
class ContinueResurrection(Effect):
    spec: Resurrect
    death_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.spec) is not Resurrect: raise ValueError('Expected resurrection specification')
        self.spec.__post_init__()
        if type(self.death_ids) is not tuple or len(set(self.death_ids)) != len(self.death_ids):
            raise ValueError('Resurrection pool requires distinct immutable death IDs')
        for death_id in self.death_ids: _integer(death_id, 'resurrection candidate ID', 1)


def resurrect(r, effect):
    if effect.cause is not None:
        from .resurrection_summons import start
        return start(r,effect)
    from .summon_quantities import reject_ambiguous
    reject_ambiguous(r)
    effect.__post_init__(); source_exists(r, effect.source_id)
    if effect.on_summon is not None: r.registry.behavior(effect.on_summon)
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Resurrection count exceeds resolution budget')
    if effect.count == 0 or len(r.player(effect.player_id).board) >= r.rules.max_board: return ()
    candidates = death_candidates(r.state, r.registry, effect.player_id, effect.query, effect.source_id)
    return (ContinueResurrection(effect, tuple(d.id for d in candidates)),)


def continue_resurrection(r, effect):
    effect.__post_init__(); spec = effect.spec
    if spec.cause is not None:raise ResolutionError('Attributed resurrection requires its original captured batch')
    if spec.count == 0 or not effect.death_ids or len(r.player(spec.player_id).board) >= r.rules.max_board:
        return ()
    records = [death_record(r.state, i) for i in effect.death_ids]
    if spec.distinct == 'card':
        groups = {}
        for record in records: groups.setdefault(record.card_id, []).append(record)
        group = r.game._rng.choice(tuple(groups.values())) if spec.selection == 'random' else next(iter(groups.values()))
        selected = r.game._rng.choice(group) if spec.selection == 'random' else group[0]
        remaining = tuple(d.id for d in records if d.card_id != selected.card_id)
    else:
        selected = r.game._rng.choice(records) if spec.selection == 'random' else records[0]
        remaining = tuple(d.id for d in records if d.id != selected.id)
    return (ResurrectMinion(spec.player_id, selected.id, spec.position, spec.source_id, spec.stats, spec.on_summon),
            ContinueResurrection(replace(spec, count=spec.count-1,
                position=None if spec.position is None else spec.position+1), remaining))


def validate_history(state, registry):
    if type(state.resurrection_history) is not list: raise ValueError('Expected resurrection history list')
    entities = set(); previous = (0, 0)
    for index, record in enumerate(state.resurrection_history, 1):
        if type(record) is not ResurrectionRecord: raise ValueError('Expected immutable resurrection record')
        record.__post_init__(); death = death_record(state, record.death_id)
        entity = state.entities.get(record.entity_id)
        if (record.id != index or entity is None or entity.owner != record.player_id or record.entity_id in entities or
                record.zone_epoch != 0 or record.entered_order >= state.next_order or
                record.entity_id <= death.entity_id or entity.origin_entity_id != death.entity_id or
                registry.card(death.card_id).kind != CardType.MINION or death.zone != Zone.BOARD or
                not death.turn <= record.turn <= state.turn or record.action > state.action_number or
                (record.turn, record.action) < previous or
                record.source_id is not None and record.source_id not in state.entities):
            raise ValueError('Invalid resurrection identity, origin or chronology')
        entities.add(record.entity_id); previous = (record.turn, record.action)


@dataclass(frozen=True)
class CopyStoredMinion(Effect):
    card: CardReference
    player_id: int
    position: int | None = None
    mode: str = 'current'
    stats: SummonStats | None = None
    cause: object = None
    minion_grant: object = None

    def __post_init__(self):
        from .card_creation import validate_minion_grant
        validate_minion_grant(self.minion_grant)
        if self.minion_grant is not None and self.cause is None:raise ValueError('Copy entry grant requires its original attributed summon')
        if self.cause is not None:
            from .summon_quantities import SummonCause
            if type(self.cause)is not SummonCause:raise ValueError('Typed stored copy cause required')
            self.cause.__post_init__()
        from .zones import reference_value
        reference_value(self.card); _player(self.player_id); position_value(self.position)
        validate_summon_stats(self.stats)
        if self.mode not in ('current', 'base'): raise ValueError('Invalid stored summon copy mode')


def copy_stored_minion(r, effect):
    from .summon_quantities import reject_ambiguous
    if effect.cause is None:reject_ambiguous(r)
    else:
        from .copy_materials import validate_effect_scope
        validate_effect_scope(r.state,r.registry,effect)
    from .zones import reference_entity
    from .lifecycle import copy_attachments, apply_summon_stats
    from .colossal import enter_minion
    source = reference_entity(r, effect.card)
    if source is None: return ()
    if source.kind != CardType.MINION: raise ResolutionError('Stored summon copy requires a minion')
    if effect.cause is not None:
        from .copy_materials import accept_copy
        return accept_copy(r,effect,source,'stored_copy')
    if len(r.player(effect.player_id).board) >= r.rules.max_board: return ()
    entity = r.create_entity(effect.player_id, source.card_id, Zone.BOARD, effect.position, components=source.components)
    entity.origin_entity_id = source.id
    from .jade import inherit_printed
    inherit_printed(source, entity)
    if effect.mode == 'current':
        entity.base_attack, entity.base_health, entity.base_cost = source.base_attack, source.base_health, source.base_cost
        entity.damage, entity.corpse_value = source.damage, source.corpse_value
        copy_attachments(r.state, source, entity)
        from .herald import initialize_instance
        initialize_instance(r.state,entity,r.registry.card(entity.card_id))
    apply_summon_stats(r.state, entity, effect.stats)
    r.refresh_auras()
    return enter_minion(r, entity, 'copy', origin_id=source.id, copy_mode=effect.mode)


def register(mechanics):
    mechanics.register(CopyStoredMinion, copy_stored_minion)
    mechanics.register_payload_type(DeathQuery)
    for kind, handler in ((SummonFromZone, summon_from_zone),
                          (SummonFromStoredCandidates, summon_from_stored_candidates),
                          (ResurrectMinion, resurrect_minion),
                          (Resurrect, resurrect), (ContinueResurrection, continue_resurrection),
                          (ContinueResurrectedMinion, continue_resurrected_minion)):
        mechanics.register(kind, handler)
