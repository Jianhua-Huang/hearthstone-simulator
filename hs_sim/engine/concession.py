"""Replayable seat concession, reusing the interpreter's terminal interruption."""
from .actions import Concede


def concede(r, player_id):
    Concede(player_id)  # The host cannot forge a seat or a boolean ID.
    frame = r.game._frame
    work = ()
    if frame is not None:
        r._steps = frame.steps
        r.root_action_number = frame.root_action_number
        r.ending_turn = frame.ending_turn
        r.death_deferrals = frame.death_deferrals
        work = (*frame.prefix, *frame.continuation)
    r.state.status = 'finished'
    r.state.winner = 3 - player_id
    event = r.emit('game_ended', player_id=r.state.winner, reason='concede',
                   result='finished', conceding_player=player_id, _capture=False)
    from .hero_lethal_windows import interrupt_concession
    interrupt_concession(r, work, event)
    # Retain real pending tails for their existing acceptance validators. No
    # choice callback, queued effect, gameplay checkpoint or RNG is executed.
    r.run(work)


def validate_boundary(game):
    events = [e for e in game._events
              if e.kind == 'game_ended' and dict(e.data).get('reason') == 'concede']
    if not events:
        if any(row.interrupted_event is not None for row in game._state.hero_lethal_roots):
            raise ValueError('Interrupted Hero root lost its real concession event')
        return
    if len(events) != 1:
        raise ValueError('A match can concede only once')
    event = events[0]
    data = dict(event.data)
    if set(data) != {'reason', 'result', 'conceding_player'}:
        raise ValueError('Concession requires its exact public terminal fact')
    Concede(data['conceding_player'])
    state = game._state
    if (state.status != 'finished' or state.winner != 3 - data['conceding_player']
            or event.player_id != state.winner or data['result'] != 'finished'
            or event.action != state.action_number or event.action < 1
            or event.source_id is not None or event.target_id is not None or event.amount != 0
            or game._frame is not None or state.pending_choice is not None):
        raise ValueError('Concession terminal fact differs from the finished match')
    for root in state.hero_lethal_roots:
        if root.interrupted_event is not None and (
                root.interrupted_event != event.sequence or root.interrupted_action != event.action):
            raise ValueError('Interrupted Hero root borrowed another terminal event')

