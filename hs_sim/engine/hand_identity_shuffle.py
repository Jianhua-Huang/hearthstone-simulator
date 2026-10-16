"""One physical enemy hand card sharing a current printed face with own hand."""
from dataclasses import dataclass
from .deck_shuffles import ShuffleDeckCards
from .effects import Effect,_player,_source
from .model import Zone
from .zones import CardReference,MoveCard,source_exists


@dataclass(frozen=True)
class ShuffleSharedHandCard(Effect):
    player_id:int
    source_id:int|None=None
    def __post_init__(self):_player(self.player_id);_source(self.source_id)


def shuffle_shared(r,effect):
    effect.__post_init__();source_exists(r,effect.source_id)
    own=r.player(effect.player_id);enemy=r.player(3-effect.player_id)
    own_ids={r.registry.card(r.state.entities[e].card_id).id for e in own.hand}
    candidates=[]
    for eid in enemy.hand:
        entity=r.state.entities[eid]
        if r.registry.card(entity.card_id).id in own_ids:candidates.append(CardReference.capture(entity))
    if not candidates:return ()
    selected=r.game._rng.choice(candidates)
    return(ShuffleDeckCards(enemy.id,effect.player_id,(MoveCard(selected,enemy.id,Zone.DECK,'random',source_id=effect.source_id),),effect.source_id),)


def register(mechanics):mechanics.register(ShuffleSharedHandCard,shuffle_shared)
