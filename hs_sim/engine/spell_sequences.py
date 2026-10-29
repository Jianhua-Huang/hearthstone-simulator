"""Finite spell waves and continuations bound to their physical draw/batch."""
from dataclasses import dataclass
from .effects import Damage, Draw, Effect, _integer, _player
from .errors import ResolutionError
from .model import CardType, CostSpec, DamageKind, Zone
from .pools import PoolQuery


@dataclass(frozen=True)
class SpellSequence(Effect):
    player_id: int
    cast_id: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.cast_id, 'sequence cast', 1)
        _integer(self.source_id, 'sequence source', 1)


@dataclass(frozen=True)
class DecreasingMinionDamage(SpellSequence):
    amount: int

    def __post_init__(self):
        super().__post_init__()
        _integer(self.amount, 'initial decreasing damage', 1)


@dataclass(frozen=True)
class MinionDamageWave(SpellSequence):
    initial: int
    remaining: int

    def __post_init__(self):
        super().__post_init__()
        _integer(self.initial, 'initial quoted damage', 1)
        _integer(self.remaining, 'remaining wave damage', 1)
        if self.remaining > self.initial:
            raise ValueError('A decreasing wave cannot grow past its original quote')


@dataclass(frozen=True)
class DamageMinionsDrawDeaths(SpellSequence):
    amount: int

    def __post_init__(self):
        super().__post_init__()
        _integer(self.amount, 'damage before death draws', 0)


@dataclass(frozen=True)
class DrawSpellBatchDeaths(SpellSequence):
    batch_id: int

    def __post_init__(self):
        super().__post_init__()
        _integer(self.batch_id, 'original health batch', 1)


@dataclass(frozen=True)
class DamageMinionsRepeatIfNoDeaths(DamageMinionsDrawDeaths):
    """One first batch, followed by at most one fresh-board damage batch."""


@dataclass(frozen=True)
class RepeatSpellBatchIfNoDeaths(DrawSpellBatchDeaths):
    amount:int

    def __post_init__(self):
        super().__post_init__()
        _integer(self.amount,'second minion wave base damage',0)

    def validate_in_state(self,state,registry):
        original_wave_results(state,registry,self)


@dataclass(frozen=True)
class DrawWithCostReduction(Effect):
    player_id: int
    reduction: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.reduction, 'drawn card reduction', 0)
        _integer(self.source_id, 'draw source', 1)


@dataclass(frozen=True)
class DrawWithTemporaryCostReduction(DrawWithCostReduction):
    expires_turn: int

    def __post_init__(self):
        super().__post_init__()
        _integer(self.expires_turn,'drawn card current-turn expiry',1)


@dataclass(frozen=True)
class DrawMatchingWithCostReduction(DrawWithCostReduction):
    """One physical matching draw; reduce that actual hand arrival after reactions."""
    query: PoolQuery

    def __post_init__(self):
        super().__post_init__()
        if type(self.query) is not PoolQuery:
            raise ValueError('Discounted matching draw requires a PoolQuery')
        self.query.__post_init__()


@dataclass(frozen=True)
class DrawIfCheap(Effect):
    player_id: int
    maximum: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.maximum, 'draw price threshold', 0)
        _integer(self.source_id, 'conditional draw source', 1)


def require_cast(r, request):
    request.__post_init__()
    from .spell_casts import active_cast
    cast = active_cast(r.state, request.source_id, request.player_id)
    source = r.state.entities.get(request.source_id)
    if (cast is None or cast.id != request.cast_id or not cast.payload_started or
            source is None or r.registry.card(source.card_id).kind != CardType.SPELL):
        raise ResolutionError('Spell sequence requires its original active SPELL cast')
    return cast


def minions(r):
    return tuple(eid for pid in (1, 2) for eid in r.state.players[pid].board
        for entity in (r.state.entities[eid],)
        if entity.kind == CardType.MINION and entity.active and entity.health > 0
        and not entity.doomed and r.registry.card(entity.card_id).interactable is None)


def begin_decreasing(r, request):
    cast = require_cast(r, request)
    from .health_rules import spell_bonus
    amount = request.amount + spell_bonus(r.state, request.player_id, r.registry,
        r.registry.card(cast.card_id).spell_school, cast_id=cast.id)
    return (MinionDamageWave(request.player_id, cast.id, request.source_id, amount, amount),)


def decreasing_wave(r, request):
    require_cast(r, request)
    from .resolver import settle_health_batch
    # The original spell bonus is already in the declining amount. All other
    # routing, numeric rules, protection, lifesteal and deaths remain shared.
    work = settle_health_batch(r, tuple(Damage(eid, request.remaining, request.source_id,
        DamageKind.SPELL) for eid in minions(r)), apply_spell_bonus=False)
    return (*work, *((MinionDamageWave(request.player_id, request.cast_id, request.source_id,
        request.initial, request.remaining-1),) if request.remaining > 1 else ()))


def damage_then_draw(r, request):
    require_cast(r, request)
    from .resolver import settle_health_batch
    hits = tuple(Damage(eid, request.amount, request.source_id, DamageKind.SPELL) for eid in minions(r))
    if not hits:
        return ()
    batch_id = len(r.game._events)+1
    work = settle_health_batch(r, hits)
    return (*work, DrawSpellBatchDeaths(request.player_id, request.cast_id, request.source_id, batch_id))


def draw_batch_deaths(r, request):
    require_cast(r, request)
    from .health_outcomes import health_result
    results = tuple(result.payload() for event in r.game._events
        if event.kind == 'health_resolved' and event.source_id == request.source_id
        for result in (health_result(event),) if result.batch_id == request.batch_id)
    if not results:
        raise ResolutionError('Death draw lost its original committed health batch')
    count = sum(death.cause is not None and death.cause.kind in ('damage', 'poison')
        and death.cause.result in results
        for death in r.state.death_history)
    return (Draw(request.player_id, count, request.source_id),) if count else ()


