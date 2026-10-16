"""Resumable entry expansion; bodies and appendages remain independent minions."""
from dataclasses import dataclass, replace

from .effects import Effect, _behavior, _integer, _player
from .errors import ResolutionError
from .model import CardType, ColossalRecord, Keyword, SummonStats, Zone, validate_summon_stats
from .zones import CardReference, reference_entity, reference_value


@dataclass(frozen=True)
class SummonStoredCard(Effect):
    card: CardReference
    player_id: int
    position: int | None = None
    stats: SummonStats | None = None
    cause: object = None
    producer_link: object = None
    on_summon: str | None = None

    def __post_init__(self):
        if self.on_summon is not None:
            _behavior(self.on_summon)
            if self.cause is None: raise ValueError('Stored recruit followup requires original card attribution')
        if self.cause is not None:
            from .summon_quantities import SummonCause
            if type(self.cause)is not SummonCause:raise ValueError('Typed stored movement cause required')
            self.cause.__post_init__()
        if self.producer_link is not None:
            from .recruit_summons import RecruitEntryLink
            if type(self.producer_link)is not RecruitEntryLink or self.cause is None:raise ValueError('Typed attributed original physical selection required')
            self.producer_link.__post_init__()
        reference_value(self.card);_player(self.player_id)
        validate_summon_stats(self.stats)
        if self.position is not None:_integer(self.position,'position',0)


@dataclass(frozen=True)
class SummonAppendage(Effect):
    record_id: int
    index: int

    def __post_init__(self):
        _integer(self.record_id,'colossal record',1);_integer(self.index,'appendage index',0)


@dataclass(frozen=True)
class FinishColossal(Effect):
    record_id: int

    def __post_init__(self):_integer(self.record_id,'colossal record',1)


@dataclass(frozen=True)
class ColossalBattlecry(Effect):
    record_id: int
    play_id: int

    def __post_init__(self):
        _integer(self.record_id,'colossal record',1);_integer(self.play_id,'play record',1)


def record_at(state, record_id):
    if type(record_id) is not int or not 1<=record_id<=len(state.colossal_history):
        raise ValueError('Unknown colossal entry record')
    return state.colossal_history[record_id-1]


def update(state, record, **fields):
    state.colossal_history[record.id-1]=replace(record,**fields)


def announce(r, entity, reason, origin_id=None, copy_mode=None, death_id=None):
    if reason=='transform':return
    data={}
    if reason=='copy':data.update(copied_from=origin_id,copy_mode=copy_mode)
    if reason=='reborn':data.update(reborn_from=origin_id,death_id=death_id)
    if reason=='resurrect':data.update(resurrected_from=origin_id,death_id=death_id)
    r.emit('minion_summoned',source_id=entity.id,target_id=entity.id,player_id=entity.controller,**data)
    if reason=='reborn':
        r.emit('minion_reborn',source_id=origin_id,target_id=entity.id,player_id=entity.controller,death_id=death_id)
    if reason=='resurrect':
        r.emit('minion_resurrected',source_id=origin_id,target_id=entity.id,player_id=entity.controller,death_id=death_id)


def enter_minion(r, entity, reason, *, origin_id=None, copy_mode=None, death_id=None, play_id=None):
    """Called after the source path finishes installing the body's current state."""
    definition=r.registry.card(entity.card_id)
    has_keyword=any(a.kind=='keyword' and a.keyword==Keyword.COLOSSAL and not a.consumed for a in entity.abilities)
    if not definition.colossal or not has_keyword:
        announce(r,entity,reason,origin_id,copy_mode,death_id)
        return []
    record=ColossalRecord(len(r.state.colossal_history)+1,entity.id,entity.card_id,entity.controller,
        r.state.turn,r.state.action_number,entity.entered_order,entity.zone_epoch,reason,
        (None,)*len(definition.colossal),origin_id=origin_id,copy_mode=copy_mode,death_id=death_id,play_id=play_id)
    r.state.colossal_history.append(record)
    return [*(SummonAppendage(record.id,i) for i in range(len(record.limbs))),FinishColossal(record.id)]


