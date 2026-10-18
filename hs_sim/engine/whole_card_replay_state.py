"""Durable whole-card replay state shared by live and captured GameState.

Persistence and genuine submitted-prefix binding accompany the interpreter.
Active roots require complete original acceptance and full-body Finish tails.
"""
from dataclasses import is_dataclass
from enum import Enum

from . import whole_card_history as history
from . import whole_card_replay_ledger as ledger_types
from . import offered_card_selection as offered_types
from .whole_card_replay_ledger import (
    ReplayChildStatus, ReplayRootStatus, WholeCardReplayLedger, interrupt_replay_ledger,
    ledger_from_dict, ledger_to_dict, validate_ledger_registry)


def empty_ledger():
    return WholeCardReplayLedger()


def encode(ledger):
    return ledger_to_dict(ledger)


def decode(value):
    return ledger_from_dict(value)


def validate_history(state, registry):
    ledger = state.whole_card_replay_ledger
    if type(ledger) is not WholeCardReplayLedger:
        raise ValueError('GameState requires its typed whole-card replay ledger')
    validate_ledger_registry(ledger, registry)
    for root in ledger.roots:
        frontier = root.selection.frontier
        if (root.accepted_turn > state.turn or root.accepted_action > state.action_number
                or frontier.history_size > len(state.play_history)
                or frontier.owner_turn_size > len(state.owner_turn_history)
                or root.owner_turn_id > len(state.owner_turn_history)):
            raise ValueError('Replay acceptance refers to future game history or clocks')
        interval = state.owner_turn_history[root.owner_turn_id - 1]
        if interval.turn != root.accepted_turn or interval.start_action > root.accepted_action:
            raise ValueError('Replay acceptance lost its actual active owner interval')
        caster = state.entities.get(root.caster.entity_id)
        if caster is None or caster.zone_epoch < root.caster.zone_epoch:
            raise ValueError('Replay acceptance lost its original physical caster')
        # Current faces, class, ownership and outcomes may legitimately advance.
        # The original immutable paid-submission face and time cannot change.
        if type(root.selection) is offered_types.OfferedCardSelection:
            offered_types.validate_origin(root.selection, state, registry)
        for row in (() if type(root.selection) is offered_types.OfferedCardSelection else frontier.rows):
            occurrence = row.occurrence
            actual = state.play_history[occurrence.id - 1]
            if ((actual.played_face, actual.turn, actual.action)
                    != (occurrence.face, occurrence.turn, occurrence.action)):
                raise ValueError('Replay acceptance differs from its real frozen submission prefix')
            for flag in ('completed', 'countered', 'interrupted'):
                if getattr(occurrence, flag) and not getattr(actual, flag):
                    raise ValueError('Replay acceptance lost a committed original outcome')
        if state.status == 'playing' and root.status == ReplayRootStatus.INTERRUPTED:
            raise ValueError('Live game cannot contain terminal-interrupted replay roots')
        if state.status != 'playing' and root.status == ReplayRootStatus.RUNNING:
            raise ValueError('Terminal game cannot retain running replay roots')
    used_casts = set()
    for child in ledger.children:
        root = ledger.roots[child.root_id - 1]
        if child.failure == 'original_offer_unavailable':
            from .offered_card_execution import original
            if (type(root.selection) is not offered_types.OfferedCardSelection or
                    original(registry, root.selection, child.occurrence_id)[1].route != 'unavailable' or
                    child.spell_cast_id is not None or child.physical is not None):
                raise ValueError('Unavailable offer cannot erase an actual history or allocated body')
        if (root.runtime_route in ('spells_v1', 'cards_v1') and child.kind.value == 'spell' and child.status != ReplayChildStatus.RUNNING
                and child.failure not in ('ancestor_excluded', 'original_offer_unavailable') and child.spell_cast_id is None):
            raise ValueError('Actual replay child cannot erase its allocated spell body')
        if child.spell_cast_id is None: continue
        if child.spell_cast_id > len(state.cast_history) or child.spell_cast_id in used_casts:
            raise ValueError('Replay child lost its unique real spell cast')
        used_casts.add(child.spell_cast_id)
        cast = state.cast_history[child.spell_cast_id - 1]
        from .history_branch_replays import validate_receipt as validate_branch
        validate_branch(state, registry, root, child, cast)
        entity = state.entities[cast.source_id]
        if (cast.origin != 'effect' or cast.play_id is not None or cast.from_zone is not None
                or cast.card_id != child.card_id or cast.caster_id != root.caster.entity_id
                or cast.player_id != root.player_id or cast.turn < root.accepted_turn
                or cast.action < root.accepted_action or entity.origin_entity_id != cast.caster_id):
            raise ValueError('Replay child and its actual full spell provenance differ')
        if child.status == ReplayChildStatus.FINISHED and (not cast.completed or cast.failure is not None):
            raise ValueError('Finished replay child lost its actual completed spell body')
        if child.status == ReplayChildStatus.FAILED and (not cast.completed or child.failure != cast.failure):
            raise ValueError('Failed replay child lost its actual failed spell attempt')
        if child.status == ReplayChildStatus.INTERRUPTED and not (cast.completed or cast.interrupted):
            raise ValueError('Interrupted replay child lost its actual terminal cast outcome')
    from .whole_card_physical import validate_physical_history
    validate_physical_history(state, registry)


def validate_boundary(game):
    validate_history(game._state, game.registry)
    from .whole_card_replays import validate_boundary as validate_runtime_boundary
    validate_runtime_boundary(game)


def interrupt(r):
    state = r.state
    if state.whole_card_replay_ledger.stack:
        from .whole_card_replays import validate_queue
        validate_queue(state, r.registry, tuple(r._work_queue))
        state.whole_card_replay_ledger = interrupt_replay_ledger(
            state.whole_card_replay_ledger, state)


def register_payloads(mechanics):
    for module in (history, ledger_types, offered_types):
        for value in vars(module).values():
            if (isinstance(value, type) and value.__module__ == module.__name__
                    and (issubclass(value, Enum) or
                         is_dataclass(value) and value.__dataclass_params__.frozen)):
                if value not in mechanics.payload_types:
                    mechanics.register_payload_type(value)
