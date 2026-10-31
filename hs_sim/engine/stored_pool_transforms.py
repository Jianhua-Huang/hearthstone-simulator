"""One ordinary full-pool draw into an original stored physical card."""
from dataclasses import dataclass
from random import Random

from .allocation_facts import SourceAllocationFact, validate_allocation
from .construction import name
from .effects import Effect, _integer, _source
from .errors import ResolutionError
from .model import CardClass, CardType, SummonStats, Zone, validate_end_turn_rng, validate_summon_stats
from .pools import (GenerationContext, GenerationPolicy, PoolMember, PoolQuery,
    resolve_candidates, sample_candidates, validate_policy)
from .zones import CardReference, reference_entity, source_exists

DRAW = 'stored_pool_transformation_drawn'


def needs_class(query):
    return any(q.class_mode in ('current', 'other') for q in (query, *query.any_of))


@dataclass(frozen=True)
class TransformStoredFromPool(Effect):
    target: CardReference
    pool_id: str
    query: PoolQuery = PoolQuery(collectible=True)
    source_id: int | None = None
    policy: GenerationPolicy = GenerationPolicy()
    empty: str = 'skip'
    retained_stats: SummonStats | None = None
    retained_cost: int | None = None

    def __post_init__(self):
        if type(self.target) is not CardReference:
            raise ValueError('Stored random transformation requires its original CardReference')
        self.target.__post_init__(); name(self.pool_id, 'stored transformation pool')
        if type(self.query) is not PoolQuery:
            raise ValueError('Stored random transformation requires PoolQuery')
        self.query.__post_init__(); _source(self.source_id); validate_policy(self.policy)
        if type(self.empty) is not str or self.empty not in ('skip', 'error'):
            raise ValueError('Unknown stored transformation empty policy')
        if self.retained_stats is not None and self.retained_cost is None:
            raise ValueError('Retained hand stats require their numeric Cost')
        if self.retained_cost is not None:
            _integer(self.retained_cost, 'retained stored transformation cost', 0)
        if self.retained_stats is None and self.retained_cost is not None:
            if (self.target.zone not in (Zone.HAND,Zone.DECK) or self.source_id is None or
                    self.query.kinds != (CardType.SPELL,) or self.query.collectible is not True):
                raise ValueError('Cost-only retention requires a source-bound stored-to-spell transformation')
            if self.target.zone==Zone.DECK and (self.query.min_cost is None or
                    self.query.min_cost!=self.query.max_cost or self.query.max_cost>10):
                raise ValueError('Deck spell retention requires one original cost tier up to ten')
        if self.retained_stats is not None:
            validate_summon_stats(self.retained_stats)
            _integer(self.retained_cost, 'retained stored transformation cost', 0)
            if (self.retained_stats.attack is None or self.retained_stats.health is None or
                    self.target.zone not in (Zone.HAND, Zone.DECK) or self.source_id is None or
                    self.query.kinds != (CardType.MINION,) or self.query.collectible is not True):
                raise ValueError('Retained numbers require a complete source-bound stored-minion transformation')
            if self.target.zone == Zone.DECK and self.query != PoolQuery(
                    kinds=(CardType.MINION,), collectible=True, tribes_any=('dragon',)):
                raise ValueError('Retained deck numbers require the complete collectible Dragon query')