def live_body(state, record):
    entity=state.entities[record.entity_id]
    current=next(x.id for x in reversed(state.colossal_history) if x.entity_id==record.entity_id)
    if (entity.zone!=Zone.BOARD or entity.controller!=record.player_id or entity.card_id!=record.card_id or
            entity.entered_order!=record.entered_order or entity.zone_epoch!=record.zone_epoch or
            entity.doomed or entity.health<=0 or current!=record.id):return None
    return entity


def summon_appendage(r, effect):
    record=record_at(r.state,effect.record_id)
    if record.completed:return
    if effect.index!=record.attempted:raise ResolutionError('Out-of-order colossal continuation')
    body=live_body(r.state,record)
    if body is None:
        update(r.state,record,completed=True,canceled=True);return
    spec=r.registry.card(record.card_id).colossal[effect.index]
    player=r.player(record.player_id)
    limb_id=None
    if len(player.board)>=r.rules.max_board:
        r.emit('summon_failed',player_id=player.id,card_id=spec.card_id,reason='board_full')
    else:
        position=player.board.index(body.id)
        if spec.side=='right':
            # Preserve declared order; a removed/transferred previous limb is no anchor.
            previous=[i for n,i in enumerate(record.limbs[:effect.index]) if i in player.board and
                      r.registry.card(record.card_id).colossal[n].side=='right']
            position=max([position]+[player.board.index(i) for i in previous])+1
        limb=r.create_entity(player.id,spec.card_id,Zone.BOARD,position)
        limb_id=limb.id
        r.refresh_auras()
    limbs=list(record.limbs);limbs[effect.index]=limb_id
    update(r.state,record,limbs=tuple(limbs),attempted=effect.index+1)
    if limb_id is not None:
        r.emit('minion_summoned',source_id=limb_id,target_id=limb_id,player_id=player.id)


def finish_colossal(r, effect):
    record=record_at(r.state,effect.record_id)
    if record.completed:return
    if record.attempted!=len(record.limbs):raise ResolutionError('Incomplete colossal expansion')
    body=live_body(r.state,record)
    update(r.state,record,completed=True,canceled=body is None)
    if body is not None:announce(r,body,record.reason,record.origin_id,record.copy_mode,record.death_id)


def summon_stored(r,effect):
    from .summon_quantities import reject_ambiguous
    if effect.cause is None:reject_ambiguous(r)
    else:
        from .recruit_summons import validate_effect
        validate_effect(r.state,r.registry,effect)
    entity=reference_entity(r,effect.card)
    if entity is None:
        if effect.producer_link is not None:
            from .recruit_summons import bind_entry
            bind_entry(r,effect.producer_link)
        return
    if entity.kind!=CardType.MINION:raise ResolutionError('Stored summon requires a minion')
    if effect.cause is not None:
        from .recruit_summons import accept_entry
        return accept_entry(r,effect,entity)
    player=r.player(effect.player_id)
    if len(player.board)>=r.rules.max_board:
        # Hidden source is not revealed or removed by a failed attempt.
        return
    if entity.controller!=player.id:
        getattr(r.player(entity.controller),entity.zone.value).remove(entity.id)
        entity.controller=player.id
        getattr(player,entity.zone.value).append(entity.id)
    r.move(entity,Zone.BOARD,effect.position)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state,entity,effect.stats)
    r.refresh_auras()
    return enter_minion(r,entity,'stored')


def battlecry(r,effect):
    from .lifecycle import active_abilities
    from .play_history import play_record, accept_battlecries
    record=record_at(r.state,effect.record_id);body=live_body(r.state,record)
    play=play_record(r.state,effect.play_id)
    if play.source_id!=record.entity_id or record.reason!='play' or record.play_id!=play.id:
        raise ResolutionError('Invalid colossal battlecry origin')
    if body is None:
        # This delayed phase was reached, but its physical body no longer
        # qualifies. Record an explicit empty root without executing BC/Combo
        # bodies or changing the already completed entry's cancellation facts.
        from .model import BattlecryAcceptanceReceipt
        from .battlecry_matching import capture_recipient
        recipient = capture_recipient(r.state, r.registry, play.source_id)
        accept_battlecries(r.state, play.id, BattlecryAcceptanceReceipt(play.player_id, (), None, recipient))
        from .rewind_outcomes import canceled_combos
        return canceled_combos(r,play_record(r.state,play.id),'colossal_canceled',colossal_record_id=record.id)
    from .rewind_outcomes import payload
    from .battlecries import capture
    return payload(r,body.id,body.controller,play.target_id,
        tuple(a.behavior_id for a in active_abilities(body,'on_play')),play=play,battlecries=capture(body),colossal_record_id=record.id)


