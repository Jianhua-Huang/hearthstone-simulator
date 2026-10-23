"""Physical printed minion growth, separate from local buffs and player auras."""
from dataclasses import dataclass

from .copy_materials import CapturedCardCopyMaterial,validate_captured_card_copy
from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .model import CardType,Enchantment,SummonStats,Zone

LABEL='permanent_minion_stats'


def validate_value(stats):
    if stats is None:return
    if type(stats)is not SummonStats:raise ValueError('Permanent minion bases require typed numeric stats')
    stats.__post_init__()
    if stats.attack is None or stats.health is None:
        raise ValueError('Permanent minion bases require both printed attributes')


def value(carrier):
    stored=getattr(carrier,'permanent_stats',None)
    validate_value(stored)
    rows=tuple(e for e in getattr(carrier,'enchantments',())if e.label==LABEL)
    if len(rows)>1:raise ValueError('A physical minion has one permanent printed base')
    if rows:
        row=rows[0];row.__post_init__();result=SummonStats(row.set_attack,row.set_health)
        if stored is not None and stored!=result:raise ValueError('Permanent printed recipes disagree')
        return result
    return stored


def imprint(state,entity,stats,source_id=None):
    validate_value(stats)
    if stats is None:return
    if entity.kind!=CardType.MINION or entity.components or entity.starship_building:
        raise ValueError('Permanent printed growth currently requires an ordinary minion')
    from .lifecycle import attachment_id,refresh_entity
    entity.enchantments=[e for e in entity.enchantments if e.label!=LABEL]
    entity.enchantments.append(Enchantment(attachment_id(state),source_id=source_id,
        set_attack=stats.attack,set_health=stats.health,remove_on_silence=False,label=LABEL))
    refresh_entity(entity)


def inherit(state,source,destination,stats=None):
    stats=value(source)if stats is None else stats
    if stats is not None:
        if state is None:raise ValueError('Printed growth copies require the real attachment allocator')
        imprint(state,destination,stats,getattr(source,'entity_id',getattr(source,'id',None)))


def validate_carrier(carrier):
    stats=value(carrier)
    if stats is not None and (getattr(carrier,'kind',CardType.MINION)!=CardType.MINION or
            getattr(carrier,'components',())or getattr(carrier,'starship_building',False)):
        raise ValueError('Permanent printed bases require an ordinary minion carrier')


@dataclass(frozen=True)
class CreateGrowingMinion(Effect):
    original:CapturedCardCopyMaterial
    player_id:int
    attack_growth:int
    health_growth:int
    position:str='random'

    def __post_init__(self):
        _player(self.player_id)
        if type(self.original)is not CapturedCardCopyMaterial:
            raise ValueError('Permanent copy requires its full original physical material')
        self.original.__post_init__()
        if self.original.origin.kind!=CardType.MINION or self.original.origin.zone not in(Zone.BOARD,Zone.GRAVEYARD):
            raise ValueError('Permanent copy requires its original board/death minion')
        _integer(self.attack_growth,'permanent Attack growth',0)
        _integer(self.health_growth,'permanent Health growth',0)
        if not(self.attack_growth or self.health_growth)or self.position not in('random','bottom'):
            raise ValueError('Permanent minion copy requires its actual growth and deck placement')

    @property
    def source_id(self):return self.original.origin.entity_id


def create(r,request):
    request.__post_init__();material=request.original
    validate_captured_card_copy(r.state,r.registry,material)
    source=material.entity();validate_carrier(source)
    if material.components or source.kind!=CardType.MINION:
        raise ResolutionError('Permanent growing copies require an ordinary original minion')
    from .jade import printed_definition
    base=printed_definition(r.registry,source)
    stats=SummonStats(base.attack+request.attack_growth,base.health+request.health_growth)
    from .zones import CopyCard,copy_physical_card
    copy_physical_card(r,CopyCard(material,request.player_id,destination=Zone.DECK,mode='base',
        position=request.position,source_id=request.source_id),permanent_stats=stats)


def register(mechanics):mechanics.register(CreateGrowingMinion,create)
