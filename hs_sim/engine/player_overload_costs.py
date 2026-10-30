"""One finite all-game price operand from actual overloaded crystal amounts."""
from .model import CardType, PlayerOverloadCostSpec, PlayerOverloadCostFact, _player_overload_quantity
from .overload_history import validate_state


def validate_definition(definition):
    spec = definition.player_overload_cost
    if spec is None: return
    if type(spec) is not PlayerOverloadCostSpec:
        raise ValueError('Expected PlayerOverloadCostSpec')
    spec.__post_init__()
    kind = CardType.SPELL if spec.profile_id == 'cost.player-current-overload-discount-v1' else CardType.MINION
    if definition.kind != kind or not definition.hand_playable or definition.starship_for:
        raise ValueError('Overload price belongs to an ordinary physical minion')
    if any(value is not None for value in (definition.board_minion_cost, definition.hand_count_cost,
            definition.hero_missing_health_cost, definition.player_spell_count_cost,
            definition.player_hero_power_count_cost, definition.player_spell_mana_cost, definition.minion_death_cost)):
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_overload_cost is None: return None
    validate_state(state)
    records = tuple(state.overload_history)
    spec = definition.player_overload_cost
    current = spec.profile_id == 'cost.player-current-overload-discount-v1'
    player = state.players[player_id]
    owed, locked = (player.overload_owed, player.overload_locked) if current else (None, None)
    quantity = _player_overload_quantity(spec, player_id, records, owed, locked)
    return PlayerOverloadCostFact(definition.player_overload_cost, player_id, state.turn, state.action_number,
        state.next_entity_id, state.next_overload_id, len(records), records,
        quantity, base_cost, max(0, base_cost - quantity), owed, locked)


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_overload_cost is None:
        if fact is not None: raise ValueError('A minion without overload pricing invented a crystal stage')
        return
    if type(fact) is not PlayerOverloadCostFact:
        raise ValueError('Overload price lost its complete original crystal history')
    fact.__post_init__()
    if fact.spec != definition.player_overload_cost:
        raise ValueError('Overload price changed its pinned declaration')


def validate_prefix(fact, state, registry):
    validate_state(state)
    if (fact.next_entity_id > state.next_entity_id or fact.next_overload_id > state.next_overload_id or
            fact.turn > state.turn or fact.action > state.action_number or
            fact.records != tuple(state.overload_history[:len(fact.records)])):
        raise ValueError('Overload price rewrote its complete actual crystal prefix')
