"""One actual random minion per original stored or board acceptance window."""
from dataclasses import dataclass
from .effects import Effect,_integer,_player
from .model import CardType,Zone
from .pools import PoolQuery
from .sacrifice import DestroyCapturedMinion,MinionReference
from .zones import DestroyStoredCard,source_exists,zone_candidates


@dataclass(frozen=True)
class DestroyRandomZoneMinion(Effect):
    player_id:int
    owner_id:int
    zone:Zone
    source_id:int
    def __post_init__(self):
        _player(self.player_id);_player(self.owner_id);_integer(self.source_id,'random destruction source',1)
        if type(self.zone)is not Zone or self.zone not in(Zone.HAND,Zone.DECK,Zone.BOARD):
            raise ValueError('Random minion destruction requires a physical hand, deck or board')


def destroy(r,request):
    request.__post_init__();source_exists(r,request.source_id)
    if request.zone==Zone.BOARD:
        from .cross_zone import MinionScope,minion_references
        candidates=minion_references(r.state,r.registry,request.owner_id,MinionScope((Zone.BOARD,)),request.source_id)
    else:
        candidates=zone_candidates(r,request.owner_id,request.zone,PoolQuery(kinds=(CardType.MINION,)),request.player_id,request.source_id)
    if not candidates:return()
    selected=r.game._rng.choice(candidates)
    return(DestroyCapturedMinion(selected,request.source_id),)if type(selected)is MinionReference else(DestroyStoredCard(selected,request.source_id),)


def register(mechanics):mechanics.register(DestroyRandomZoneMinion,destroy)
