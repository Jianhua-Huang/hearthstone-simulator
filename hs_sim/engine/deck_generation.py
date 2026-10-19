"""Counted generated deck copies materialize only available physical slots.

The semantic shuffle retains its original count, including very large counts.
Ordinary AddToDeck remains the only card creator and insertion publisher.
"""
from dataclasses import dataclass
from .effects import Effect,_integer,_player,_source,_behavior

from .deck_capacity import MAX_DECK_SIZE as MAX_GENERATED_DECK_SIZE, room


@dataclass(frozen=True)
class ShuffleGeneratedCopies(Effect):
    player_id:int
    actor_id:int
    card_id:str
    count:int
    source_id:int|None=None

    def __post_init__(self):
        _player(self.player_id);_player(self.actor_id);_behavior(self.card_id)
        _integer(self.count,'generated deck copy count',0);_source(self.source_id)


def validate_request(state,registry,effect):
    effect.__post_init__()
    if not registry.card(effect.card_id).hand_playable:raise ValueError('Generated deck copies require a playable original card')
    if effect.source_id is not None and effect.source_id not in state.entities:raise ValueError('Generated shuffle source does not exist')


def execute(r,effect):
    validate_request(r.state,r.registry,effect)
    from .zones import AddToDeck
    from .deck_shuffles import group
    count=min(effect.count,room(r.state,effect.player_id))
    with group(r,effect.actor_id,effect.player_id,effect.count,effect.source_id):
        for _ in range(count):
            r.charge();work=AddToDeck(effect.player_id,effect.card_id,source_id=effect.source_id)
            result=r.game.mechanics.handler(work)(r,work)
            if isinstance(result,(tuple,list,Effect)) or r._choice_request is not None:
                raise ValueError('Generated shuffle primitive returned asynchronous work')
    return ()


def register(mechanics):mechanics.register(ShuffleGeneratedCopies,execute)
