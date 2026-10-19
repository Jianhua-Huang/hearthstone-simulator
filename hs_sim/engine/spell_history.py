"""Frozen historical candidates and sequential, versioned spell batches (R-090).

History is a record of attempts, not a physical zone or a generation inventory.
Recasting creates a base spell and evaluates it now; it never replays old RNG.
"""
from dataclasses import dataclass, replace

from .effects import Effect, AddToHand, ChoiceOption, RequestChoice, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardClass, CardType, Zone, _name
from .pools import PoolQuery, PoolMember, GenerationPolicy, validate_policy, generation_candidates, matches_metadata, sample_candidates, resolve_candidates
from .spell_casts import CAST_ORIGINS, CastSpell, automatic, cast_record, policies
from .zones import filter_value, source_exists
from .automatic_targets import validate_preferred_source


def spell_query(query):
    filter_value(query)
    if query.kinds and query.kinds != (CardType.SPELL,):
        raise ValueError('Spell queries may only select spells')
    return replace(query, kinds=(CardType.SPELL,))


def integer_ids(value, name):
    if type(value) is not tuple or len(set(value)) != len(value):
        raise ValueError(f'{name} must contain unique immutable IDs')
    for item in value: _integer(item, name, 1)


@dataclass(frozen=True)
class SpellHistoryQuery:
    side: str = 'friendly'
    cards: PoolQuery = PoolQuery()
    origins: tuple[str, ...] = ()
    outcomes: str = 'successful'
    min_turn: int | None = None
    max_turn: int | None = None
    before_id: int | None = None
    exclude_cast_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if self.side not in ('friendly','enemy','both'):
            raise ValueError('Unknown spell history side')
        spell_query(self.cards)
        if (type(self.origins) is not tuple or len(set(self.origins)) != len(self.origins) or
                any(v not in CAST_ORIGINS for v in self.origins)):
            raise ValueError('Unknown spell history origins')
        if self.outcomes not in ('successful','completed','attempts'):
            raise ValueError('Unknown spell history outcomes')
        for value in (self.min_turn,self.max_turn,self.before_id):
            if value is not None: _integer(value,'spell history bound',1)
        if self.min_turn is not None and self.max_turn is not None and self.min_turn > self.max_turn:
            raise ValueError('Invalid spell history turn interval')
        integer_ids(self.exclude_cast_ids,'excluded spell attempts')


def spell_history_candidates(state, registry, player_id, query=SpellHistoryQuery(), source_id=None):
    _player(player_id); _source(source_id)
    if type(query) is not SpellHistoryQuery: raise ValueError('Expected SpellHistoryQuery')
    query.__post_init__()
    if source_id is not None and source_id not in state.entities:
        raise ResolutionError('Spell history source does not exist')
    cards = spell_query(query.cards)
    current_class = state.players[player_id].hero_class
    if cards.class_mode in ('current','other') and current_class in (None,CardClass.NEUTRAL):
        raise ResolutionError('Spell history requires a known current hero class')
    excluded = set(cards.exclude_card_ids)
    if cards.exclude_source:
        if source_id is None: raise ResolutionError('History source exclusion requires a source')
        excluded.add(state.entities[source_id].card_id)
    result = []
    for record in state.cast_history:
        if ((query.side == 'friendly' and record.player_id != player_id) or
                (query.side == 'enemy' and record.player_id == player_id) or
                query.origins and record.origin not in query.origins or
                query.outcomes != 'attempts' and not record.completed or
                query.outcomes == 'successful' and record.failure is not None or
                record.id in query.exclude_cast_ids or record.card_id in excluded or
                query.min_turn is not None and record.turn < query.min_turn or
                query.max_turn is not None and record.turn > query.max_turn or
                query.before_id is not None and record.id >= query.before_id):
            continue
        card = registry.card(record.card_id)
        if card.kind != CardType.SPELL or not card.hand_playable:
            raise ResolutionError('Historical candidate is not a physical spell')
        if matches_metadata(cards,card_id=card.id,kind=card.kind,cost=card.cost,meta=card.metadata,
                spell_school=card.spell_school,keywords=card.keywords,current_class=current_class,
                printed_battlecry=card.battlecry is not None,current_battlecry=False):
            result.append(record)
    return tuple(result)


