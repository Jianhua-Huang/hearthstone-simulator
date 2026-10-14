"""Finite all-game manual hero power quantity from the original activation ledger."""
from dataclasses import fields

from .model import (CardType, PlayerHeroPowerCountCostSpec, PlayerHeroPowerCountCostRow,
                    PlayerHeroPowerCountCostFact)


def validate_definition(definition):
    spec = definition.player_hero_power_count_cost
    if spec is None:
        return
    if type(spec) is not PlayerHeroPowerCountCostSpec:
        raise ValueError('Expected PlayerHeroPowerCountCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Personal power count belongs to an ordinary physical minion')
    if any(value is not None for value in (definition.board_minion_cost, definition.hand_count_cost,
            definition.hero_missing_health_cost, definition.player_spell_count_cost)):
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def row_for(record):
    return PlayerHeroPowerCountCostRow(**{field.name: getattr(record, field.name)
                                        for field in fields(PlayerHeroPowerCountCostRow)})


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_hero_power_count_cost is None:
        return None
    from .hero_powers import validate_history
    validate_history(state, registry)
    rows = tuple(row_for(record) for record in state.hero_power_history)
    quantity = sum(row.counts_for(player_id) for row in rows)
    return PlayerHeroPowerCountCostFact(definition.player_hero_power_count_cost, player_id,
        state.next_entity_id, len(rows), rows, quantity, base_cost, max(0, base_cost - quantity))


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_hero_power_count_cost is None:
        if fact is not None:
            raise ValueError('A minion without personal power pricing invented a count stage')
        return
    if type(fact) is not PlayerHeroPowerCountCostFact:
        raise ValueError('Personal power price lost its complete original prefix')
    fact.__post_init__()
    if fact.spec != definition.player_hero_power_count_cost:
        raise ValueError('Personal power price changed its pinned declaration')
    for row in fact.rows:
        face = registry.card(row.card_id)
        if face.kind != CardType.HERO_POWER:
            raise ValueError('Personal power price contains an unsupported original power face')
        if row.failure != 'disabled' and (row.failure == 'passive') != face.passive_hero_power:
            raise ValueError('Personal power price changed the original passive activation policy')


def validate_prefix(fact, state, registry):
    from .hero_powers import validate_history
    validate_history(state, registry)
    if fact.next_entity_id > state.next_entity_id or len(fact.rows) > len(state.hero_power_history):
        raise ValueError('Personal power price lost its complete original allocation prefix')
    # Completion and interruption may progress; neither contributes to this
    # original-use policy. Every identity, origin, payment and failed result is fixed.
    if any(old != row_for(current) for old, current in zip(fact.rows, state.hero_power_history)):
        raise ValueError('Personal power price rewrote its original physical activation prefix')
