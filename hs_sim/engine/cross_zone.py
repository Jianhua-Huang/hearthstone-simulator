"""Captured physical-minion batches, stored transformations and cost-tier pools."""
from dataclasses import dataclass, replace
from copy import deepcopy
from random import Random

from .construction import integer, name
from .effects import Effect, GrantDeathrattle, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .hand_upgrades import BuffStoredCard
from .model import CardClass, CardType, CostSpec, SummonStats, Zone, validate_end_turn_rng, validate_summon_stats
from .pools import (GenerationContext, GenerationPolicy, PoolMember, PoolQuery, matches_metadata,
                    resolve_candidates, sample_candidates, validate_policy)
from .sacrifice import MinionReference, BuffCapturedMinion, live_minion
from .zones import CardReference, reference_entity, source_exists
from .card_conditions import has_battlecry


@dataclass(frozen=True)
class MinionScope:
    zones: tuple[Zone, ...] = (Zone.HAND, Zone.DECK, Zone.BOARD)
    query: PoolQuery = PoolQuery()
    exclude_source: bool = False
    tribe_basis: str = 'printed'

    def __post_init__(self):
        if (type(self.zones) is not tuple or not self.zones or len(set(self.zones)) != len(self.zones)
                or any(type(z) is not Zone or z not in (Zone.HAND, Zone.DECK, Zone.BOARD) for z in self.zones)):
            raise ValueError('Minion scope requires ordered unique hand/deck/board zones')
        if type(self.query) is not PoolQuery or type(self.exclude_source) is not bool:
            raise ValueError('Invalid minion scope query or physical-source exclusion')
        self.query.__post_init__()
        if type(self.tribe_basis) is not str or self.tribe_basis not in ('printed', 'current'):
            raise ValueError('Minion scope tribe basis must be printed or current')
        if self.query.exclude_source:
            raise ValueError('Use MinionScope.exclude_source to exclude a physical entity')


def scope_value(scope):
    if type(scope) is not MinionScope: raise ValueError('Expected MinionScope')
    scope.__post_init__()


def minion_references(state, registry, player_id, scope=MinionScope(), source_id=None):
    """Freeze physical refs; tribe basis is explicit, other metadata stays printed."""
    _player(player_id); scope_value(scope); _source(source_id)
    if source_id is not None and source_id not in state.entities:
        raise ResolutionError('Cross-zone source does not exist')
    if scope.exclude_source and source_id is None:
        raise ResolutionError('Physical-source exclusion requires a source')
    query=scope.query; player=state.players[player_id]
    metadata_query = replace(query, tribes_any=()) if scope.tribe_basis == 'current' else query
    hero_class=player.hero_class if query.class_mode in ('current','other') else None
    if query.class_mode in ('current','other') and (type(hero_class) is not CardClass or hero_class==CardClass.NEUTRAL):
        raise ResolutionError('Minion query requires a playable current hero class')
    found=[]
    for zone in scope.zones:
        for eid in getattr(player,zone.value):
            entity=state.entities[eid]
            if entity.kind!=CardType.MINION or (scope.exclude_source and eid==source_id):continue
            if zone==Zone.BOARD and (not entity.active or entity.doomed or entity.health<=0):continue
            from .jade import printed_definition
            definition=printed_definition(registry, entity)
            if entity.card_id in query.exclude_card_ids:continue
            if matches_metadata(metadata_query,card_id=entity.card_id,kind=definition.kind,cost=definition.cost,
                meta=definition.metadata,spell_school=definition.spell_school,keywords=definition.keywords,
                current_class=hero_class,printed_battlecry=definition.battlecry is not None,
                current_battlecry=has_battlecry(entity.abilities),printed_attack=definition.attack):
                if scope.tribe_basis == 'current' and query.tribes_any:
                    from .tribes import has_any_tribe
                    if not has_any_tribe(registry, entity, query.tribes_any):
                        continue
                found.append(MinionReference.capture(entity) if zone==Zone.BOARD else CardReference.capture(entity))
    return tuple(found)


def reference_value(reference):
    if type(reference) not in (CardReference,MinionReference):
        raise ValueError('Expected a captured stored-card or board-minion reference')
    reference.__post_init__()


def current_target(r, reference):
    entity=live_minion(r.state,reference) if type(reference) is MinionReference else reference_entity(r,reference)
    if entity is not None and entity.kind!=CardType.MINION:
        raise ResolutionError('Cross-zone effect requires a minion')
    return entity


@dataclass(frozen=True)
class BuffMinionsInZones(Effect):
    player_id: int
    attack: int = 0
    health: int = 0
    scope: MinionScope = MinionScope()
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.attack,'batch attack'); integer(self.health,'batch health',0)
        scope_value(self.scope); _source(self.source_id)


