"""Current-turn actual spell damage prices over the original settled ledger."""
from .damage_history import damage_records, spell_damage_dealt, validate_state
from .model import (CardType, DamageKind, PlayerSpellDamageCostSpec,
                    PlayerSpellDamageCostRow, PlayerSpellDamageCostFact)


def validate_definition(definition):
    spec = definition.player_spell_damage_cost
    if spec is None:
        return
    if type(spec) is not PlayerSpellDamageCostSpec:
        raise ValueError('Expected PlayerSpellDamageCostSpec')
    spec.__post_init__()
    if definition.kind is not CardType.SPELL or not definition.hand_playable or definition.starship_for:
        raise ValueError('Current-turn spell damage pricing requires an ordinary physical Spell')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost,
            definition.player_weapon_attack_cost, definition.player_armor_cost, definition.player_summon_count_cost,
            definition.player_elemental_streak_cost, definition.player_corpse_spend_cost,
            definition.hero_damage_taken_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def row_for(record, registry):
    cid = record.health_result.source_card_id
    return PlayerSpellDamageCostRow(record, None if cid is None else registry.card(cid).kind)


def validate_operand(fact):
    if type(fact.rows) is not tuple or fact.next_damage_id != len(fact.rows) + 1:
        raise ValueError('Spell damage price lost its complete original packet prefix')
    last_turn = last_action = 0
    last_packet = (0, 0)
    quantity = 0
    for index, row in enumerate(fact.rows, 1):
        if type(row) is not PlayerSpellDamageCostRow:
            raise ValueError('Spell damage price requires typed original rows')
        row.__post_init__()
        record = row.record
        result = record.health_result
        packet = (result.batch_id, result.packet_index)
        if (record.id != index or not last_turn <= result.turn <= fact.turn or
                not last_action <= record.action <= fact.action or packet <= last_packet):
            raise ValueError('Spell damage price changed its original chronology')
        ids = (result.target_id, result.original_target_id, *result.redirect_path)
        if result.source_id is not None:
            ids += (result.source_id,)
        if result.weapon_id is not None:
            ids += (result.weapon_id,)
        orders = (result.target_entered_order, result.source_entered_order, result.weapon_entered_order)
        if (any(identity >= fact.next_entity_id for identity in ids) or
                any(order is not None and order >= fact.next_order for order in orders)):
            raise ValueError('Spell damage price borrowed a future physical allocation')
        if result.turn == fact.turn:
            if (result.source_controller is None and result.damage_dealt > 0 and
                    result.damage_kind != DamageKind.FATIGUE.value):
                from .registry import UnsupportedDefinitionError
                raise UnsupportedDefinitionError('Actual spell damage price has unknown original source controller')
            if result.source_controller == fact.player_id and row.source_kind is CardType.SPELL:
                quantity += result.damage_dealt
        last_turn, last_action, last_packet = result.turn, record.action, packet
    if fact.quantity != quantity or fact.after != max(0, fact.before - quantity):
        raise ValueError('Spell damage price differs from actual original current-turn units')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_spell_damage_cost is None:
        return None
    validate_state(state, registry)
    rows = tuple(row_for(record, registry) for record in damage_records(state))
    quantity = spell_damage_dealt(state, registry, player_id, turn=state.turn)
    fact = PlayerSpellDamageCostFact(definition.player_spell_damage_cost, player_id, state.turn,
        state.action_number, state.next_entity_id, state.next_order, state.next_damage_id,
        rows, quantity, base_cost, max(0, base_cost - quantity))
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_spell_damage_cost is None:
        if fact is not None:
            raise ValueError('A card without spell damage pricing invented a packet operand')
        return
    if type(fact) is not PlayerSpellDamageCostFact:
        raise ValueError('Spell damage price lost its complete original packet prefix')
    fact.__post_init__()
    if fact.spec != definition.player_spell_damage_cost:
        raise ValueError('Spell damage price changed its finite declaration')
    for row in fact.rows:
        result = row.record.health_result
        if registry.card(result.target_card_id).kind.value != result.target_kind:
            raise ValueError('Spell damage price changed an original target kind')
        if row != row_for(row.record, registry):
            raise ValueError('Spell damage price rewrote an original source kind')


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    validate_state(state, registry)
    if (fact.turn > state.turn or fact.action > state.action_number or
            fact.next_entity_id > state.next_entity_id or fact.next_order > state.next_order or
            fact.next_damage_id > state.next_damage_id or
            tuple(row.record for row in fact.rows) != tuple(state.damage_history[:len(fact.rows)]) or
            any(row.action < fact.action for row in state.damage_history[len(fact.rows):])):
        raise ValueError('Spell damage price rewrote its complete original packet prefix')
