"""Original random spell draws, ordinary delivery, then cost-based healing."""
from dataclasses import dataclass
import json
from random import Random

from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import Effect, Heal, _integer
from .model import CardClass, CardType, Event, HealingKind, HealthFlow, validate_end_turn_rng
from .pools import (GenerateFromPool, GenerationContext, GenerationPolicy, PoolMember,
    PoolQuery, deliver_generated, generation_candidates, resolve_candidates, sample_candidates)
from .spell_casts import accepted_cast, accepted_fact_id
from .spell_sequences import SpellSequence, require_cast

ACCEPTED = 'generated_spell_healing_accepted'
FINISHED = 'generated_spell_healing_finished'


@dataclass(frozen=True)
class GenerateSpellsAndHeal(SpellSequence):
    pool_id: str
    query: PoolQuery
    count: int = 1
    policy: GenerationPolicy = GenerationPolicy()

    def __post_init__(self):
        super().__post_init__()
        self.request().__post_init__()
        if self.query.kinds != (CardType.SPELL,) or self.query.collectible is not True:
            raise ValueError('Generated cost healing requires a collectible spell query')

    def request(self):
        return GenerateFromPool(self.player_id, self.pool_id, self.query, count=self.count,
            source_id=self.source_id, policy=self.policy)


@dataclass(frozen=True)
class CompleteGeneratedSpellHealing(Effect):
    request: GenerateSpellsAndHeal
    event_sequence: int
    cast_event: Event
    source: SourceAllocationFact
    context: GenerationContext
    pool_version: str
    hero_class: CardClass | None
    candidates: tuple[tuple[str, int], ...]
    selected: tuple[str, ...]
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.request) is not GenerateSpellsAndHeal:
            raise ValueError('Generated healing requires its original typed request')
        self.request.__post_init__()
        _integer(self.event_sequence, 'generated healing acceptance', 1)
        if type(self.cast_event) is not Event or accepted_fact_id(self.cast_event) != self.request.cast_id:
            raise ValueError('Generated healing requires its actual original physical cast fact')
        if (type(self.source) is not SourceAllocationFact or type(self.context) is not GenerationContext or
                type(self.pool_version) is not str or not self.pool_version):
            raise ValueError('Generated healing requires its complete source and pool context')
        self.source.__post_init__(); self.context.__post_init__()
        if ((self.source.entity_id, self.source.controller, self.source.kind) !=
                (self.request.source_id, self.request.player_id, CardType.SPELL) or
                (self.cast_event.source_id, self.cast_event.player_id) !=
                (self.request.source_id, self.request.player_id) or self.cast_event.sequence >= self.event_sequence):
            raise ValueError('Generated healing substituted its original caster or source')
        if (self.request.query.class_mode in ('current', 'other')) != (self.hero_class is not None):
            raise ValueError('Generated healing changed its original class policy')
        if self.hero_class is not None and type(self.hero_class) is not CardClass:
            raise ValueError('Generated healing requires its typed captured class')
        if type(self.candidates) is not tuple or any(type(x) is not tuple or len(x) != 2 for x in self.candidates):
            raise ValueError('Generated healing requires complete ordered weighted candidates')
        for cid, weight in self.candidates:
            PoolMember(cid, weight).__post_init__()
        if len({cid for cid, _ in self.candidates}) != len(self.candidates):
            raise ValueError('Generated healing duplicated its canonical candidates')
        if (type(self.selected) is not tuple or any(type(x) is not str or not x for x in self.selected) or
                len(self.selected) != (self.request.count if self.candidates else 0)):
            raise ValueError('Generated healing cropped its original random draws')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)


def wire(game, result):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(game.mechanics, game.registry).encode(result),
        ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def decode(game, event):
    from .continuations import FrameCodec
    if set(dict(event.data)) != {'generation'}:
        raise ValueError('Generated healing requires its complete original acceptance receipt')
    result = FrameCodec(game.mechanics, game.registry).decode(json.loads(dict(event.data)['generation']))
    if type(result) is not CompleteGeneratedSpellHealing or result.event_sequence != event.sequence:
        raise ValueError('Generated healing lost its original acceptance position')
    return result