def buff_minions(r, effect):
    effect.__post_init__()
    refs=minion_references(r.state,r.registry,effect.player_id,effect.scope,effect.source_id)
    if len(refs)>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Minion batch exceeds resolution budget')
    return tuple(BuffCapturedMinion(ref,effect.attack,effect.health,effect.source_id) if type(ref) is MinionReference
                 else BuffStoredCard(ref,effect.attack,effect.health,effect.source_id) for ref in refs)


@dataclass(frozen=True)
class RandomBuffStoredMinion(Effect):
    player_id: int
    attack: int = 0
    health: int = 0
    zone: Zone = Zone.HAND
    query: PoolQuery = PoolQuery()
    source_id: int | None = None
    cost: CostSpec | None = None
    expires_turn: int | None = None
    tribe_basis: str = 'printed'

    def __post_init__(self):
        from .zones import card_zone,filter_value
        _player(self.player_id); _source(self.source_id); card_zone(self.zone); filter_value(self.query)
        _integer(self.attack,'random stored attack'); integer(self.health,'random stored health',0)
        if type(self.tribe_basis) is not str or self.tribe_basis not in ('printed', 'current'):
            raise ValueError('Random stored tribe basis must be printed or current')
        if self.query.kinds not in ((),(CardType.MINION,)):
            raise ValueError('Random stored buff requires a minion query')
        if self.cost is not None:
            if type(self.cost) is not CostSpec:raise ValueError('Random stored buff cost requires CostSpec')
            self.cost.__post_init__()
        if self.expires_turn is not None:integer(self.expires_turn,'stored buff expiry')


def random_buff_stored(r,effect):
    from .zones import zone_candidates
    from .costs import validate_cost_targets
    effect.__post_init__(); source_exists(r,effect.source_id)
    query=replace(effect.query,kinds=(CardType.MINION,))
    metadata_query=replace(query,tribes_any=()) if effect.tribe_basis=='current' else query
    refs=zone_candidates(r,effect.player_id,effect.zone,metadata_query,
                        effect.player_id,effect.source_id)
    if effect.tribe_basis=='current' and query.tribes_any:
        from .tribes import has_any_tribe
        refs=tuple(ref for ref in refs if has_any_tribe(r.registry,r.state.entities[ref.entity_id],query.tribes_any))
    validate_cost_targets(r.state,effect,((r.registry.card(ref.card_id),r.state.entities[ref.entity_id]) for ref in refs))
    if not refs or effect.attack==effect.health==0 and effect.cost is None:return ()
    # One physical candidate supplies both modifications; no second random draw.
    target=r.game._rng.choice(refs)
    return (BuffStoredCard(target,effect.attack,effect.health,effect.source_id,effect.expires_turn,effect.cost),)


@dataclass(frozen=True)
class TransformCapturedMinion(Effect):
    target: CardReference | MinionReference
    card_id: str
    source_id: int | None = None
    retained_cost: int | None = None
    deathrattle_grant: GrantDeathrattle | None = None

    def __post_init__(self):
        reference_value(self.target); name(self.card_id,'transformation card'); _source(self.source_id)
        if self.retained_cost is not None:integer(self.retained_cost,'retained transformation cost',0)
        validate_transform_grant(self.target, self.deathrattle_grant)


def validate_transform_grant(target, grant):
    if grant is None: return
    if (type(target) is not MinionReference or type(grant) is not GrantDeathrattle or
            grant.target_id != target.entity_id or grant.deathrattle_memory is None):
        raise ValueError('Transformation grant requires its original physical board recipient')
    grant.__post_init__()
    original = grant.deathrattle_memory.summon_copy.origin
    if (original.entity_id, original.controller, original.card_id, original.zone_epoch, original.entered_order) != (
            target.entity_id, target.player_id, target.card_id, target.zone_epoch, target.entered_order):
        raise ValueError('Transformation grant borrowed another original minion')


@dataclass(frozen=True)
class TakeCapturedMinion(Effect):
    target: MinionReference | None
    player_id: int
    source_id: int | None = None
    play_id: int | None = None

    def __post_init__(self):
        if self.target is None:
            if self.play_id is None or self.source_id is None:raise ValueError('Paid target control requires its actual play and source')
        else:
            if type(self.target) is not MinionReference:raise ValueError('Captured control requires a board minion reference')
            self.target.__post_init__()
            if self.play_id is not None:raise ValueError('Captured and original paid target are independent reference producers')
        _player(self.player_id);_source(self.source_id)
        if self.play_id is not None:integer(self.play_id,'original control play',1)


