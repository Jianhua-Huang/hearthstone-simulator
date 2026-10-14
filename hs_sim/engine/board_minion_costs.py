"""Finite pure board-count price operand, without persistent cost modifiers."""
from .model import (BoardMinionCostSpec, BoardMinionCostRow, BoardMinionCostFact,
                    CardType, Zone)


def validate_definition(definition):
    spec = definition.board_minion_cost
    if spec is None:
        return
    if type(spec) is not BoardMinionCostSpec:
        raise ValueError('Expected BoardMinionCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Board minion cost belongs to an ordinary physical minion')


def quantity(registry, boards, spec, player_id):
    # Validate every declared face, including the unselected side and inert
    # objects. Zero cost and friendly scope cannot conceal an unknown row.
    eligible = tuple(tuple(registry.card(row.card_id).kind == CardType.MINION and
        registry.card(row.card_id).interactable is None for row in board) for board in boards)
    selected = eligible if spec.scope == 'all' else (eligible[player_id - 1],)
    return sum(sum(board) for board in selected)


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    spec = definition.board_minion_cost
    if spec is None:
        return None
    boards = []
    for pid in (1, 2):
        rows = []
        for eid in state.players[pid].board:
            entity = state.entities[eid]
            if entity.zone != Zone.BOARD or entity.controller != pid:
                raise ValueError('Board price inventory differs from its physical zone/controller')
            rows.append(BoardMinionCostRow(eid, entity.card_id))
        boards.append(tuple(rows))
    boards = tuple(boards)
    count = quantity(registry, boards, spec, player_id)
    return BoardMinionCostFact(spec, player_id, state.next_entity_id, boards,
        count, base_cost, max(0, base_cost - count))


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.board_minion_cost is None:
        if fact is not None:
            raise ValueError('A minion without board pricing invented a count stage')
        return
    if type(fact) is not BoardMinionCostFact:
        raise ValueError('Board-priced minion lost its complete original count stage')
    fact.__post_init__()
    if fact.spec != definition.board_minion_cost:
        raise ValueError('Board cost changed its pinned declaration')
    if quantity(registry, fact.boards, fact.spec, fact.player_id) != fact.quantity:
        raise ValueError('Board cost quantity differs from all complete physical rows')
