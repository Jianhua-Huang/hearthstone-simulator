"""Next tribal plays use the original consumed payment and first board entry."""
from dataclasses import dataclass

from .effects import CopyMinion, Effect, _integer
from .model import CardType


@dataclass(frozen=True)
class CopyPaidMinion(Effect):
    play_id: int
    modifier_id: int

    def __post_init__(self):
        _integer(self.play_id, 'original paid copy play', 1)
        _integer(self.modifier_id, 'original paid copy budget', 1)

    def validate_in_state(self, state):
        from .costs import _paid_minion_modifiers
        from .play_history import play_record
        self.__post_init__(); play=play_record(state,self.play_id)
        if (play.kind!=CardType.MINION or not play.completed or play.countered or play.interrupted or
                play.minion_result!='summoned' or play.minion_entry is None):
            raise ValueError('Paid copy requires its completed original successful minion play')
        modifiers=_paid_minion_modifiers(state,play,'copy_after_play')
        if sum(m.id==self.modifier_id for m in modifiers)!=1:
            raise ValueError('Paid copy lost its exact consumed next-Draenei budget')
        return play


def completed(state,play):
    from .costs import _paid_minion_modifiers
    if play.kind!=CardType.MINION or play.minion_result!='summoned' or play.countered or play.minion_entry is None:return ()
    return tuple(CopyPaidMinion(play.id,m.id)for m in _paid_minion_modifiers(state,play,'copy_after_play'))


def copy(r,effect):
    from .allocation_facts import SourceAllocationFact
    from .board_presence import resolve_board_presence
    from .summon_quantities import SummonCause
    play=effect.validate_in_state(r.state)
    source=resolve_board_presence(r.state,play.minion_entry.reference)
    if source is None or not source.active or source.doomed or source.health<=0:return ()
    cause=SummonCause(SourceAllocationFact.capture(r.state,source),play.player_id,r.state.turn,r.state.action_number)
    return (CopyMinion(play.minion_entry.reference,play.player_id,cause=cause),)


def register(mechanics):mechanics.register(CopyPaidMinion,copy)