def take_captured_minion(r,effect):
    from .effects import ChangeControl
    from .resolver import change_control
    effect.__post_init__();source_exists(r,effect.source_id)
    reference=effect.target
    if effect.play_id is not None:
        from .paid_hand_acceptance import original_target
        record,fact=original_target(r,effect.play_id)
        if (record.source_id,record.player_id)!=(effect.source_id,effect.player_id) or fact.zone!=Zone.BOARD or fact.kind!=CardType.MINION:
            raise ResolutionError('Original control target differs from its actual source/player/board minion')
        reference=MinionReference(fact.entity_id,fact.controller,fact.card_id,fact.zone_epoch,fact.entered_order)
    if r.registry.card(reference.card_id).kind!=CardType.MINION:
        raise ResolutionError('Captured control requires an original minion')
    entity=live_minion(r.state,reference)
    if entity is None:
        r.stale(effect,reference.entity_id);return ()
    return change_control(r,ChangeControl(entity.id,effect.player_id))


@dataclass(frozen=True)
class TransformStoredCard(Effect):
    """Reset a captured physical hand/deck card to a new printed definition."""
    target: CardReference
    card_id: str
    source_id: int | None = None
    retained_cost: int | None = None

    def __post_init__(self):
        if type(self.target) is not CardReference:
            raise ValueError('Stored transformation requires CardReference')
        self.target.__post_init__()
        name(self.card_id,'transformation card'); _source(self.source_id)
        if self.retained_cost is not None:integer(self.retained_cost,'retained transformation cost',0)


@dataclass(frozen=True)
class TransformStoredIntoCopy(Effect):
    target: CardReference
    card: CardReference
    source_id: int | None = None

    def __post_init__(self):
        for reference in (self.target,self.card):
            if type(reference) is not CardReference:
                raise ValueError('Stored copy transformation requires physical CardReference values')
            reference.__post_init__()
        _source(self.source_id)


@dataclass(frozen=True)
class TransformMinionIntoCopy(Effect):
    """Install current board material in the original physical recipient."""
    target: MinionReference
    card: MinionReference
    source_id: int | None = None
    stats: SummonStats | None = None

    def __post_init__(self):
        for reference in (self.target, self.card):
            if type(reference) is not MinionReference:
                raise ValueError('Board copy transformation requires MinionReference values')
            reference.__post_init__()
        _source(self.source_id)
        validate_summon_stats(self.stats)


