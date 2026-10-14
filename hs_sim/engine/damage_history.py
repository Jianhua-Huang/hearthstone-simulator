"""Pure queries over original settled damage; no second damage executor."""
from . import health_history
from .model import CardType, HealthFlow


def validate_record(record):
    return health_history.validate_record(record, HealthFlow.DAMAGE)


def validate_state(state, registry=None):
    health_history.checked_rows(state, HealthFlow.DAMAGE, registry)


def damage_records(state, *, source_player=None, target_player=None, target_kind=None,
                   turn=None, before_id=None, target_own_turn=False):
    """Complete original occurrences, including zero/prevented/converted packets."""
    return health_history.select_records(state, HealthFlow.DAMAGE, source_player=source_player,
        target_player=target_player, target_kind=target_kind, turn=turn, before_id=before_id,
        target_own_turn=target_own_turn)


def hero_damage_taken(state, player_id, *, own_turn_only=False, turn=None):
    """Actual received damage, including armor, using original target ownership."""
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Hero damage query requires an actual target player')
    return sum(row.health_result.damage_dealt for row in damage_records(state,
        target_player=player_id, target_kind=CardType.HERO, turn=turn, target_own_turn=own_turn_only))


def _source_card_damage(state, registry, player_id, kind, *, turn=None, before_id=None):
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Card damage query requires an actual source player')
    validate_state(state, registry)
    return sum(row.health_result.damage_dealt for row in damage_records(state,
        source_player=player_id, turn=turn, before_id=before_id)
        if row.health_result.source_card_id is not None and
        registry.card(row.health_result.source_card_id).kind is kind)


def hero_power_damage(state, registry, player_id, *, turn=None):
    """Actual units from captured HERO_POWER sources, regardless of current slot.

This finite direct-source policy does not invent credit for indirect cast or
summoned sources. Unknown positive attribution raises explicitly.
"""
    return _source_card_damage(state, registry, player_id, CardType.HERO_POWER, turn=turn)


def spell_damage_dealt(state, registry, player_id, *, turn=None, before_id=None):
    """Actual units attributed to the original SPELL face and controller.

Damage kind, number of casts and current source face cannot replace these
captured operands. Includes all targets and final converted damage; summoned
minions remain their own sources. The exclusive prefix supports original-window
consumers without an extra counter or damage executor.
"""
    return _source_card_damage(state, registry, player_id, CardType.SPELL,
                               turn=turn, before_id=before_id)


def rows_from_dict(value):
    health_history.rows_from_dict(value, HealthFlow.DAMAGE)


def record_from_dict(value):
    return health_history.record_from_dict(value, HealthFlow.DAMAGE)
