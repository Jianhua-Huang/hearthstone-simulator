"""One finite intrinsic price from actual received damage on all own turns."""
from .damage_history import damage_records, hero_damage_taken, validate_state
from .model import CardType, DamageRecord, HeroDamageTakenCostFact, HeroDamageTakenCostSpec


def contribution(result, spec, player_id, turn):
    if result.target_kind != CardType.HERO.value:
        return 0
    if spec.profile_id == 'cost.enemy-hero-current-turn-damage-count-v1':
        return int(result.target_controller == 3 - player_id and result.turn == turn and result.damage_dealt > 0)
    return result.damage_dealt if result.target_controller == player_id and result.active_player == player_id else 0


def validate_definition(definition):
    spec = definition.hero_damage_taken_cost
    if spec is None: return
    if type(spec) is not HeroDamageTakenCostSpec: raise ValueError('Expected HeroDamageTakenCostSpec')
    spec.__post_init__()
    from .stat_relations import validate_ordinary_face
    validate_ordinary_face(definition)
    if not definition.hand_playable:
        raise ValueError('Received-damage pricing requires a playable physical minion')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost,
            definition.player_weapon_attack_cost, definition.player_armor_cost, definition.player_summon_count_cost,
            definition.player_elemental_streak_cost, definition.player_corpse_spend_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def validate_operand(fact):
    if type(fact.records) is not tuple or fact.next_damage_id != len(fact.records) + 1:
        raise ValueError('Received-damage price lost its complete original packet prefix')
    last_turn = last_action = 0; last_packet = (0, 0); quantity = 0
    for index, row in enumerate(fact.records, 1):
        if type(row) is not DamageRecord: raise ValueError('Received-damage price requires typed original packets')
        row.__post_init__(); result = row.health_result
        packet = (result.batch_id, result.packet_index)
        if (row.id != index or not last_turn <= result.turn <= fact.turn or
                not last_action <= row.action <= fact.action or packet <= last_packet):
            raise ValueError('Received-damage price changed its original packet chronology')
        ids = (result.target_id, result.original_target_id, *result.redirect_path)
        if result.source_id is not None: ids += (result.source_id,)
        if result.weapon_id is not None: ids += (result.weapon_id,)
        orders = (result.target_entered_order, result.source_entered_order, result.weapon_entered_order)
        if any(identity >= fact.next_entity_id for identity in ids) or any(order is not None and order >= fact.next_order for order in orders):
            raise ValueError('Received-damage price borrowed a future physical allocation')
        quantity += contribution(result, fact.spec, fact.player_id, fact.turn)
        last_turn, last_action, last_packet = result.turn, row.action, packet
    if fact.quantity != quantity or fact.after != max(0, fact.before - quantity):
        raise ValueError('Received-damage price differs from its complete actual hero quantity')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.hero_damage_taken_cost is None: return None
    validate_state(state, registry)
    records = damage_records(state)
    quantity = sum(contribution(row.health_result, definition.hero_damage_taken_cost, player_id, state.turn)
                   for row in records)
    fact = HeroDamageTakenCostFact(definition.hero_damage_taken_cost, player_id, state.turn,
        state.action_number, state.next_entity_id, state.next_order, state.next_damage_id,
        records, quantity, base_cost, max(0, base_cost - quantity))
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.hero_damage_taken_cost is None:
        if fact is not None: raise ValueError('A minion without damage pricing invented a packet operand')
        return
    if type(fact) is not HeroDamageTakenCostFact:
        raise ValueError('Received-damage price lost its complete original packet prefix')
    fact.__post_init__()
    if fact.spec != definition.hero_damage_taken_cost:
        raise ValueError('Received-damage price changed its finite declaration')
    for row in fact.records:
        result = row.health_result
        if registry.card(result.target_card_id).kind.value != result.target_kind:
            raise ValueError('Received-damage price changed an original target kind')
        if result.source_card_id is not None: registry.card(result.source_card_id)


def validate_prefix(fact, state, registry):
    fact.__post_init__(); validate_state(state, registry)
    if (fact.turn > state.turn or fact.action > state.action_number or
            fact.next_entity_id > state.next_entity_id or fact.next_order > state.next_order or
            fact.next_damage_id > state.next_damage_id or
            fact.records != tuple(state.damage_history[:len(fact.records)]) or
            any(row.action < fact.action for row in state.damage_history[len(fact.records):])):
        raise ValueError('Received-damage price rewrote its complete original packet prefix')
