"""Finite all-game/current-turn price consumers of original physical draws."""
from dataclasses import replace

from .draw_casts import drawn_cards, validate_history
from .model import CardType, PlayerDrawCountCostFact, PlayerDrawCountCostSpec


def validate_definition(definition):
    spec = definition.player_draw_count_cost
    if spec is None:
        return
    if type(spec) is not PlayerDrawCountCostSpec:
        raise ValueError('Expected PlayerDrawCountCostSpec')
    spec.__post_init__()
    if definition.kind not in (CardType.MINION, CardType.SPELL) or not definition.hand_playable or definition.starship_for:
        raise ValueError('Physical draw price belongs to an ordinary physical minion or spell')
    if definition.intrinsic_costs or any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost,
            definition.player_overload_cost, definition.player_played_class_cost, definition.hero_health_change_cost)):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_draw_count_cost is None:
        return None
    validate_history(state, registry)
    turn = state.turn if definition.player_draw_count_cost.profile_id == 'cost.player-physical-draw-count-turn-v1' else None
    selected = tuple(row.id for row in drawn_cards(state, player_id, turn=turn) if row.outcome != 'fatigue')
    fact = PlayerDrawCountCostFact(definition.player_draw_count_cost, player_id, state.turn,
        state.action_number, state.next_entity_id, len(state.cast_history), len(state.draw_history),
        tuple(state.draw_history), selected, len(selected), base_cost, max(0, base_cost - len(selected)))
    validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_draw_count_cost is None:
        if fact is not None:
            raise ValueError('A card without draw pricing invented a physical draw stage')
        return
    if type(fact) is not PlayerDrawCountCostFact:
        raise ValueError('Draw price lost its complete original attempt prefix')
    fact.__post_init__()
    if fact.spec != definition.player_draw_count_cost:
        raise ValueError('Draw price changed its pinned finite declaration')
    for row in fact.records:
        if row.card_id is not None:
            face = registry.card(row.card_id)
            if row.outcome == 'cast' and (face.kind != CardType.SPELL or row.cast_grant is None and face.cast_when_drawn != row.spec):
                raise ValueError('Draw price changed an original automatic draw declaration')


def _phases(row):
    if row.outcome != 'cast':
        return ('drawing', 'done')
    if row.transformation is not None:
        return ('pending_cast','converted','after_draw','done')
    return ('pending_cast', 'casting', *(('pending_replacement', 'replacing')
            if row.spec.replacement else ()), 'after_draw', 'done')


def validate_prefix(fact, state, registry):
    fact.__post_init__()
    validate_history(state, registry)
    if (fact.next_entity_id > state.next_entity_id or fact.cast_history_length > len(state.cast_history) or
            fact.draw_history_length > len(state.draw_history) or fact.turn > state.turn or
            fact.action > state.action_number):
        raise ValueError('Draw price lost its original allocation or complete history prefix')
    for old, new in zip(fact.records, state.draw_history):
        if (old.interrupted and old != new or
                old.cast_id is not None and old.cast_id != new.cast_id or
                old.replacement_id is not None and old.replacement_id != new.replacement_id or
                old.hand_entry_id is not None and old.hand_entry_id!=new.hand_entry_id or
                old.transformation is not None and old.transformation!=new.transformation or
                _phases(new).index(new.phase) < _phases(new).index(old.phase) or
                replace(old, phase=new.phase, cast_id=new.cast_id, replacement_id=new.replacement_id,
                    interrupted=new.interrupted,hand_entry_id=new.hand_entry_id,transformation=new.transformation) != new):
            raise ValueError('Draw price rewrote an original physical draw or reversed legal progress')
