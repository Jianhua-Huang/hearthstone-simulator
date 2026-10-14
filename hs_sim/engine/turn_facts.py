"""Pure current actual-interval public counts, separate from prior hand turns."""
from .effects import _player
from .model import CurrentTurnFactQuery, GameState
from .owner_turns import current_owner_turn
from .spell_casts import cast_spells


def current_turn_fact_count(state, player_id, query):
    _player(player_id)
    if type(state) is not GameState or type(query) is not CurrentTurnFactQuery:
        raise ValueError('Current-turn count requires typed state and query')
    query.__post_init__()
    if not state.owner_turn_history:
        if state.opening is not None and state.opening.stage != 'complete':
            return 0
        raise ValueError('Current-turn count has no actual interval')
    interval = current_owner_turn(state)
    if query.window == 'owner_turn' and interval.player_id != player_id:
        return 0
    if query.kind == 'hero_attack':
        # Only voluntary hero declarations currently consume this count.
        return state.entities[state.players[player_id].hero_id].attacks_this_turn
    records = cast_spells(state, player_id, turn=interval.turn)
    return sum(1 for record in records
        if record.owner_turn_id == interval.id and record.origin in query.origins and
        (query.phase == 'attempt' or
         query.phase == 'payload_accepted' and record.payload_started and record.failure is None or
         query.phase == 'completed' and record.completed and record.failure is None))
