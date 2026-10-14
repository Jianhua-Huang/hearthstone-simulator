"""H1: real own-turn intervals and immutable submitted faces.

The latest closed own interval is a versioned prototype policy, not CN evidence.
Terminal interruption leaves the current interval open; configured natural-end
draw closes it without starting another interval. Queries never inspect live
entities, acquisition time, global-turn parity, RNG, or cast history.
"""
from dataclasses import fields, replace

from .model import (CardDefinition, CardType, FrozenPlayedFaceFact, GameState,
                    OwnerTurnMatchRow, OwnerTurnRecord, OwnerTurnStartInterruption, PlayedTypeQuery,
                    PreviousOwnerTurnMatch, OwnerTurnTypeMatch, OwnerTurnTypeHistory)


def current_owner_turn(state):
    if type(state.owner_turn_history) is not list:
        raise ValueError('Owner-turn history requires a list')
    if not state.owner_turn_history or state.owner_turn_history[-1].closed:
        raise ValueError('A committed hand play requires a genuinely started interval')
    value = state.owner_turn_history[-1]
    if (value.turn, value.player_id) != (state.turn, state.active_player):
        raise ValueError('Current owner interval differs from the actual turn')
    return value


def owner_turn_index(state, player_id):
    """Count genuine starts, including only the constructor's conceptual start."""
    previous = next((r for r in reversed(state.owner_turn_history) if r.player_id == player_id), None)
    if previous is not None:
        return previous.owner_index
    return int(not state.owner_turn_history and state.opening is None and state.active_player == player_id)


def start_owner_turn(state, event_cursor, *, origin='actual'):
    """Resolver-only operation at genuine scenario/first/next start entrances."""
    if state.owner_turn_history and not state.owner_turn_history[-1].closed:
        raise ValueError('Cannot start another interval before actual handoff')
    previous = next((r for r in reversed(state.owner_turn_history)
                     if r.player_id == state.active_player), None)
    record = OwnerTurnRecord(len(state.owner_turn_history) + 1, state.active_player,
        1 if previous is None else previous.owner_index + 1, state.turn,
        None if previous is None else previous.id, state.action_number, event_cursor, origin)
    state.owner_turn_history.append(record)
    return record


def close_owner_turn(state, event_cursor):
    """Close only after all natural-end reactions and expiry have settled."""
    record = current_owner_turn(state)
    closed = replace(record, closed_action=state.action_number, closed_event=event_cursor)
    state.owner_turn_history[-1] = closed
    return closed


def publish_owner_start(state, event):
    record = current_owner_turn(state)
    if (record.origin != 'actual' or record.publication_event is not None or record.start_interruption is not None
            or event.kind != 'turn_started' or event.player_id != record.player_id
            or dict(event.data).get('turn') != record.turn or event.sequence <= record.start_event
            or event.action < record.start_action):
        raise ValueError('Genuine owner start publication differs from its pending interval')
    state.owner_turn_history[-1] = replace(record, publication_event=event.sequence, publication_action=event.action)


def mark_owner_end(state, event):
    record = current_owner_turn(state)
    if record.end_event is not None or event.kind != 'turn_ended' or event.player_id != record.player_id:
        raise ValueError('Owner interval requires its unique actual natural end')
    state.owner_turn_history[-1] = replace(record, end_event=event.sequence, end_action=event.action)


def interrupt_owner_start(resolution, queue):
    """Capture interrupted startup before the interpreter discards real work."""
    if not resolution.state.owner_turn_history:
        return
    record = resolution.state.owner_turn_history[-1]
    if record.origin != 'actual' or record.publication_event is not None:
        return
    from .resolver import BeginTurnEvents
    starts = [work for work in queue if type(work) is BeginTurnEvents]
    if (len(starts) != 1 or record.closed or record.id == 1
            or resolution.root_action_number != record.start_action):
        raise ValueError('Unpublished terminal turn lost its unique real pending start work')
    terminal = [event for event in resolution.game._events if event.kind == 'game_ended'
                and dict(event.data).get('reason') == 'hero_death' and event.sequence > record.start_event]
    if len(terminal) != 1:
        raise ValueError('Interrupted startup requires its genuine terminal checkpoint')
    event = terminal[0]
    proof = OwnerTurnStartInterruption(resolution.root_action_number, event.sequence, event.action)
    resolution.state.owner_turn_history[-1] = replace(record, start_interruption=proof)


def freeze_played_face(state, registry, source, play_id):
    definition = registry.card(source.card_id)
    if state.opening is not None and state.opening.stage != 'complete':
        if state.owner_turn_history:
            raise ValueError('Pre-first payment cannot borrow an actual owner interval')
        return FrozenPlayedFaceFact(play_id, source.id, source.controller, None,
            definition.id, definition.kind, definition.metadata, definition.spell_school,
            state.opening.stage, state.opening.first_player)
    interval = current_owner_turn(state)
    return FrozenPlayedFaceFact(play_id, source.id, source.controller, interval.id,
        definition.id, definition.kind, definition.metadata, definition.spell_school)


