"""U65 C1-C3 detached host history component, pending execution and integration.

Only real committed hand submissions are captured. This module does not play
cards, invent payments, add history roots, or execute a natural end-turn tail.
Its strict codec and local RNG replay detect structural inconsistency. They do
not authenticate an unsigned origin, registry, or random state.
"""
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from math import isfinite
from random import Random

from hs_sim.engine.model import CardClass, CardType, FrozenPlayedFaceFact, GameState
from hs_sim.engine.owner_turns import validate_face, validate_history as validate_owner_history
from hs_sim.engine.play_history import validate_history as validate_play_history
from hs_sim.engine.pools import PoolMember, sample_candidates
from hs_sim.engine.serialization import _played_face_from_dict


class HistoryOutcome(StrEnum):
    ATTEMPTS = 'attempts'
    COMPLETED = 'completed'
    SUCCESSFUL = 'successful'


class ClassRelation(StrEnum):
    ANY = 'any'
    SAME = 'same'
    OTHER = 'other'


class ClassBasis(StrEnum):
    NONE = 'none'
    CURRENT_HERO = 'current_hero_at_capture'
    EXPLICIT = 'explicit'


class NeutralClassPolicy(StrEnum):
    EXCLUDE = 'exclude'
    AS_SAME = 'as_same'
    AS_OTHER = 'as_other'


class ClassQuantifier(StrEnum):
    ANY = 'any_member'
    ALL = 'all_members'


class HistorySelectionMode(StrEnum):
    ALL = 'all'
    LAST = 'last'
    FIRST_COUNT = 'first_count'
    RANDOM_COUNT = 'random_count'


class HistoryProcessingOrder(StrEnum):
    CHRONOLOGICAL = 'chronological'
    DRAW = 'draw'


def integer(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} requires an integer >= {minimum}')


def known_class(value):
    if type(value) is not CardClass or value == CardClass.NEUTRAL:
        raise ValueError('Class comparison requires a known non-Neutral class')


def unique_ids(value, name):
    if type(value) is not tuple:
        raise ValueError(f'{name} requires an immutable ID tuple')
    for item in value:
        integer(item, name)
    if len(value) != len(set(value)):
        raise ValueError(f'{name} contains duplicate IDs')


@dataclass(frozen=True)
class WholeCardHistoryQuery:
    player_id: int
    before_play_id: int
    owner_turn_id: int | None = None
    min_turn: int | None = None
    max_turn: int | None = None
    kinds: tuple[CardType, ...] = ()
    outcomes: HistoryOutcome = HistoryOutcome.COMPLETED
    exclude_play_ids: tuple[int, ...] = ()
    exclude_card_ids: tuple[str, ...] = ()
    class_relation: ClassRelation = ClassRelation.ANY
    class_basis: ClassBasis = ClassBasis.NONE
    comparison_class: CardClass | None = None
    neutral: NeutralClassPolicy = NeutralClassPolicy.EXCLUDE
    class_quantifier: ClassQuantifier = ClassQuantifier.ALL

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('History query requires a player seat')
        integer(self.before_play_id, 'exclusive history frontier')
        for name in ('owner_turn_id', 'min_turn', 'max_turn'):
            if getattr(self, name) is not None:
                integer(getattr(self, name), name)
        if self.min_turn is not None and self.max_turn is not None and self.min_turn > self.max_turn:
            raise ValueError('History turn range is reversed')
        if (type(self.kinds) is not tuple or any(type(v) is not CardType or v == CardType.HERO_POWER for v in self.kinds)
                or len(set(self.kinds)) != len(self.kinds)):
            raise ValueError('History kinds must be unique hand-card types')
        unique_ids(self.exclude_play_ids, 'excluded physical submission')
        if (type(self.exclude_card_ids) is not tuple or any(type(v) is not str or not v.strip() for v in self.exclude_card_ids)
                or len(set(self.exclude_card_ids)) != len(self.exclude_card_ids)):
            raise ValueError('Face-wide exclusion requires unique explicit card IDs')
        for name, enum in (('outcomes', HistoryOutcome), ('class_relation', ClassRelation),
                           ('class_basis', ClassBasis), ('neutral', NeutralClassPolicy),
                           ('class_quantifier', ClassQuantifier)):
            if type(getattr(self, name)) is not enum:
                raise ValueError(f'Unknown typed history policy: {name}')
        if self.class_relation == ClassRelation.ANY:
            if self.class_basis != ClassBasis.NONE or self.comparison_class is not None:
                raise ValueError('Unfiltered classes cannot borrow a comparison window')
        elif self.class_basis == ClassBasis.EXPLICIT:
            known_class(self.comparison_class)
        elif self.class_basis != ClassBasis.CURRENT_HERO or self.comparison_class is not None:
            raise ValueError('Class filtering requires an explicit comparison window')


