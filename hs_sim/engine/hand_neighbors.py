"""Pure access to original submitted physical hand neighbors."""
from .model import Zone
from .zones import CardReference
from .registry import UnsupportedDefinitionError


def current_hand_neighbors(state, entity_id):
    """Physical neighbors now; an unplaced or departed subject has no hand slot."""
    entity = state.entities.get(entity_id)
    if entity is None or entity.zone != Zone.HAND:
        return ()
    hand = state.players[entity.controller].hand
    if entity_id not in hand:
        raise ValueError('Current hand neighbor subject lost its physical hand slot')
    position = hand.index(entity_id)
    return tuple(hand[max(0, position-1):position] + hand[position+1:position+2])


def submitted_hand_neighbors(context):
    if context.play is None:
        # A battlecry source with no actual hand submission has no hand position.
        return ()
    if context.play.hand_neighbors is None:
        raise UnsupportedDefinitionError('Original submitted hand neighbors were not captured')
    return tuple(CardReference(x.entity_id,x.player_id,Zone.HAND,x.card_id,x.zone_epoch)
                 for x in context.play.hand_neighbors)
