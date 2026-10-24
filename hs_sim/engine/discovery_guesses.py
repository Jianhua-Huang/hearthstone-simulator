"""Source-bound delayed guesses of genuine original pool selections."""
from dataclasses import dataclass, fields, replace
import json
from types import SimpleNamespace

from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import AddToHand, ChoiceOption, Effect, RequestChoice
from .model import (AbilityInstance, CardType, ChoiceResult, DiscoveryGuessMemory,
    Enchantment, Event, Rarity, Zone, _int, _name)
from .pools import DiscoverFromPool, PoolQuery
from .sacrifice import MinionReference, live_minion

START = 'discovery.guess.start'
SELECTED = 'discovery.guess.selected'
OFFERED = 'discovery_guess_offered'
FINISHED = 'discovery_guess_finished'
SPELLS = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current')
LEGENDARIES = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current',
    rarities=(Rarity.LEGENDARY,))


@dataclass(frozen=True)
class DiscoveryGuessProfile:
    card_id: str
    behavior_id: str
    query: PoolQuery

    def __post_init__(self):
        _name(self.card_id, 'native guessing source'); _name(self.behavior_id, 'native guessing Battlecry')
        if type(self.query) is not PoolQuery or self.query not in (SPELLS, LEGENDARIES):
            raise ValueError('Guess discovery supports its two reviewed ordinary queries')


def validate_profile(registry, profile):
    if type(profile) is not DiscoveryGuessProfile: raise ValueError('Typed guess discovery profile required')
    profile.__post_init__(); card = registry.card(profile.card_id)
    if card.kind != CardType.MINION or card.battlecry != profile.behavior_id:
        raise ValueError('Guess discovery requires its declared native Battlecry')
    registry.behavior(profile.behavior_id); registry.behavior(START); registry.behavior(SELECTED)


@dataclass(frozen=True)
class DiscoveryGuessTarget:
    source_card_id: str
    battlecry_id: int
    reference: MinionReference | None

    def __post_init__(self):
        _name(self.source_card_id, 'original guess declaration'); _int(self.battlecry_id, 'guess Battlecry', 1)
        if self.reference is not None:
            if type(self.reference) is not MinionReference: raise ValueError('Guess memory requires its original minion residence')
            self.reference.__post_init__()


def validate_spec(spec):
    if type(spec) is not DiscoverFromPool or type(spec.memory_target) is not DiscoveryGuessTarget:
        raise ValueError('Guess discovery requires its original typed target')
    spec.memory_target.__post_init__()
    if spec.query not in (SPELLS, LEGENDARIES) or spec.source_id is None:
        raise ValueError('Guess discovery lost its ordinary source or native query')
    plain = DiscoverFromPool(spec.player_id, spec.pool_id, spec.query,
        source_id=spec.source_id, prompt=spec.prompt)
    if any(getattr(spec, f.name) != getattr(plain, f.name) for f in fields(spec) if f.name != 'memory_target'):
        raise ValueError('Guess discovery supports one ordinary three-option hand delivery')


def validate_target(state, registry, spec, *, active=True):
    validate_spec(spec); target = spec.memory_target
    from .battlecries import battlecry_record
    row = battlecry_record(state, target.battlecry_id)
    profile = registry.discovery_guess_profiles.get(target.source_card_id)
    if (profile is None or profile.query != spec.query or row.payload.behavior_id != profile.behavior_id or
            (row.source_id, row.player_id) != (spec.source_id, spec.player_id) or
            not row.payload_started or row.failure is not None or active and (row.completed or row.interrupted)):
        raise ValueError('Guess discovery borrowed another original Battlecry')
    if target.reference is not None and target.reference.entity_id != row.source_id:
        raise ValueError('Guess target borrowed another original physical actor')
    return row


def original(game, memory):
    memory.__post_init__(); state = game._state
    if memory.discovery_id > len(state.card_discovery_history): raise ValueError('Missing original guessed discovery')
    row = state.card_discovery_history[memory.discovery_id-1]
    from .discovery import ResolvePoolDiscovery
    from .discovery_offers import offer_for_result
    offer = offer_for_result(game, row.result)
    option = next(o for o in offer.options if o.id == row.result.selected_ids[0])
    if len(option.effects) != 1 or type(option.effects[0]) is not ResolvePoolDiscovery:
        raise ValueError('Guess memory lost its original ordinary selection recipe')
    spec = option.effects[0].batch.spec
    if type(spec.memory_target) is not DiscoveryGuessTarget or spec.memory_target.battlecry_id != memory.battlecry_id:
        raise ValueError('Guess memory substituted its original Battlecry')
    validate_target(state, game.registry, spec, active=False)
    fact = memory.recipient
    if fact is not None:
        validate_allocation(state, game.registry, fact, closed=True)
        if (fact.card_id, fact.controller, fact.owner) != (option.card_id, spec.player_id, spec.player_id):
            raise ValueError('Guess memory substituted the actual discovered recipient')
    return row, offer, option, spec


def apply_selection(r, effect):
    validate_target(r.state, r.registry, effect.batch.spec)
    from .discovery import deliver_pick
    return deliver_pick(effect.batch.spec, replace(effect.selection, result=effect.choice_result), r.registry)