@dataclass(frozen=True)
class PlayedOccurrence:
    face: FrozenPlayedFaceFact
    turn: int
    action: int
    completed: bool
    countered: bool
    interrupted: bool

    def __post_init__(self):
        if type(self.face) is not FrozenPlayedFaceFact:
            raise ValueError('History occurrence lost its complete frozen submitted face')
        self.face.__post_init__()
        integer(self.turn, 'submission turn')
        integer(self.action, 'submission action')
        for name in ('completed', 'countered', 'interrupted'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} requires a boolean')
        if self.completed and self.interrupted:
            raise ValueError('A completed occurrence cannot be interrupted')
        if self.countered and self.face.kind not in (CardType.SPELL, CardType.MINION):
            raise ValueError('Only supported Spell/Minion submissions can be countered')

    @property
    def id(self):
        return self.face.play_id


def classify_occurrence(occurrence, query, comparison_class):
    """Pure frozen-fact predicate; unneeded metadata is not inferred or read."""
    if type(occurrence) is not PlayedOccurrence or type(query) is not WholeCardHistoryQuery:
        raise ValueError('History matching requires typed occurrence and query')
    occurrence.__post_init__()
    query.__post_init__()
    if query.class_relation == ClassRelation.ANY:
        if comparison_class is not None:
            raise ValueError('Unfiltered matching has no comparison class')
    else:
        known_class(comparison_class)
        if query.class_basis == ClassBasis.EXPLICIT and query.comparison_class != comparison_class:
            raise ValueError('Explicit comparison class differs from its query')
    face = occurrence.face
    failed = []
    for flag, reason in (
        (face.player_id != query.player_id, 'player'),
        (occurrence.id >= query.before_play_id, 'frontier'),
        (query.owner_turn_id is not None and face.owner_turn_id != query.owner_turn_id, 'owner_turn'),
        (query.min_turn is not None and occurrence.turn < query.min_turn, 'min_turn'),
        (query.max_turn is not None and occurrence.turn > query.max_turn, 'max_turn'),
        (bool(query.kinds) and face.kind not in query.kinds, 'kind'),
        (occurrence.id in query.exclude_play_ids, 'submission_exclusion'),
        (face.card_id in query.exclude_card_ids, 'face_exclusion'),
        (query.outcomes != HistoryOutcome.ATTEMPTS and not occurrence.completed, 'incomplete'),
        (query.outcomes == HistoryOutcome.SUCCESSFUL and occurrence.countered, 'countered'),
        (query.outcomes == HistoryOutcome.SUCCESSFUL and occurrence.interrupted, 'interrupted'),
    ):
        if flag:
            failed.append(reason)
    # Excluded/opponent/other-turn rows remain present, but need no class verdict.
    if not failed and query.class_relation != ClassRelation.ANY:
        if face.metadata is None:
            raise ValueError(f'Unknown frozen card classes for play {occurrence.id}')
        classes = face.metadata.classes
        if classes == (CardClass.NEUTRAL,):
            matches = (query.neutral == NeutralClassPolicy.AS_SAME and query.class_relation == ClassRelation.SAME
                       or query.neutral == NeutralClassPolicy.AS_OTHER and query.class_relation == ClassRelation.OTHER)
        else:
            values = tuple((c == comparison_class if query.class_relation == ClassRelation.SAME
                            else c != comparison_class) for c in classes)
            matches = any(values) if query.class_quantifier == ClassQuantifier.ANY else all(values)
        if not matches:
            failed.append('class')
    return tuple(failed)


