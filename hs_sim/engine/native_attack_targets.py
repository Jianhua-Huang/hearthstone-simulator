"""Native attack replacement at the original physical listener position.

One accepted window keeps its original declaration, actual target and RNG proof.
Secrets may redirect the result; they never restart the native policy.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from types import SimpleNamespace

from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import Effect
from .model import ActionWindow, CardType, Event, GameState, Zone
from .native_random_targets import NativeTargetSelection, attack_partition, current_sources, sample
from .rules import Ruleset

ACCEPTED = 'native_attack_target_selected'
FINISHED = 'native_attack_target_finished'


def original_event(state, event):
    from .character_attacks import record
    if type(event) is not Event or event.kind != 'attack_declared':
        raise ValueError('Native attack requires its actual declaration event')
    row = record(state, dict(event.data).get('window_id'))
    w = row.declaration
    if ((event.source_id, event.target_id, event.player_id, event.action, event.sequence) !=
            (w.source_id, w.target_id, w.player_id, row.declaration_action, row.declaration_event_cursor + 1)):
        raise ValueError('Native attack borrowed a different original declaration')
    return row


def live_carrier(state, registry, captured):
    return any((x.source.entity_id, x.source.zone_epoch, x.source.entered_order) ==
               (captured.entity_id, captured.zone_epoch, captured.entered_order)
               for x in current_sources(state, registry))


@dataclass(frozen=True)
class CheckNativeAttackTarget(Effect):
    carrier: SourceAllocationFact
    event: Event

    def __post_init__(self):
        if type(self.carrier) is not SourceAllocationFact or type(self.event) is not Event:
            raise ValueError('Native attack listener requires its physical source and original event')
        self.carrier.__post_init__()
        if self.carrier.kind != CardType.MINION or self.carrier.zone != Zone.BOARD or self.event.kind != 'attack_declared':
            raise ValueError('Native attack listener requires an original battlefield declaration')


@dataclass(frozen=True)
class NativeAttackTargetProof:
    before_state: GameState
    rules: Ruleset
    window: ActionWindow
    selection: NativeTargetSelection
    listener: CheckNativeAttackTarget

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset or
                type(self.window) is not ActionWindow or type(self.selection) is not NativeTargetSelection or
                type(self.listener) is not CheckNativeAttackTarget):
            raise ValueError('Native attack proof requires the complete original acceptance')
        self.window.__post_init__(); self.selection.__post_init__(); self.listener.__post_init__()
        p = self.selection.partition
        if self.window.kind != 'attack' or not p.applied or (p.origin, p.window_id, p.source.entity_id,
                p.submitted_target_id) != ('attack', self.window.id, self.window.source_id, self.window.target_id):
            raise ValueError('Native attack proof changed its original window or source')


def validate_proof(proof, registry):
    from .interrupts import find_window
    proof.__post_init__(); state = proof.before_state
    validate_allocation(state, registry, proof.listener.carrier)
    row = original_event(state, proof.listener.event)
    if (state.status != 'playing' or row.native_target is not None or
            find_window(state, proof.window.id) != proof.window or
            not live_carrier(state, registry, proof.listener.carrier)):
        raise ValueError('Native attack proof lost its original live, unaccepted listener window')
    actual = attack_partition(SimpleNamespace(state=state, registry=registry), proof.window)
    if actual != proof.selection.partition:
        raise ValueError('Native attack proof cropped or changed its complete original domain')


@dataclass(frozen=True)
class FinishNativeAttackTarget(Effect):
    proof: NativeAttackTargetProof

    def __post_init__(self):
        if type(self.proof) is not NativeAttackTargetProof:
            raise ValueError('Native attack Finish requires its complete original proof')
        self.proof.__post_init__()


def capture(r, entity, event):
    if event.kind != 'attack_declared' or not r.registry.random_target_cards:
        return None
    from .lifecycle import active_abilities
    if entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not active_abilities(entity, 'random_targets'):
        return None
    source = SourceAllocationFact.capture(r.state, entity)
    if not live_carrier(r.state, r.registry, source):
        return None
    return CheckNativeAttackTarget(source, event)


def check(r, effect):
    from .character_attacks import update
    from .interrupts import find_window, redirect, RedirectAttack
    from .native_target_acceptance import encode
    row = original_event(r.state, effect.event)
    if row.native_target is not None or not live_carrier(r.state, r.registry, effect.carrier):
        return ()
    window = find_window(r.state, row.declaration.id)
    if window is None:
        return ()
    partition = attack_partition(r, window)
    if not partition.applied:
        return ()
    before = deepcopy(r.state); selection = sample(r.game._rng, partition)
    proof = NativeAttackTargetProof(before, r.rules, window, selection, effect)
    update(r.state, row, native_target=selection)
    r.emit(ACCEPTED, source_id=window.source_id, target_id=selection.target_id, player_id=window.player_id,
        window_id=window.id, window=encode(r, window), selection=encode(r, selection),
        listener=encode(r, effect), _capture=False)
    if selection.failure is None:
        redirect(r, RedirectAttack(window.id, selection.target_id), native_selection=selection)
    return (FinishNativeAttackTarget(proof),)


def finish(r, effect):
    from .character_attacks import record
    proof = effect.proof; validate_proof(proof, r.registry)
    if record(r.state, proof.window.id).native_target != proof.selection:
        raise ValueError('Native attack Finish changed its accepted selection')
    r.emit(FINISHED, source_id=proof.window.source_id, target_id=proof.selection.target_id,
        player_id=proof.window.player_id, window_id=proof.window.id, _capture=False)
    return ()


def validate_boundary(game):
    from .character_attacks import record
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    rows = game._state.character_attack_history
    if not game.registry.random_target_cards:
        if any(row.native_target is not None for row in rows):
            raise ValueError('Native attack material borrowed an unregistered source policy')
        return
    codec = FrameCodec(game.mechanics, game.registry); events = effective_events(game._events)
    accepted = {}; finished = set()
    for event in events:
        if event.kind not in (ACCEPTED, FINISHED):
            continue
        data = dict(event.data); wid = data['window_id']; row = record(game._state, wid)
        if event.kind == ACCEPTED:
            if wid in accepted:
                raise ValueError('Native attack selected its target more than once')
            selection = codec.decode(json.loads(data['selection']))
            window = codec.decode(json.loads(data['window'])); listener = codec.decode(json.loads(data['listener']))
            if type(selection) is not NativeTargetSelection or type(window) is not ActionWindow or type(listener) is not CheckNativeAttackTarget:
                raise ValueError('Native attack receipt lost its complete typed material')
            p = selection.partition; original_event(game._state, listener.event)
            if (row.native_target != selection or window.id != wid or not p.applied or
                    (p.origin, p.window_id, p.source.entity_id, p.submitted_target_id) != ('attack', wid, window.source_id, window.target_id) or
                    (event.source_id, event.player_id, event.target_id) != (window.source_id, window.player_id, selection.target_id) or
                    not 0 < listener.event.sequence < event.sequence or game._events[listener.event.sequence-1] != listener.event):
                raise ValueError('Native attack receipt borrowed its original declaration or target')
            for fact in (listener.carrier, p.source, *(x.source for x in p.carriers), *p.candidates):
                validate_allocation(game._state, game.registry, fact)
            redirects = [e for e in events if e.kind == 'attack_redirected' and
                dict(e.data).get('window_id') == wid and dict(e.data).get('native_random_target') is True]
            if (selection.failure is None and (len(redirects) != 1 or redirects[0].target_id != selection.target_id or
                    redirects[0].sequence <= event.sequence) or selection.failure is not None and redirects):
                raise ValueError('Native attack lost its actual one-time target replacement')
            accepted[wid] = (selection, window, listener)
        else:
            if wid not in accepted or wid in finished:
                raise ValueError('Native attack Finish duplicated or borrowed a selection')
            selection, window, _ = accepted[wid]
            if (event.source_id, event.player_id, event.target_id) != (window.source_id, window.player_id, selection.target_id):
                raise ValueError('Native attack Finish changed its accepted identity')
            finished.add(wid)
    for row in rows:
        if row.native_target is not None and row.declaration.id not in accepted:
            raise ValueError('Native attack history lost its original selection receipt')
    frame = game._frame; queue = () if frame is None else (*frame.prefix, *frame.continuation)
    for item in queue:
        if type(item) is CheckNativeAttackTarget:
            original_event(game._state, item.event); validate_allocation(game._state, game.registry, item.carrier)
            if not 0 < item.event.sequence <= len(game._events) or game._events[item.event.sequence-1] != item.event:
                raise ValueError('Pending native listener lost its original actual event')
    if game._state.status != 'playing':
        return
    for wid, (selection, window, listener) in accepted.items():
        if wid in finished:
            continue
        tails = [x for x in queue if type(x) is FinishNativeAttackTarget and x.proof.window.id == wid]
        if len(tails) != 1 or (tails[0].proof.selection, tails[0].proof.window, tails[0].proof.listener) != (selection, window, listener):
            raise ValueError('Waiting native attack lost its unique original Finish')
        validate_proof(tails[0].proof, game.registry)


def register(mechanics):
    mechanics.register_payload_type(NativeAttackTargetProof)
    mechanics.register(CheckNativeAttackTarget, check)
    mechanics.register(FinishNativeAttackTarget, finish)
