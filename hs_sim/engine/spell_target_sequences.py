"""Finite real spell selections over original cast and physical target facts."""
from dataclasses import dataclass
from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Damage,DestroyBatch,Effect,Freeze,_integer
from .model import CardType,DamageKind,Zone
from .sacrifice import MinionReference,live_minion,reference_value
from .spell_sequences import SpellSequence,DrawSpellBatchDeaths,minions,require_cast


@dataclass(frozen=True)
class FreezeRandomEnemyMinions(SpellSequence):
    count:int
    def __post_init__(self):
        super().__post_init__();_integer(self.count,'random freeze count',1)


@dataclass(frozen=True)
class FreezeSelectedEnemy(SpellSequence):
    target:MinionReference
    def __post_init__(self):
        super().__post_init__();reference_value(self.target)
        if self.target.player_id!=3-self.player_id:raise ValueError('Selected freeze requires its original enemy controller')


@dataclass(frozen=True)
class DamageEnemyAndRandomOthers(SpellSequence):
    primary:SourceAllocationFact
    primary_amount:int
    other_amount:int
    count:int
    def __post_init__(self):
        super().__post_init__()
        if type(self.primary)is not SourceAllocationFact:raise ValueError('Mixed damage requires original primary allocation')
        self.primary.__post_init__()
        if (self.primary.kind,self.primary.zone)not in((CardType.HERO,Zone.HERO),(CardType.MINION,Zone.BOARD))or self.primary.controller!=3-self.player_id:
            raise ValueError('Mixed damage primary must be its original enemy character')
        _integer(self.primary_amount,'primary damage',0);_integer(self.other_amount,'other damage',0);_integer(self.count,'other enemy count',1)


@dataclass(frozen=True)
class RandomMinionDamageDrawDeaths(SpellSequence):
    amount:int
    count:int
    def __post_init__(self):
        super().__post_init__();_integer(self.amount,'random minion damage',0);_integer(self.count,'random damaged minions',1)


@dataclass(frozen=True)
class FreezeAdjacentThenDestroyDamaged(SpellSequence):
    target:MinionReference
    def __post_init__(self):
        super().__post_init__();reference_value(self.target)


@dataclass(frozen=True)
class DestroyDamagedFrozenGroup(FreezeAdjacentThenDestroyDamaged):
    members:tuple[MinionReference,...]
    def __post_init__(self):
        super().__post_init__()
        if type(self.members)is not tuple or not 1<=len(self.members)<=3:
            raise ValueError('Frozen adjacent group requires one to three original minions')
        for ref in self.members:
            reference_value(ref)
            if ref.player_id!=self.target.player_id:raise ValueError('Frozen adjacent group changed its original controller')
        if len({ref.entity_id for ref in self.members})!=len(self.members)or self.target not in self.members:
            raise ValueError('Frozen adjacent group lost its primary or duplicated an original resident')


@dataclass(frozen=True)
class FreezeOriginalGroupMember(Effect):
    group:DestroyDamagedFrozenGroup
    index:int
    def __post_init__(self):
        if type(self.group)is not DestroyDamagedFrozenGroup:raise ValueError('Freeze member requires its complete original group')
        self.group.__post_init__();_integer(self.index,'original freeze member index',0)
        if self.index>=len(self.group.members):raise ValueError('Freeze index is outside its original group')


def validate_frozen_group(state,registry,request):
    request.__post_init__();group=request.group if type(request)is FreezeOriginalGroupMember else request
    from .spell_casts import cast_record
    cast=cast_record(state,group.cast_id)
    if ((cast.source_id,cast.player_id,cast.target_id)!=(group.source_id,group.player_id,group.target.entity_id)
            or not cast.payload_started or cast.completed or cast.interrupted or registry.card(cast.card_id).kind!=CardType.SPELL):
        raise ValueError('Frozen group borrowed another original active spell or target')
    if group.source_id not in state.entities:raise ValueError('Frozen group has an unknown physical spell source')
    refs=group.members if type(group)is DestroyDamagedFrozenGroup else(group.target,)
    for ref in refs:
        entity=state.entities.get(ref.entity_id)
        if(entity is None or registry.card(ref.card_id).kind!=CardType.MINION or ref.zone_epoch>entity.zone_epoch
                or ref.entered_order>=state.next_order):
            raise ValueError('Frozen group contains an unknown or future original minion')