def begin_repeat_if_no_deaths(r,request):
    require_cast(r,request)
    from .resolver import settle_health_batch
    hits=tuple(Damage(eid,request.amount,request.source_id,DamageKind.SPELL)for eid in minions(r))
    if not hits:return ()
    batch_id=len(r.game._events)+1
    work=settle_health_batch(r,hits)
    return (*work,RepeatSpellBatchIfNoDeaths(request.player_id,request.cast_id,request.source_id,batch_id,request.amount))


def original_wave_results(state,registry,request):
    request.__post_init__()
    from .spell_casts import active_cast
    from .model import HealthFlow
    cast=active_cast(state,request.source_id,request.player_id)
    if (cast is None or cast.id!=request.cast_id or not cast.payload_started or
            request.batch_id<=cast.recorded_event):
        raise ResolutionError('Second wave lost its original active CAST and first batch window')
    rows=tuple(row.health_result for row in state.damage_history
        if row.health_result.batch_id==request.batch_id and row.health_result.source_id==request.source_id
        and row.health_result.original_flow==HealthFlow.DAMAGE.value and not row.health_result.from_lifesteal)
    if not rows or any((row.source_card_id,row.source_controller,row.base_amount,row.damage_kind)!=
            (cast.card_id,request.player_id,request.amount,DamageKind.SPELL.value)for row in rows):
        raise ResolutionError('Second wave changed or lost the complete original first-batch damage')
    return rows


def repeat_if_no_deaths(r,request):
    require_cast(r,request)
    results=tuple(row.payload()for row in original_wave_results(r.state,r.registry,request))
    if any(death.cause is not None and death.cause.kind in('damage','poison')and death.cause.result in results
            for death in r.state.death_history):return ()
    from .effects import DamageBatch
    return (DamageBatch(tuple(Damage(eid,request.amount,request.source_id,DamageKind.SPELL)for eid in minions(r))),)


@dataclass(frozen=True)
class FinishDrawDiscount(Effect):
    request:DrawWithCostReduction
    draw_id:int

    def __post_init__(self):
        if type(self.request)not in(DrawWithCostReduction,DrawWithTemporaryCostReduction,DrawMatchingWithCostReduction):
            raise ValueError('Draw discount requires its original finite request')
        self.request.__post_init__();_integer(self.draw_id,'original discounted draw',1)

    def validate_in_state(self,state,registry):
        from .draw_casts import draw_record
        self.__post_init__();row=draw_record(state,self.draw_id)
        if (row.player_id,row.source_id,row.parent_id)!=(self.request.player_id,self.request.source_id,None):
            raise ValueError('Draw discount borrowed another original physical draw')


def finish_draw_discount(r,effect):
    from .draw_casts import draw_record
    from .draw_transformations import hand_reference
    from .zones import ModifyStoredCost
    effect.validate_in_state(r.state,r.registry);request=effect.request
    reference=hand_reference(r.state,draw_record(r.state,effect.draw_id),completed=True)
    return ()if reference is None else(ModifyStoredCost(reference,CostSpec(delta=-request.reduction),request.source_id,
        expires_turn=getattr(request,'expires_turn',None)),)


def draw_discount(r, request, *, card=None):
    request.__post_init__()
    if type(request)is DrawWithTemporaryCostReduction and request.expires_turn!=r.state.turn:
        raise ResolutionError('Temporary draw reduction requires its original current turn')
    from .draw_casts import draw_one
    index = len(r.state.draw_history)
    work = draw_one(r, request.player_id, card=card, source_id=request.source_id)
    record = r.state.draw_history[index]
    return (*work,FinishDrawDiscount(request,record.id))


def draw_matching_discount(r, request):
    request.__post_init__()
    from .zones import zone_candidates
    candidates = zone_candidates(r, request.player_id, Zone.DECK, request.query,
                                 request.player_id, request.source_id)
    if not candidates:
        return ()
    return draw_discount(r, request, card=r.game._rng.choice(candidates))


def draw_if_cheap(r, request):
    request.__post_init__()
    from .costs import quote_unselected_cost
    from .draw_casts import draw_one
    index = len(r.state.draw_history)
    work = draw_one(r, request.player_id, source_id=request.source_id)
    record = r.state.draw_history[index]
    # Quote this physical draw's resulting position before draw reactions run.
    # Burn/cast still refer to their original card; fatigue has no card to quote.
    if record.entity_id is not None:
        card = r.state.entities[record.entity_id]
        if quote_unselected_cost(r.state, r.registry, card).amount <= request.maximum:
            return (*work, Draw(request.player_id, source_id=request.source_id))
    return work


def register(mechanics):
    mechanics.register(FinishDrawDiscount,finish_draw_discount)
    for kind, handler in ((DecreasingMinionDamage, begin_decreasing),
            (MinionDamageWave, decreasing_wave), (DamageMinionsDrawDeaths, damage_then_draw),
            (DrawSpellBatchDeaths, draw_batch_deaths), (DrawWithCostReduction, draw_discount),
            (DrawWithTemporaryCostReduction, draw_discount),
            (DrawMatchingWithCostReduction, draw_matching_discount),
            (DrawIfCheap, draw_if_cheap),
            (DamageMinionsRepeatIfNoDeaths,begin_repeat_if_no_deaths),
            (RepeatSpellBatchIfNoDeaths,repeat_if_no_deaths)):
        mechanics.register(kind, handler)
