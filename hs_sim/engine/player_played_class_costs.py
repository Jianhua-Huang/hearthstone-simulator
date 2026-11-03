"""Finite class, turn, last Cost and deck prices from one physical-play ledger."""
from dataclasses import replace
from .model import (CardType, PlayRecord, PlayerPlayedClassCostSpec,
                    PlayerPlayedClassCostRow, PlayerPlayedClassCostFact)


def validate_definition(definition):
    spec = definition.player_played_class_cost
    if spec is None: return
    if type(spec) is not PlayerPlayedClassCostSpec:
        raise ValueError('Expected PlayerPlayedClassCostSpec')
    spec.__post_init__()
    other = spec.profile_id == 'cost.player-played-other-class-v1'
    if definition.kind != (CardType.SPELL if other else CardType.MINION) or not definition.hand_playable or definition.starship_for:
        raise ValueError('Played-class price belongs to an ordinary physical minion')
    if other and spec.card_class is not None:
        raise ValueError('Other-class declaration captures its recipient at query time')
    if any(value is not None for value in (definition.board_minion_cost, definition.hand_count_cost,
            definition.hero_missing_health_cost, definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost)):
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
    if spec.profile_id == 'cost.player-played-rafaam-v1':
        from .rafaams import GIANT
        if definition.id != GIANT: raise ValueError('Native Rafaam price belongs only to its actual Giant')
    if spec.profile_id in ('cost.player-played-outside-starting-deck-v1',
                           'cost.player-played-combo-turn-v1',
                           'cost.player-last-played-cost-v1', 'cost.player-played-rafaam-v1',
                           'cost.player-played-other-class-v1') and (
            definition.intrinsic_costs or any(value is not None for value in (
                definition.hero_health_change_cost, definition.player_draw_count_cost,
                definition.player_weapon_attack_cost, definition.player_armor_cost,
                definition.player_summon_count_cost, definition.player_elemental_streak_cost,
                definition.player_corpse_spend_cost, definition.hero_damage_taken_cost,
                definition.player_spell_damage_cost))):
        raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def row_for(record):
    return PlayerPlayedClassCostRow(record.played_face, record.turn, record.action,
        record.hand_entry_id, record.hand_entry_turn, record.cost)


def _rows(state, registry):
    from .hand_history import hand_entry
    from .owner_turns import validate_face
    if type(state.play_history) is not list:
        raise ValueError('Played-class price requires the original physical-play history')
    rows = []
    for record in state.play_history:
        if type(record) is not PlayRecord:
            raise ValueError('Played-class price requires immutable original hand roots')
        record.__post_init__()
        if record.submitted_cost is None:
            raise ValueError('Played-class price lost an original paid hand receipt')
        validate_face(record.played_face, registry)
        entry = hand_entry(state, record.hand_entry_id)
        if (record.source_id not in state.entities or
                (entry.entity_id, entry.player_id, entry.turn) != (record.source_id, record.player_id, record.hand_entry_turn) or
                entry.action > record.action):
            raise ValueError('Played-class price changed its original physical acquisition identity')
        rows.append(row_for(record))
    return tuple(rows)


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    spec = definition.player_played_class_cost
    if spec is None: return None
    from .play_history import played_cards
    rows = _rows(state, registry)
    turn = state.turn if spec.profile_id == 'cost.player-played-card-count-turn-v1' else None
    entities = cards = None
    combo = spec.profile_id == 'cost.player-played-combo-turn-v1'
    combo_inputs = None
    if combo:
        from .play_history import matches_played_combo
        combo_inputs = tuple(record.submitted_cost.quote.quote_input for record in state.play_history)
        selected = tuple(row.face.play_id for row, original in zip(rows, combo_inputs)
            if row.face.player_id == player_id and row.turn == state.turn and matches_played_combo(original))
    elif spec.profile_id == 'cost.player-played-outside-starting-deck-v1':
        from .play_history import starting_deck_identity, played_outside_starting_deck
        entities, cards = starting_deck_identity(state)
        selected = tuple(record.id for record in played_outside_starting_deck(state, player_id))
    elif spec.profile_id == 'cost.player-played-rafaam-v1':
        from .rafaams import played_ids
        selected = played_ids(state, registry, player_id)
    elif spec.profile_id == 'cost.player-played-other-class-v1':
        from .play_history import matches_other_played_class
        spec = replace(spec, card_class=state.players[player_id].hero_class)
        selected = tuple(row.face.play_id for row in rows if row.face.player_id == player_id
            and matches_other_played_class(row.face, spec.card_class))
    else:
        selected = tuple(record.id for record in played_cards(state, player_id, turn=turn,
            registry=registry, card_class=spec.card_class))
    if spec.profile_id == 'cost.player-last-played-cost-v1':
        selected = selected[-1:]
        quantity = 0 if not selected else rows[selected[0]-1].accepted_cost
    else:
        quantity = len(selected)
    fact = PlayerPlayedClassCostFact(spec, player_id, state.turn, state.action_number,
        state.next_entity_id, len(rows), rows, selected, quantity, base_cost, max(0, base_cost-(2 if combo else 1)*quantity),
        entities, cards, combo_inputs)
    if cards is not None:
        validate_fact(registry, definition, fact)
    return fact


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_played_class_cost is None:
        if fact is not None: raise ValueError('A minion without played-class pricing invented an original quantity')
        return
    if type(fact) is not PlayerPlayedClassCostFact:
        raise ValueError('Played-class price lost its complete original face prefix')
    fact.__post_init__()
    if fact.spec.profile_id == 'cost.player-played-rafaam-v1':
        from .rafaams import validate_registry
        validate_registry(registry)
    expected = definition.player_played_class_cost
    if expected.profile_id == 'cost.player-played-other-class-v1':
        expected = replace(expected, card_class=fact.spec.card_class)
    if fact.spec != expected:
        raise ValueError('Played-class price changed its pinned declaration')
    from .owner_turns import validate_face
    for row in fact.rows: validate_face(row.face, registry)
    if fact.starting_cards is not None:
        for group in fact.starting_cards:
            if any(not registry.card(card_id).hand_playable for card_id in group):
                raise ValueError('Starting-deck price invented an original non-hand card')


def validate_prefix(fact, state, registry):
    rows = _rows(state, registry)
    if (fact.next_entity_id > state.next_entity_id or fact.turn > state.turn or fact.action > state.action_number or
            len(fact.rows) > len(rows) or fact.rows != rows[:len(fact.rows)]):
        raise ValueError('Played-class price rewrote its complete original physical face prefix')
    if fact.combo_inputs is not None and fact.combo_inputs != tuple(
            record.submitted_cost.quote.quote_input for record in state.play_history[:fact.play_history_length]):
        raise ValueError('Combo-card price rewrote its original submitted physical input prefix')
    if fact.starting_entities is not None:
        from .play_history import starting_deck_identity
        fact.__post_init__()
        if starting_deck_identity(state) != (fact.starting_entities, fact.starting_cards):
            raise ValueError('Played-card price rewrote the complete original starting decks')
