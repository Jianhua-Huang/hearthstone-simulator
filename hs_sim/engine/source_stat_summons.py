"""Original native-body stat summons with a retained accepted source basis."""
from dataclasses import dataclass
from .effects import Effect, _player
from .errors import ResolutionError
from .model import CardType, SummonStats
from .sacrifice import MinionReference, live_minion, reference_value
from .summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial


@dataclass(frozen=True)
class SummonBySourceStats(Effect):
    player_id: int
    card_id: str
    source: MinionReference
    accepted_stats: SummonStats
    cause: SummonCause

    def __post_init__(self):
        _player(self.player_id)
        reference_value(self.source)
        if type(self.accepted_stats) is not SummonStats:
            raise ValueError('Source-stat summon requires its complete accepted stats')
        self.accepted_stats.__post_init__()
        if self.accepted_stats.attack is None or self.accepted_stats.health is None:
            raise ValueError('Source-stat summon requires both accepted source attributes')
        SummonEntryMaterial(self.card_id,self.accepted_stats).__post_init__()
        if type(self.cause) is not SummonCause:
            raise ValueError('Source-stat summon requires its original attribution')
        self.cause.__post_init__()
        original=self.cause.source
        if ((self.player_id,self.source.entity_id,self.source.player_id,self.source.card_id,
                self.source.zone_epoch,self.source.entered_order) !=
                (self.cause.player_id,original.entity_id,original.controller,original.card_id,
                 original.zone_epoch,original.entered_order) or original.kind != CardType.MINION):
            raise ValueError('Source-stat summon differs from its original minion attribution')


def summon(r,request):
    request.__post_init__()
    definition=r.registry.card(request.source.card_id)
    if definition.kind != CardType.MINION or definition.interactable is not None:
        raise ResolutionError('Source-stat summon requires its original ordinary minion')
    if request.source.entity_id not in r.state.entities:
        raise ResolutionError('Source-stat summon lost its original allocated source')
    entity=live_minion(r.state,request.source)
    stats=SummonStats(entity.attack,entity.health) if entity is not None else request.accepted_stats
    return (SummonByCard(request.player_id,(SummonEntryMaterial(request.card_id,stats),),request.cause),)


def register(mechanics):
    mechanics.register(SummonBySourceStats,summon)
