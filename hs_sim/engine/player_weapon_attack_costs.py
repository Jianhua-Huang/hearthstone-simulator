"""Pure current weapon Attack pricing, using original equipment and allocation."""
from enum import Enum

from .allocation_facts import SourceAllocationFact, allocation_from_payload, validate_allocation
from .equipment import equipped_weapon
from .model import CardType, PlayerWeaponAttackCostFact, PlayerWeaponAttackCostSpec, Zone


def validate_definition(definition):
    spec = definition.player_weapon_attack_cost
    if spec is None:
        return
    if type(spec) is not PlayerWeaponAttackCostSpec:
        raise ValueError('Expected PlayerWeaponAttackCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Equipped weapon Attack price belongs to an ordinary physical minion')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    spec = definition.player_weapon_attack_cost
    if spec is None:
        return None
    player = state.players[player_id]
    raw = None if player.weapon_id is None else state.entities.get(player.weapon_id)
    if player.weapon_id is not None and raw is None:
        raise ValueError('Weapon price lost its original equipment slot')
    if raw is None:
        allocation = attack = durability = doomed = None
    else:
        if (raw.kind, raw.zone, raw.controller) != (CardType.WEAPON, Zone.WEAPON, player_id):
            raise ValueError('Weapon price requires its actual payer equipment identity')
        if registry.card(raw.card_id).kind != CardType.WEAPON:
            raise ValueError('Weapon price requires a supported original weapon face')
        allocation = tuple((key, value.value if isinstance(value, Enum) else value)
                           for key, value in SourceAllocationFact.capture(state, raw).payload())
        attack, durability, doomed = raw.attack, raw.durability, raw.doomed
    live = equipped_weapon(state, player)
    quantity = 0 if live is None else live.attack
    fact = PlayerWeaponAttackCostFact(spec, player_id, state.turn, state.action_number,
        state.next_entity_id, state.next_order, allocation, attack, durability, doomed,
        quantity, base_cost, max(0, base_cost - quantity))
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_weapon_attack_cost is None:
        if fact is not None:
            raise ValueError('A minion without weapon pricing invented an equipment stage')
        return
    if type(fact) is not PlayerWeaponAttackCostFact:
        raise ValueError('Weapon price lost its complete original equipment fact')
    fact.__post_init__()
    if fact.spec != definition.player_weapon_attack_cost:
        raise ValueError('Weapon price changed its pinned declaration')
    if fact.weapon_allocation is not None:
        allocation = allocation_from_payload(fact.weapon_allocation)
        if registry.card(allocation.card_id).kind != CardType.WEAPON:
            raise ValueError('Weapon price changed its original weapon face')


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    if (fact.next_entity_id > state.next_entity_id or fact.next_order > state.next_order or
            fact.turn > state.turn or fact.action > state.action_number):
        raise ValueError('Weapon price lost its original physical allocation or time window')
    if fact.weapon_allocation is not None:
        validate_allocation(state, registry, allocation_from_payload(fact.weapon_allocation))
