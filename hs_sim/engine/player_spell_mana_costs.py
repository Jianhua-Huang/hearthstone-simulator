"""One finite mana-expenditure operand from already committed physical payments."""
from dataclasses import fields

from .model import (CardType, PlayRecord, PlayerSpellManaCostSpec,
                    PlayerSpellManaCostRow, PlayerSpellManaCostFact)


def validate_definition(definition):
    spec = definition.player_spell_mana_cost
    if spec is None:
        return
    if type(spec) is not PlayerSpellManaCostSpec:
        raise ValueError('Expected PlayerSpellManaCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Spell mana cost belongs to an ordinary physical minion')
    if any(value is not None for value in (definition.board_minion_cost, definition.hand_count_cost,
            definition.hero_missing_health_cost, definition.player_spell_count_cost,
            definition.player_hero_power_count_cost)):
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def row_for(record):
    return PlayerSpellManaCostRow(**{field.name: getattr(record, field.name)
                                   for field in fields(PlayerSpellManaCostRow)})


def _rows(state, registry):
    from .hand_history import hand_entry
    if type(state.play_history) is not list:
        raise ValueError('Spell mana cost requires the original physical play ledger')
    rows = []
    for record in state.play_history:
        if type(record) is not PlayRecord:
            raise ValueError('Spell mana cost requires immutable original paid roots')
        # The root is appended only after pay_quote applies its resource writes.
        # Its typed receipt binds cost/account/source, and its own validator binds
        # the mana endpoints. Do not re-execute bodies or recursively quote roots.
        record.__post_init__()
        if record.submitted_cost is None:
            raise ValueError('Spell mana cost lost a committed original payment receipt')
        face = registry.card(record.card_id)
        entry = hand_entry(state, record.hand_entry_id)
        if (face.kind != record.kind or not face.hand_playable or
                record.source_id not in state.entities or
                (entry.entity_id, entry.player_id, entry.turn) !=
                (record.source_id, record.player_id, record.hand_entry_turn) or
                entry.action > record.action or record.turn > state.turn or record.action > state.action_number):
            raise ValueError('Spell mana cost changed a complete original paid play identity')
        rows.append(row_for(record))
    return tuple(rows)


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    if definition.player_spell_mana_cost is None:
        return None
    rows = _rows(state, registry)
    from .resources import validate_mana_consumption_history
    validate_mana_consumption_history(state,registry)
    direct=tuple(state.mana_consumption_history)
    quantity = sum(row.mana_for(player_id) for row in (*rows,*direct))
    return PlayerSpellManaCostFact(definition.player_spell_mana_cost, player_id,
        state.next_entity_id, len(rows), rows, quantity, base_cost, max(0, base_cost - quantity),direct,len(direct))


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.player_spell_mana_cost is None:
        if fact is not None:
            raise ValueError('A minion without spell mana pricing invented an expenditure stage')
        return
    if type(fact) is not PlayerSpellManaCostFact:
        raise ValueError('Spell mana price lost its complete original paid prefix')
    fact.__post_init__()
    if fact.spec != definition.player_spell_mana_cost:
        raise ValueError('Spell mana price changed its pinned declaration')
    for row in fact.rows:
        face = registry.card(row.card_id)
        if face.kind != row.kind or not face.hand_playable:
            raise ValueError('Spell mana price contains an unsupported original physical face')
    for row in fact.consumption_rows:
        if row.source_card_id is not None and registry.card(row.source_card_id).kind!=row.source_kind:
            raise ValueError('Spell mana price changed original consumption source type')


def validate_prefix(fact, state, registry):
    rows = _rows(state, registry)
    if (fact.next_entity_id > state.next_entity_id or len(fact.rows) > len(rows) or
            fact.rows != rows[:len(fact.rows)]):
        raise ValueError('Spell mana price rewrote its complete original physical payment prefix')
    from .resources import validate_mana_consumption_history
    validate_mana_consumption_history(state,registry)
    direct=tuple(state.mana_consumption_history)
    if len(fact.consumption_rows)>len(direct) or fact.consumption_rows!=direct[:len(fact.consumption_rows)]:
        raise ValueError('Spell mana price rewrote its complete original direct consumption prefix')