@dataclass(frozen=True)
class HistoryMatchRow:
    occurrence: PlayedOccurrence
    excluded_by: tuple[str, ...]

    def __post_init__(self):
        if type(self.occurrence) is not PlayedOccurrence:
            raise ValueError('History row requires its typed occurrence')
        self.occurrence.__post_init__()
        if type(self.excluded_by) is not tuple or any(type(v) is not str for v in self.excluded_by):
            raise ValueError('History row requires immutable exclusion reasons')


@dataclass(frozen=True)
class WholeCardHistoryFrontier:
    query: WholeCardHistoryQuery
    captured_turn: int
    captured_action: int
    history_size: int
    owner_turn_size: int
    comparison_class: CardClass | None
    rows: tuple[HistoryMatchRow, ...]

    def __post_init__(self):
        if type(self.query) is not WholeCardHistoryQuery:
            raise ValueError('History frontier requires its complete original query')
        self.query.__post_init__()
        integer(self.captured_turn, 'capture turn')
        integer(self.captured_action, 'capture action', 0)
        integer(self.history_size, 'captured history size', 0)
        integer(self.owner_turn_size, 'captured interval count', 0)
        if self.query.before_play_id > self.history_size + 1:
            raise ValueError('History frontier is newer than the captured submissions')
        if any(v > self.history_size for v in self.query.exclude_play_ids):
            raise ValueError('Excluded submission is unknown at the accepted window')
        if self.query.owner_turn_id is not None and self.query.owner_turn_id > self.owner_turn_size:
            raise ValueError('Requested owner interval is unknown at the accepted window')
        if type(self.rows) is not tuple or len(self.rows) != self.query.before_play_id - 1:
            raise ValueError('History frontier requires every original true/false row')
        last_action, last_turn = 0, 0
        # Empty class-filtered frontiers must still bind a known comparison class.
        if self.query.class_relation == ClassRelation.ANY:
            if self.comparison_class is not None:
                raise ValueError('Unfiltered frontier cannot carry a comparison class')
        else:
            known_class(self.comparison_class)
            if self.query.class_basis == ClassBasis.EXPLICIT and self.comparison_class != self.query.comparison_class:
                raise ValueError('Frontier changed the explicit comparison class')
        for index, row in enumerate(self.rows, 1):
            if type(row) is not HistoryMatchRow:
                raise ValueError('History frontier requires typed match rows')
            row.__post_init__()
            occurrence = row.occurrence
            if (occurrence.id != index or not last_action < occurrence.action <= self.captured_action
                    or not last_turn <= occurrence.turn <= self.captured_turn
                    or occurrence.face.owner_turn_id is not None and occurrence.face.owner_turn_id > self.owner_turn_size):
                raise ValueError('History occurrence identity, chronology or interval differs')
            if row.excluded_by != classify_occurrence(occurrence, self.query, self.comparison_class):
                raise ValueError('History matching differs from complete frozen facts')
            last_action, last_turn = occurrence.action, occurrence.turn

    @property
    def candidate_ids(self):
        return tuple(row.occurrence.id for row in self.rows if not row.excluded_by)


def capture_history_frontier(state, registry, query):
    """Accept a prefix from validated genuine history; never inspect live faces."""
    if type(state) is not GameState or type(query) is not WholeCardHistoryQuery:
        raise ValueError('History capture requires typed current state and query')
    query.__post_init__()
    validate_owner_history(state, registry)
    validate_play_history(state, registry)
    if query.before_play_id > len(state.play_history) + 1:
        raise ValueError('Exclusive frontier references future submissions')
    if any(v > len(state.play_history) for v in query.exclude_play_ids):
        raise ValueError('Excluded submission is unknown at this window')
    if query.owner_turn_id is not None and query.owner_turn_id > len(state.owner_turn_history):
        raise ValueError('Unknown actual owner interval')
    for card_id in query.exclude_card_ids:
        registry.card(card_id)
    comparison = (state.players[query.player_id].hero_class if query.class_basis == ClassBasis.CURRENT_HERO
                  else query.comparison_class)
    if query.class_relation != ClassRelation.ANY:
        known_class(comparison)
    rows = []
    for play in state.play_history[:query.before_play_id - 1]:
        occurrence = PlayedOccurrence(play.played_face, play.turn, play.action,
                                      play.completed, play.countered, play.interrupted)
        rows.append(HistoryMatchRow(occurrence, classify_occurrence(occurrence, query, comparison)))
    return WholeCardHistoryFrontier(query, state.turn, state.action_number, len(state.play_history),
                                   len(state.owner_turn_history), comparison, tuple(rows))


