"""Bounded sequences of committed Battlecry payloads, provisional R-124.

The rule cap counts direct attempts (including no-target failures). Descendant
activations keep their own policies; the interpreter budget still bounds all
work. Selection and execution order are separate, frozen before any attempt.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player
from .errors import ResolutionLimitExceeded
from .model import BattlecryPayload, CardType, Zone, _name
from .played_battlecries import PlayedBattlecryQuery, played_battlecry_candidates
from .targeting import effect_policies


def unique_tuple(value, label, validate):
    if type(value) is not tuple:
        raise ValueError(f'{label} must be an immutable tuple')
    for item in value: validate(item, label)
    if len(set(value)) != len(value): raise ValueError(f'Duplicate {label}')


@dataclass(frozen=True)
class PlayedBattlecryFilter:
    exclude_played_cards: tuple[str, ...] = ()
    exclude_declaring_cards: tuple[str, ...] = ()
    exclude_behaviors: tuple[str, ...] = ()

    def __post_init__(self):
        for values in (self.exclude_played_cards, self.exclude_declaring_cards, self.exclude_behaviors):
            unique_tuple(values, 'Battlecry exclusion identity', _name)


@dataclass(frozen=True)
class PlayedBattlecryCandidate:
    play_id: int
    payload: BattlecryPayload

    def __post_init__(self):
        _integer(self.play_id, 'candidate play', 1)
        if type(self.payload) is not BattlecryPayload: raise ValueError('Expected Battlecry payload')
        self.payload.__post_init__()


def played_battlecry_payloads(state, player_id, query=PlayedBattlecryQuery(), filters=PlayedBattlecryFilter()):
    """Flatten by play order, then captured attachment order; never deduplicate faces."""
    if type(filters) is not PlayedBattlecryFilter: raise ValueError('Expected PlayedBattlecryFilter')
    filters.__post_init__()
    return tuple(PlayedBattlecryCandidate(p.id, b)
        for p in played_battlecry_candidates(state, player_id, query)
        if p.card_id not in filters.exclude_played_cards
        for b in p.battlecries
        if b.card_id not in filters.exclude_declaring_cards and b.behavior_id not in filters.exclude_behaviors)


@dataclass(frozen=True)
class BattlecrySequencePolicy:
    source: str = 'captured'
    controller: str = 'captured'
    stop_on_silence: bool = False
    exclude_source_target: bool = False

    def __post_init__(self):
        if self.source not in ('captured','in_play','same_incarnation') or self.controller not in ('captured','current'):
            raise ValueError('Invalid Battlecry sequence source/controller policy')
        for value in (self.stop_on_silence,self.exclude_source_target):
            if type(value) is not bool: raise ValueError('Expected Battlecry sequence policy boolean')


@dataclass(frozen=True)
class RepeatPlayedBattlecrySequence(Effect):
    player_id: int
    source_id: int
    limit: int
    query: PlayedBattlecryQuery = PlayedBattlecryQuery()
    filters: PlayedBattlecryFilter = PlayedBattlecryFilter()
    selection: str = 'oldest'
    order: str = 'chronological'
    choices: str = 'random'
    policy: BattlecrySequencePolicy = BattlecrySequencePolicy()
    profile_id: str | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'sequence carrier', 1)
        _integer(self.limit, 'Battlecry rule cap', 0)
        if type(self.query) is not PlayedBattlecryQuery: raise ValueError('Expected PlayedBattlecryQuery')
        if type(self.filters) is not PlayedBattlecryFilter: raise ValueError('Expected PlayedBattlecryFilter')
        self.query.__post_init__(); self.filters.__post_init__()
        if self.selection not in ('oldest', 'newest', 'random') or self.order not in ('chronological', 'random'):
            raise ValueError('Invalid bounded Battlecry selection/order')
        effect_policies('random', None, self.choices)
        if type(self.policy) is not BattlecrySequencePolicy: raise ValueError('Expected BattlecrySequencePolicy')
        self.policy.__post_init__()
        if self.profile_id is not None: _name(self.profile_id,'historical target profile')


@dataclass(frozen=True)
class ContinueBattlecrySequence(Effect):
    spec: RepeatPlayedBattlecrySequence
    card_id: str
    before_play_id: int
    pending_play_ids: tuple[int, ...]
    before_battlecry_id: int
    parent_id: int | None
    candidates: tuple[PlayedBattlecryCandidate, ...]
    order: tuple[int, ...]
    started_ids: tuple[int, ...] = ()
    source_epoch: int | None = None

    def __post_init__(self):
        if type(self.spec) is not RepeatPlayedBattlecrySequence: raise ValueError('Expected bounded Battlecry spec')
        self.spec.__post_init__(); _name(self.card_id, 'captured sequence carrier')
        if (self.spec.policy.source == 'same_incarnation') != (self.source_epoch is not None):
            raise ValueError('Sequence source policy and captured incarnation differ')
        if self.source_epoch is not None: _integer(self.source_epoch, 'sequence source incarnation', 0)
        for value in (self.before_play_id, self.before_battlecry_id): _integer(value, 'sequence history bound', 1)
        if self.parent_id is not None:
            _integer(self.parent_id, 'sequence parent', 1)
            if self.parent_id >= self.before_battlecry_id: raise ValueError('Sequence parent follows its start')
        for ids in (self.pending_play_ids, self.started_ids):
            unique_tuple(ids, 'sequence history IDs', lambda v,n: _integer(v,n,1))
            if ids != tuple(sorted(ids)): raise ValueError('Sequence history IDs are out of order')
        if any(i >= self.before_play_id for i in self.pending_play_ids): raise ValueError('Pending play exceeds frozen frontier')
        if any(i < self.before_battlecry_id for i in self.started_ids): raise ValueError('Sequence attempt precedes acceptance')
        unique_tuple(self.candidates, 'sequence candidates', lambda v,n: (
            v.__post_init__() if type(v) is PlayedBattlecryCandidate else _invalid_candidate()))
        unique_tuple(self.order, 'sequence positions', lambda v,n: _integer(v,n,0))
        count = min(self.spec.limit, len(self.candidates))
        if len(self.order) != count or any(i >= len(self.candidates) for i in self.order):
            raise ValueError('Sequence schedule differs from the rule cap')
        selected = tuple(sorted(self.order))
        if (self.spec.selection == 'oldest' and selected != tuple(range(count)) or
                self.spec.selection == 'newest' and selected != tuple(range(len(self.candidates)-count,len(self.candidates))) or
                self.spec.order == 'chronological' and self.order != selected):
            raise ValueError('Sequence schedule differs from its selection/order policy')
        if len(self.started_ids) > count: raise ValueError('Sequence progress exceeds its schedule')


def _invalid_candidate(): raise ValueError('Expected PlayedBattlecryCandidate')


@dataclass(frozen=True)
class FinishSequenceAttempt(Effect):
    sequence: ContinueBattlecrySequence
    record_id: int

    def __post_init__(self):
        if type(self.sequence) is not ContinueBattlecrySequence: raise ValueError('Expected captured sequence')
        self.sequence.__post_init__(); _integer(self.record_id, 'sequence attempt', 1)
        # Validate the current attempt against the next planned position, so a
        # saved cursor cannot be shortened to replay already consumed entries.
        replace(self.sequence,started_ids=(*self.sequence.started_ids,self.record_id))


def frozen_query(work):
    query = work.spec.query
    return replace(query, before_id=min(query.before_id or work.before_play_id, work.before_play_id),
        exclude_ids=tuple(sorted(set(query.exclude_ids) | set(work.pending_play_ids))))


def source_allows(state, spec, card_id, epoch):
    source = state.entities[spec.source_id]
    policy = spec.policy
    if policy.stop_on_silence and source.silenced: return False
    if policy.source == 'captured': return True
    zones = {CardType.MINION:Zone.BOARD,CardType.HERO:Zone.HERO,CardType.WEAPON:Zone.WEAPON}
    if (not source.active or source.zone != zones.get(source.kind) or source.doomed or
            (source.durability <= 0 if source.kind == CardType.WEAPON else source.health <= 0)):
        return False
    return policy.source != 'same_incarnation' or (source.zone_epoch == epoch and source.card_id == card_id)


def start(r, effect):
    from .battlecry_sources import carrier_card
    effect.__post_init__()
    card_id = carrier_card(r.state, r.registry, effect.source_id)
    epoch = r.state.entities[effect.source_id].zone_epoch if effect.policy.source == 'same_incarnation' else None
    if not source_allows(r.state,effect,card_id,epoch): return ()
    candidates = played_battlecry_payloads(r.state, effect.player_id, effect.query, effect.filters)
    count = min(effect.limit, len(candidates))
    if count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Bounded Battlecry sequence exceeds resolution budget')
    if not count: return ()
    indices = tuple(range(len(candidates)))
    if effect.selection == 'oldest': selected = indices[:count]
    elif effect.selection == 'newest': selected = indices[-count:]
    else: selected = tuple(sorted(r.game._rng.sample(indices,count)))
    if effect.order == 'random': selected = tuple(r.game._rng.sample(selected,count))
    parent = next((b.id for b in reversed(r.state.battlecry_history) if not b.completed and not b.interrupted),None)
    return (ContinueBattlecrySequence(effect,card_id,len(r.state.play_history)+1,
        tuple(p.id for p in r.state.play_history if not p.completed),len(r.state.battlecry_history)+1,
        parent,candidates,selected,source_epoch=epoch),)


def validate_sequence(state, registry, work):
    from .battlecry_sources import validate_payload
    from .battlecries import battlecry_record
    work.__post_init__(); spec = work.spec
    if spec.source_id not in state.entities: raise ValueError('Sequence carrier is missing')
    if work.source_epoch is not None and work.source_epoch > state.entities[spec.source_id].zone_epoch:
        raise ValueError('Sequence source incarnation is in the future')
    if work.before_play_id > len(state.play_history)+1 or work.before_battlecry_id > len(state.battlecry_history)+1:
        raise ValueError('Sequence frontier is in the future')
    # Already committed but incomplete plays cannot join an accepted sequence.
    if any(i > len(state.play_history) for i in work.pending_play_ids): raise ValueError('Unknown pending play')
    expected = played_battlecry_payloads(state,spec.player_id,frozen_query(work),spec.filters)
    if work.candidates != expected: raise ValueError('Frozen Battlecry candidates differ from committed history')
    for candidate in work.candidates:
        validate_payload(state,registry,spec.source_id,work.card_id,candidate.payload,spec.source_id)
    if work.parent_id is not None:
        parent = battlecry_record(state,work.parent_id)
        if parent.completed or parent.interrupted: raise ValueError('Sequence parent already finished')
        if parent.source_id == spec.source_id and parent.card_id != work.card_id:
            raise ValueError('Sequence carrier differs from its captured parent')
    for n, record_id in enumerate(work.started_ids):
        b = battlecry_record(state,record_id); candidate = work.candidates[work.order[n]]
        if spec.profile_id is not None:
            from .historical_body_targets import receipt_for
            if receipt_for(state,b).request.historical_profile_id != spec.profile_id:
                raise ValueError('Historical sequence changed its actual invocation producer')
        elif b.historical_body_id is not None:
            raise ValueError('Legacy sequence cannot borrow a historical target producer')
        if (b.origin != 'played_history' or b.history_play_id != candidate.play_id or b.payload != candidate.payload or
                b.source_id != spec.source_id or b.caster_id != spec.source_id or b.history_player_id != spec.player_id or
                b.controller_policy != spec.policy.controller or b.exclude_source_target != spec.policy.exclude_source_target or
                spec.policy.controller == 'captured' and b.player_id != spec.player_id or
                b.card_id != work.card_id or b.parent_id != work.parent_id or b.choices != spec.choices or
                b.interrupted or n < len(work.started_ids)-1 and not b.completed):
            raise ValueError('Sequence progress differs from its attempted payloads')


def continue_sequence(r, work):
    from .battlecry_sources import BeginIndirectBattlecry, begin
    from .battlecries import battlecry_record
    validate_sequence(r.state,r.registry,work)
    if work.started_ids and not battlecry_record(r.state,work.started_ids[-1]).completed:
        raise ValueError('Sequence cannot advance before its child finishes')
    n = len(work.started_ids)
    if n == len(work.order): return ()
    spec = work.spec; candidate = work.candidates[work.order[n]]
    if not source_allows(r.state,spec,work.card_id,work.source_epoch): return ()
    player_id = r.state.entities[spec.source_id].controller if spec.policy.controller == 'current' else spec.player_id
    record_id = len(r.state.battlecry_history)+1
    effects = begin(r,BeginIndirectBattlecry(spec.source_id,player_id,work.card_id,candidate.payload,
        'played_history',caster_id=spec.source_id,choices=spec.choices,history_play_id=candidate.play_id,
        history_player_id=spec.player_id,controller_policy=spec.policy.controller,
        exclude_source_target=spec.policy.exclude_source_target,historical_profile_id=spec.profile_id),historical_sequence=work)
    return (*effects,FinishSequenceAttempt(work,record_id))


def finish_attempt(r, effect):
    effect.__post_init__()
    return continue_sequence(r,replace(effect.sequence,
        started_ids=(*effect.sequence.started_ids,effect.record_id)))


def validate_boundary(game):
    from .battlecries import FinishBattlecry, battlecry_record
    if game._frame is None: return
    queue = (*game._frame.prefix,*game._frame.continuation)
    sequences = [w for w in queue if type(w) in (ContinueBattlecrySequence,FinishSequenceAttempt)]
    if len(set(sequences)) != len(sequences): raise ValueError('Duplicate Battlecry sequence continuation')
    claimed = set()
    for marker in sequences:
        marker.__post_init__()
        work = (replace(marker.sequence,started_ids=(*marker.sequence.started_ids,marker.record_id))
            if type(marker) is FinishSequenceAttempt else marker)
        if type(marker) is ContinueBattlecrySequence and work.started_ids:
            raise ValueError('Started sequence must retain its attempt completion marker')
        validate_sequence(game._state,game.registry,work)
        if len(work.order) > game.ruleset.max_resolution_steps: raise ValueError('Sequence exceeds resolution budget')
        if claimed.intersection(work.started_ids): raise ValueError('Battlecry attempt belongs to multiple sequences')
        claimed.update(work.started_ids)
        position = queue.index(marker)
        if work.parent_id is not None:
            end = FinishBattlecry(work.parent_id)
            if end not in queue or position >= queue.index(end): raise ValueError('Sequence must precede its parent completion')
        if work.started_ids:
            child = battlecry_record(game._state,work.started_ids[-1])
            if not child.completed:
                end = FinishBattlecry(child.id)
                if end not in queue or queue.index(end) >= position: raise ValueError('Sequence must follow its child completion')


def register(mechanics):
    mechanics.register_payload_type(BattlecrySequencePolicy)
    mechanics.register_payload_type(PlayedBattlecryFilter)
    mechanics.register_payload_type(PlayedBattlecryCandidate)
    mechanics.register(RepeatPlayedBattlecrySequence,start)
    mechanics.register(ContinueBattlecrySequence,continue_sequence)
    mechanics.register(FinishSequenceAttempt,finish_attempt)
