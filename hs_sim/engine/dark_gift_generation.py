"""Bind native Dark Gift generation to the host's actual discovery context."""
from dataclasses import dataclass

from .construction import name
from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import CardType, CostSpec
from .pools import DiscoverFromPool, PoolQuery


@dataclass(frozen=True)
class DiscoverDarkGift(Effect):
    player_id: int
    pool_id: str
    query: PoolQuery
    source_id: int
    cost: CostSpec | None = None

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.source_id, 'Dark Gift generation source', 1)
        name(self.pool_id, 'Dark Gift minion pool')
        if type(self.query) is not PoolQuery:
            raise ValueError('Dark Gift generation requires a typed minion query')
        self.query.__post_init__()
        if self.query.kinds != (CardType.MINION,) or self.query.collectible is not True:
            raise ValueError('Dark Gift generation requires collectible minions')
        if self.cost is not None:
            if type(self.cost) is not CostSpec:
                raise ValueError('Native Dark Gift cost requires CostSpec')
            self.cost.__post_init__()
            if (self.cost.delta >= 0 or self.cost.set_to is not None or self.cost.minimum or
                    self.cost.payment is not None or self.cost.card_ids or self.cost.ability is not None or
                    self.cost.card_types != (CardType.MINION,)):
                raise ValueError('Native Dark Gift cost supports a plain minion reduction only')

    def validate_in_state(self, state):
        self.__post_init__()
        if self.player_id not in state.players or self.source_id not in state.entities:
            raise ValueError('Dark Gift generation lost its original player or allocated source')


def discover(r, effect):
    effect.validate_in_state(r.state)
    context = r.game._generation_context
    if context is None:
        raise ResolutionError('Dark Gift generation requires the actual host generation context')
    from .dark_gifts import dark_gift_pool
    return (DiscoverFromPool(effect.player_id, effect.pool_id, effect.query, source_id=effect.source_id,
                             gift_pool=dark_gift_pool(context.target_id, context.mode), cost=effect.cost),)


def register(mechanics):
    mechanics.register(DiscoverDarkGift, discover)