def transform_minion_into_copy(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    definition = destination(r.registry, effect.target, effect.card.card_id)
    source = live_minion(r.state, effect.card)
    target = live_minion(r.state, effect.target)
    if source is None or target is None:
        r.emit('zone_target_skipped', source_id=effect.source_id,
               target_id=(effect.card if source is None else effect.target).entity_id,
               reason='captured_minion_departed')
        return ()
    # Self-copy must read the complete local state before the original is reset.
    material = deepcopy(source)
    from .resolver import transform_minion
    return transform_minion(r, target, definition, source_id=effect.source_id,
                            copy_material=material, stats=effect.stats)


@dataclass(frozen=True)
class TransformDefiningHandCard(Effect):
    """A native source changes its own stored face and retains only that source."""
    target: CardReference
    card_id: str
    source_ability_id: int

    def __post_init__(self):
        if type(self.target) is not CardReference or self.target.zone != Zone.HAND:
            raise ValueError('Defining transformation requires a physical hand reference')
        self.target.__post_init__()
        name(self.card_id, 'defining transformation card')
        integer(self.source_ability_id, 'defining source ability', 1)


def transform_defining_hand_card(r, effect):
    effect.__post_init__()
    definition = stored_destination(r.registry, effect.target, effect.card_id, state=r.state)
    entity = reference_entity(r, effect.target)
    if entity is None:
        return ()
    binding = next((a for a in entity.abilities if a.id == effect.source_ability_id and
                    a.kind == 'defining_hand_source'), None)
    if binding is None:
        raise ResolutionError('Defining transformation requires its original native source')
    r.registry.validate_defining_hand_binding(entity, binding)
    if definition.kind != r.registry.card(binding.defining_card_id).kind:
        raise ResolutionError('Native turn-start shifter retains its original physical card type')
    if definition.defining_hand_source is not None and definition.id != binding.defining_card_id:
        raise ResolutionError('Nested defining sources require a supported lifecycle policy')
    old_card = entity.card_id
    reset_stored_entity(r, entity, definition)
    entity.abilities = [a for a in entity.abilities if a.kind != 'defining_hand_source']
    entity.abilities.append(binding)
    from .lifecycle import refresh_entity
    refresh_entity(entity)
    announce_stored_transform(r, entity, old_card, source_id=entity.id)
    return ()


def transform_stored_into_copy(r, effect):
    effect.__post_init__();source_exists(r,effect.source_id)
    definition=stored_destination(r.registry,effect.target,effect.card.card_id)
    source=reference_entity(r,effect.card)
    target=reference_entity(r,effect.target)
    if source is None or target is None:return ()
    if source.components:
        raise ResolutionError('Composite stored copy transformation requires a supported material policy')
    # Read the guarded current source before resetting a potentially identical recipient.
    material=deepcopy(source);old_card=target.card_id
    reset_stored_entity(r,target,definition)
    from .zones import copy_current_stored_state
    copy_current_stored_state(r.state,material,target)
    announce_stored_transform(r,target,old_card,source_id=effect.source_id)
    return ()


@dataclass(frozen=True)
class TransformDefiningHandCardFromPool(Effect):
    target: CardReference
    defining_card_id: str
    source_ability_id: int
    pool_id: str
    query: PoolQuery = PoolQuery()
    policy: GenerationPolicy = GenerationPolicy()
    empty: str = 'skip'

    def __post_init__(self):
        if type(self.target) is not CardReference or self.target.zone != Zone.HAND:
            raise ValueError('Native pool transformation requires a physical hand reference')
        self.target.__post_init__()
        name(self.defining_card_id, 'original native source card')
        integer(self.source_ability_id, 'native source ability', 1)
        name(self.pool_id, 'native transformation pool')
        if type(self.query) is not PoolQuery:
            raise ValueError('Native transformation requires PoolQuery')
        self.query.__post_init__(); validate_policy(self.policy)
        if self.empty not in ('skip', 'error'):
            raise ValueError('Unknown native transformation empty policy')


@dataclass(frozen=True)
class DefiningHandTransformDraw:
    request: TransformDefiningHandCardFromPool
    context: GenerationContext
    hero_class: CardClass | None
    owner_event_sequence: int
    candidates: tuple[PoolMember, ...]
    selected: tuple[str, ...]
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.request) is not TransformDefiningHandCardFromPool or type(self.context) is not GenerationContext:
            raise ValueError('Native draw requires its complete request and generation context')
        self.request.__post_init__(); self.context.__post_init__()
        integer(self.owner_event_sequence, 'native owner-turn witness', 1)
        needs_class = self.request.query.class_mode in ('current', 'other')
        if needs_class != (self.hero_class is not None) or self.hero_class is not None and (
                type(self.hero_class) is not CardClass or self.hero_class == CardClass.NEUTRAL):
            raise ValueError('Native draw class differs from its query')
        if type(self.candidates) is not tuple or any(type(m) is not PoolMember for m in self.candidates):
            raise ValueError('Native draw requires its complete ordered candidates')
        for member in self.candidates: member.__post_init__()
        if type(self.selected) is not tuple or len(self.selected) > 1 or any(type(i) is not str for i in self.selected):
            raise ValueError('Native draw selects at most one card')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        probe = Random(); probe.setstate(self.rng_before)
        if sample_candidates(probe, self.candidates, 1, replacement=True) != self.selected or probe.getstate() != self.rng_after:
            raise ValueError('Native draw lost its original integer sampling or RNG')


def native_pool_candidates(registry, context, request, hero_class=None):
    request.__post_init__()
    original = registry.card(request.defining_card_id)
    if original.defining_hand_source is None or registry.card(request.target.card_id).kind != original.kind:
        raise ResolutionError('Native pool request requires its declared original source and physical type')
    if request.query.kinds not in ((), (original.kind,)):
        raise ResolutionError('Native pool query changes its original physical card type')
    query = replace(request.query, kinds=(original.kind,))
    rows = resolve_candidates(registry, context, request.pool_id, query, current_class=hero_class,
        source_card_id=original.id, policy=request.policy, player_id=request.target.player_id)
    for row in rows:
        definition = stored_destination(registry, request.target, row.card_id)
        if definition.kind != original.kind or definition.defining_hand_source is not None and definition.id != original.id:
            raise ResolutionError('Eligible native transformation candidate requires an unsupported source lifecycle')
    if not rows and request.empty == 'error':
        raise ResolutionError('Empty native transformation pool')
    return rows


def native_pool_binding(registry, entity, request):
    binding = next((a for a in entity.abilities if a.kind == 'defining_hand_source' and
                    a.id == request.source_ability_id), None)
    if binding is None or binding.defining_card_id != request.defining_card_id:
        raise ResolutionError('Native pool request borrowed another defining source')
    registry.validate_defining_hand_binding(entity, binding)
    return binding


