"""Actual paid spell arrows, sharing one native draw window and one cast root."""
from .runtime_copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
from types import SimpleNamespace

from hs_sim.targets import canonical_digest
from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer
from .errors import ResolutionError
from .model import ActionWindow, BoardPresenceReference, CardType, Event, GameState, Zone
from .native_random_targets import NativeTargetSelection, manual_partition, sample
from .rules import Ruleset
from .spell_target_groups import SpellTargetGroupSelection, selection_from_dict

ACCEPTED = 'spell_target_group_accepted'
REDIRECTED = 'spell_target_group_redirected'
SETTLED = 'spell_target_group_arrow_settled'
FINISHED = 'spell_target_group_finished'


def _facts(value, count):
    if type(value) is not tuple or len(value) != count:
        raise ValueError('Actual spell arrows require every original position, including empty ones')
    for fact in value:
        if fact is not None:
            if type(fact) is not SourceAllocationFact:
                raise ValueError('Actual spell target requires its complete physical fact')
            fact.__post_init__()


def _presences(facts, values):
    if type(values) is not tuple or len(values) != len(facts):
        raise ValueError('Actual target facts lost their physical board residence positions')
    for fact, ref in zip(facts, values):
        if fact is not None and fact.kind == CardType.MINION and fact.zone == Zone.BOARD:
            if type(ref) is not BoardPresenceReference or ref.entity_id != fact.entity_id or ref.presence_id >= fact.next_order:
                raise ValueError('Actual spell target borrowed another physical board residence')
            ref.__post_init__()
        elif ref is not None:
            raise ValueError('Non-board spell target invented a board residence')


@dataclass(frozen=True)
class SpellGroupRedirect:
    index: int
    previous_target_id: int
    target: SourceAllocationFact
    presence: BoardPresenceReference | None

    def __post_init__(self):
        _integer(self.index, 'redirected spell arrow', 0)
        _integer(self.previous_target_id, 'previous spell arrow target', 1)
        if type(self.target) is not SourceAllocationFact:
            raise ValueError('Spell redirect requires its actual new physical target')
        self.target.__post_init__()
        _presences((self.target,), (self.presence,))