def validate_result(game, result):
    result.__post_init__(); state, registry = game._state, game.registry
    validate_allocation(state, registry, result.source, closed=True)
    from .starting_generation import validate_context
    validate_context(result.context, state)
    if result.context != game._generation_context or registry.pool(result.request.pool_id, result.context).version != result.pool_version:
        raise ValueError('Generated healing changed its original pool identity')
    spec = result.request.request()
    rows = resolve_candidates(registry, result.context, spec.pool_id, spec.query,
        current_class=result.hero_class, source_card_id=result.source.card_id,
        policy=spec.policy, player_id=spec.player_id, exclude_source_by_rule=True)
    if tuple((m.card_id, m.weight) for m in rows) != result.candidates:
        raise ValueError('Generated healing lost/reordered/reweighted its complete original pool')
    if any(registry.card(m.card_id).kind != CardType.SPELL or not registry.card(m.card_id).hand_playable
            or registry.card(m.card_id).choice_only for m in rows):
        raise ValueError('Generated healing borrowed a non-playable spell candidate')
    replay = Random(); replay.setstate(result.rng_before)
    if (sample_candidates(replay, rows, spec.count, replacement=True) != result.selected or
            replay.getstate() != result.rng_after):
        raise ValueError('Generated healing changed its original weighted draw or RNG receipt')
    if (not 1 <= result.cast_event.sequence <= len(game._events) or
            game._events[result.cast_event.sequence-1] != result.cast_event):
        raise ValueError('Generated healing borrowed a fabricated cast acceptance')


def accept(r, request):
    cast = require_cast(r, request)
    spec = request.request()
    if spec.count > r.rules.max_resolution_steps:
        from .errors import ResolutionLimitExceeded
        raise ResolutionLimitExceeded('Generated healing exceeds the ordinary generation budget')
    rows = generation_candidates(r, spec)
    from .costs import validate_creation_cost
    validate_creation_cost(r.state, spec, (r.registry.card(m.card_id) for m in rows))
    fact = next(e for e in reversed(r.game._events) if e.sequence > cast.recorded_event and
        e.kind == 'spell_cast_accepted' and dict(e.data)['cast_id'] == cast.id)
    if accepted_cast(r.state, fact) != cast:
        raise ValueError('Generated healing lost its actual accepted spell payload')
    before = r.game._rng.getstate()
    selected = sample_candidates(r.game._rng, rows, spec.count, replacement=True)
    result = CompleteGeneratedSpellHealing(request, len(r.game._events)+1, fact,
        SourceAllocationFact.capture(r.state, r.state.entities[spec.source_id]), r.game._generation_context,
        r.registry.pool(spec.pool_id, r.game._generation_context).version,
        r.player(spec.player_id).hero_class if spec.query.class_mode in ('current', 'other') else None,
        tuple((m.card_id, m.weight) for m in rows), selected, before, r.game._rng.getstate())
    r.emit(ACCEPTED, source_id=spec.source_id, player_id=spec.player_id,
        generation=wire(r.game, result), _capture=False)
    return (*deliver_generated(spec, selected), result)


def finish(r, result):
    from .resolver import settle_health_batch
    from .errors import ResolutionError
    validate_result(r.game, result); require_cast(r, result.request)
    event = r.game._events[result.event_sequence-1]
    if event.kind != ACCEPTED or decode(r.game, event) != result:
        raise ResolutionError('Generated healing differs from its original accepted result')
    if any(e.kind == FINISHED and dict(e.data)['accepted_sequence'] == result.event_sequence for e in r.game._events):
        raise ResolutionError('Generated healing already completed')
    player, source = result.request.player_id, result.request.source_id
    amount = sum(r.registry.card(cid).cost for cid in result.selected)
    hero, batch = r.player(player).hero_id, len(r.game._events)+1
    work = settle_health_batch(r, (Heal(hero, amount, source, HealingKind.SPELL),))
    r.emit(FINISHED, source_id=source, target_id=hero, player_id=player,
        accepted_sequence=result.event_sequence, health_batch=batch, requested_amount=amount, _capture=False)
    return work


