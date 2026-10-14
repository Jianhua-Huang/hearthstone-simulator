"""Finite consecutive own Elemental intervals, over the original frozen facts.

The open-unmatched interval policy is internal, pending CN calibration. This
module only queries and validates price operands; it does not advance turns,
record plays, cache streaks, or execute card effects.
"""
from types import SimpleNamespace

from .model import (CardType, OwnerTurnQueryBoundaryFact, OwnerTurnRecord,
                    PlayedTypeQuery, PlayerPlayedClassCostRow,
                    PlayerElementalStreakCostSpec, PlayerElementalStreakCostFact)
from .owner_turns import (_type_history_relation, _validate_history_input,
                          _validate_owner_interval_prefix, validate_history)
from .player_played_class_costs import _rows


ELEMENTAL = PlayedTypeQuery(CardType.MINION, ('elemental',))


def validate_definition(definition):
    spec = definition.player_elemental_streak_cost
    if spec is None:
        return
    if type(spec) is not PlayerElementalStreakCostSpec:
        raise ValueError('Expected a finite Elemental-streak price declaration')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Elemental-streak price belongs to an ordinary physical minion')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost,
            definition.player_draw_count_cost, definition.player_weapon_attack_cost,
            definition.player_armor_cost, definition.player_summon_count_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def _selected_intervals(owner_turns, faces, player_id):
    # Original matching checks all own candidates, including unknowns before a
    # break. It also preserves empty intervals and outside-own submissions.
    relation = _type_history_relation(owner_turns, faces, player_id, ELEMENTAL)
    intervals = relation.intervals
    if intervals and not intervals[-1].owner_turn.closed and not intervals[-1].matched:
        intervals = intervals[:-1]
    selected = []
    for interval in reversed(intervals):
        if not interval.matched:
            break
        selected.append(interval.owner_turn.id)
    return tuple(reversed(selected))


def consecutive_elemental_turn_count(state, player_id):
    """Read the finite v1 count without writes, allocation, events, or RNG."""
    from .owner_turns import _validate_type_query
    _validate_type_query(state, player_id, ELEMENTAL)
    return len(_selected_intervals(state.owner_turn_history,
        tuple(play.played_face for play in state.play_history), player_id))


def _original_view(fact):
    """Private projection of saved original metadata for the shared validator.

    No fake GameState, live zones, submitted receipts, or second turn ledger.
    Avoid nesting old paid receipts recursively inside each new price fact.
    """
    boundary = fact.boundary
    return SimpleNamespace(owner_turn_history=list(fact.owner_turns),
        play_history=[SimpleNamespace(played_face=row.face, id=row.face.play_id,
            source_id=row.face.source_id, player_id=row.face.player_id,
            card_id=row.face.card_id, kind=row.face.kind, turn=row.turn, action=row.action)
            for row in fact.rows], turn=fact.turn, action_number=fact.action,
        status=boundary.status, active_player=(fact.owner_turns[-1].player_id
            if fact.owner_turns else boundary.opening_first_player),
        opening=(None if boundary.opening_stage is None else
            SimpleNamespace(stage=boundary.opening_stage, first_player=boundary.opening_first_player)))


def validate_operand(fact):
    if type(fact.boundary) is not OwnerTurnQueryBoundaryFact:
        raise ValueError('Elemental price lost its original quotation boundary')
    fact.boundary.__post_init__()
    if type(fact.owner_turns) is not tuple or any(type(r) is not OwnerTurnRecord for r in fact.owner_turns):
        raise ValueError('Elemental price requires every original owner interval')
    if type(fact.rows) is not tuple or any(type(r) is not PlayerPlayedClassCostRow for r in fact.rows):
        raise ValueError('Elemental price requires every original physical submission')
    boundary = fact.boundary
    if ((fact.turn, fact.action, len(fact.owner_turns), len(fact.rows)) !=
            (boundary.turn, boundary.action, boundary.owner_history_length, boundary.play_history_length) or
            (fact.owner_turns[-1] if fact.owner_turns else None) != boundary.last_owner_turn):
        raise ValueError('Elemental price changed its complete original window')
    last_turn = last_action = 0
    for index, row in enumerate(fact.rows, 1):
        row.__post_init__()
        if (row.face.play_id != index or row.face.source_id >= fact.next_entity_id or
                not last_turn <= row.turn <= fact.turn or not last_action <= row.action <= fact.action):
            raise ValueError('Elemental price changed its ordered original allocation or chronology')
        last_turn, last_action = row.turn, row.action
    _validate_history_input(_original_view(fact))
    selected = _selected_intervals(fact.owner_turns, tuple(row.face for row in fact.rows), fact.player_id)
    if (type(fact.selected_interval_ids) is not tuple or
            any(type(i) is not int for i in fact.selected_interval_ids) or
            fact.selected_interval_ids != selected or fact.quantity != len(selected) or
            fact.after != max(0, fact.before - len(selected))):
        raise ValueError('Elemental price differs from its complete original consecutive interval count')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_elemental_streak_cost is None:
        return None
    validate_history(state, registry)
    rows = _rows(state, registry)
    owner_turns = tuple(state.owner_turn_history)
    selected = _selected_intervals(owner_turns, tuple(row.face for row in rows), player_id)
    boundary = OwnerTurnQueryBoundaryFact(state.turn, state.action_number, state.status,
        len(owner_turns), len(rows), owner_turns[-1] if owner_turns else None,
        None if state.opening is None else state.opening.stage,
        None if state.opening is None else state.opening.first_player)
    return PlayerElementalStreakCostFact(definition.player_elemental_streak_cost, player_id,
        state.turn, state.action_number, state.next_entity_id, boundary, owner_turns,
        rows, selected, len(selected), base_cost, max(0, base_cost-len(selected)))


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_elemental_streak_cost is None:
        if fact is not None:
            raise ValueError('A minion without Elemental pricing invented a streak operand')
        return
    if type(fact) is not PlayerElementalStreakCostFact:
        raise ValueError('Elemental price lost its complete original prefix')
    fact.__post_init__()
    if fact.spec != definition.player_elemental_streak_cost:
        raise ValueError('Elemental price changed its pinned finite declaration')
    _validate_history_input(_original_view(fact), registry)


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    validate_history(state, registry)
    rows = _rows(state, registry)
    if (fact.turn > state.turn or fact.action > state.action_number or
            fact.next_entity_id > state.next_entity_id or len(fact.owner_turns) > len(state.owner_turn_history) or
            len(fact.rows) > len(rows) or fact.rows != rows[:len(fact.rows)]):
        raise ValueError('Elemental price rewrote its complete original submission prefix')
    _validate_owner_interval_prefix(fact.owner_turns, state.owner_turn_history, fact.action)