def freeze_adjacent(r,request):
    require_cast(r,request);validate_frozen_group(r.state,r.registry,request)
    primary=live_minion(r.state,request.target)
    if primary is None:r.stale(request,request.target.entity_id);return ()
    board=r.state.players[primary.controller].board;index=board.index(primary.id)
    members=tuple(MinionReference.capture(entity)for eid in board[max(0,index-1):index+2]
        for entity in(r.state.entities[eid],)if entity.kind==CardType.MINION and entity.active and entity.health>0 and not entity.doomed)
    group=DestroyDamagedFrozenGroup(request.player_id,request.cast_id,request.source_id,request.target,members)
    return(*(FreezeOriginalGroupMember(group,index)for index in range(len(members))),group)


def freeze_original_member(r,request):
    validate_frozen_group(r.state,r.registry,request);ref=request.group.members[request.index]
    if live_minion(r.state,ref)is None:r.stale(request,ref.entity_id);return ()
    from .resolver import freeze_character
    freeze_character(r,Freeze(ref.entity_id,request.group.source_id));return ()


def destroy_damaged_group(r,request):
    validate_frozen_group(r.state,r.registry,request)
    targets=tuple(ref.entity_id for ref in request.members
        if(entity:=live_minion(r.state,ref))is not None and entity.damage>0)
    return(DestroyBatch(targets,request.source_id),)if targets else()


def select(r,ids,count,source_id):
    ordered=tuple(sorted(ids))
    selected=tuple(r.game._rng.sample(ordered,count))if len(ordered)>count else ordered
    for eid in selected:r.emit('random_choice',source_id=source_id,target_id=eid,candidates=ordered)
    return selected


def freeze_random(r,request):
    require_cast(r,request)
    ids=tuple(eid for eid in minions(r)if r.state.entities[eid].controller==3-request.player_id)
    selected=select(r,ids,request.count,request.source_id)
    return tuple(FreezeSelectedEnemy(request.player_id,request.cast_id,request.source_id,
        MinionReference.capture(r.state.entities[eid]))for eid in selected)


def freeze_selected(r,request):
    require_cast(r,request);r.registry.card(request.target.card_id)
    if live_minion(r.state,request.target)is None:
        r.stale(request,request.target.entity_id);return ()
    from .resolver import freeze_character
    freeze_character(r,Freeze(request.target.entity_id,request.source_id))
    return ()


def matches_primary(entity,fact):
    return entity is not None and(entity.id,entity.card_id,entity.kind,entity.owner,entity.controller,entity.zone,entity.zone_epoch,entity.entered_order)==(
        fact.entity_id,fact.card_id,fact.kind,fact.owner,fact.controller,fact.zone,fact.zone_epoch,fact.entered_order)


def damage_with_others(r,request):
    require_cast(r,request);validate_allocation(r.state,r.registry,request.primary)
    primary=r.live_character(request.primary.entity_id)
    if not matches_primary(primary,request.primary)or primary.health<=0 or primary.doomed:
        r.stale(request,request.primary.entity_id);return ()
    enemy=r.player(3-request.player_id)
    ids=tuple(eid for eid in(enemy.hero_id,*enemy.board)if eid!=primary.id and(e:=r.live_character(eid))is not None and e.health>0 and not e.doomed)
    selected=select(r,ids,request.count,request.source_id)
    hits=(Damage(primary.id,request.primary_amount,request.source_id,DamageKind.SPELL),
        *(Damage(eid,request.other_amount,request.source_id,DamageKind.SPELL)for eid in selected))
    from .resolver import settle_health_batch
    return settle_health_batch(r,hits)


def random_damage_draw(r,request):
    require_cast(r,request)
    ids=tuple(eid for eid in minions(r)if r.state.entities[eid].controller==3-request.player_id)
    selected=select(r,ids,request.count,request.source_id)
    if not selected:return ()
    from .resolver import settle_health_batch
    batch_id=len(r.game._events)+1
    work=settle_health_batch(r,tuple(Damage(eid,request.amount,request.source_id,DamageKind.SPELL)for eid in selected))
    return(*work,DrawSpellBatchDeaths(request.player_id,request.cast_id,request.source_id,batch_id))


def register(mechanics):
    mechanics.register(FreezeRandomEnemyMinions,freeze_random)
    mechanics.register(FreezeSelectedEnemy,freeze_selected)
    mechanics.register(DamageEnemyAndRandomOthers,damage_with_others)
    mechanics.register(RandomMinionDamageDrawDeaths,random_damage_draw)
    mechanics.register(FreezeAdjacentThenDestroyDamaged,freeze_adjacent)
    mechanics.register(FreezeOriginalGroupMember,freeze_original_member)
    mechanics.register(DestroyDamagedFrozenGroup,destroy_damaged_group)