def transform_defining_hand_card_from_pool(r, effect):
    hero_class = r.player(effect.target.player_id).hero_class if effect.query.class_mode in ('current', 'other') else None
    context = r.game._generation_context
    rows = native_pool_candidates(r.registry, context, effect, hero_class)
    entity = reference_entity(r, effect.target)
    if entity is None: return ()
    binding = native_pool_binding(r.registry, entity, effect)
    if not binding.progress_keys:
        raise ResolutionError('Native pool draw requires an accepted owner-turn witness')
    owner_event = int(binding.progress_keys[-1].split(':')[1])
    before = r.game._rng.getstate()
    selected = sample_candidates(r.game._rng, rows, 1, replacement=True)
    draw = DefiningHandTransformDraw(effect, context, hero_class, owner_event, rows, selected, before, r.game._rng.getstate())
    from .continuations import FrameCodec
    r.emit('defining_hand_card_randomized', source_id=entity.id, target_id=entity.id,
        player_id=entity.controller, draw=FrameCodec(r.game.mechanics, r.registry).encode(draw))
    if not selected: return ()
    return (TransformDefiningHandCard(effect.target, selected[0], binding.id),)


def validate_native_pool_events(game):
    from .continuations import FrameCodec
    codec = None
    for event in game._events:
        if event.kind != 'defining_hand_card_randomized': continue
        if set(dict(event.data)) != {'draw'}:
            raise ValueError('Native draw requires exactly its complete private receipt')
        if codec is None: codec = FrameCodec(game.mechanics, game.registry)
        draw = codec.decode(dict(event.data)['draw'])
        if type(draw) is not DefiningHandTransformDraw or draw.context != game._generation_context:
            raise ValueError('Native draw changed its original generation context')
        request = draw.request
        if (event.source_id != request.target.entity_id or event.target_id != request.target.entity_id or
                event.player_id != request.target.player_id or event.amount != 0 or
                request.target.entity_id not in game._state.entities or draw.owner_event_sequence >= event.sequence):
            raise ValueError('Native draw changed its physical source or owner window')
        witness = game._events[draw.owner_event_sequence - 1]
        if witness.kind != 'turn_started' or witness.player_id != event.player_id:
            raise ValueError('Native draw requires its actual owner-turn event')
        if native_pool_candidates(game.registry, draw.context, request, draw.hero_class) != draw.candidates:
            raise ValueError('Native draw changed its complete original pool')


def stored_destination(registry, reference, card_id, *, state=None):
    if state is not None:
        from .game_boards import resolve_card_id
        card_id = resolve_card_id(state, registry, card_id)
    original, definition = registry.card(reference.card_id), registry.card(card_id)
    if not original.hand_playable or not definition.hand_playable:
        raise ResolutionError('Stored transformation requires physical hand/deck definitions')
    return definition


def transform_stored_card(r, effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    definition=stored_destination(r.registry,effect.target,effect.card_id,state=r.state)
    entity=reference_entity(r,effect.target)
    if entity is None:return ()
    return transform_stored_entity(r,entity,definition,source_id=effect.source_id,
                                   retained_cost=effect.retained_cost)


def destination(registry, reference, card_id):
    original=registry.card(reference.card_id); definition=registry.card(card_id)
    if original.kind!=CardType.MINION or definition.kind!=CardType.MINION or definition.choice_only:
        raise ResolutionError('Transformation requires physical minion definitions')
    if type(reference) is CardReference and not definition.hand_playable:
        raise ResolutionError('Transformation cannot put this minion in a stored zone')
    return definition


def transform_captured(r, effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    definition=destination(r.registry,effect.target,effect.card_id)
    entity=current_target(r,effect.target)
    if entity is None:return ()
    if type(effect.target) is MinionReference:
        from .resolver import transform_minion
        return transform_minion(r,entity,definition,source_id=effect.source_id,retained_cost=effect.retained_cost,
            deathrattle_grant=effect.deathrattle_grant)
    return transform_stored_entity(r,entity,definition,source_id=effect.source_id,
                                   retained_cost=effect.retained_cost)


def transform_stored_entity(r, entity, definition, *, source_id=None, retained_cost=None, retained_stats=None):
    """One lifecycle for the original minion operation and general stored cards."""
    from .costs import attach_cost
    if retained_stats is not None:
        validate_summon_stats(retained_stats)
        if (retained_stats.attack is None or retained_stats.health is None or retained_cost is None or
                entity.kind != CardType.MINION or definition.kind != CardType.MINION):
            raise ResolutionError('Retained stored stats require complete minion numbers and Cost')
    old_card=entity.card_id
    reset_stored_entity(r,entity,definition)
    if retained_cost is not None:
        attach_cost(r.state,entity,CostSpec(set_to=retained_cost),source_id)
    if retained_stats is not None:
        from .lifecycle import attachment_id, refresh_entity
        from .model import Enchantment
        entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=source_id,
            set_attack=retained_stats.attack, set_health=retained_stats.health, label='retained_transform_stats'))
        refresh_entity(entity)
    announce_stored_transform(r,entity,old_card,source_id=source_id)
    return ()


def reset_stored_entity(r, entity, definition):
    from .lifecycle import reset_to_definition
    entity.face_replaced=True
    entity.zone_epoch+=1
    reset_to_definition(r.state,entity,definition,r.registry,components=())


