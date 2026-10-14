"""Two real finite prices from current Armor, using original hero/allocation."""
from enum import Enum

from .allocation_facts import SourceAllocationFact, allocation_from_payload, validate_allocation
from .model import CardType, PlayerArmorCostFact, PlayerArmorCostSpec, Zone


def validate_definition(definition):
    spec = definition.player_armor_cost
    if spec is None:
        return
    if type(spec) is not PlayerArmorCostSpec:
        raise ValueError('Expected PlayerArmorCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.SPELL or not definition.hand_playable:
        raise ValueError('Current Armor price belongs to an ordinary physical Spell')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost,
            definition.player_weapon_attack_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    spec = definition.player_armor_cost
    if spec is None:
        return None
    hero = state.entities.get(state.players[player_id].hero_id)
    if hero is None or (hero.kind, hero.zone, hero.owner, hero.controller) != (
            CardType.HERO, Zone.HERO, player_id, player_id):
        raise ValueError('Armor price requires its actual current payer hero')
    if registry.card(hero.card_id).kind != CardType.HERO:
        raise ValueError('Armor price requires a supported original hero face')
    allocation = tuple((key, value.value if isinstance(value, Enum) else value)
                       for key, value in SourceAllocationFact.capture(state, hero).payload())
    after = (max(0, base_cost-hero.armor) if spec.profile_id == 'cost.player-current-hero-armor-v1'
             else 0 if hero.armor == 0 else base_cost)
    fact = PlayerArmorCostFact(spec, player_id, state.turn, state.action_number,
        state.next_entity_id, state.next_order, allocation, hero.armor, hero.armor, base_cost, after)
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_armor_cost is None:
        if fact is not None:
            raise ValueError('A Spell without Armor pricing invented a hero stage')
        return
    if type(fact) is not PlayerArmorCostFact:
        raise ValueError('Armor price lost its complete original hero fact')
    fact.__post_init__()
    if fact.spec != definition.player_armor_cost:
        raise ValueError('Armor price changed its pinned declaration')
    if registry.card(allocation_from_payload(fact.hero_allocation).card_id).kind != CardType.HERO:
        raise ValueError('Armor price changed its original hero face')


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    if (fact.next_entity_id > state.next_entity_id or fact.next_order > state.next_order or
            fact.turn > state.turn or fact.action > state.action_number):
        raise ValueError('Armor price lost its original physical allocation or time window')
    validate_allocation(state, registry, allocation_from_payload(fact.hero_allocation))