def validate_history(state,registry):
    if type(state.colossal_history) is not list:raise ValueError('Colossal history requires a list')
    seen=set();previous=(0,0)
    for index,record in enumerate(state.colossal_history,1):
        if type(record) is not ColossalRecord:raise ValueError('Invalid colossal record')
        record.__post_init__();spec=registry.card(record.card_id).colossal
        if record.play_id is not None:
            from .play_history import play_record
            play=play_record(state,record.play_id)
            if ((play.source_id,play.card_id,play.player_id,play.turn)!=(
                    record.entity_id,record.card_id,record.player_id,record.turn) or play.action>record.action or
                    play.kind!=CardType.MINION or play.minion_result!='summoned'):
                raise ValueError('Colossal play record differs from its precise paid entry root')
        if (record.id!=index or not spec or len(spec)!=len(record.limbs) or record.entity_id not in state.entities or
                record.entered_order>=state.next_order or record.turn>state.turn or record.action>state.action_number or
                (record.turn,record.action)<previous or
                (record.origin_id is not None and record.origin_id not in state.entities)):
            raise ValueError('Invalid colossal provenance')
        if record.death_id is not None and not any(d.id==record.death_id and d.entity_id==record.origin_id and d.card_id==record.card_id for d in state.death_history):
            raise ValueError('Invalid colossal death origin')
        if record.reason=='resurrect' and not any(x.entity_id==record.entity_id and x.death_id==record.death_id
                for x in state.resurrection_history):
            raise ValueError('Missing colossal resurrection provenance')
        last_entity=record.entity_id
        for entity_id in record.limbs:
            if entity_id is not None:
                if entity_id in seen or entity_id not in state.entities or entity_id<=last_entity:
                    raise ValueError('Invalid appendage provenance')
                if state.entities[entity_id].kind!=CardType.MINION or state.entities[entity_id].owner!=record.player_id:
                    raise ValueError('Invalid original appendage owner/type')
                seen.add(entity_id)
                last_entity=entity_id
        previous=(record.turn,record.action)


def validate_boundary(game):
    records=game._state.colossal_history
    pending=[x.id for x in records if not x.completed]
    frame=game._frame
    work=(*frame.prefix,*frame.continuation) if frame else ()
    finishers=[x.record_id for x in work if isinstance(x,FinishColossal)]
    for record_id in finishers:record_at(game._state,record_id)
    if sorted(x for x in finishers if not records[x-1].completed)!=pending:
        raise ValueError('Colossal entries and continuations do not match')
    for record_id in pending:
        record=records[record_id-1]
        indices=[x.index for x in work if isinstance(x,SummonAppendage) and x.record_id==record_id]
        if indices!=list(range(record.attempted,len(record.limbs))):raise ValueError('Invalid remaining appendage sequence')
    for item in work:
        if isinstance(item,SummonAppendage):
            record=record_at(game._state,item.record_id)
            if item.index>=len(record.limbs):raise ValueError('Unknown pending appendage')
        if isinstance(item,ColossalBattlecry):
            from .play_history import play_record
            record=record_at(game._state,item.record_id);play=play_record(game._state,item.play_id)
            if record.reason!='play' or record.play_id!=play.id or (play.source_id,play.card_id,play.player_id)!=(record.entity_id,record.card_id,record.player_id):
                raise ValueError('Invalid pending colossal battlecry')


def register(mechanics):
    for effect,handler in ((SummonStoredCard,summon_stored),(SummonAppendage,summon_appendage),(FinishColossal,finish_colossal),(ColossalBattlecry,battlecry)):
        mechanics.register(effect,handler)
