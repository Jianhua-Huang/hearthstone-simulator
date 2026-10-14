"""Original healing-related packets, retained as immutable State facts.

The original resolver owns all numbers, conversion and reactions. This module
records settled results before their batch's first event capture. Queries use
State facts, never the host event log or a mutable player total.
"""
from . import health_history
from .model import CardType, GameState, HealingRecord, HeroHealedTurnMatch, HealthFlow, _int


def healing_related(result):
    return health_history.related(result, HealthFlow.HEALING)


def validate_record(record):
    return health_history.validate_record(record, HealthFlow.HEALING)


def _checked_rows(state, registry=None):
    return health_history.checked_rows(state, HealthFlow.HEALING, registry)


def validate_state(state, registry=None):
    _checked_rows(state, registry)


def _player(value, name):
    if value is not None and (type(value) is not int or value not in (1, 2)):
        raise ValueError('Invalid healing query ' + name)


def healing_records(state, *, source_player=None, target_player=None, target_kind=None, turn=None, before_id=None):
    """Complete selected occurrences, including zero/prevented/converted rows.

Positive actual healing with unknown source cannot be guessed into or out of a
source-player total. A target-only query does not need that attribution.
"""
    return health_history.select_records(state, HealthFlow.HEALING, source_player=source_player,
        target_player=target_player, target_kind=target_kind, turn=turn, before_id=before_id)


def restored_health(state, player_id, *, turn=None):
    """Actual units restored by the captured source, to any character."""
    _player(player_id, 'source player')
    if player_id is None: raise ValueError('Restored-health total requires an actual source player')
    return sum(row.health_result.healed for row in healing_records(state, source_player=player_id, turn=turn))


def hero_was_healed(state, player_id, *, turn):
    """Actual positive restoration of this player's hero, regardless of source."""
    _player(player_id, 'target player')
    if player_id is None: raise ValueError('Hero-healed query requires an actual target player')
    _int(turn, 'hero-healed query turn', 1)
    return any(row.health_result.healed > 0 for row in healing_records(state,
        target_player=player_id, target_kind=CardType.HERO, turn=turn))


def capture_hero_healed_turn(state, player_id):
    """Finite intrinsic consumer; retain every original row, including false ones."""
    return HeroHealedTurnMatch(player_id, state.turn, state.action_number,
        state.next_healing_id, healing_records(state), hero_was_healed(state, player_id, turn=state.turn))


def validate_hero_healed_match(match, registry):
    match.__post_init__()
    for row in match.records:
        result = row.health_result
        if registry.card(result.target_card_id).kind.value != result.target_kind:
            raise ValueError('Hero-healed condition changed its original target kind')
        if result.source_card_id is not None: registry.card(result.source_card_id)


def validate_hero_healed_prefix(match, state, registry):
    validate_hero_healed_match(match, registry)
    rows = healing_records(state)
    if (match.turn > state.turn or match.action > state.action_number or
            match.next_healing_id > state.next_healing_id or rows[:len(match.records)] != match.records or
            any(row.action < match.action for row in rows[len(match.records):])):
        raise ValueError('Hero-healed condition lost its original complete physical healing prefix')


def commit_batch(state, pending_events):
    """Resolver-only recording after original numeric settlement, before capture.

Use the existing packet identity, without predicting event positions or
adding a second event, health calculation or checkpoint.
"""
    health_history.commit_batch(state, pending_events, (HealthFlow.HEALING,))


def validate_boundary(game):
    health_history.validate_boundary(game, (HealthFlow.HEALING,))


def record_from_dict(value):
    return health_history.record_from_dict(value, HealthFlow.HEALING)


def rows_from_dict(value):
    health_history.rows_from_dict(value, HealthFlow.HEALING)