def validate_frontier_registry(frontier, registry):
    """Bind each retained frozen face, including false rows, to pinned definitions."""
    if type(frontier) is not WholeCardHistoryFrontier:
        raise ValueError('Expected a typed history frontier')
    frontier.__post_init__()
    for card_id in frontier.query.exclude_card_ids:
        registry.card(card_id)
    for row in frontier.rows:
        validate_face(row.occurrence.face, registry)


def verify_frontier_origin(frontier, state, registry):
    """Compare at the supplied original window; this is not origin authentication."""
    if type(frontier) is not WholeCardHistoryFrontier:
        raise ValueError('Expected a typed history frontier')
    if frontier != capture_history_frontier(state, registry, frontier.query):
        raise ValueError('Frontier differs from the supplied original acceptance window')


@dataclass(frozen=True)
class HistorySelectionPolicy:
    mode: HistorySelectionMode = HistorySelectionMode.ALL
    count: int | None = None
    replacement: bool = False
    order: HistoryProcessingOrder = HistoryProcessingOrder.CHRONOLOGICAL

    def __post_init__(self):
        if type(self.mode) is not HistorySelectionMode or type(self.order) is not HistoryProcessingOrder:
            raise ValueError('Unknown typed historical selection policy')
        if type(self.replacement) is not bool:
            raise ValueError('Replacement requires a boolean')
        if self.mode in (HistorySelectionMode.ALL, HistorySelectionMode.LAST):
            if self.count is not None:
                raise ValueError('All/last selection has no count')
        else:
            integer(self.count, 'historical selection count', 0)
        if self.mode != HistorySelectionMode.RANDOM_COUNT and (
                self.replacement or self.order != HistoryProcessingOrder.CHRONOLOGICAL):
            raise ValueError('Only random-count selection accepts draw order/replacement')


def rng_state(value):
    if (type(value) is not tuple or len(value) != 3 or type(value[0]) is not int or value[0] != 3
            or type(value[1]) is not tuple or len(value[1]) != 625
            or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in value[1][:-1])
            or type(value[1][-1]) is not int or not 0 <= value[1][-1] <= 624
            or value[2] is not None and (type(value[2]) is not float or not isfinite(value[2]))):
        raise ValueError('Expected complete MT19937 v3 state')
    check = Random(0)
    check.setstate(value)


def drawn_occurrences(frontier, policy, rng):
    candidates = frontier.candidate_ids
    if policy.mode == HistorySelectionMode.ALL:
        return candidates
    if policy.mode == HistorySelectionMode.LAST:
        return candidates[-1:]
    if policy.mode == HistorySelectionMode.FIRST_COUNT:
        return candidates[:policy.count]
    # Equal weight per physical submission; same card face is never deduplicated.
    return tuple(int(v) for v in sample_candidates(rng,
        tuple(PoolMember(str(i)) for i in candidates), policy.count, replacement=policy.replacement))


def processing_ids(drawn, policy):
    return tuple(sorted(drawn)) if policy.order == HistoryProcessingOrder.CHRONOLOGICAL else drawn


@dataclass(frozen=True)
class HistorySelectionReceipt:
    frontier: WholeCardHistoryFrontier
    policy: HistorySelectionPolicy
    drawn_ids: tuple[int, ...]
    selected_ids: tuple[int, ...]
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.frontier) is not WholeCardHistoryFrontier or type(self.policy) is not HistorySelectionPolicy:
            raise ValueError('Selection requires the complete typed original frontier/policy')
        self.frontier.__post_init__()
        self.policy.__post_init__()
        for name in ('drawn_ids', 'selected_ids'):
            if type(getattr(self, name)) is not tuple:
                raise ValueError('Drawn/selected occurrences require immutable tuples')
            for value in getattr(self, name):
                integer(value, name)
        rng_state(self.rng_before)
        rng_state(self.rng_after)
        replay = Random(0)
        replay.setstate(self.rng_before)
        expected = drawn_occurrences(self.frontier, self.policy, replay)
        if (self.drawn_ids != expected or self.selected_ids != processing_ids(expected, self.policy)
                or replay.getstate() != self.rng_after):
            raise ValueError('Selected occurrences or RNG differ from local original sampling')