@dataclass(frozen=True)
class StoredPoolTransformDraw:
    request: TransformStoredFromPool
    context: GenerationContext
    pool_version: str
    hero_class: CardClass | None
    target: SourceAllocationFact
    source: SourceAllocationFact | None
    candidates: tuple[tuple[str, int], ...]
    selected: tuple[str, ...]
    rng_before: tuple
    rng_after: tuple
    transformation_sequence: int | None

    def __post_init__(self):
        if type(self.request) is not TransformStoredFromPool or type(self.context) is not GenerationContext:
            raise ValueError('Stored draw requires its complete typed request and context')
        self.request.__post_init__(); self.context.__post_init__(); name(self.pool_version, 'stored pool version')
        if needs_class(self.request.query) != (self.hero_class is not None) or self.hero_class is not None and (
                type(self.hero_class) is not CardClass or self.hero_class == CardClass.NEUTRAL):
            raise ValueError('Stored draw changed its captured class policy')
        if type(self.target) is not SourceAllocationFact:
            raise ValueError('Stored draw requires its original physical allocation')
        self.target.__post_init__()
        ref = self.request.target
        if (self.target.entity_id, self.target.controller, self.target.zone, self.target.card_id, self.target.zone_epoch) != (
                ref.entity_id, ref.player_id, ref.zone, ref.card_id, ref.zone_epoch):
            raise ValueError('Stored draw changed its original physical residence')
        if self.request.source_id is None:
            if self.source is not None:
                raise ValueError('Sourceless stored draw borrowed a source')
        else:
            if type(self.source) is not SourceAllocationFact or self.source.entity_id != self.request.source_id:
                raise ValueError('Stored draw lost its actual source allocation')
            self.source.__post_init__()
        if type(self.candidates) is not tuple or any(type(m) is not tuple or len(m) != 2 for m in self.candidates):
            raise ValueError('Stored draw requires complete ordered weighted candidates')
        for cid, weight in self.candidates:
            PoolMember(cid, weight).__post_init__()
        if len({cid for cid, _ in self.candidates}) != len(self.candidates):
            raise ValueError('Stored draw duplicated its canonical candidates')
        if type(self.selected) is not tuple or len(self.selected) != bool(self.candidates) or any(
                type(cid) is not str or not cid for cid in self.selected):
            raise ValueError('Stored draw requires exactly its original result')
        if self.selected:
            _integer(self.transformation_sequence, 'stored transformation sequence', 1)
        elif self.transformation_sequence is not None:
            raise ValueError('Empty stored draw cannot claim a transformation')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        local = Random(); local.setstate(self.rng_before)
        rows = tuple(PoolMember(cid, weight) for cid, weight in self.candidates)
        if sample_candidates(local, rows, 1, replacement=True) != self.selected or local.getstate() != self.rng_after:
            raise ValueError('Stored draw changed its original integer draw or RNG')


def candidates(registry, state, context, request, hero_class, source_card_id):
    from .cross_zone import stored_destination
    request.__post_init__()
    if (request.target.zone==Zone.DECK and request.retained_cost is not None and request.retained_stats is None and
            registry.card(request.target.card_id).kind!=CardType.SPELL):
        raise ResolutionError('Retained deck spell transformation requires its original physical spell')
    if request.retained_stats is not None and registry.card(request.target.card_id).kind != CardType.MINION:
        raise ResolutionError('Retained stored numbers require an original minion')
    rows = resolve_candidates(registry, context, request.pool_id, request.query,
        current_class=hero_class, source_card_id=source_card_id, policy=request.policy,
        player_id=request.target.player_id, exclude_source_by_rule=False)
    for row in rows:
        definition = stored_destination(registry, request.target, row.card_id, state=state)
        if request.retained_stats is not None and definition.kind != CardType.MINION:
            raise ResolutionError('Retained stored numbers require complete minion destinations')
    if not rows and request.empty == 'error':
        raise ResolutionError('Empty stored transformation pool')
    return rows


