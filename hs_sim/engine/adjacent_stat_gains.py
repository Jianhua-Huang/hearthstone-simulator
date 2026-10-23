"""One live neighboring minion supplies numbers; ordinary buffs own delivery."""
from dataclasses import dataclass

from .board_presence import resolve_board_presence
from .death_neighbors import capture
from .effects import Effect, _source
from .model import BoardPresenceReference
from .sacrifice import BuffCapturedMinion


@dataclass(frozen=True)
class GainRandomAdjacentStats(Effect):
    beneficiary: BoardPresenceReference
    source_id: int

    def __post_init__(self):
        if type(self.beneficiary) is not BoardPresenceReference:
            raise ValueError('Adjacent stat gain requires its original board residence')
        self.beneficiary.__post_init__()
        _source(self.source_id)
        if self.source_id != self.beneficiary.entity_id:
            raise ValueError('Adjacent stat gain must retain its original beneficiary as source')


def gain(r, request):
    request.__post_init__()
    source = resolve_board_presence(r.state, request.beneficiary)
    if source is None or not source.active or source.health <= 0 or source.doomed:
        return ()
    neighbors = tuple(entity for reference in capture(r.state, source)
        if (entity := resolve_board_presence(r.state, reference)) is not None and
        entity.active and entity.health > 0 and not entity.doomed)
    if not neighbors:
        return ()
    chosen = r.game._rng.choice(neighbors)
    reward = BuffCapturedMinion(request.beneficiary, chosen.attack, chosen.health, request.source_id)
    r.emit('random_choice', source_id=request.source_id, target_id=chosen.id,
        player_id=source.controller, candidates=tuple(entity.id for entity in neighbors))
    return (reward,)


def register(mechanics):
    mechanics.register(GainRandomAdjacentStats, gain)