def announce_stored_transform(r, entity, old_card, *, source_id=None):
    if entity.zone==Zone.HAND:r.game._information.hide_hand_identity(entity.id)
    else:r.game._information.conceal(entity.id)
    r.refresh_auras()
    r.emit('stored_card_transformed',target_id=entity.id,source_id=source_id,
           player_id=entity.controller,old_card_id=old_card,card_id=entity.card_id)


def cost_value(registry, entity, basis):
    if basis=='printed':
        from .jade import printed_definition
        return printed_definition(registry, entity).cost
    from .costs import local_cost
    return local_cost(entity)[0]


def transformed_cost_tier(source_cost, delta):
    """Published 32.2 Evolve tier; Devolve availability is resolved separately."""
    integer(source_cost, 'original transformation cost', 0)
    _integer(delta, 'transformation cost delta')
    if delta > 0:
        return min(10, source_cost + delta) if source_cost <= 10 else source_cost
    return max(0, source_cost + delta)


@dataclass(frozen=True)
class TransformMinionsInZones(Effect):
    player_id: int
    pool_id: str
    cost_delta: int = 0
    scope: MinionScope = MinionScope()
    query: PoolQuery = PoolQuery(kinds=(CardType.MINION,),collectible=True)
    cost_basis: str = 'printed'
    retain_cost_basis: str | None = None
    source_id: int | None = None
    policy: GenerationPolicy = GenerationPolicy()
    empty: str = 'skip'
    deathrattle_behavior_id: str | None = None

    def __post_init__(self):
        _player(self.player_id); name(self.pool_id,'transformation pool'); _integer(self.cost_delta,'cost delta')
        scope_value(self.scope); _source(self.source_id); validate_policy(self.policy)
        if type(self.query) is not PoolQuery:raise ValueError('Expected transformation PoolQuery')
        self.query.__post_init__()
        if self.query.kinds not in ((),(CardType.MINION,)) or self.query.min_cost is not None or self.query.max_cost is not None:
            raise ValueError('Transformation determines its own minion cost tier')
        if self.cost_basis not in ('printed','local') or self.retain_cost_basis not in (None,'printed','local'):
            raise ValueError('Invalid transformation cost basis')
        if self.empty not in ('skip','error'):raise ValueError('Invalid empty transformation pool policy')
        if self.deathrattle_behavior_id is not None:
            name(self.deathrattle_behavior_id, 'original transformation Deathrattle')
            if self.scope.zones != (Zone.BOARD,) or self.source_id is None or self.retain_cost_basis is not None:
                raise ValueError('Remembered transformation requires a sourced ordinary board batch')


@dataclass(frozen=True)
class TransformPoolTarget(Effect):
    target: CardReference | MinionReference
    pool_id: str
    query: PoolQuery
    policy: GenerationPolicy
    player_id: int
    hero_class: CardClass | None = None
    source_card_id: str | None = None
    source_id: int | None = None
    retained_cost: int | None = None
    empty: str = 'skip'
    deathrattle_grant: GrantDeathrattle | None = None

    def __post_init__(self):
        _player(self.player_id)
        reference_value(self.target); name(self.pool_id,'transformation pool'); _source(self.source_id)
        validate_policy(self.policy)
        if type(self.query) is not PoolQuery:raise ValueError('Expected captured pool query')
        self.query.__post_init__()
        if self.query.kinds!=(CardType.MINION,) or self.query.min_cost is None or self.query.min_cost!=self.query.max_cost:
            raise ValueError('Captured transformation requires one minion cost tier')
        if (self.query.class_mode in ('current','other')) != (self.hero_class is not None):
            raise ValueError('Captured transformation class disagrees with query')
        if self.hero_class is not None and (type(self.hero_class) is not CardClass or self.hero_class==CardClass.NEUTRAL):
            raise ValueError('Captured transformation requires playable class')
        if (self.source_id is None)!=(self.source_card_id is None):
            raise ValueError('Captured transformation source is inconsistent')
        if self.source_card_id is not None:name(self.source_card_id,'captured transformation source')
        if self.retained_cost is not None:integer(self.retained_cost,'retained transformation cost',0)
        if self.empty not in ('skip','error'):raise ValueError('Invalid empty pool policy')
        validate_transform_grant(self.target, self.deathrattle_grant)


@dataclass(frozen=True)
class TransformMinionFromPool(Effect):
    target: CardReference | MinionReference
    pool_id: str
    cost_delta: int = 0
    query: PoolQuery = PoolQuery(kinds=(CardType.MINION,),collectible=True)
    cost_basis: str = 'printed'
    retain_cost_basis: str | None = None
    source_id: int | None = None
    policy: GenerationPolicy = GenerationPolicy()
    empty: str = 'skip'

    def __post_init__(self):
        reference_value(self.target)
        # Single and batch declarations share exactly the same pool/cost policy.
        self.batch_spec().__post_init__()

    def batch_spec(self):
        return TransformMinionsInZones(self.target.player_id,self.pool_id,self.cost_delta,
            query=self.query,cost_basis=self.cost_basis,retain_cost_basis=self.retain_cost_basis,
            source_id=self.source_id,policy=self.policy,empty=self.empty)


