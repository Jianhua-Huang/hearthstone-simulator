"""Pure current own-hand class condition; immutable quote operands, no cache."""
from .model import CardClass, HandOtherClassRow, HandOtherClassMatch, Zone
from .pools import PoolQuery, matches_metadata

OTHER_CLASS = PoolQuery(class_mode='other', include_neutral=False)


def _matches(registry, card_id, hero_class):
    card = registry.card(card_id)
    return matches_metadata(OTHER_CLASS, card_id=card_id, kind=card.kind, cost=card.cost,
        meta=card.metadata, spell_school=card.spell_school, keywords=card.keywords,
        current_class=hero_class)


def capture_hand_other_class(state, registry, player_id):
    if type(player_id) is not int or player_id not in (1,2):
        raise ValueError('Hand class condition requires player 1 or 2')
    player = state.players[player_id]
    if type(player.hero_class) is not CardClass or player.hero_class == CardClass.NEUTRAL:
        raise ValueError('Hand class condition requires a known playable hero class')
    rows = []
    for eid in player.hand:
        entity = state.entities[eid]
        card = registry.card(entity.card_id)
        if entity.zone != Zone.HAND or entity.controller != player_id or entity.kind != card.kind:
            raise ValueError('Hand class condition differs from its physical hand')
        rows.append(HandOtherClassRow(eid, entity.card_id, _matches(registry, entity.card_id, player.hero_class)))
    return HandOtherClassMatch(player_id,state.turn,state.action_number,state.next_entity_id,player.hero_class,tuple(rows))


def hand_has_other_class(state, registry, player_id):
    return capture_hand_other_class(state,registry,player_id).matched


def validate_hand_other_class_match(match, registry):
    if type(match) is not HandOtherClassMatch:
        raise ValueError('Hand class condition requires its typed original inventory')
    match.__post_init__()
    for row in match.rows:
        if row.matched != _matches(registry,row.card_id,match.hero_class):
            raise ValueError('Hand class match changed its original printed classification')


def validate_hand_other_class_prefix(match, state, registry):
    validate_hand_other_class_match(match,registry)
    if match.next_entity_id > state.next_entity_id or any(row.entity_id not in state.entities for row in match.rows):
        raise ValueError('Hand class price lost its original allocation prefix')