@dataclass(frozen=True)
class SpellGroupTargets:
    play_id: int
    window_id: int
    source: SourceAllocationFact
    original: SpellTargetGroupSelection
    definition_digest: str
    initial_targets: tuple[SourceAllocationFact | None, ...]
    targets: tuple[SourceAllocationFact | None, ...]
    initial_presences: tuple[BoardPresenceReference | None, ...]
    presences: tuple[BoardPresenceReference | None, ...]
    native_selections: tuple[NativeTargetSelection, ...] = ()
    phase: int = 0
    redirects: tuple[SpellGroupRedirect, ...] = ()

    def __post_init__(self):
        _integer(self.play_id, 'spell group play', 1)
        _integer(self.window_id, 'spell group window', 1)
        _integer(self.phase, 'settled spell arrows', 0)
        if type(self.source) is not SourceAllocationFact or type(self.original) is not SpellTargetGroupSelection:
            raise ValueError('Actual spell group lost its physical source or complete original submission')
        self.source.__post_init__(); self.original.__post_init__()
        count = len(self.original.target_ids)
        _facts(self.initial_targets, count); _facts(self.targets, count)
        _presences(self.initial_targets, self.initial_presences); _presences(self.targets, self.presences)
        if self.phase > count or self.source.entity_id != self.original.plan.source.entity_id:
            raise ValueError('Actual spell group borrowed another source or arrow cursor')
        if type(self.definition_digest) is not str or len(self.definition_digest) != 64:
            raise ValueError('Actual spell group requires its effective definition digest')
        ids = [x.entity_id for x in self.initial_targets if x is not None]
        if len(ids) != len(set(ids)):
            raise ValueError('Original actual spell selection must be distinct')
        if type(self.native_selections) is not tuple or self.native_selections and len(self.native_selections) != count:
            raise ValueError('Native group lost one of its complete joint samples')
        first = previous = None; chosen = set()
        for i, selection in enumerate(self.native_selections):
            if type(selection) is not NativeTargetSelection:
                raise ValueError('Native group requires typed original samples')
            selection.__post_init__(); p = selection.partition
            if (not p.applied or p.origin != 'manual_card' or p.source != self.source or
                    p.player_id != self.player_id or p.submitted_target_id != self.original.target_ids[i] or
                    p.definition_digest != self.definition_digest):
                raise ValueError('Native spell group changed its original source, input or domain')
            if first is not None and (p.carriers != first.carriers or
                    p.candidates != tuple(x for x in first.candidates if x.entity_id not in chosen) or
                    selection.rng_before != previous.rng_after):
                raise ValueError('Native spell arrows lost their joint window or no-replacement RNG chain')
            expected = next((x for x in p.candidates if x.entity_id == selection.target_id), None)
            if self.initial_targets[i] != expected:
                raise ValueError('Native target facts differ from their original selected candidate')
            if selection.target_id is not None: chosen.add(selection.target_id)
            first = p if first is None else first; previous = selection
        if type(self.redirects) is not tuple or any(type(x) is not SpellGroupRedirect for x in self.redirects):
            raise ValueError('Actual spell group requires its immutable ordered redirections')
        for delta in self.redirects:
            delta.__post_init__()
            if delta.index >= count:
                raise ValueError('Spell redirect borrowed an absent arrow')

    @property
    def player_id(self): return self.original.plan.player_id

    @property
    def closed(self): return self.phase == len(self.targets)

    @property
    def primary_target_id(self): return next((x.entity_id for x in self.targets if x is not None), None)


def _live_fact(state, fact, presence=None):
    if fact is None: return None
    target = state.entities.get(fact.entity_id)
    if (target is None or not target.active or target.doomed or target.health <= 0 or
            target.kind not in (CardType.HERO, CardType.MINION) or target.zone != fact.zone):
        return None
    if target.zone == Zone.BOARD:
        from .board_presence import resolve_board_presence
        if presence is None: raise ValueError('Physical spell minion target lost its explicit residence')
        if resolve_board_presence(state, presence) is None: return None
    elif target.zone != Zone.HERO or state.players[target.controller].hero_id != target.id:
        return None
    # Face epochs and control can change within the same actual board residence.
    return SourceAllocationFact.capture(state, target)


def _initial(state, registry, window, *, rng=None, native=()):
    from .native_target_acceptance import effective_definition
    play = state.play_history[window.play_id-1]
    original = play.spell_target_group
    if original is None or play.spell_target_receipt is not None or window.countered:
        raise ValueError('Actual spell group must start once at its original uncountered target window')
    definition = effective_definition(state, registry, 'manual_card', window)
    probe = SimpleNamespace(state=state, registry=registry, game=SimpleNamespace())
    source = state.entities[window.source_id]
    selections = []; targets = []; excluded = set()
    original_presences = {x.entity_id:x for x in original.plan.board_presences}
    for i, submitted in enumerate(original.target_ids):
        part = manual_partition(probe, source, definition, submitted, player_id=window.player_id)
        if part.applied:
            part = replace(part, candidates=tuple(x for x in part.candidates if x.entity_id not in excluded))
            if rng is not None:
                selection = sample(rng, part)
            else:
                if len(native) != len(original.target_ids) or native[i].partition != part:
                    raise ValueError('Actual spell group changed the complete original native domain')
                selection = native[i]
            selections.append(selection)
            selected = next((x for x in part.candidates if x.entity_id == selection.target_id), None)
            targets.append(selected)
            if selected is not None: excluded.add(selected.entity_id)
        else:
            if native: raise ValueError('Actual spell group invented a native source')
            targets.append(_live_fact(state, original.targets[i], original_presences.get(submitted)))
    presences = tuple(BoardPresenceReference.capture(state, fact.entity_id)
        if fact is not None and fact.kind == CardType.MINION and fact.zone == Zone.BOARD else None for fact in targets)
    return SpellGroupTargets(play.id, window.id, SourceAllocationFact.capture(state, source), original,
        canonical_digest(asdict(definition)), tuple(targets), tuple(targets), presences, presences, tuple(selections))