def candidates(registry, context, effect):
    effect.__post_init__()
    if effect.source_card_id is not None:registry.card(effect.source_card_id)
    rows=resolve_candidates(registry,context,effect.pool_id,effect.query,policy=effect.policy,
                            current_class=effect.hero_class,source_card_id=effect.source_card_id,
                            player_id=effect.player_id)
    for row in rows:destination(registry,effect.target,row.card_id)
    if not rows and effect.empty=='error':raise ResolutionError('Empty transformation cost tier')
    return rows


def prepare_transforms(r,effect,refs):
    effect.__post_init__(); source_exists(r,effect.source_id)
    context=r.game._generation_context
    if type(context) is not GenerationContext:raise ResolutionError('Transformation needs a generation context')
    r.registry.pool(effect.pool_id,context)
    if len(refs)>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Transformation batch exceeds resolution budget')
    hero_class=r.player(effect.player_id).hero_class if effect.query.class_mode in ('current','other') else None
    source_card_id=r.state.entities[effect.source_id].card_id if effect.source_id is not None else None
    if effect.query.class_mode in ('current','other') and (type(hero_class) is not CardClass or hero_class==CardClass.NEUTRAL):
        raise ResolutionError('Transformation query requires a playable current hero class')
    if effect.query.exclude_source and source_card_id is None:
        raise ResolutionError('Transformation pool excludes its source but has no source')
    work=[]
    if effect.deathrattle_behavior_id is not None:r.registry.behavior(effect.deathrattle_behavior_id)
    for ref in refs:
        if r.registry.card(ref.card_id).kind!=CardType.MINION:
            raise ResolutionError('Transformation requires a captured minion')
        entity=current_target(r,ref)
        if entity is None:continue
        cost=transformed_cost_tier(cost_value(r.registry,entity,effect.cost_basis),effect.cost_delta)
        retained=cost_value(r.registry,entity,effect.retain_cost_basis) if effect.retain_cost_basis is not None else None
        grant = None
        if effect.deathrattle_behavior_id is not None:
            from .copy_materials import CopyEntryMaterial
            from .model import DeathrattleMemory, NativeDeathrattleSpec
            material = CopyEntryMaterial.capture(r.state, entity, 'remembered_copy', 'current', registry=r.registry)
            grant = GrantDeathrattle(entity.id, effect.deathrattle_behavior_id, effect.source_id,
                deathrattle_memory=DeathrattleMemory(NativeDeathrattleSpec('copy_summon'), summon_copy=material))
        step=TransformPoolTarget(ref,effect.pool_id,replace(effect.query,kinds=(CardType.MINION,),min_cost=cost,max_cost=cost),
             effect.policy,effect.player_id,hero_class,source_card_id,effect.source_id,retained,effect.empty,grant)
        if effect.cost_delta < 0:
            # Visit only costs that physically occur in this immutable pool.
            # A large local cost must not cause billions of empty integer probes.
            pool = r.registry.pool(effect.pool_id, context)
            tiers = sorted({r.registry.pool_card(row.card_id).cost for row in pool.members
                if r.registry.pool_card(row.card_id).cost <= cost}, reverse=True)
            for tier in tiers:
                probe = replace(step, query=replace(step.query, min_cost=tier, max_cost=tier), empty='skip')
                if candidates(r.registry, context, probe):
                    step = replace(probe, empty=effect.empty)
                    break
        candidates(r.registry,context,step)  # Validate the entire captured batch before any RNG or mutation.
        work.append(step)
    return tuple(work)


def transform_batch(r,effect):
    effect.__post_init__()
    refs=minion_references(r.state,r.registry,effect.player_id,effect.scope,effect.source_id)
    return prepare_transforms(r,effect,refs)


def transform_single(r,effect):
    effect.__post_init__()
    return prepare_transforms(r,effect.batch_spec(),(effect.target,))


def transform_pool_target(r, effect):
    source_exists(r,effect.source_id)
    rows=candidates(r.registry,r.game._generation_context,effect)
    if current_target(r,effect.target) is None or not rows:return ()
    selected=sample_candidates(r.game._rng,rows,1,replacement=True)[0]
    return transform_captured(r,TransformCapturedMinion(effect.target,selected,effect.source_id,effect.retained_cost,
        effect.deathrattle_grant))


