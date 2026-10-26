"""One original random enemy group; ordinary captured control owns delivery."""
from dataclasses import dataclass
from .effects import Effect,_integer,_player


@dataclass(frozen=True)
class TakeRandomEnemyMinions(Effect):
    player_id:int
    source_id:int
    count:int=3

    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'random-control source',1)
        _integer(self.count,'random-control count',1)

    def validate_in_state(self,state):
        self.__post_init__()
        if self.source_id not in state.entities:raise ValueError('Random control lost its original allocated source')


def take(r,effect):
    from .cross_zone import MinionScope,minion_references,TakeCapturedMinion
    from .model import Zone
    effect.validate_in_state(r.state)
    candidates=minion_references(r.state,r.registry,3-effect.player_id,MinionScope((Zone.BOARD,)),effect.source_id)
    if not candidates:return()
    selected=r.game._rng.sample(candidates,min(effect.count,len(candidates)))
    r.emit('random_choice',source_id=effect.source_id,player_id=effect.player_id,
        candidates=tuple(ref.entity_id for ref in candidates),selected=tuple(ref.entity_id for ref in selected),producer='enemy_control')
    return tuple(TakeCapturedMinion(ref,effect.player_id,effect.source_id)for ref in selected)


def register(mechanics):mechanics.register(TakeRandomEnemyMinions,take)
