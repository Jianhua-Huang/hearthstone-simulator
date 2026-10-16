"""Pure access to original submitted physical hand neighbors."""
from .model import Zone
from .zones import CardReference
from .registry import UnsupportedDefinitionError


def submitted_hand_neighbors(context):
    if context.play is None:
        # A battlecry source with no actual hand submission has no hand position.
        return ()
    if context.play.hand_neighbors is None:
        raise UnsupportedDefinitionError('Original submitted hand neighbors were not captured')
    return tuple(CardReference(x.entity_id,x.player_id,Zone.HAND,x.card_id,x.zone_epoch)
                 for x in context.play.hand_neighbors)