@dataclass(frozen=True)
class SpellGroupTargetProof:
    before_state: GameState
    rules: Ruleset
    window: ActionWindow
    initial: SpellGroupTargets
    acceptance_event: Event
    phase_states: tuple[GameState, ...] = ()
    publications: tuple[Event | None, ...] = ()
    settlement_states: tuple[GameState, ...] = ()
    settlement_events: tuple[Event, ...] = ()

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset or
                type(self.window) is not ActionWindow or type(self.initial) is not SpellGroupTargets or
                type(self.acceptance_event) is not Event):
            raise ValueError('Actual group proof requires its complete original window')
        self.window.__post_init__(); self.initial.__post_init__(); self.rules.__post_init__()
        if (self.initial.phase or self.initial.redirects or self.initial.targets != self.initial.initial_targets or
                self.initial.presences != self.initial.initial_presences or
                type(self.phase_states) is not tuple or type(self.settlement_states) is not tuple or
                type(self.publications) is not tuple or type(self.settlement_events) is not tuple or
                any(type(x) is not GameState for x in (*self.phase_states, *self.settlement_states)) or
                any(x is not None and type(x) is not Event for x in self.publications) or
                any(type(x) is not Event for x in self.settlement_events) or
                len(self.publications) != len(self.phase_states) or
                len(self.settlement_events) != len(self.settlement_states) or
                not len(self.settlement_states) <= len(self.phase_states) <= min(len(self.initial.targets), len(self.settlement_states)+1)):
            raise ValueError('Actual group proof lost an ordered arrow phase or settlement')


def _receipt(state, play_id): return state.play_history[play_id-1].spell_target_receipt


def _put(r, value):
    play = r.state.play_history[value.play_id-1]
    r.state.play_history[value.play_id-1] = replace(play, spell_target_receipt=value)


def _window(state, window_id):
    return next((x for x in state.action_windows if x.id == window_id), None)


def _slot(value, index, target, presence, *, settle=False):
    targets = list(value.targets); targets[index] = target
    presences = list(value.presences); presences[index] = presence
    return replace(value, targets=tuple(targets), presences=tuple(presences), phase=index+1 if settle else value.phase)


def _redirect(value, delta):
    delta.__post_init__()
    if (value.closed or delta.index != value.phase or value.targets[delta.index] is None or
            value.targets[delta.index].entity_id != delta.previous_target_id):
        raise ValueError('Spell redirection lost its active original arrow')
    return replace(_slot(value, delta.index, delta.target, delta.presence), redirects=(*value.redirects, delta))


def _advance_redirects(value, newer):
    if newer.redirects[:len(value.redirects)] != value.redirects:
        raise ValueError('Actual spell group rewrote its earlier redirections')
    for delta in newer.redirects[len(value.redirects):]: value = _redirect(value, delta)
    if value != newer: raise ValueError('Actual spell group changed an unaccepted slot or phase')
    return value


def _event(event, kind, value, *, data, target=None, action=None):
    if (event.kind != kind or (event.source_id, event.player_id, event.target_id, event.amount) !=
            (value.source.entity_id, value.player_id, target, 0) or dict(event.data) != data or
            action is not None and event.action != action):
        raise ValueError('Actual spell group differs from its original event receipt')