def validate_face(face, registry):
    face.__post_init__()
    definition = registry.card(face.card_id)
    if ((face.kind, face.metadata, face.spell_school) !=
            (definition.kind, definition.metadata, definition.spell_school)
            or not definition.hand_playable):
        raise ValueError('Frozen submitted face differs from its pinned definition')


def validate_history(state, registry=None):
    """Complete structural history, optionally binding all faces to the registry."""
    if type(state) is not GameState or type(state.owner_turn_history) is not list:
        raise ValueError('Expected typed state and owner-turn list')
    _validate_history_input(state, registry)


def _validate_history_input(state, registry=None):
    """Original history validator over live state or a typed saved projection."""
    last_for_owner = {}
    previous = None
    for index, record in enumerate(state.owner_turn_history, 1):
        if type(record) is not OwnerTurnRecord:
            raise ValueError('Owner-turn history requires immutable typed intervals')
        record.__post_init__()
        progress_actions = (record.publication_action, record.end_action, record.closed_action,
                            None if record.start_interruption is None
                            else record.start_interruption.game_ended_action)
        if any(action is not None and action > state.action_number for action in progress_actions):
            raise ValueError('Owner-turn progress is newer than its captured state')
        prior = last_for_owner.get(record.player_id)
        if (record.id != index or record.owner_index != (1 if prior is None else prior.owner_index + 1)
                or record.previous_id != (None if prior is None else prior.id)
                or record.turn > state.turn or record.start_action > state.action_number
                or record.closed_action is not None and record.closed_action > state.action_number):
            raise ValueError('Invalid owner-turn identity, predecessor, or clock')
        if previous is not None and (not previous.closed or record.turn <= previous.turn
                or record.start_action != previous.closed_action or record.start_event != previous.closed_event):
            raise ValueError('Owner-turn history lost an actual handoff boundary')
        if record.origin == 'scenario' and (index != 1 or record.turn != 1
                or record.start_action != 0 or state.opening is not None):
            raise ValueError('Scenario supplies only one conceptual initial interval')
        if record.origin == 'actual' and index == 1 and record.turn != 1:
            raise ValueError('First actual owner interval must start the first turn')
        last_for_owner[record.player_id] = record
        previous = record
    before_first = state.opening is not None and state.opening.stage != 'complete'
    if before_first:
        if state.owner_turn_history:
            raise ValueError('Opening has no genuinely started turn')
    elif not state.owner_turn_history:
        raise ValueError('Started games require their actual owner interval history')
    if state.owner_turn_history:
        current = state.owner_turn_history[-1]
        if (current.turn, current.player_id) != (state.turn, state.active_player):
            raise ValueError('Latest owner interval differs from current turn')
        if state.status == 'playing' and current.closed:
            raise ValueError('A playing game requires its still-open current interval')
        if state.opening is not None and state.owner_turn_history[0].origin != 'actual':
            raise ValueError('Constructed games cannot retain the temporary scenario interval')
    for play in state.play_history:
        face = play.played_face
        if type(face) is not FrozenPlayedFaceFact:
            raise ValueError('Committed hand root lost its frozen played face')
        face.__post_init__()
        if ((face.play_id, face.source_id, face.player_id, face.card_id, face.kind) !=
                (play.id, play.source_id, play.player_id, play.card_id, play.kind)):
            raise ValueError('Frozen face differs from its accepted root')
        if face.owner_turn_id is None:
            if (state.opening is None or face.opening_first_player != state.opening.first_player or play.turn != 1
                    or state.owner_turn_history and play.action > state.owner_turn_history[0].start_action):
                raise ValueError('Pre-first frozen face lost its actual opening identity')
            order = {'dealing': 0, 'mulligan': 1, 'starting': 2, 'complete': 3}
            if order[face.opening_stage] > order[state.opening.stage]:
                raise ValueError('Pre-first frozen face is newer than its opening phase')
        else:
            if not 1 <= face.owner_turn_id <= len(state.owner_turn_history):
                raise ValueError('Played face references an unknown actual interval')
            interval = state.owner_turn_history[face.owner_turn_id - 1]
            if (interval.turn != play.turn or play.action < interval.start_action
                    or interval.closed and play.action > interval.closed_action):
                raise ValueError('Frozen face differs from its actual interval')
        if registry is not None:
            validate_face(face, registry)


def query_for_definition(definition):
    if type(definition) is not CardDefinition:
        raise ValueError('Historical type query requires a pinned printed definition')
    tribes = (None if definition.metadata is None else definition.metadata.tribes)
    return PlayedTypeQuery(definition.kind, tribes if definition.kind == CardType.MINION else None,
                           definition.spell_school)