def select_history_occurrences(frontier, policy, rng):
    if type(frontier) is not WholeCardHistoryFrontier or type(policy) is not HistorySelectionPolicy or type(rng) is not Random:
        raise ValueError('Historical selection requires typed frontier/policy and the supplied RNG')
    frontier.__post_init__()
    policy.__post_init__()
    before = rng.getstate()
    try:
        drawn = drawn_occurrences(frontier, policy, rng)
        return HistorySelectionReceipt(frontier, policy, drawn, processing_ids(drawn, policy), before, rng.getstate())
    except Exception:
        rng.setstate(before)
        raise


def exact_row(value, cls):
    if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
        raise ValueError(f'Invalid {cls.__name__} fields')
    return dict(value)


def array(value):
    if type(value) is not list:
        raise ValueError('Historical codec requires an array')
    return value


def frontier_to_dict(frontier):
    if type(frontier) is not WholeCardHistoryFrontier:
        raise ValueError('Expected typed historical frontier')
    frontier.__post_init__()
    # JSON wire data consists only of arrays, objects, scalar values and nulls.
    import json
    return json.loads(json.dumps(asdict(frontier)))


def frontier_from_dict(value):
    row = exact_row(value, WholeCardHistoryFrontier)
    query = exact_row(row['query'], WholeCardHistoryQuery)
    for name, enum in (('outcomes', HistoryOutcome), ('class_relation', ClassRelation), ('class_basis', ClassBasis),
                       ('neutral', NeutralClassPolicy), ('class_quantifier', ClassQuantifier)):
        if type(query[name]) is not str:
            raise ValueError('Serialized history policy requires a string')
        query[name] = enum(query[name])
    query['kinds'] = tuple(CardType(v) for v in array(query['kinds']))
    for name in ('exclude_play_ids', 'exclude_card_ids'):
        query[name] = tuple(array(query[name]))
    if query['comparison_class'] is not None:
        query['comparison_class'] = CardClass(query['comparison_class'])
    row['query'] = WholeCardHistoryQuery(**query)
    if row['comparison_class'] is not None:
        row['comparison_class'] = CardClass(row['comparison_class'])
    matches = []
    for value in array(row['rows']):
        match = exact_row(value, HistoryMatchRow)
        occurrence = exact_row(match['occurrence'], PlayedOccurrence)
        occurrence['face'] = _played_face_from_dict(occurrence['face'])
        match['occurrence'] = PlayedOccurrence(**occurrence)
        match['excluded_by'] = tuple(array(match['excluded_by']))
        matches.append(HistoryMatchRow(**match))
    row['rows'] = tuple(matches)
    return WholeCardHistoryFrontier(**row)


def selection_to_dict(receipt):
    if type(receipt) is not HistorySelectionReceipt:
        raise ValueError('Expected typed historical selection')
    receipt.__post_init__()
    import json
    return json.loads(json.dumps(asdict(receipt)))


def selection_from_dict(value):
    row = exact_row(value, HistorySelectionReceipt)
    row['frontier'] = frontier_from_dict(row['frontier'])
    policy = exact_row(row['policy'], HistorySelectionPolicy)
    for name, enum in (('mode', HistorySelectionMode), ('order', HistoryProcessingOrder)):
        if type(policy[name]) is not str:
            raise ValueError('Serialized selection policy requires a string')
        policy[name] = enum(policy[name])
    row['policy'] = HistorySelectionPolicy(**policy)
    for name in ('drawn_ids', 'selected_ids'):
        row[name] = tuple(array(row[name]))
    for name in ('rng_before', 'rng_after'):
        stamp = array(row[name])
        if len(stamp) != 3:
            raise ValueError('Invalid serialized random state')
        row[name] = (stamp[0], tuple(array(stamp[1])), stamp[2])
    return HistorySelectionReceipt(**row)
