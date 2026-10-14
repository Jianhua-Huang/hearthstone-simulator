"""One finite price from complete original character attack declarations."""
from dataclasses import replace
from .character_attacks import character_attack_count, validate_history
from .model import (CardType, CharacterAttackRecord, PlayerCharacterAttackCostSpec,
                    PlayerCharacterAttackCostFact)


def validate_definition(definition):
    spec = definition.player_character_attack_cost
    if spec is None:
        return
    if type(spec) is not PlayerCharacterAttackCostSpec:
        raise ValueError('Expected PlayerCharacterAttackCostSpec')
    spec.__post_init__()
    if definition.kind is not CardType.SPELL or not definition.hand_playable or definition.starship_for:
        raise ValueError('Character declaration pricing requires an ordinary physical Spell')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost,
            definition.player_weapon_attack_cost, definition.player_armor_cost, definition.player_summon_count_cost,
            definition.player_elemental_streak_cost, definition.player_corpse_spend_cost,
            definition.hero_damage_taken_cost, definition.player_spell_damage_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def declaration_for(record):
    return replace(record, delivery=None, delivery_action=None, delivery_event_cursor=None,
                   combat=None, terminal=None)


def validate_operand(fact):
    if type(fact.records) is not tuple:
        raise ValueError('Character declaration price requires its immutable complete prefix')
    previous = action = turn = quantity = 0
    for record in fact.records:
        if type(record) is not CharacterAttackRecord:
            raise ValueError('Character declaration price requires original typed rows')
        record.__post_init__()
        w = record.declaration
        if declaration_for(record) != record:
            raise ValueError('Declaration-only price cannot carry later attack phases')
        if (not previous < w.id < fact.next_window_id or not action <= record.declaration_action <= fact.action or
                not turn <= record.turn <= fact.turn or record.source_entered_order >= fact.next_order or
                w.source_id >= fact.next_entity_id or w.target_id >= fact.next_entity_id):
            raise ValueError('Character price lost its original allocation or chronology')
        quantity += w.player_id == fact.player_id
        previous, action, turn = w.id, record.declaration_action, record.turn
    if fact.quantity != quantity or fact.after != max(0, fact.before - quantity):
        raise ValueError('Character price differs from its original declaration count')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_character_attack_cost is None:
        return None
    validate_history(state, registry)
    records = tuple(declaration_for(row) for row in state.character_attack_history)
    quantity = character_attack_count(state, player_id, phase='declared')
    return PlayerCharacterAttackCostFact(definition.player_character_attack_cost, player_id,
        state.turn, state.action_number, state.next_entity_id, state.next_order, state.next_window_id,
        records, quantity, base_cost, max(0, base_cost - quantity))


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_character_attack_cost is None:
        if fact is not None:
            raise ValueError('A card without character pricing invented a declaration prefix')
        return
    if type(fact) is not PlayerCharacterAttackCostFact:
        raise ValueError('Character declaration price lost its complete original prefix')
    fact.__post_init__()
    if fact.spec != definition.player_character_attack_cost:
        raise ValueError('Character declaration price changed its original policy')
    for row in fact.records:
        if registry.card(row.source_card_id).kind is not row.source_kind:
            raise ValueError('Character declaration price changed an original source kind')


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    validate_history(state, registry)
    original = tuple(declaration_for(row) for row in state.character_attack_history
                     if row.declaration.id < fact.next_window_id)
    if (fact.turn > state.turn or fact.action > state.action_number or
            fact.next_entity_id > state.next_entity_id or fact.next_order > state.next_order or
            fact.next_window_id > state.next_window_id or fact.records != original or
            any(row.declaration_action < fact.action for row in state.character_attack_history[len(fact.records):])):
        raise ValueError('Character declaration price rewrote its complete original prefix')