def completed(r, completion):
    if not r.registry.discovery_guess_profiles: return
    from .card_discoveries import require_original_result
    from .discovery_offers import offer_for_result
    from .discovery import ResolvePoolDiscovery
    row = require_original_result(r.state, completion.result)
    offer = offer_for_result(r.game, row.result)
    option = next(o for o in offer.options if o.id == row.result.selected_ids[0])
    if len(option.effects) != 1 or type(option.effects[0]) is not ResolvePoolDiscovery: return
    spec = option.effects[0].batch.spec
    if type(spec.memory_target) is not DiscoveryGuessTarget: return
    validate_target(r.state, r.registry, spec)
    ref = spec.memory_target.reference
    source = None if ref is None else live_minion(r.state, ref)
    if source is None: return
    if completion.recipient is None: raise ValueError('Plain guess discovery lost its actual hand creation')
    from .lifecycle import attachment_id, refresh_entity
    memory = DiscoveryGuessMemory(spec.memory_target.battlecry_id, row.id, completion.recipient)
    source.enchantments.append(Enchantment(attachment_id(r.state), source_id=spec.source_id,
        label='discovery_guess', discovery_guess=memory))
    if not any(a.kind == 'trigger' and a.event == 'turn_started' and a.behavior_id == START and not a.consumed
            for a in source.abilities):
        source.abilities.append(AbilityInstance(attachment_id(r.state), 'trigger', source_id=source.id,
            origin='granted', event='turn_started', behavior_id=START))
    refresh_entity(source)


@dataclass(frozen=True)
class DiscoveryGuessRequest:
    source: SourceAllocationFact
    attachment_id: int
    memory: DiscoveryGuessMemory
    event: Event

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact or type(self.memory) is not DiscoveryGuessMemory or type(self.event) is not Event:
            raise ValueError('Guess request requires its original source, memory and start event')
        self.source.__post_init__(); self.memory.__post_init__(); _int(self.attachment_id, 'guess attachment', 1)
        if (self.source.kind, self.source.zone) != (CardType.MINION, Zone.BOARD) or self.event.kind != 'turn_started':
            raise ValueError('Guess requires an original active minion at an actual turn start')


@dataclass(frozen=True)
class BeginDiscoveryGuess(Effect):
    request: DiscoveryGuessRequest
    def __post_init__(self):
        if type(self.request) is not DiscoveryGuessRequest: raise ValueError('Typed guess request required')
        self.request.__post_init__()


@dataclass(frozen=True)
class ResolveDiscoveryGuess(Effect):
    request: DiscoveryGuessRequest
    result: ChoiceResult
    def __post_init__(self):
        if type(self.request) is not DiscoveryGuessRequest or type(self.result) is not ChoiceResult:
            raise ValueError('Guess resolution requires its actual request and choice')
        self.request.__post_init__(); self.result.__post_init__()


