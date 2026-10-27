"""Finite pure board-count price operand, without persistent cost modifiers."""
from .model import (BoardMinionCostSpec, BoardMinionCostRow, BoardMinionCostFact,
                    CardType, Zone)
from .card_conditions import UnknownCardFactError
from .tribes import tribe_changes,tribe_state_for


def validate_definition(definition):
    spec = definition.board_minion_cost
    if spec is None:
        return
    if type(spec) is not BoardMinionCostSpec:
        raise ValueError('Expected BoardMinionCostSpec')
    spec.__post_init__()
    if definition.kind not in (CardType.MINION, CardType.SPELL) or not definition.hand_playable or definition.starship_for or definition.interactable:
        raise ValueError('Board minion cost belongs to an ordinary physical minion or spell')


def quantity(registry, boards, spec, player_id):
    # Validate every declared face, including the unselected side and inert
    # objects. Zero cost and friendly scope cannot conceal an unknown row.
    spec.__post_init__()
    filtered = bool(spec.tribes_any)
    selected = (1,2) if spec.scope == 'all' else (player_id if spec.scope == 'friendly' else 3-player_id,)
    count = 0
    for pid,board in enumerate(boards,1):
        for row in board:
            card = registry.card(row.card_id)
            ordinary = card.kind == CardType.MINION and card.interactable is None
            needs_tribes = filtered and pid == player_id and ordinary
            if needs_tribes != (row.tribe_changes is not None):
                raise ValueError('Board price changed its complete selected tribe operands')
            matches = ordinary
            if needs_tribes:
                current = tribe_state_for(registry,row.card_id,row.tribe_changes)
                if current is None:raise UnknownCardFactError('Unknown current board tribe identity: '+row.card_id)
                matches = current.matches_any(spec.tribes_any)
            if pid in selected:count += matches
    return count


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
            card = registry.card(entity.card_id)
            needs_tribes = (bool(spec.tribes_any) and pid == player_id and
                card.kind == CardType.MINION and card.interactable is None)
            rows.append(BoardMinionCostRow(eid, entity.card_id,tribe_changes(entity) if needs_tribes else None))
        boards.append(tuple(rows))
    boards = tuple(boards)
    count = quantity(registry, boards, spec, player_id)
    return BoardMinionCostFact(spec, player_id, state.next_entity_id, boards,
        count, base_cost, max(0, base_cost - count),
        next_attachment_id=state.next_attachment_id if spec.tribes_any else None)


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
