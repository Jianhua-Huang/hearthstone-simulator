"""One finite intrinsic price from actual own-turn hero health occurrences."""
from .hero_health_history import health_change_count, validate_state
from .model import CardType, HeroHealthChangeCostFact, HeroHealthChangeCostSpec


def validate_definition(definition):
    spec = definition.hero_health_change_cost
    if spec is None:
        return
    if type(spec) is not HeroHealthChangeCostSpec:
        raise ValueError('Expected HeroHealthChangeCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Health-change price belongs to an ordinary physical minion')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost,
            definition.player_overload_cost, definition.player_played_class_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.hero_health_change_cost is None:
        return None
    quantity = health_change_count(state, player_id)
    records = tuple(state.hero_health_change_history)
    fact = HeroHealthChangeCostFact(definition.hero_health_change_cost, player_id, state.turn,
        state.action_number, state.next_entity_id, state.next_hero_health_change_id, len(records),
        records, quantity, base_cost, max(0, base_cost - quantity))
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.hero_health_change_cost is None:
        if fact is not None:
            raise ValueError('A minion without health-change pricing invented an occurrence stage')
        return
    if type(fact) is not HeroHealthChangeCostFact:
        raise ValueError('Health-change price lost its complete original occurrence history')
    fact.__post_init__()
    if fact.spec != definition.hero_health_change_cost:
        raise ValueError('Health-change price changed its pinned declaration')
    for row in fact.records:
        for card in (row.old_hero_card_id, row.hero_card_id):
            if registry.card(card).kind != CardType.HERO:
                raise ValueError('Health-change price changed an original hero face')


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    validate_state(state, registry)
    if (fact.next_entity_id > state.next_entity_id or
            fact.next_hero_health_change_id > state.next_hero_health_change_id or
            fact.turn > state.turn or fact.action > state.action_number or
            fact.records != tuple(state.hero_health_change_history[:fact.health_history_length])):
        raise ValueError('Health-change price rewrote its complete actual occurrence prefix')