def distinct_policy(distinct):
    if distinct not in ('cast','card','identity'): raise ValueError('Unknown historical distinctness policy')


def historical_groups(registry, records, distinct):
    distinct_policy(distinct)
    groups = {}
    for record in records:
        key = record.id if distinct == 'cast' else record.card_id
        if distinct == 'identity' and record.card_id in registry.pool_cards:
            key = registry.pool_card(record.card_id).generation_identity
        groups.setdefault(key,[]).append(record)
    return tuple(tuple(g) for g in groups.values())


@dataclass(frozen=True)
class DiscoverSpellHistory(Effect):
    player_id: int
    query: SpellHistoryQuery = SpellHistoryQuery()
    count: int = 3
    distinct: str = 'card'
    source_id: int | None = None
    prompt: str = '发现一张施放过的法术'
    branch_policy: str = 'current'

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id); _integer(self.count,'history offer count',1)
        _name(self.prompt,'history choice prompt'); distinct_policy(self.distinct)
        if type(self.query) is not SpellHistoryQuery: raise ValueError('Expected SpellHistoryQuery')
        self.query.__post_init__()
        if type(self.branch_policy) is not str or self.branch_policy not in ('current', 'inherit'):
            raise ValueError('Unknown discovered history branch policy')


def discover_history(r, effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    if effect.count > r.rules.max_choice_options: raise ResolutionLimitExceeded('History offers exceed choice budget')
    records = spell_history_candidates(r.state,r.registry,effect.player_id,effect.query,effect.source_id)
    groups = historical_groups(r.registry,records,effect.distinct)
    selected = r.game._rng.sample(groups,min(effect.count,len(groups)))
    if not selected: return ()
    # Repeated occurrences may offer duplicate faces only under explicit 'cast'.
    # Identity/card policies use a canonical first face, not occurrence weighting.
    def selection(record):
        if effect.branch_policy == 'current' or r.registry.card(record.card_id).choose_one is None: return None
        from .choose_branch_state import validate_selection
        from .model import ChooseBranchSelection
        return validate_selection(r.registry, ChooseBranchSelection(record.card_id, record.branch_id, ('hand',)))
    options = tuple(ChoiceOption(f'history-{n}',r.registry.card(group[0].card_id).name,
        (AddToHand(effect.player_id,group[0].card_id,effect.source_id,choose_branch=selection(group[0])),),card_id=group[0].card_id)
        for n,group in enumerate(selected,1))
    return (RequestChoice(effect.player_id,options,source_id=effect.source_id,prompt=effect.prompt),)


@dataclass(frozen=True)
class RecastSpell(Effect):
    player_id: int
    cast_id: int
    source_id: int | None = None
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    target_preference: object | None = None
    branch_policy: str = 'current'

    def __post_init__(self):
        _player(self.player_id); _integer(self.cast_id,'historical cast',1); _source(self.source_id)
        validate_preferred_source(self.target_preference, self.source_id)
        if type(self.branch_policy) is not str or self.branch_policy not in ('current', 'inherit'):
            raise ValueError('Unknown historical branch policy')
        if self.targeting == 'original':
            if self.target_id is not None: raise ValueError('Original targeting cannot prescribe another target')
            policies('explicit',None,self.choices,self.target_preference)
        else: policies(self.targeting,self.target_id,self.choices,self.target_preference)


def recast(r, effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    original = cast_record(r.state,effect.cast_id)
    card = r.registry.card(original.card_id)
    if not card.hand_playable or card.kind != CardType.SPELL:
        raise ResolutionError('Historical cast requires a physical spell')
    entity = r.create_entity(effect.player_id,card.id,Zone.GRAVEYARD)
    entity.origin_entity_id = original.source_id
    from .held_higher_cost import install as install_higher_cost
    install_higher_cost(r.state, r.registry, entity, original.held_higher_cost)
    if original.native_spell_value is not None:
        from .native_spell_values import ability_value, install
        install(r.state,r.registry,entity,ability_value(original.native_spell_value))
    if effect.branch_policy == 'inherit' and card.choose_one is not None:
        from .choose_branch_state import validate_selection
        from .model import ChooseBranchSelection
        entity.choose_branch = validate_selection(r.registry, ChooseBranchSelection(card.id, original.branch_id, ('cast_history',)))
    spec = CastSpell(effect.player_id,card.id,effect.source_id,
        original.target_id if effect.targeting == 'original' else effect.target_id,
        'explicit' if effect.targeting == 'original' else effect.targeting,effect.choices,
        target_preference=effect.target_preference)
    return automatic(r,spec,entity,None,origin='history',recast_id=original.id)


@dataclass(frozen=True)
class RecastFromHistory(Effect):
    player_id: int
    query: SpellHistoryQuery = SpellHistoryQuery()
    count: int | None = None
    distinct: str = 'cast'
    selection: str = 'oldest'
    replacement: bool = False
    source_id: int | None = None
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    branch_policy: str = 'current'
    target_preference: object | None = None

    def __post_init__(self):
        RecastSpell(self.player_id,1,self.source_id,self.target_id,self.targeting,self.choices,
            target_preference=self.target_preference,branch_policy=self.branch_policy)
        if type(self.query) is not SpellHistoryQuery: raise ValueError('Expected SpellHistoryQuery')
        self.query.__post_init__(); distinct_policy(self.distinct)
        if self.count is not None: _integer(self.count,'history cast count',0)
        if self.selection not in ('oldest','newest','random') or type(self.replacement) is not bool:
            raise ValueError('Invalid historical cast sampling policy')


@dataclass(frozen=True)
class ContinueHistoryCasts(Effect):
    spec: RecastFromHistory
    cast_ids: tuple[int, ...]
    remaining: int
    before_id: int

    def __post_init__(self):
        if type(self.spec) is not RecastFromHistory: raise ValueError('Expected history batch specification')
        self.spec.__post_init__(); integer_ids(self.cast_ids,'frozen cast candidates')
        _integer(self.remaining,'remaining history casts',0)
        _integer(self.before_id,'frozen history boundary',1)
        if tuple(sorted(self.cast_ids)) != self.cast_ids or any(i >= self.before_id for i in self.cast_ids):
            raise ValueError('Historical candidates cross their frozen boundary')
        if self.spec.count is not None and self.remaining > self.spec.count:
            raise ValueError('Historical batch grew beyond its request')


def history_batch(r, effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    validate_preferred_source(effect.target_preference,effect.source_id,r.state)
    records = spell_history_candidates(r.state,r.registry,effect.player_id,effect.query,effect.source_id)
    count = len(historical_groups(r.registry,records,effect.distinct)) if effect.count is None else effect.count
    if count > r.rules.max_resolution_steps: raise ResolutionLimitExceeded('Historical casts exceed resolution budget')
    return (ContinueHistoryCasts(effect,tuple(c.id for c in records),count,len(r.state.cast_history)+1),) if count else ()


def continue_history(r, effect):
    effect.__post_init__(); spec = effect.spec
    if not effect.remaining or not effect.cast_ids: return ()
    records = tuple(cast_record(r.state,i) for i in effect.cast_ids)
    groups = historical_groups(r.registry,records,spec.distinct)
    if spec.selection == 'random':
        group = r.game._rng.choice(groups)
        selected = r.game._rng.choice(group)
    elif spec.selection == 'newest':
        group = max(groups,key=lambda g:g[-1].id); selected = group[-1]
    else:
        group = groups[0]; selected = group[0]
    remove = {c.id for c in group} if not spec.replacement else set()
    remaining_ids = tuple(i for i in effect.cast_ids if i not in remove)
    return (RecastSpell(spec.player_id,selected.id,spec.source_id,spec.target_id,spec.targeting,spec.choices,
                target_preference=spec.target_preference,branch_policy=spec.branch_policy),
            ContinueHistoryCasts(spec,remaining_ids,effect.remaining-1,effect.before_id))


@dataclass(frozen=True)
class CastFromPool(Effect):
    player_id: int
    pool_id: str
    query: PoolQuery = PoolQuery()
    count: int = 1
    source_id: int | None = None
    replacement: bool = True
    refresh: str = 'per_cast'
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    while_source_in_play: bool = False
    policy: GenerationPolicy = GenerationPolicy()

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id); _name(self.pool_id,'spell pool')
        _integer(self.count,'pool cast count',0); spell_query(self.query)
        validate_policy(self.policy)
        policies(self.targeting,self.target_id,self.choices)
        if type(self.replacement) is not bool or self.refresh not in ('per_cast','frozen'):
            raise ValueError('Invalid spell pool batch policy')
        if type(self.while_source_in_play) is not bool or self.while_source_in_play and self.source_id is None:
            raise ValueError('Conditional batch requires a source')


@dataclass(frozen=True)
class ContinuePoolCasts(Effect):
    spec: CastFromPool
    candidates: tuple[PoolMember, ...]
    used_identities: tuple[str, ...]
    remaining: int
    source_epoch: int | None = None
    frozen_class: CardClass | None = None
    frozen_source_card: str | None = None

    def __post_init__(self):
        if type(self.spec) is not CastFromPool: raise ValueError('Expected pool casting specification')
        self.spec.__post_init__(); _integer(self.remaining,'remaining pool casts',0)
        if self.remaining > self.spec.count: raise ValueError('Pool cast batch grew beyond its request')
        if type(self.candidates) is not tuple or any(type(m) is not PoolMember for m in self.candidates):
            raise ValueError('Pool batch needs immutable candidates')
        for member in self.candidates: member.__post_init__()
        if len({m.card_id for m in self.candidates}) != len(self.candidates): raise ValueError('Duplicate pool batch candidates')
        if self.spec.refresh == 'per_cast' and self.candidates: raise ValueError('Dynamic pool cannot retain stale candidates')
        if type(self.used_identities) is not tuple or len(set(self.used_identities)) != len(self.used_identities):
            raise ValueError('Pool identity exclusions must be immutable and unique')
        for identity in self.used_identities: _name(identity,'used pool identity')
        if self.spec.replacement and self.used_identities: raise ValueError('Replacement batches cannot remove candidates')
        if self.spec.while_source_in_play != (self.source_epoch is not None): raise ValueError('Missing source epoch policy')
        if self.source_epoch is not None: _integer(self.source_epoch,'batch source epoch',0)
        if self.frozen_class is not None and type(self.frozen_class) is not CardClass:
            raise ValueError('Invalid frozen pool class')
        if self.frozen_source_card is not None: _name(self.frozen_source_card,'frozen source card')
        if self.spec.refresh == 'per_cast' and (self.frozen_class is not None or self.frozen_source_card is not None):
            raise ValueError('Dynamic pools cannot freeze query context')
        if not self.spec.replacement and len(self.used_identities) != self.spec.count-self.remaining:
            raise ValueError('Removed identities and attempted pool casts disagree')


def source_in_play(r, source_id, epoch=None):
    source = r.state.entities[source_id]
    return source.active and source.zone in (Zone.BOARD,Zone.HERO,Zone.WEAPON) and (epoch is None or source.zone_epoch == epoch)


def pool_candidates(r, spec):
    return generation_candidates(r,replace(spec,query=spell_query(spec.query)))


def pool_batch(r, effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    if effect.count > r.rules.max_resolution_steps: raise ResolutionLimitExceeded('Pool casts exceed resolution budget')
    # Even a zero request validates its declared eligible content, not coverage.
    candidates = pool_candidates(r,effect)
    if not effect.count or effect.while_source_in_play and not source_in_play(r,effect.source_id): return ()
    epoch = r.state.entities[effect.source_id].zone_epoch if effect.while_source_in_play else None
    frozen = effect.refresh == 'frozen'
    return (ContinuePoolCasts(effect,candidates if frozen else (),(),effect.count,epoch,
        r.player(effect.player_id).hero_class if frozen and effect.query.class_mode in ('current','other') else None,
        r.state.entities[effect.source_id].card_id if frozen and effect.source_id is not None else None),)


def continue_pool(r, effect):
    effect.__post_init__(); spec = effect.spec
    if not effect.remaining or spec.while_source_in_play and not source_in_play(r,spec.source_id,effect.source_epoch): return ()
    candidates = effect.candidates if spec.refresh == 'frozen' else pool_candidates(r,spec)
    candidates = tuple(m for m in candidates if r.registry.pool_card(m.card_id).generation_identity not in effect.used_identities)
    selected = sample_candidates(r.game._rng,candidates,1,replacement=True)
    if not selected: return ()
    card_id = selected[0]
    used = effect.used_identities if spec.replacement else (*effect.used_identities,r.registry.pool_card(card_id).generation_identity)
    return (CastSpell(spec.player_id,card_id,spec.source_id,spec.target_id,spec.targeting,spec.choices),
            replace(effect,used_identities=used,remaining=effect.remaining-1))


def validate_boundary(game):
    if game._frame is None: return
    state,registry = game._state,game.registry
    original = game._frame.paid_hand_choice_boundary
    batches = lambda queue: tuple(w for w in queue if type(w) is ContinueHistoryCasts)
    if batches((*game._frame.prefix, *game._frame.continuation)) != batches(original.work):
        raise ValueError('Historical spell batch changed its complete original pending request')
    for work in (*game._frame.prefix,*game._frame.continuation):
        if not isinstance(work,(ContinueHistoryCasts,ContinuePoolCasts)): continue
        work.__post_init__(); source_id = work.spec.source_id
        if source_id is not None and source_id not in state.entities:
            raise ValueError('Pending spell batch has an unknown source')
        if isinstance(work,ContinueHistoryCasts):
            if work.before_id > len(state.cast_history)+1: raise ValueError('Frozen history boundary is in the future')
            for cast_id in work.cast_ids: cast_record(state,cast_id)
        else:
            spec = work.spec
            if spec.refresh == 'frozen':
                expected = resolve_candidates(registry,game._generation_context,spec.pool_id,spell_query(spec.query),
                    current_class=work.frozen_class,source_card_id=work.frozen_source_card,policy=spec.policy,player_id=spec.player_id,
                    exclude_source_by_rule=True)
                if work.candidates != expected: raise ValueError('Frozen spell pool differs from its declared inventory')
            pool = registry.pool(spec.pool_id,game._generation_context)
            identities = {registry.pool_card(m.card_id).generation_identity for m in pool.members}
            if not set(work.used_identities).issubset(identities): raise ValueError('Batch removed an unknown pool identity')
            if work.source_epoch is not None and work.source_epoch > state.entities[source_id].zone_epoch:
                raise ValueError('Batch source epoch is in the future')


def register(mechanics):
    mechanics.register_payload_type(SpellHistoryQuery)
    mechanics.register_payload_type(PoolMember)
    for kind,handler in ((DiscoverSpellHistory,discover_history),(RecastSpell,recast),
            (RecastFromHistory,history_batch),(ContinueHistoryCasts,continue_history),
            (CastFromPool,pool_batch),(ContinuePoolCasts,continue_pool)):
        mechanics.register(kind,handler)