def _encode(mechanics, registry, value):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(mechanics, registry).encode(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _check_window(state, proof, value, index):
    window = _window(state, proof.window.id)
    expected = None if value.targets[index] is None else value.targets[index].entity_id
    if (window is None or window.spell_target_index != index or window.target_id != expected or
            replace(window, target_id=proof.window.target_id, spell_target_index=None,
                    countered=proof.window.countered) != proof.window):
        raise ValueError('Spell group arrow lost its actual live original window')
    return window


def validate_proof(proof, registry, mechanics):
    proof.__post_init__(); before = proof.before_state; original = proof.window
    if (before.status != 'playing' or _window(before, original.id) != original or
            original.kind != 'spell' or not original.target_phase or original.spell_target_index is not None or
            not before.action_windows or before.action_windows[-1].id != original.id or
            _initial(before, registry, original, native=proof.initial.native_selections) != proof.initial):
        raise ValueError('Spell group changed its complete original acceptance window')
    value = proof.initial
    _event(proof.acceptance_event, ACCEPTED, value, data={'play_id':value.play_id, 'window_id':value.window_id,
        'receipt':_encode(mechanics, registry, value)}, action=before.action_number)
    from .spell_acceptance import _bind_prefix_and_references
    previous = before
    for index, phase_state in enumerate(proof.phase_states):
        _bind_prefix_and_references(previous, phase_state, registry)
        if _receipt(phase_state, value.play_id) != value or value.phase != index:
            raise ValueError('Spell group phase changed its accepted preceding slots')
        window = _check_window(phase_state, proof, value, index)
        fact = None if window.countered else _live_fact(phase_state, value.targets[index], value.presences[index])
        publication = proof.publications[index]
        if fact is None:
            if publication is not None: raise ValueError('Empty spell arrow invented a target publication')
        else:
            if publication is None: raise ValueError('Live spell arrow lost its target publication')
            _event(publication, 'spell_targeted', value, data={'window_id':value.window_id, 'spell_target_index':index},
                target=fact.entity_id, action=phase_state.action_number)
        previous = phase_state
        if index >= len(proof.settlement_states): break
        settlement = proof.settlement_states[index]
        _bind_prefix_and_references(previous, settlement, registry)
        value = _advance_redirects(value, _receipt(settlement, value.play_id))
        window = _check_window(settlement, proof, value, index)
        fact = None if window.countered else _live_fact(settlement, value.targets[index], value.presences[index])
        _event(proof.settlement_events[index], SETTLED, value, data={'play_id':value.play_id,
            'window_id':value.window_id, 'index':index, 'target':_encode(mechanics, registry, fact),
            'publication_id':None if publication is None else publication.sequence},
            target=None if fact is None else fact.entity_id, action=settlement.action_number)
        if (proof.settlement_events[index].sequence <= proof.acceptance_event.sequence or
                publication is not None and not proof.acceptance_event.sequence < publication.sequence < proof.settlement_events[index].sequence):
            raise ValueError('Spell arrow publication lost its original event order')
        value = _slot(value, index, fact, None if fact is None else value.presences[index], settle=True)
        previous = settlement
    return value


def _bind_proof_events(proof, by_sequence):
    for event in (proof.acceptance_event, *proof.publications, *proof.settlement_events):
        if event is not None and by_sequence.get(event.sequence) != event:
            raise ValueError('Spell group proof borrowed an event outside its actual effective timeline')


@dataclass(frozen=True)
class SpellGroupArrow(Effect):
    window_id: int
    index: int
    def __post_init__(self):
        _integer(self.window_id, 'spell group window', 1); _integer(self.index, 'spell arrow', 0)


@dataclass(frozen=True)
class SettleSpellGroupArrow(SpellGroupArrow): pass


@dataclass(frozen=True)
class FinishSpellGroupTargets(Effect):
    proof: SpellGroupTargetProof
    def __post_init__(self):
        if type(self.proof) is not SpellGroupTargetProof: raise ValueError('Spell group Finish lost its original proof')
        self.proof.__post_init__()


def _tail(r, window_id):
    matches = [(i,x) for i,x in enumerate(r._work_queue) if type(x) is FinishSpellGroupTargets and x.proof.window.id == window_id]
    if len(matches) != 1: raise ValueError('Actual spell group requires exactly one original Finish')
    return matches[0]


def begin(r, window):
    before = deepcopy(r.state)
    value = _initial(before, r.registry, window, rng=r.game._rng)
    _put(r, value)
    event = r.emit(ACCEPTED, source_id=window.source_id, player_id=window.player_id,
        play_id=value.play_id, window_id=window.id, receipt=_encode(r.game.mechanics, r.registry, value), _capture=False)
    proof = SpellGroupTargetProof(before, r.rules, window, value, event)
    return (SpellGroupArrow(window.id, 0), FinishSpellGroupTargets(proof))


def arrow(r, effect):
    window = _window(r.state, effect.window_id)
    if window is None or window.spell_target_index is not None: raise ResolutionError('Spell group arrow lost its live window')
    value = _receipt(r.state, window.play_id)
    if value is None or value.closed or value.phase != effect.index: raise ResolutionError('Spell group arrow changed its accepted cursor')
    target = value.targets[effect.index]
    window = replace(window, target_id=None if target is None else target.entity_id, spell_target_index=effect.index)
    r.state.action_windows[r.state.action_windows.index(_window(r.state, window.id))] = window
    before = deepcopy(r.state); publication = None
    if not window.countered and _live_fact(r.state, target, value.presences[effect.index]) is not None:
        publication = r.emit('spell_targeted', source_id=window.source_id, target_id=window.target_id,
            player_id=window.player_id, window_id=window.id, spell_target_index=effect.index)
    index, tail = _tail(r, window.id)
    r._work_queue[index] = replace(tail, proof=replace(tail.proof,
        phase_states=(*tail.proof.phase_states, before), publications=(*tail.proof.publications, publication)))
    return (SettleSpellGroupArrow(window.id, effect.index),)


def settle(r, effect):
    window = _window(r.state, effect.window_id)
    if window is None or window.spell_target_index != effect.index: raise ResolutionError('Spell group settlement lost its active arrow')
    value = _receipt(r.state, window.play_id)
    if value.phase != effect.index: raise ResolutionError('Spell group settlement duplicated an arrow')
    before = deepcopy(r.state)
    target = None if window.countered else _live_fact(r.state, value.targets[effect.index], value.presences[effect.index])
    index, tail = _tail(r, window.id)
    publication = tail.proof.publications[effect.index]
    updated = _slot(value, effect.index, target, None if target is None else value.presences[effect.index], settle=True); _put(r, updated)
    window = replace(window, spell_target_index=None,
        target_id=updated.primary_target_id if updated.closed else window.target_id)
    r.state.action_windows[r.state.action_windows.index(_window(r.state, window.id))] = window
    event = r.emit(SETTLED, source_id=window.source_id, target_id=None if target is None else target.entity_id,
        player_id=window.player_id, play_id=value.play_id, window_id=window.id, index=effect.index,
        target=_encode(r.game.mechanics, r.registry, target),
        publication_id=None if publication is None else publication.sequence, _capture=False)
    r._work_queue[index] = replace(tail, proof=replace(tail.proof,
        settlement_states=(*tail.proof.settlement_states, before), settlement_events=(*tail.proof.settlement_events, event)))
    if updated.closed:
        from .interrupts import ResolveSpell
        return (ResolveSpell(window.id),)
    return (SpellGroupArrow(window.id, updated.phase),)


def redirect(r, window, target):
    value = _receipt(r.state, window.play_id)
    if window.spell_target_index is None or window.spell_target_index != value.phase:
        raise ResolutionError('Spell group redirect requires its active arrow')
    presence = BoardPresenceReference.capture(r.state, target.id) if target.kind == CardType.MINION and target.zone == Zone.BOARD else None
    delta = SpellGroupRedirect(value.phase, window.target_id, SourceAllocationFact.capture(r.state, target), presence)
    _put(r, _redirect(value, delta))
    r.state.action_windows[r.state.action_windows.index(window)] = replace(window, target_id=target.id)
    public = r.emit('spell_redirected', source_id=window.source_id, target_id=target.id,
        player_id=window.player_id, window_id=window.id, spell_target_index=value.phase)
    r.emit(REDIRECTED, source_id=window.source_id, target_id=target.id, player_id=window.player_id,
        play_id=value.play_id, window_id=window.id, redirect=_encode(r.game.mechanics, r.registry, delta),
        event_id=public.sequence, _capture=False)


def finish(r, effect):
    value = validate_proof(effect.proof, r.registry, r.game.mechanics)
    from .hero_health_history import effective_events
    _bind_proof_events(effect.proof, {e.sequence:e for e in effective_events(r.game._events)})
    from .spell_acceptance import _bind_prefix_and_references
    for state in (effect.proof.before_state, *effect.proof.phase_states, *effect.proof.settlement_states):
        _bind_prefix_and_references(state, r.state, r.registry)
    if not value.closed or _receipt(r.state, value.play_id) != value:
        raise ValueError('Actual spell group Finish lost its complete final accepted slots')
    r.emit(FINISHED, source_id=value.source.entity_id, player_id=value.player_id,
        play_id=value.play_id, window_id=value.window_id, receipt=_encode(r.game.mechanics, r.registry, value), _capture=False)
    return ()


def receipt_from_dict(value):
    if value is None: return None
    from .serialization import _row, _list
    from .native_target_acceptance import selection_from_dict as native_from_dict
    row = _row(value, SpellGroupTargets)
    row['source'] = allocation_from_dict(row['source']); row['original'] = selection_from_dict(row['original'])
    for key in ('initial_targets', 'targets'):
        row[key] = tuple(allocation_from_dict(x) for x in _list(row[key], 'actual spell '+key))
    for key in ('initial_presences', 'presences'):
        row[key] = tuple(None if x is None else BoardPresenceReference(**_row(x, BoardPresenceReference))
            for x in _list(row[key], 'actual spell '+key))
    row['native_selections'] = tuple(native_from_dict(x) for x in _list(row['native_selections'], 'joint spell samples'))
    deltas = []
    for item in _list(row['redirects'], 'spell redirections'):
        delta = _row(item, SpellGroupRedirect); delta['target'] = allocation_from_dict(delta['target'])
        if delta['presence'] is not None: delta['presence'] = BoardPresenceReference(**_row(delta['presence'], BoardPresenceReference))
        deltas.append(SpellGroupRedirect(**delta))
    row['redirects'] = tuple(deltas)
    return SpellGroupTargets(**row)


def validate_material(record, *, cast=False):
    value = record.spell_target_receipt
    if value is None: return
    from .automatic_spell_groups import AutomaticSpellTargets, validate_material as validate_automatic
    if cast and type(value) is AutomaticSpellTargets:
        return validate_automatic(record)
    if type(value) is not SpellGroupTargets: raise ValueError('Actual spell group requires its typed complete receipt')
    value.__post_init__()
    if (value.original != record.spell_target_group or value.play_id != (record.play_id if cast else record.id) or
            value.source.entity_id != record.source_id or value.player_id != record.player_id or
            cast and (not value.closed or value.primary_target_id != record.target_id)):
        raise ValueError('Actual spell targets borrowed another paid activation or CAST')


def validate_boundary(game):
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    codec = FrameCodec(game.mechanics, game.registry)
    decode = lambda raw: codec.decode(json.loads(raw))
    events = tuple(effective_events(game._events)); by_sequence = {e.sequence:e for e in events}
    publications = {}
    for event in events:
        if event.kind == 'spell_targeted' and 'spell_target_index' in dict(event.data):
            data = dict(event.data); key = (data.get('window_id'), data.get('spell_target_index'))
            if type(key[0]) is not int or type(key[1]) is not int or key in publications:
                raise ValueError('Actual spell arrow publication is malformed or duplicated')
            publications[key] = event
    values = {}; accepted = {}; finished = set()
    for event in events:
        if event.kind not in (ACCEPTED, REDIRECTED, SETTLED, FINISHED): continue
        data = dict(event.data); play_id = data.get('play_id')
        if event.kind == ACCEPTED:
            value = decode(data['receipt'])
            if (type(value) is not SpellGroupTargets or value.phase or value.redirects or
                    value.targets != value.initial_targets or value.presences != value.initial_presences or
                    play_id != value.play_id or play_id in values):
                raise ValueError('Actual spell group lost its unique original acceptance')
            _event(event, ACCEPTED, value, data={'play_id':play_id, 'window_id':value.window_id, 'receipt':data['receipt']})
            values[play_id] = value; accepted[play_id] = event
        else:
            value = values.get(play_id)
            if value is None or play_id in finished: raise ValueError('Spell group progress borrowed a closed or absent acceptance')
            if event.kind == REDIRECTED:
                delta = decode(data['redirect']); public = by_sequence.get(data.get('event_id'))
                if type(delta) is not SpellGroupRedirect or public is None or not accepted[play_id].sequence < public.sequence < event.sequence:
                    raise ValueError('Spell group redirect lost its actual public event')
                _event(public, 'spell_redirected', value, data={'window_id':value.window_id, 'spell_target_index':delta.index},
                    target=delta.target.entity_id, action=event.action)
                _event(event, REDIRECTED, value, data={'play_id':play_id, 'window_id':value.window_id,
                    'redirect':data['redirect'], 'event_id':public.sequence}, target=delta.target.entity_id)
                value = _redirect(value, delta)
            elif event.kind == SETTLED:
                index = data.get('index'); fact = decode(data['target'])
                if type(index) is not int or index != value.phase or value.closed:
                    raise ValueError('Spell group settled an absent or repeated arrow')
                publication = publications.pop((value.window_id, index), None)
                publication_id = data.get('publication_id')
                if ((publication is None) != (publication_id is None) or publication is not None and
                        (type(publication_id) is not int or publication.sequence != publication_id or
                         not accepted[play_id].sequence < publication.sequence < event.sequence or
                         publication.source_id != value.source.entity_id or publication.player_id != value.player_id or
                         value.initial_targets[index] is None or publication.target_id != value.initial_targets[index].entity_id)):
                    raise ValueError('Spell group settlement lost its exact actual target publication')
                _facts((fact,), 1)
                previous = value.targets[index]
                if fact is not None and (previous is None or
                        (fact.entity_id, fact.zone) != (previous.entity_id, previous.zone)):
                    raise ValueError('Spell group settlement changed physical target without a redirection')
                _event(event, SETTLED, value, data={'play_id':play_id, 'window_id':value.window_id,
                    'index':index, 'target':data['target'], 'publication_id':publication_id}, target=None if fact is None else fact.entity_id)
                value = _slot(value, index, fact, None if fact is None else value.presences[index], settle=True)
            else:
                if not value.closed or decode(data['receipt']) != value:
                    raise ValueError('Spell group Finish changed its full final result')
                _event(event, FINISHED, value, data={'play_id':play_id, 'window_id':value.window_id, 'receipt':data['receipt']})
                finished.add(play_id)
            values[play_id] = value
    queue = () if game._frame is None else (*game._frame.prefix, *game._frame.continuation)
    windows = {value.window_id:value for value in values.values()}
    for window in game._state.action_windows:
        if window.spell_target_index is not None:
            value = windows.get(window.id)
            if value is None or value.closed or window.spell_target_index != value.phase:
                raise ValueError('Active spell arrow borrowed an absent or closed actual group')
    for control in queue:
        if type(control) in (SpellGroupArrow, SettleSpellGroupArrow) and (
                control.window_id not in windows or windows[control.window_id].closed):
            raise ValueError('Spell arrow continuation borrowed an absent or closed actual acceptance')
        if type(control) is FinishSpellGroupTargets and control.proof.initial.window_id not in windows:
            raise ValueError('Spell group Finish borrowed an absent actual acceptance')
    for play in game._state.play_history:
        value = play.spell_target_receipt
        if value != values.get(play.id) or value is not None and value.original != play.spell_target_group:
            raise ValueError('Actual spell group differs from its original accepted event sequence')
        if value is None:
            if play.spell_target_group is not None and play.spell_payload is not None:
                raise ValueError('Paid group payload lost its actual target acceptance')
            continue
        validate_material(play)
        for fact in (value.source, *value.initial_targets, *value.targets, *(x.target for x in value.redirects)):
            if fact is not None: validate_allocation(game._state, game.registry, fact)
        controls = [x for x in queue if type(x) is FinishSpellGroupTargets and x.proof.initial.play_id == play.id]
        if play.id in finished:
            if controls: raise ValueError('Closed spell group retained a duplicate Finish')
            continue
        if game._state.status != 'playing': continue
        if len(controls) != 1 or controls[0].proof.acceptance_event != accepted[play.id]:
            raise ValueError('Pending spell group lost its one original acceptance proof')
        proof = controls[0].proof; verified = validate_proof(proof, game.registry, game.mechanics)
        _bind_proof_events(proof, by_sequence)
        from .spell_acceptance import _bind_prefix_and_references
        for state in (proof.before_state, *proof.phase_states, *proof.settlement_states):
            _bind_prefix_and_references(state, game._state, game.registry)
        _advance_redirects(verified, value)
        window = _window(game._state, value.window_id)
        arrows = [x for x in queue if type(x) in (SpellGroupArrow, SettleSpellGroupArrow) and x.window_id == value.window_id]
        if value.closed:
            if window is not None or arrows or len(proof.settlement_states) != len(value.targets):
                raise ValueError('Closed spell arrow group retained an unfinished target stage')
        elif (window is None or window.spell_target_index != value.phase or
                len(proof.phase_states) != value.phase+1 or len(arrows) != 1 or
                type(arrows[0]) is not SettleSpellGroupArrow or arrows[0].index != value.phase or
                window.target_id != (None if value.targets[value.phase] is None else value.targets[value.phase].entity_id)):
            raise ValueError('Pending spell group lost its exact current arrow continuation')
    if set(values)-{p.id for p in game._state.play_history}:
        raise ValueError('Actual spell group event borrowed an absent hand play')
    for (window_id, index), publication in publications.items():
        value = windows.get(window_id)
        if value is None or value.closed or index != value.phase:
            raise ValueError('Spell target publication lost its actual active or settled group arrow')
    for cast in game._state.cast_history:
        value = cast.spell_target_receipt
        play = None if cast.play_id is None else game._state.play_history[cast.play_id-1]
        if play is None:
            from .automatic_spell_groups import AutomaticSpellTargets
            if value is not None and type(value) is not AutomaticSpellTargets:
                raise ValueError('Automatic CAST borrowed a paid target group')
            continue
        if value != (None if play is None else play.spell_target_receipt):
            raise ValueError('Physical CAST lost its complete actual target group')
        if value is not None: validate_material(cast, cast=True)


def register(mechanics):
    for cls in (SpellGroupRedirect, SpellGroupTargets, SpellGroupTargetProof): mechanics.register_payload_type(cls)
    mechanics.register(SpellGroupArrow, arrow)
    mechanics.register(SettleSpellGroupArrow, settle)
    mechanics.register(FinishSpellGroupTargets, finish)