def validate_boundary(game):
    from .transform_replacements import validate_events as validate_replacements
    validate_replacements(game)
    from .stored_pool_transforms import TransformStoredFromPool, validate_events, validate_pending
    validate_events(game)
    validate_native_pool_events(game)
    if game._frame is None:return
    def check(work):
        grant = getattr(work, 'deathrattle_grant', None)
        if grant is not None:
            from .deathrattle_memory import validate_copy_memory
            validate_copy_memory(game._state, game.registry, grant.deathrattle_memory)
            game.registry.behavior(grant.behavior_id)
            if grant.source_id != work.source_id:
                raise ValueError('Pending transformation changed its original grant source')
        if type(work) is TransformStoredFromPool:
            validate_pending(game, work)
        elif type(work) is TransformPoolTarget:
            candidates(game.registry,game._generation_context,work)
        elif type(work) is TransformMinionFromPool:
            if type(game._generation_context) is not GenerationContext:
                raise ValueError('Transformation needs a generation context')
            game.registry.pool(work.pool_id,game._generation_context)
            if game.registry.card(work.target.card_id).kind!=CardType.MINION:
                raise ValueError('Transformation requires a minion reference')
        elif type(work) is TransformCapturedMinion:
            destination(game.registry,work.target,work.card_id)
        elif type(work) is TransformStoredCard:
            work.__post_init__()
            stored_destination(game.registry,work.target,work.card_id,state=game._state)
        elif type(work) is TransformDefiningHandCardFromPool:
            hero_class = game._state.players[work.target.player_id].hero_class if work.query.class_mode in ('current', 'other') else None
            native_pool_candidates(game.registry, game._generation_context, work, hero_class)
            entity = game._state.entities.get(work.target.entity_id)
            if entity is not None and (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) == (
                    work.target.player_id, work.target.zone, work.target.card_id, work.target.zone_epoch):
                native_pool_binding(game.registry, entity, work)
        elif type(work) is TransformDefiningHandCard:
            work.__post_init__()
            stored_destination(game.registry, work.target, work.card_id, state=game._state)
            entity = game._state.entities.get(work.target.entity_id)
            if entity is not None and (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) == (
                    work.target.player_id, work.target.zone, work.target.card_id, work.target.zone_epoch):
                binding = next((a for a in entity.abilities if a.kind == 'defining_hand_source' and
                                a.id == work.source_ability_id), None)
                if binding is None:
                    raise ValueError('Pending defining transformation has no native source')
                game.registry.validate_defining_hand_binding(entity, binding)
                if game.registry.card(work.card_id).kind != game.registry.card(binding.defining_card_id).kind:
                    raise ValueError('Pending native shifter changes its original physical card type')
        elif type(work) is TransformStoredIntoCopy:
            work.__post_init__()
            stored_destination(game.registry,work.target,work.card.card_id)
            if work.card.entity_id not in game._state.entities:
                raise ValueError('Stored copy transformation references a missing source card')
        elif type(work) is TransformMinionIntoCopy:
            work.__post_init__()
            destination(game.registry, work.target, work.card.card_id)
            if work.card.entity_id not in game._state.entities:
                raise ValueError('Board copy transformation references a missing source minion')
        if type(work) in (TransformPoolTarget,TransformCapturedMinion,TransformMinionFromPool,TransformStoredCard,TransformStoredIntoCopy,TransformMinionIntoCopy,TransformDefiningHandCard,TransformDefiningHandCardFromPool):
            if work.target.entity_id not in game._state.entities or (getattr(work, 'source_id', None) is not None and work.source_id not in game._state.entities):
                raise ValueError('Transformation references a missing entity')
    for work in (*game._frame.prefix,*game._frame.continuation):check(work)
    for option in game._frame.options:
        for work in option.effects:check(work)


def register(mechanics):
    from .stored_pool_transforms import register as register_stored_pool
    register_stored_pool(mechanics)
    mechanics.register_payload_type(MinionScope)
    mechanics.register_payload_type(DefiningHandTransformDraw)
    mechanics.register(BuffMinionsInZones,buff_minions)
    mechanics.register(RandomBuffStoredMinion,random_buff_stored)
    mechanics.register(TransformCapturedMinion,transform_captured)
    mechanics.register(TakeCapturedMinion,take_captured_minion)
    mechanics.register(TransformStoredCard,transform_stored_card)
    mechanics.register(TransformStoredIntoCopy,transform_stored_into_copy)
    mechanics.register(TransformMinionIntoCopy,transform_minion_into_copy)
    mechanics.register(TransformDefiningHandCard,transform_defining_hand_card)
    mechanics.register(TransformDefiningHandCardFromPool,transform_defining_hand_card_from_pool)
    mechanics.register(TransformMinionsInZones,transform_batch)
    mechanics.register(TransformPoolTarget,transform_pool_target)
    mechanics.register(TransformMinionFromPool,transform_single)