def share_tribes(first, second):
    """Symmetric all relationship; explicit empty tribes never match all."""
    for value in (first, second):
        if value is None:
            raise ValueError('Previous-own-turn query requires known Minion tribes')
        if type(value) is not tuple or any(type(t) is not str or not t.strip() for t in value):
            raise ValueError('Invalid history tribes')
    return bool(first and second and
                ('all' in first or 'all' in second or set(first).intersection(second)))


def _validate_type_query(state, player_id, query):
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Invalid previous-owner query player')
    if type(query) is not PlayedTypeQuery:
        raise ValueError('Expected explicit historical type query')
    query.__post_init__()
    validate_history(state)
    if query.kind == CardType.MINION and query.tribes is None:
        raise ValueError('History subject has unknown Minion tribes')


def _match_face(face, query):
    if query.kind == CardType.MINION:
        tribes = None if face.metadata is None else face.metadata.tribes
        matched = share_tribes(query.tribes, tribes)
    else:
        # None is an explicitly unschooled Spell, never a matching type.
        matched = query.spell_school is not None and face.spell_school == query.spell_school
    return matched


def query_previous_owner_turn(state, player_id, query):
    """Return the complete ordered true/false relation before aggregating."""
    _validate_type_query(state, player_id, query)
    interval = next((r for r in reversed(state.owner_turn_history)
                     if r.player_id == player_id and r.closed), None)
    rows = []
    if interval is not None:
        for play in state.play_history:
            face = play.played_face
            if (face.owner_turn_id, face.player_id, face.kind) != (interval.id, player_id, query.kind):
                continue
            matched = _match_face(face, query)
            rows.append(OwnerTurnMatchRow(face, matched))
    return PreviousOwnerTurnMatch(player_id, query, interval, tuple(rows), any(r.matched for r in rows))


def query_owner_turn_history(state, player_id, query):
    """Complete original own intervals, without deciding a cost/streak policy."""
    _validate_type_query(state, player_id, query)
    return _type_history_relation(state.owner_turn_history,
        tuple(play.played_face for play in state.play_history), player_id, query)


def _type_history_relation(owner_turn_history, played_faces, player_id, query):
    """Original complete collector, shared by live query and saved price."""
    intervals = tuple(r for r in owner_turn_history if r.player_id == player_id)
    groups = {r.id: [] for r in intervals}
    outside = []
    for face in played_faces:
        if (face.player_id, face.kind) != (player_id, query.kind):
            continue
        if face.owner_turn_id not in groups:
            # Pre-first or actual foreign-owner interval: preserve the face,
            # without inventing an own turn or applying its type predicate.
            outside.append(face)
            continue
        groups[face.owner_turn_id].append(OwnerTurnMatchRow(face, _match_face(face, query)))
    relations = tuple(OwnerTurnTypeMatch(r, tuple(groups[r.id]), any(row.matched for row in groups[r.id]))
        for r in intervals)
    return OwnerTurnTypeHistory(player_id, query, relations, tuple(outside))


def validate_accepted_prefix(original, state, registry):
    """Original controls bind all intervals and all submitted faces, including false rows."""
    validate_history(original, registry)
    validate_history(state, registry)
    if len(state.owner_turn_history) < len(original.owner_turn_history) or len(state.play_history) < len(original.play_history):
        raise ValueError('Accepted owner-turn/played-face prefix was truncated')
    _validate_owner_interval_prefix(original.owner_turn_history, state.owner_turn_history, original.action_number)
    if any(old.played_face != new.played_face for old, new in zip(original.play_history, state.play_history)):
        raise ValueError('Accepted frozen hand-play face prefix was rewritten')


def _validate_owner_interval_prefix(before_rows, after_rows, capture_action):
    """Original interval/progress prefix check, without reconstructing world state."""
    for before, after in zip(before_rows, after_rows):
        progress = ('closed_action', 'closed_event', 'publication_event', 'publication_action', 'end_event', 'end_action', 'start_interruption')
        names = tuple(f.name for f in fields(OwnerTurnRecord) if f.name not in progress)
        if tuple(getattr(before, n) for n in names) != tuple(getattr(after, n) for n in names):
            raise ValueError('Accepted actual owner interval was rewritten')
        if before.closed and before != after:
            raise ValueError('Accepted closed owner interval was rewritten')
        if any(getattr(before, name) is not None and getattr(before, name) != getattr(after, name) for name in progress):
            raise ValueError('Accepted genuine owner-turn progress was rewritten')
        # An early emit may capture the original pending state in the same
        # action. A later captured state cannot erase already completed progress.
        for event_name, action_name in (('publication_event', 'publication_action'),
                                       ('end_event', 'end_action'),
                                       ('closed_event', 'closed_action')):
            if (getattr(before, event_name) is None and getattr(after, event_name) is not None
                    and getattr(after, action_name) < capture_action):
                raise ValueError('Original owner-turn progress contradicts its capture action')
        if (before.start_interruption is None and after.start_interruption is not None
                and after.start_interruption.game_ended_action < capture_action):
            raise ValueError('Original startup interruption contradicts its capture action')