def validate_boundary(game):
    from .hero_health_history import effective_events
    from .health_outcomes import health_result
    from .summon_quantities import walk_work
    from .spell_casts import FinishSpellCast
    frame = game._frame
    queue = tuple(walk_work((*frame.prefix, *frame.continuation))) if frame is not None else ()
    controls = tuple(x for x in queue if type(x) is CompleteGeneratedSpellHealing)
    if frame is not None and any(type(x) is CompleteGeneratedSpellHealing for x in walk_work(frame.options)):
        raise ValueError('Player choices cannot inject generated healing control work')
    accepts = tuple(e for e in game._events if e.kind == ACCEPTED)
    if not accepts and not controls and not any(e.kind == FINISHED for e in game._events):
        return
    roots = {}
    for event in accepts:
        result = decode(game, event); validate_result(game, result)
        if (event.source_id, event.player_id, event.target_id) != (result.request.source_id, result.request.player_id, None):
            raise ValueError('Generated healing changed its original acceptance header')
        roots[event.sequence] = result
    finished, used_batches = set(), set()
    health = {}
    for event in game._events:
        if event.kind == 'health_resolved':
            result = health_result(event)
            if result.packet_index == 1:
                health[result.batch_id] = (event.sequence, result)
        if event.kind != FINISHED:
            continue
        data = dict(event.data)
        if set(data) != {'accepted_sequence', 'health_batch', 'requested_amount'}:
            raise ValueError('Generated healing lost its complete health completion receipt')
        _integer(data['accepted_sequence'], 'generated healing accepted sequence', 1)
        _integer(data['health_batch'], 'generated healing health batch', 1)
        _integer(data['requested_amount'], 'generated healing requested amount', 0)
        root = roots.get(data['accepted_sequence']); entry = health.get(data['health_batch'])
        if root is None or root.event_sequence in finished or data['health_batch'] in used_batches or entry is None:
            raise ValueError('Generated healing duplicated or borrowed its committed health batch')
        sequence, result = entry
        amount = sum(game.registry.card(cid).cost for cid in root.selected)
        if (not root.event_sequence < sequence < event.sequence or data['requested_amount'] != amount or
                (event.source_id, event.player_id, event.target_id) !=
                (root.request.source_id, root.request.player_id, result.original_target_id) or
                (result.source_id, result.original_flow, result.healing_kind, result.base_amount) !=
                (root.request.source_id, HealthFlow.HEALING.value, HealingKind.SPELL.value, amount)):
            raise ValueError('Generated healing differs from its original generated costs or health result')
        finished.add(root.event_sequence); used_batches.add(data['health_batch'])
    current = {e.sequence for e in effective_events(game._events) if e.kind == ACCEPTED}
    pending = set()
    for seq, root in roots.items():
        if seq in finished:
            continue
        if seq not in current:
            raise ValueError('Rewound generated healing lost its original completion')
        cast = accepted_cast(game._state, root.cast_event)
        if cast.interrupted and not cast.completed and game._state.status != 'playing':
            continue
        if cast.completed or cast.interrupted or game._state.status != 'playing':
            raise ValueError('Generated healing closed without its original health result')
        pending.add(seq)
    if len(controls) != len(pending) or {x.event_sequence for x in controls} != pending:
        raise ValueError('Generated healing lost or duplicated its owed completion')
    for control in controls:
        if control != roots[control.event_sequence]:
            raise ValueError('Generated healing continuation changed its accepted result')
        finish_positions = [i for i, x in enumerate(queue) if type(x) is FinishSpellCast and x.cast_id == control.request.cast_id]
        if len(finish_positions) != 1 or queue.index(control) >= finish_positions[0]:
            raise ValueError('Generated healing moved beyond its original cast completion')


def register(mechanics):
    mechanics.register(GenerateSpellsAndHeal, accept)
    mechanics.register(CompleteGeneratedSpellHealing, finish)
