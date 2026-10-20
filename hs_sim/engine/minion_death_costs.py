"""Finite death quantity prices using existing physical deaths and pure queries."""
from .model import (CardType, DeathRecord, MinionDeathCostSpec, MinionDeathCostFact,
                    Zone, validate_composition)


def validate_definition(definition):
    spec = definition.minion_death_cost
    if spec is None: return
    if type(spec) is not MinionDeathCostSpec:
        raise ValueError('Expected MinionDeathCostSpec')
    spec.__post_init__()
    if definition.kind not in (CardType.MINION, CardType.SPELL) or not definition.hand_playable or definition.starship_for:
        raise ValueError('Death quantity cost belongs to an ordinary physical minion or spell')
    if definition.kind == CardType.SPELL and definition.intrinsic_costs:
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')
    if any(value is not None for value in (definition.board_minion_cost, definition.hand_count_cost,
            definition.hero_missing_health_cost, definition.player_spell_count_cost,
            definition.player_hero_power_count_cost, definition.player_spell_mana_cost)):
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def selected_ids(registry, player_id, spec, turn, records):
    from .summon_sources import DeathQuery, death_query_candidates
    spec.__post_init__()
    if spec.profile_id == 'cost.minion-deaths-friendly-game-v1':
        query = DeathQuery()
    else:
        query = DeathQuery(side='both' if spec.profile_id == 'cost.minion-deaths-both-turn-v1' else 'friendly',
            min_turn=turn, max_turn=turn)
    return tuple(row.id for row in death_query_candidates(registry, player_id, query, records, None))


def _validate_faces(registry, records):
    for row in records:
        row.__post_init__()
        face = registry.card(row.card_id)
        kinds = {Zone.BOARD: (CardType.MINION, CardType.LOCATION),
                 Zone.WEAPON: (CardType.WEAPON,), Zone.HERO: (CardType.HERO,)}
        if face.kind not in kinds[row.zone]:
            raise ValueError('Death price changed an original destruction type or zone')
        validate_composition(row, registry)
        cause = row.cause
        registry.card(cause.target_card_id)
        if cause.source_id is not None: registry.card(cause.source_card_id)
        result = cause.health_result
        if result is not None and result.target_kind != face.kind.value:
            raise ValueError('Death price changed the original fatal target kind')


def _records(state, registry):
    from .death_causes import validate_in_state
    if type(state.death_history) is not list or any(type(row) is not DeathRecord for row in state.death_history):
        raise ValueError('Death price requires the complete original physical destruction ledger')
    records = tuple(state.death_history)
    _validate_faces(registry, records)
    for row in records:
        if row.entity_id not in state.entities or row.turn > state.turn:
            raise ValueError('Death price has a missing original entity or future death')
        validate_in_state(state, registry, row.cause)
    return records


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.minion_death_cost is None: return None
    records = _records(state, registry)
    selected = selected_ids(registry, player_id, definition.minion_death_cost, state.turn, records)
    quantity = len(selected)
    return MinionDeathCostFact(definition.minion_death_cost, player_id, state.turn,
        state.next_entity_id, state.next_attachment_id, state.next_order,
        state.next_death_id, state.next_death_batch, len(records), records,
        selected, quantity, base_cost, definition.minion_death_cost.price(base_cost, quantity))


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.minion_death_cost is None:
        if fact is not None: raise ValueError('A card without death pricing invented an occurrence stage')
        return
    if type(fact) is not MinionDeathCostFact:
        raise ValueError('Death price lost its complete original history')
    fact.__post_init__()
    if fact.spec != definition.minion_death_cost:
        raise ValueError('Death price changed its pinned declaration')
    _validate_faces(registry, fact.records)
    if selected_ids(registry, fact.player_id, fact.spec, fact.turn, fact.records) != fact.selected_ids:
        raise ValueError('Death price changed its complete original minion selection')


def validate_prefix(fact, state, registry):
    records = _records(state, registry)
    if (any(getattr(fact, name) > getattr(state, name) for name in (
            'next_entity_id', 'next_attachment_id', 'next_order', 'next_death_id', 'next_death_batch')) or
            len(fact.records) > len(records) or fact.records != records[:len(fact.records)]):
        raise ValueError('Death price rewrote its complete original physical destruction prefix')