def transform(r, request):
    from .continuations import FrameCodec
    from .cross_zone import stored_destination, transform_stored_entity
    request.__post_init__(); source_exists(r, request.source_id)
    context = r.game._generation_context
    source = SourceAllocationFact.capture(r.state, r.state.entities.get(request.source_id))
    hero_class = r.player(request.target.player_id).hero_class if needs_class(request.query) else None
    rows = candidates(r.registry, r.state, context, request, hero_class, source.card_id if source else None)
    entity = reference_entity(r, request.target)
    if entity is None:
        return ()
    target = SourceAllocationFact.capture(r.state, entity)
    before = r.game._rng.getstate()
    selected = sample_candidates(r.game._rng, rows, 1, replacement=True)
    after = r.game._rng.getstate()
    sequence = None
    if selected:
        definition = stored_destination(r.registry, request.target, selected[0], state=r.state)
        cursor = len(r.game._events)
        transform_stored_entity(r, entity, definition, source_id=request.source_id,
            retained_cost=request.retained_cost, retained_stats=request.retained_stats)
        event, = (e for e in r.game._events[cursor:] if e.kind == 'stored_card_transformed')
        sequence = event.sequence
    draw = StoredPoolTransformDraw(request, context, r.registry.pool(request.pool_id, context).version,
        hero_class, target, source, tuple((m.card_id, m.weight) for m in rows), selected, before, after, sequence)
    r.emit(DRAW, source_id=request.source_id, target_id=request.target.entity_id,
        player_id=request.target.player_id, draw=FrameCodec(r.game.mechanics, r.registry).encode(draw), _capture=False)
    return ()


def decode(game, event):
    from .continuations import FrameCodec
    if set(dict(event.data)) != {'draw'}:
        raise ValueError('Stored draw requires its complete private receipt')
    value = FrameCodec(game.mechanics, game.registry).decode(dict(event.data)['draw'])
    if type(value) is not StoredPoolTransformDraw:
        raise ValueError('Stored draw requires its registered payload type')
    return value


def validate_events(game):
    from .cross_zone import stored_destination
    used = set()
    for event in game._events:
        if event.kind != DRAW:
            continue
        draw = decode(game, event); draw.__post_init__(); request = draw.request
        validate_allocation(game._state, game.registry, draw.target, closed=True)
        if draw.source is not None:
            validate_allocation(game._state, game.registry, draw.source, closed=True)
        if (event.source_id, event.target_id, event.player_id, event.amount) != (
                request.source_id, request.target.entity_id, request.target.player_id, 0):
            raise ValueError('Stored draw changed its original event header')
        if draw.context != game._generation_context or game.registry.pool(request.pool_id, draw.context).version != draw.pool_version:
            raise ValueError('Stored draw changed its original pool identity')
        rows = candidates(game.registry, game._state, draw.context, request, draw.hero_class,
            draw.source.card_id if draw.source else None)
        if tuple((m.card_id, m.weight) for m in rows) != draw.candidates:
            raise ValueError('Stored draw cropped/reordered/reweighted its complete original pool')
        if draw.transformation_sequence is None:
            continue
        seq = draw.transformation_sequence
        if seq in used or not 1 <= seq < event.sequence:
            raise ValueError('Stored draw duplicated or borrowed its original transformation')
        actual = game._events[seq-1]
        applied = stored_destination(game.registry, request.target, draw.selected[0], state=game._state).id
        if actual.kind != 'stored_card_transformed' or (actual.source_id, actual.target_id, actual.player_id) != (
                request.source_id, request.target.entity_id, request.target.player_id) or dict(actual.data) != {
                    'old_card_id': request.target.card_id, 'card_id': applied}:
            raise ValueError('Stored draw differs from its original committed transformation')
        used.add(seq)


def validate_pending(game, request):
    request.__post_init__()
    ref = request.target; entity = game._state.entities.get(ref.entity_id)
    source = game._state.entities.get(request.source_id)
    if entity is None or ref.zone_epoch > entity.zone_epoch or request.source_id is not None and source is None:
        raise ValueError('Stored random transformation references a missing or future residence')
    hero_class = game._state.players[ref.player_id].hero_class if needs_class(request.query) else None
    candidates(game.registry, game._state, game._generation_context, request, hero_class, source.card_id if source else None)


def register(mechanics):
    mechanics.register_payload_type(StoredPoolTransformDraw)
    mechanics.register(TransformStoredFromPool, transform)
