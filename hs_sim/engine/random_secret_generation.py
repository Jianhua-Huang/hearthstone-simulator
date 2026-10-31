"""A complete ordinary pool draw followed by the original hidden Secret install."""
from dataclasses import dataclass

from .effects import Effect,_behavior,_integer,_player
from .model import CardType,Keyword
from .pools import GenerateFromPool,PoolQuery,generation_candidates,sample_candidates
from .secrets import SetSecret,activation_error


@dataclass(frozen=True)
class SetRandomSecretFromPool(Effect):
    player_id:int
    pool_id:str
    source_id:int
    query:PoolQuery

    def __post_init__(self):
        _player(self.player_id);_behavior(self.pool_id);_integer(self.source_id,'original Secret generator',1)
        if type(self.query)is not PoolQuery:
            raise ValueError('Random Secret install requires a complete typed pool query')
        self.query.__post_init__()
        if (self.query.kinds!=(CardType.SPELL,)or self.query.collectible is not True or
                self.query.keywords_all!=(Keyword.SECRET,)):
            raise ValueError('Random Secret install requires ordinary collectible Secret spells')


def install(r,request):
    request.__post_init__()
    # Query and validate the entire eligible inventory before considering local
    # capacity/duplicate keys. Missing implementations can never shrink the pool.
    candidates=generation_candidates(r,GenerateFromPool(request.player_id,request.pool_id,
        request.query,source_id=request.source_id))
    available=tuple(m for m in candidates if activation_error(r.state,r.registry,r.rules,request.player_id,m.card_id)is None)
    if not available:return ()
    selected,=sample_candidates(r.game._rng,available,1,replacement=True)
    # No CAST, hand card or public random-choice event may reveal this identity.
    return(SetSecret(request.player_id,selected),)


def register(mechanics):mechanics.register(SetRandomSecretFromPool,install)