def encode(game, value):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(game.mechanics, game.registry).encode(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def decode(game, value):
    from .continuations import FrameCodec
    return FrameCodec(game.mechanics, game.registry).decode(json.loads(value))


def validate_request(game, request):
    request.__post_init__(); row, offer, option, spec = original(game, request.memory)
    event = request.event
    if (event.player_id != 3-spec.player_id or event.sequence > len(game._events) or
            game._events[event.sequence-1] != event):
        raise ValueError('Guess request lost its actual original opponent start')
    validate_allocation(game._state, game.registry, request.source, closed=True)
    if request.attachment_id >= game._state.next_attachment_id:
        raise ValueError('Guess request borrowed a future attachment')
    return row, offer, option, spec


def option_id(game, request, slot):
    return json.dumps(dict(request=encode(game, request), slot=slot), sort_keys=True, separators=(',', ':'))


def validate_menu(game, request, choice):
    row, _, _, spec = validate_request(game, request)
    faces = tuple(o.card_id for o in row.result.choice.options)
    if (choice.player_id, choice.source_id, choice.min_count, choice.max_count) != (3-spec.player_id, request.source.entity_id, 1, 1):
        raise ValueError('Guess menu changed its original actor or owner')
    if len(choice.options) != len(faces) or any(
            (o.id, o.card_id, o.label, o.entity_id, o.preview) !=
            (option_id(game, request, i), cid, game.registry.card(cid).name, None, None)
            for i, (o, cid) in enumerate(zip(choice.options, faces))):
        raise ValueError('Guess menu changed its complete original ordered discovery options')


def begin(r, effect):
    request = effect.request; row, _, _, spec = validate_request(r.game, request)
    source = r.state.entities[request.source.entity_id]
    source.enchantments = [e for e in source.enchantments if e.id != request.attachment_id]
    if not any(e.discovery_guess is not None for e in source.enchantments):
        source.abilities = [a for a in source.abilities if not (a.kind == 'trigger' and a.behavior_id == START)]
    from .lifecycle import refresh_entity
    refresh_entity(source)
    value = encode(r.game, request)
    r.emit(OFFERED, source_id=source.id, player_id=3-spec.player_id, request=value, _capture=False)
    options = tuple(ChoiceOption(option_id(r.game, request, i), r.registry.card(o.card_id).name,
        card_id=o.card_id) for i, o in enumerate(row.result.choice.options))
    return (RequestChoice(3-spec.player_id, options, source.id, prompt='猜测对手发现了哪张牌', on_select=SELECTED),)


def resolve(r, effect):
    effect.__post_init__(); request, result = effect.request, effect.result
    validate_menu(r.game, request, result.choice)
    if len(result.selected) != 1: raise ValueError('Guess requires one actual selected option')
    row, offer, option, spec = original(r.game, request.memory)
    correct = result.selected[0].card_id == row.result.selected[0].card_id
    r.emit(FINISHED, source_id=request.source.entity_id, player_id=result.choice.player_id,
        request=encode(r.game, request), result=encode(r.game, result), correct=correct, _capture=False)
    if not correct: return ()
    # Reuse current material in the same original residence, and the original
    # recipe after departure. Both paths preserve the actual copy provenance.
    from .discovered_card_copies import copy_original_selection
    material = next(m for m in offer.materials if m.option_id == option.id)
    completion = SimpleNamespace(result=row.result, recipient=request.memory.recipient,
        recipe=AddToHand(spec.player_id, option.card_id, spec.source_id))
    actor = SimpleNamespace(player_id=result.choice.player_id, source_id=request.source.entity_id)
    return copy_original_selection(r, actor, row, completion, offer, option, material)


def register_behaviors(registry):
    def started(c):
        if c.event is None or c.event.kind != 'turn_started': return ()
        result = []
        for enchantment in c.source.enchantments:
            memory = enchantment.discovery_guess
            if memory is None: continue
            row = c.state.card_discovery_history[memory.discovery_id-1]
            if c.event.player_id != 3-row.result.choice.player_id: continue
            result.append(BeginDiscoveryGuess(DiscoveryGuessRequest(
                SourceAllocationFact.capture(c.state, c.source), enchantment.id, memory, c.event)))
        return tuple(result)
    def selected(c):
        result = c.choice
        if result is None or len(result.selected) != 1: raise ValueError('Guess callback requires its actual choice')
        raw = json.loads(result.selected_ids[0])
        # FrameCodec is supplied by execution, not an arbitrary callback import.
        from .continuations import FrameCodec
        from .resolver import default_mechanics
        request = FrameCodec(default_mechanics(), registry).decode(json.loads(raw['request']))
        return (ResolveDiscoveryGuess(request, result),)
    registry.register_behavior(START, started)
    registry.register_behavior(SELECTED, selected)


def validate_boundary(game):
    from .hero_health_history import effective_events
    from .discovery_delivery import COMPLETED, original_recipient
    events = effective_events(game._events)
    completions = {dict(e.data)['discovery_id']: e for e in events if e.kind == COMPLETED}
    memories = {e.discovery_guess for entity in (*game._state.entities.values(), *game._state.death_history)
        for e in entity.enchantments if e.discovery_guess is not None}
    for memory in memories:
        original(game, memory)
        event = completions.get(memory.discovery_id)
        if event is None or original_recipient(game._state, event) != memory.recipient:
            raise ValueError('Guess memory lost its actual completed discovery recipient')
    offered = {}; finished = set()
    for event in events:
        if event.kind not in (OFFERED, FINISHED): continue
        data = dict(event.data); request = decode(game, data['request']); validate_request(game, request)
        key = (request.source.entity_id, request.attachment_id)
        if event.kind == OFFERED:
            if key in offered: raise ValueError('Original guess attachment was accepted twice')
            offered[key] = request
        else:
            if key not in offered or key in finished or offered[key] != request:
                raise ValueError('Guess resolution has no unique original offer')
            result = decode(game, data['result']); validate_menu(game, request, result.choice)
            row, _, _, _ = original(game, request.memory)
            if type(data['correct']) is not bool or data['correct'] != (result.selected[0].card_id == row.result.selected[0].card_id):
                raise ValueError('Guess outcome changed its original answer')
            finished.add(key)
    if game._frame is None: return
    if game._frame.on_select == SELECTED:
        choice = game._state.pending_choice
        if choice is None or not choice.options: raise ValueError('Pending guess lost its complete menu')
        request = decode(game, json.loads(choice.options[0].id)['request'])
        validate_menu(game, request, choice)
        key = (request.source.entity_id, request.attachment_id)
        if offered.get(key) != request or key in finished: raise ValueError('Pending guess has no open original offer')
    for work in (*game._frame.prefix, *game._frame.continuation):
        if type(work) in (BeginDiscoveryGuess, ResolveDiscoveryGuess):
            validate_request(game, work.request)
            if type(work) is ResolveDiscoveryGuess: validate_menu(game, work.request, work.result.choice)


def register(mechanics):
    for kind in (DiscoveryGuessMemory, DiscoveryGuessTarget, DiscoveryGuessRequest): mechanics.register_payload_type(kind)
    mechanics.register(BeginDiscoveryGuess, begin)
    mechanics.register(ResolveDiscoveryGuess, resolve)
