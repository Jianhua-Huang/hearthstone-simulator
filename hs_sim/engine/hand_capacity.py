"""Player-owned hand admission capacity shared by existing delivery paths."""
from dataclasses import dataclass

from .effects import Effect, _integer, _player


def hand_capacity(player, rules):
    """Pure effective capacity; the ruleset supplies only the initial default."""
    override = player.hand_cap
    if override is not None:
        _integer(override, 'hand capacity', 1)
    elif len(player.hand) > rules.max_hand:
        # No gameplay operation resets an explicit override to None. A default
        # hand therefore cannot acquire an already-held excess via restoration.
        raise ValueError('Unexpanded hand exceeds default capacity')
    return rules.max_hand if override is None else override


@dataclass(frozen=True)
class SetHandCapacity(Effect):
    player_id: int
    amount: int
    mode: str = 'set'

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'hand capacity', 1)
        if type(self.mode) is not str or self.mode not in ('set', 'raise'):
            raise ValueError('Hand capacity mode must be set or raise')


def change_capacity(r, effect):
    effect.__post_init__()
    player = r.player(effect.player_id)
    before = hand_capacity(player, r.rules)
    player.hand_cap = max(before, effect.amount) if effect.mode == 'raise' else effect.amount
    # Capacity controls new admission. This operation neither moves existing
    # material nor invents a discard, draw or callback to refill the hand.
    if player.hand_cap != before:
        r.emit('hand_capacity_changed', player_id=player.id,
            amount=player.hand_cap - before, previous=before,
            capacity=player.hand_cap, mode=effect.mode)


def register(mechanics):
    mechanics.register(SetHandCapacity, change_capacity)
