"""Finite tribe price consumers of the original successful summon history."""
from .model import CardType, PlayerSummonCountCostSpec, PlayerSummonCountCostFact
from .successful_summons import SuccessfulSummonRecord, _matching_rows, validate_state
from .tribes import tribe_state_for


def _tribes(spec):
    spec.__post_init__()
    return ('BEAST',) if spec.profile_id == 'cost.player-summoned-beast-count-v1' else ('TOTEM',)


def validate_definition(definition):
    spec = definition.player_summon_count_cost
    if spec is None:
        return
    if type(spec) is not PlayerSummonCountCostSpec:
        raise ValueError('Expected PlayerSummonCountCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Successful summon price belongs to an ordinary physical minion')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost,
            definition.player_weapon_attack_cost, definition.player_armor_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def validate_operand(fact):
    """Complete immutable original prefix; selection shares the original query."""
    if type(fact.records) is not tuple or any(type(r) is not SuccessfulSummonRecord for r in fact.records):
        raise ValueError('Summon price requires its complete immutable original prefix')
    if len(fact.records) + 1 != fact.next_successful_summon_id:
        raise ValueError('Summon price lost its complete occurrence cursor')
    last_turn = last_action = last_event = 0
    seen = set()
    for index, row in enumerate(fact.records, 1):
        row.__post_init__()
        allocation = row.minion
        identity = (row.entity_id, allocation.zone_epoch, allocation.entered_order)
        if (row.id != index or not last_turn <= row.turn <= fact.turn or
                not last_action <= row.action <= fact.action or row.event_sequence <= last_event or
                allocation.next_entity_id > fact.next_entity_id or allocation.next_order > fact.next_order or
                identity in seen):
            raise ValueError('Summon price changed its original physical allocation or chronology')
        seen.add(identity)
        last_turn, last_action, last_event = row.turn, row.action, row.event_sequence
    selected = tuple(row.id for row in _matching_rows(fact.records, fact.player_id, _tribes(fact.spec), 'current', None))
    if (fact.selected_ids != selected or fact.quantity != len(selected) or
            fact.after != max(0, fact.before - len(selected))):
        raise ValueError('Summon price differs from its complete original successful tribe quantity')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_summon_count_cost is None:
        return None
    validate_state(state, registry)
    records = tuple(state.successful_summon_history)
    selected = tuple(row.id for row in _matching_rows(records, player_id,
        _tribes(definition.player_summon_count_cost), 'current', None))
    fact = PlayerSummonCountCostFact(definition.player_summon_count_cost, player_id,
        state.turn, state.action_number, state.next_entity_id, state.next_order,
        state.next_successful_summon_id, records, selected, len(selected),
        base_cost, max(0, base_cost - len(selected)))
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_summon_count_cost is None:
        if fact is not None:
            raise ValueError('A minion without summon pricing invented an occurrence stage')
        return
    if type(fact) is not PlayerSummonCountCostFact:
        raise ValueError('Summon price lost its complete original success prefix')
    fact.__post_init__()
    if fact.spec != definition.player_summon_count_cost:
        raise ValueError('Summon price changed its pinned finite declaration')
    for row in fact.records:
        if (registry.card(row.card_id).kind != CardType.MINION or
                tribe_state_for(registry, row.card_id, basis='printed') != row.printed_tribes):
            raise ValueError('Summon price changed an original pinned minion or printed tribe set')


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    validate_state(state, registry)
    if (fact.turn > state.turn or fact.action > state.action_number or
            fact.next_entity_id > state.next_entity_id or fact.next_order > state.next_order or
            fact.next_successful_summon_id > state.next_successful_summon_id or
            fact.records != tuple(state.successful_summon_history[:len(fact.records)])):
        raise ValueError('Summon price rewrote its complete original success prefix')
