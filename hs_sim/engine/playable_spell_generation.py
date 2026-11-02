"""Full ordinary spell pools qualified by the shared received-card preview."""
from collections import OrderedDict
from .runtime_copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from random import Random
from threading import Lock

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .generated_card_preview import original_information, can_receive_and_play
from .model import CardType, validate_end_turn_rng
from .pools import (GenerateFromPool, GenerationContext, GenerationPolicy, PoolMember,
    PoolQuery, generation_candidates, sample_candidates)
from .registry import RuleContext

DRAW = 'playable_temporary_spell_drawn'
_CACHE, _LOCK = OrderedDict(), Lock()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class GeneratePlayableTemporarySpell(Effect):
    player_id: int
    source_id: int
    pool_id: str
    query: PoolQuery = PoolQuery(kinds=(CardType.SPELL,), collectible=True)
    policy: GenerationPolicy = GenerationPolicy()

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'playable spell source', 1)
        self.request().__post_init__()
        if self.query.kinds != (CardType.SPELL,) or self.query.collectible is not True:
            raise ValueError('Playable generation requires a collectible spell query')

    def request(self):
        return GenerateFromPool(self.player_id, self.pool_id, self.query, source_id=self.source_id,
            policy=self.policy)


@dataclass(frozen=True)
class PlayableSpellDraw:
    request: GeneratePlayableTemporarySpell
    context: GenerationContext
    pool_version: str
    before: RuleContext
    information_json: str
    candidates: tuple[tuple[str, int], ...]
    playable: tuple[tuple[str, int], ...]
    selected: tuple[str, ...]
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.request) is not GeneratePlayableTemporarySpell or type(self.context) is not GenerationContext:
            raise ValueError('Playable draw requires its complete typed request and context')
        self.request.__post_init__(); self.context.__post_init__()
        if type(self.pool_version) is not str or not self.pool_version or type(self.before) is not RuleContext:
            raise ValueError('Playable draw requires its original state and pool version')
        if (self.before.source_id, self.before.player_id) != (self.request.source_id, self.request.player_id):
            raise ValueError('Playable draw changed its original source or recipient')
        if type(self.information_json) is not str or type(json.loads(self.information_json)) is not dict:
            raise ValueError('Playable draw requires the original private knowledge ledger')
        for rows in (self.candidates, self.playable):
            if type(rows) is not tuple or any(type(row) is not tuple or len(row) != 2 for row in rows):
                raise ValueError('Playable draw requires complete ordered weighted rows')
            for cid, weight in rows:PoolMember(cid, weight).__post_init__()
            if len({cid for cid, _ in rows}) != len(rows):
                raise ValueError('Playable draw duplicated its canonical candidates')
        if tuple(row for row in self.candidates if row[0] in {cid for cid, _ in self.playable}) != self.playable:
            raise ValueError('Playable draw reordered/reweighted its admitted subset')
        if type(self.selected) is not tuple or len(self.selected) != bool(self.playable) or any(type(cid) is not str for cid in self.selected):
            raise ValueError('Playable draw requires its original selection')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        local = Random(); local.setstate(self.rng_before)
        rows = tuple(PoolMember(cid, weight) for cid, weight in self.playable)
        if sample_candidates(local, rows, 1, replacement=True) != self.selected or local.getstate() != self.rng_after:
            raise ValueError('Playable draw changed its original integer draw or RNG')


def qualify(game, request, before, information_json, rows):
    """Cache only a full immutable input digest; never a claimed admitted subset."""
    from .continuations import encode_produced
    encoded = canonical(encode_produced(game, before, readonly=True))
    material = canonical((encoded, information_json, rows, asdict(game.ruleset)))
    key = (game.registry, game.mechanics.version, hashlib.sha256(material.encode('utf-8')).digest())
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    state = before.state
    information = original_information(state, game.registry, game.ruleset, json.loads(information_json))
    admitted = tuple((cid, weight) for cid, weight in rows if can_receive_and_play(state,
        game.registry, game.ruleset, information, request.player_id, cid, request.source_id, state.turn,
        readonly=True))
    with _LOCK:
        _CACHE[key] = admitted
        while len(_CACHE) > 64:_CACHE.popitem(last=False)
    return admitted


def generate(r, request):
    from .continuations import FrameCodec
    from .zones import source_exists
    request.__post_init__(); source_exists(r, request.source_id)
    spec = request.request()
    rows = generation_candidates(r, spec)
    if len(rows) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Playable pool preview exceeds the ordinary candidate budget')
    before = RuleContext(deepcopy(r.state), request.source_id, request.player_id)
    information = canonical(r.game._information.to_dict())
    complete = tuple((m.card_id, m.weight) for m in rows)
    playable = qualify(r.game, request, before, information, complete)
    rng_before = r.game._rng.getstate()
    selected = sample_candidates(r.game._rng, tuple(PoolMember(*row) for row in playable), 1, replacement=True)
    draw = PlayableSpellDraw(request, r.game._generation_context,
        r.registry.pool(request.pool_id, r.game._generation_context).version, before, information,
        complete, playable, selected, rng_before, r.game._rng.getstate())
    r.emit(DRAW, source_id=request.source_id, player_id=request.player_id,
        draw=FrameCodec(r.game.mechanics, r.registry).encode(draw), _capture=False)
    from .temporary_cards import CreateTemporaryCard
    return tuple(CreateTemporaryCard(request.player_id, cid, r.state.turn,
        source_id=request.source_id) for cid in selected)


def decode(game, event):
    from .continuations import FrameCodec
    if set(dict(event.data)) != {'draw'}:
        raise ValueError('Playable draw requires its complete private receipt')
    value = FrameCodec(game.mechanics, game.registry).decode(dict(event.data)['draw'])
    if type(value) is not PlayableSpellDraw:
        raise ValueError('Playable draw requires its registered payload')
    return value


def validate_events(game):
    from .pools import resolve_candidates
    for event in game._events:
        if event.kind != DRAW:continue
        draw = decode(game, event); draw.__post_init__(); request = draw.request
        state = draw.before.state
        source = state.entities.get(request.source_id)
        if source is None or request.player_id not in state.players or (event.source_id, event.player_id, event.target_id, event.amount) != (
                request.source_id, request.player_id, None, 0):
            raise ValueError('Playable draw changed its original event or source')
        if draw.context != game._generation_context or game.registry.pool(request.pool_id, draw.context).version != draw.pool_version:
            raise ValueError('Playable draw changed its original pool identity')
        if state.next_entity_id > game._state.next_entity_id or state.next_order > game._state.next_order or state.action_number > game._state.action_number:
            raise ValueError('Playable draw borrowed a future acceptance state')
        query = request.query
        current_class = state.players[request.player_id].hero_class if any(q.class_mode in ('current','other') for q in (query,*query.any_of)) else None
        rows = resolve_candidates(game.registry, draw.context, request.pool_id, query,
            current_class=current_class, source_card_id=source.card_id, policy=request.policy,
            player_id=request.player_id, exclude_source_by_rule=True)
        complete = tuple((m.card_id, m.weight) for m in rows)
        if complete != draw.candidates or qualify(game, request, draw.before, draw.information_json, complete) != draw.playable:
            raise ValueError('Playable draw cropped its full pool or changed actual admission')


def register(mechanics):
    mechanics.register_payload_type(PlayableSpellDraw)
    mechanics.register(GeneratePlayableTemporarySpell, generate)
