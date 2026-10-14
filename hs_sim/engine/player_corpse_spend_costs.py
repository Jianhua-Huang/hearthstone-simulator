"""One pure all-game price operand from actual successful corpse debits."""
from .model import CardType, CorpseSpendRecord, PlayerCorpseSpendCostSpec, PlayerCorpseSpendCostFact
from .resources import spent_corpses, validate_corpse_spend_history


def validate_definition(definition):
    spec = definition.player_corpse_spend_cost
    if spec is None:
        return
    if type(spec) is not PlayerCorpseSpendCostSpec:
        raise ValueError('Expected PlayerCorpseSpendCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Corpse-spend price belongs to an ordinary physical minion')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost,
            definition.player_weapon_attack_cost, definition.player_armor_cost, definition.player_summon_count_cost,
            definition.player_elemental_streak_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def validate_operand(fact):
    if type(fact.records) is not tuple or any(type(row) is not CorpseSpendRecord for row in fact.records):
        raise ValueError('Corpse price requires its complete immutable original debit prefix')
    if len(fact.records) != fact.corpse_spend_history_length:
        raise ValueError('Corpse price lost an original successful debit')
    last_turn = last_action = last_operation = 0
    for index, row in enumerate(fact.records, 1):
        row.__post_init__()
        if (row.id != index or not last_turn <= row.turn <= fact.turn or
                not last_action <= row.action <= fact.action or
                row.source_id is not None and row.source_id >= fact.next_entity_id):
            raise ValueError('Corpse price changed its original debit chronology or source bound')
        if row.operation_id is not None:
            if not last_operation < row.operation_id < fact.next_resource_operation_id:
                raise ValueError('Corpse price borrowed an unknown or repeated capped operation')
            last_operation = row.operation_id
        last_turn, last_action = row.turn, row.action
    quantity = sum(row.amount for row in fact.records if row.player_id == fact.player_id)
    if fact.quantity != quantity or fact.after != max(0, fact.before - quantity):
        raise ValueError('Corpse price differs from complete actual successful units')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_corpse_spend_cost is None:
        return None
    validate_corpse_spend_history(state, registry)
    records = tuple(state.corpse_spend_history)
    quantity = spent_corpses(state, player_id)
    fact = PlayerCorpseSpendCostFact(definition.player_corpse_spend_cost, player_id,
        state.turn, state.action_number, state.next_entity_id, state.next_resource_operation_id,
        len(records), records, quantity, base_cost, max(0, base_cost - quantity))
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_corpse_spend_cost is None:
        if fact is not None:
            raise ValueError('A minion without corpse pricing invented a debit stage')
        return
    if type(fact) is not PlayerCorpseSpendCostFact:
        raise ValueError('Corpse price lost its complete original debit prefix')
    fact.__post_init__()
    if fact.spec != definition.player_corpse_spend_cost:
        raise ValueError('Corpse price changed its pinned finite declaration')
    for row in fact.records:
        if row.source_card_id is not None:
            registry.card(row.source_card_id)


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    validate_corpse_spend_history(state, registry)
    if (fact.turn > state.turn or fact.action > state.action_number or
            fact.next_entity_id > state.next_entity_id or
            fact.next_resource_operation_id > state.next_resource_operation_id or
            fact.records != tuple(state.corpse_spend_history[:len(fact.records)])):
        raise ValueError('Corpse price rewrote its complete original successful debit prefix')
