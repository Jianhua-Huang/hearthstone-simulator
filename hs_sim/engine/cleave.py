"""Native adjacency damage recipients; execution stays in the combat batch."""
from .model import CardType, Keyword, Zone


def validate_definition(card):
    if type(card.cleave) is not bool:
        raise ValueError('Native cleave declaration must be boolean')
    if card.cleave and (card.kind not in (CardType.MINION, CardType.WEAPON) or
            card.starship_for or Keyword.STARSHIP_PIECE in card.keywords or
            Keyword.MAGNETIC in card.keywords):
        raise ValueError('Native cleave requires an ordinary minion or weapon')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'cleave')
    if not rows:
        return
    card = registry.card(card_id)
    validate_definition(card)
    from .crafted_faces import PREFIX, recipe_from_id
    if card_id.startswith(PREFIX):
        recipe = recipe_from_id(card_id)
        native_count = sum(registry.card(cid).cleave for cid in recipe.parts)
        if (not card.cleave or kind != CardType.MINION or type(components) is not tuple or
                components != recipe.parts or len(rows) > native_count):
            raise ValueError('Crafted cleave carrier differs from its original native ingredients')
    elif not card.cleave or kind != card.kind or components or len(rows) != 1:
        raise ValueError('Cleave carrier differs from its single native declaration')
    for row in rows:
        row.__post_init__()


def adjacent_targets(state, attacker, defender):
    """Current physical neighbors only; inactive slots do not become bridges."""
    from .equipment import equipped_weapon
    from .lifecycle import active_abilities
    source = attacker
    if attacker.kind == CardType.HERO:
        source = equipped_weapon(state, state.players[attacker.controller])
    if source is None or not active_abilities(source, 'cleave'):
        return ()
    if defender.kind != CardType.MINION or defender.zone != Zone.BOARD:
        return ()
    board = state.players[defender.controller].board
    index = board.index(defender.id)
    return tuple(entity_id for pos in (index - 1, index + 1) if 0 <= pos < len(board)
                 and (entity_id := board[pos]) != attacker.id
                 and (entity := state.entities[entity_id]).kind == CardType.MINION
                 and entity.active and entity.health > 0 and not entity.doomed)


def validate_combat_hits(state, batch):
    if batch.combat is None:
        return
    attacker = state.entities[batch.combat.attacker_id]
    defender = state.entities[batch.combat.defender_id]
    if tuple(h.target_id for h in batch.hits[2:]) != adjacent_targets(state, attacker, defender):
        raise ValueError('Combat batch lost its complete current cleave recipients')