def validate_control_work(resolution, work):
    from .repeat_windows import original_acceptance_windows
    for context, _family, _root in original_acceptance_windows(work):
        validate_accepted_prefix(context.state, resolution.state, resolution.registry)


def validate_boundary(game):
    state = game._state
    validate_history(state, game.registry)
    for record in state.owner_turn_history:
        if record.start_event > len(game._events) or (record.closed_event is not None and record.closed_event > len(game._events)):
            raise ValueError('Owner-turn cursor exceeds the saved actual event timeline')
        starts = [event for event in game._events if event.kind == 'turn_started'
            and event.player_id == record.player_id and dict(event.data).get('turn') == record.turn]
        if record.publication_event is not None:
            if (len(starts) != 1 or (starts[0].sequence, starts[0].action) != (record.publication_event, record.publication_action)):
                raise ValueError('Actual owner interval lost its exact publication event and action')
        elif record.origin == 'actual':
            if starts or record != state.owner_turn_history[-1] or record.id == 1 or record.closed:
                raise ValueError('Only the genuine current startup may remain unpublished')
            if record.start_interruption is None:
                from .resolver import BeginTurnEvents
                frame = game._frame
                if (state.status != 'playing' or frame is None or frame.ending_turn
                        or frame.root_action_number != record.start_action
                        or sum(type(work) is BeginTurnEvents for work in (*frame.prefix, *frame.continuation)) != 1):
                    raise ValueError('Pending startup lost its unique genuine continuation')
            else:
                proof = record.start_interruption
                terminal = [event for event in game._events if event.sequence == proof.game_ended_event]
                if (state.status == 'playing' or game._frame is not None or len(terminal) != 1
                        or terminal[0].kind != 'game_ended' or dict(terminal[0].data).get('reason') != 'hero_death'
                        or terminal[0].action != proof.game_ended_action):
                    raise ValueError('Interrupted startup lost its pre-clear terminal witness')
        ends = [event for event in game._events if event.kind == 'turn_ended'
            and event.player_id == record.player_id and record.start_event < event.sequence
            and (record.closed_event is None or event.sequence <= record.closed_event)
            and event.action >= record.start_action]
        if record.end_event is not None:
            if not any((event.sequence, event.action) == (record.end_event, record.end_action) for event in ends):
                raise ValueError('Owner interval lost its exact natural-end event')
        elif record.closed:
            raise ValueError('Closed interval lacks actual natural end')
    if state.owner_turn_history and state.owner_turn_history[0].origin == 'actual':
        first = state.owner_turn_history[0]
        if not any(event.kind == 'game_started' and event.sequence == first.start_event + 1
                   and (event.player_id, event.action) == (first.player_id, first.start_action)
                   for event in game._events):
            raise ValueError('Actual first owner interval lost its exact game-start boundary')
    for play in state.play_history:
        committed = [event for event in game._events if event.kind == 'card_committed'
            and dict(event.data).get('play_id') == play.id and event.action == play.action
            and (event.source_id, event.player_id) == (play.source_id, play.player_id)]
        if len(committed) != 1:
            raise ValueError('Frozen submitted phase lost its unique actual card-commit event')
        event = committed[0]
        face = play.played_face
        if face.owner_turn_id is None:
            if state.owner_turn_history and event.sequence > state.owner_turn_history[0].start_event:
                raise ValueError('Pre-first submitted phase crossed the actual first-start boundary')
        else:
            interval = state.owner_turn_history[face.owner_turn_id - 1]
            if event.sequence <= interval.start_event or interval.closed and event.sequence > interval.closed_event:
                raise ValueError('Submitted face crossed its actual interval event boundaries')
    if state.owner_turn_history and state.owner_turn_history[-1].closed:
        last = state.owner_turn_history[-1]
        if not (state.status == 'draw' and game.ruleset.draw_after_turn is not None
                and state.turn >= game.ruleset.draw_after_turn and any(
                    event.sequence == last.closed_event + 1 and event.action == last.closed_action
                    and event.kind == 'game_ended' and dict(event.data).get('reason') == 'configured_draw_turn'
                    for event in game._events)):
            raise ValueError('Closed terminal interval requires the actual configured natural-end draw')
    if game._frame is not None:
        from .repeat_windows import original_acceptance_windows
        for work in (*game._frame.prefix, *game._frame.continuation):
            for context, _family, _root in original_acceptance_windows(work):
                validate_accepted_prefix(context.state, state, game.registry)
