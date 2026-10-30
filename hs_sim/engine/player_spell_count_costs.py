"""Finite personal root, Fel and distinct-school prices from the cast ledger."""
from dataclasses import fields, replace

from .model import (CardType, PlayerSpellCountCostSpec, PlayerSpellCountCostRow,
                    PlayerSpellCountCostFact, _player_spell_count_quantity)


def validate_definition(definition):
    spec = definition.player_spell_count_cost
    if spec is None:
        return
    if type(spec) is not PlayerSpellCountCostSpec:
        raise ValueError('Expected PlayerSpellCountCostSpec')
    spec.__post_init__()
    kind = (CardType.SPELL if spec.profile_id in ('cost.player-distinct-spell-school-count-v1',
                                               'cost.player-distinct-school-cast-count-v1',
                                               'cost.player-turn-nature-cast-count-v1')
            else CardType.MINION)
    if definition.kind != kind or not definition.hand_playable or definition.starship_for:
        raise ValueError('Personal spell count requires the ordinary physical type of its finite policy')
    if any(value is not None for value in (definition.board_minion_cost,
            definition.hand_count_cost, definition.hero_missing_health_cost)):
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def row_for(record, registry):
    return PlayerSpellCountCostRow(**{field.name: getattr(record, field.name)
                                    for field in fields(PlayerSpellCountCostRow) if field.name != 'spell_school'},
                                  spell_school=registry.card(record.card_id).spell_school)


def count_distinct_cast_schools(state, registry, player_id):
    """Use the same finite started/nonfailed CAST policy without pricing a card."""
    from .effects import _player
    from .spell_casts import validate_history
    _player(player_id)
    validate_history(state, registry)
    spec = PlayerSpellCountCostSpec('cost.player-distinct-school-cast-count-v1')
    return _player_spell_count_quantity(spec, player_id,
        tuple(row_for(record, registry) for record in state.cast_history))


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    spec = definition.player_spell_count_cost
    if spec is None:
        return None
    from .spell_casts import validate_history
    validate_history(state, registry)
    rows = tuple(row_for(record, registry) for record in state.cast_history)
    turn = state.turn if spec.profile_id == 'cost.player-turn-nature-cast-count-v1' else None
    quantity = _player_spell_count_quantity(spec, player_id, rows, turn)
    return PlayerSpellCountCostFact(spec, player_id, state.next_entity_id,
        len(rows), rows, quantity, base_cost, max(0, base_cost - quantity), turn)


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_spell_count_cost is None:
        if fact is not None:
            raise ValueError('A minion without personal spell pricing invented a count stage')
        return
    if type(fact) is not PlayerSpellCountCostFact:
        raise ValueError('Personal spell price lost its complete original prefix')
    fact.__post_init__()
    if fact.spec != definition.player_spell_count_cost:
        raise ValueError('Personal spell price changed its pinned declaration')
    for row in fact.rows:
        original = registry.card(row.card_id)
        if original.kind != CardType.SPELL:
            raise ValueError('Personal spell price contains an unsupported original spell face')
        if row.spell_school != original.spell_school:
            raise ValueError('Personal spell price rewrote an original declared school')


def validate_prefix(fact, state, registry, *, _within_cast_history_check=False):
    from .spell_casts import validate_history
    if type(_within_cast_history_check) is not bool:
        raise ValueError('Cast history validation context requires a boolean')
    # The outer history validator still checks every CAST and source receipt.
    # Re-entering it from that receipt's own prefix would be a dependency cycle.
    if not _within_cast_history_check:
        validate_history(state, registry)
    if fact.turn is not None and fact.turn > state.turn:
        raise ValueError('Turn Nature price borrowed a future quotation turn')
    if fact.next_entity_id > state.next_entity_id or len(fact.rows) > len(state.cast_history):
        raise ValueError('Personal spell price lost its complete original allocation prefix')
    for old, current in zip(fact.rows, state.cast_history):
        new = row_for(current, registry)
        # Completion/interruption is not a counting operand. A pending automatic
        # cast can accept its payload later; immutable identity and failed results
        # still cannot change. An already accepted payload cannot be withdrawn.
        if old.payload_started and not new.payload_started or replace(old, payload_started=new.payload_started) != new:
            raise ValueError('Personal spell price rewrote its original physical cast prefix')
