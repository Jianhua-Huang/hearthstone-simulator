"""Finite native appendages retained after the original Colossal entry finishes."""
from dataclasses import dataclass,fields,replace

from .effects import Effect,_integer
from .model import CardType,Keyword,Zone
from .sacrifice import MinionReference,live_minion

KIND='colossal_reserve'
RESET='colossal_reserve_opened'
SPENT='colossal_reserve_spent'


@dataclass(frozen=True)
class ColossalReserveProfile:
    card_id:str


def validate_profile(registry,profile):
    if type(profile)is not ColossalReserveProfile:raise ValueError('Typed finite Colossal declaration required')
    card=registry.card(profile.card_id)
    if (card.kind!=CardType.MINION or card.choice_only or not card.colossal or
            Keyword.COLOSSAL not in card.keywords or any(s.side!='right'for s in card.colossal)):
        raise ValueError('Finite Colossal reserve requires an original right-sided native expansion')


def validate_ability(ability):
    allowed={'id','kind','source_id','origin','colossal_reserve_card_id','colossal_remaining'}
    if (ability.kind!=KIND or ability.origin!='printed' or ability.source_id is None or ability.consumed or
            type(ability.colossal_reserve_card_id)is not str or not ability.colossal_reserve_card_id or
            any(getattr(ability,f.name)!=f.default for f in fields(ability)if f.name not in allowed)):
        raise ValueError('Finite appendages require a pure original printed reserve')
    _integer(ability.colossal_remaining,'remaining native appendages',0)


def source(entity):
    return next((a for a in entity.abilities if a.kind==KIND and not a.consumed),None)


def validate_carrier(registry,card_id,kind,abilities,components=()):
    rows=[a for a in abilities if a.kind==KIND]
    if len(rows)>1:raise ValueError('One physical minion cannot duplicate its finite appendage reserve')
    for a in rows:
        a.__post_init__();profile=registry.colossal_reserve_profiles.get(a.colossal_reserve_card_id)
        if (profile is None or kind!=CardType.MINION or a.colossal_reserve_card_id not in(card_id,*components)or
                a.colossal_remaining>len(registry.card(profile.card_id).colossal)):
            raise ValueError('Finite appendages borrowed another native carrier or exceeded its reserve')


def reset_entry(r,entity):
    native=source(entity)
    if native is None:return
    total=len(r.registry.card(native.colossal_reserve_card_id).colossal)
    entity.abilities[entity.abilities.index(native)]=replace(native,colossal_remaining=total)
    r.emit(RESET,source_id=entity.id,player_id=entity.controller,ability_id=native.id,
           card_id=native.colossal_reserve_card_id,before=native.colossal_remaining,remaining=total)


def debit(r,body,limb):
    native=source(body)
    if native is None:return  # Already accepted initial limbs survive source Silence.
    definition=r.registry.card(native.colossal_reserve_card_id)
    before=native.colossal_remaining;index=len(definition.colossal)-before
    if before<=0 or definition.colossal[index].card_id!=limb.card_id:
        raise ValueError('Appendage entry changed its original finite reserve order')
    body.abilities[body.abilities.index(native)]=replace(native,colossal_remaining=before-1)
    r.emit(SPENT,source_id=body.id,target_id=limb.id,player_id=body.controller,ability_id=native.id,
           card_id=definition.id,before=before,remaining=before-1,index=index,
           limb_card_id=limb.card_id,limb_order=limb.entered_order)


@dataclass(frozen=True)
class RefillColossalAppendage(Effect):
    source:MinionReference
    ability_id:int
    remaining:int

    @property
    def source_id(self):return self.source.entity_id

    def __post_init__(self):
        if type(self.source)is not MinionReference:raise ValueError('Appendage refill requires its original board residence')
        self.source.__post_init__();_integer(self.ability_id,'original appendage reserve',1)
        _integer(self.remaining,'accepted remaining appendages',1)


def eligible(state,registry,rules):
    if not registry.colossal_reserve_profiles:return ()
    opening={x.entity_id for x in state.colossal_history if not x.completed}
    return tuple(e for i in rules.entity_order(state,[i for p in state.players.values()for i in p.board])
        for e in (state.entities[i],) if i not in opening and e.kind==CardType.MINION and e.active and
        e.health>0 and not e.doomed and not e.silenced and source(e)is not None and
        source(e).colossal_remaining>0 and len(state.players[e.controller].board)<rules.max_board)


def deathrattles_pending(state):
    return any(not d.completed and not d.interrupted for d in state.deathrattle_history)


def schedule(r,queue,continuation,triggers):
    """One ordinary reaction unit; the next checkpoint reevaluates real capacity."""
    if not r.registry.colossal_reserve_profiles or r.state.status!='playing' or r.death_deferrals:return ()
    if not any(source(r.state.entities[i])is not None for p in r.state.players.values()for i in p.board):return ()
    if deathrattles_pending(r.state):return ()
    pending={w.source for w in (*queue,*continuation,*triggers)if type(w)is RefillColossalAppendage}
    for body in eligible(r.state,r.registry,r.rules):
        ref=MinionReference.capture(body)
        if ref in pending:continue
        a=source(body)
        return (RefillColossalAppendage(ref,a.id,a.colossal_remaining),)
    return ()


def refill(r,work):
    work.__post_init__();body=live_minion(r.state,work.source)
    if body is None or body.silenced or not body.active:return ()
    native=source(body)
    if native is None or(native.id,native.colossal_remaining)!=(work.ability_id,work.remaining):return ()
    if len(r.player(body.controller).board)>=r.rules.max_board:return ()
    spec=r.registry.card(native.colossal_reserve_card_id).colossal[
        len(r.registry.card(native.colossal_reserve_card_id).colossal)-work.remaining]
    previous=[]
    from .hero_health_history import effective_events
    for event in effective_events(r.game._events):
        d=dict(event.data)
        if event.kind==SPENT and event.source_id==body.id and d['ability_id']==native.id:
            limb=r.state.entities.get(event.target_id)
            if limb is not None and limb.zone==Zone.BOARD and limb.controller==body.controller and limb.entered_order==d['limb_order']:
                previous.append(limb.id)
    from .colossal import create_appendage
    limb=create_appendage(r,body,spec,previous)
    debit(r,body,limb)
    r.emit('minion_summoned',source_id=limb.id,target_id=limb.id,player_id=body.controller)
    return ()


def public_remaining(entity):
    a=source(entity)
    return None if a is None else a.colossal_remaining


def validate_game(game):
    if not game.registry.colossal_reserve_profiles:return
    from .hero_health_history import effective_events
    events=tuple(effective_events(game._events));last={};children=set()
    for event in events:
        if event.kind not in (RESET,SPENT):continue
        d=dict(event.data);key=(event.source_id,d['ability_id'])
        _integer(d['ability_id'],'original finite attachment',1)
        _integer(d['remaining'],'remaining finite appendages',0)
        profile=game.registry.colossal_reserve_profiles.get(d['card_id'])
        if profile is None:raise ValueError('Finite reserve event lost its original native declaration')
        spec=game.registry.card(profile.card_id).colossal;total=len(spec)
        _integer(d['before'],'previous finite appendages',0)
        if d['before']>total:raise ValueError('Finite appendages exceeded their original declaration')
        if event.kind==RESET:
            if d['remaining']!=total:raise ValueError('Fresh Colossal entry lost its complete original reserve')
        else:
            _integer(d['index'],'original finite appendage ordinal',0)
            _integer(d['limb_order'],'original finite appendage birth',1)
            index=total-d['before']
            if (d['before']<=0 or d['remaining']!=d['before']-1 or d['index']!=index or
                    d['limb_card_id']!=spec[index].card_id or key in last and last[key]!=d['before'] or
                    event.target_id in children or event.target_id not in game._state.entities or
                    not any(e.sequence>event.sequence and e.kind=='minion_summoned'and
                        (e.source_id,e.target_id,e.player_id)==(event.target_id,event.target_id,event.player_id)for e in events)):
                raise ValueError('Finite appendage debit changed its original successful physical entry')
            children.add(event.target_id)
        last[key]=d['remaining']
    for entity in game._state.entities.values():
        validate_carrier(game.registry,entity.card_id,entity.kind,entity.abilities,entity.components)
        a=source(entity)
        if (entity.card_id in game.registry.colossal_reserve_profiles and not entity.silenced and
                entity.zone in (Zone.HAND,Zone.DECK,Zone.BOARD)and a is None):
            raise ValueError('Native finite Colossal lost its complete original reserve')
        if a is not None and (entity.id,a.id)in last and a.colossal_remaining!=last[(entity.id,a.id)]:
            raise ValueError('Native appendage counter differs from its actual complete debits')
    frame=game._frame
    ready=eligible(game._state,game.registry,game.ruleset)
    if frame is not None:
        pending=[]
        for w in (*frame.prefix,*frame.continuation):
            if type(w)is not RefillColossalAppendage:continue
            pending.append(w)
            w.__post_init__();entity=game._state.entities.get(w.source.entity_id)
            a=source(entity)if entity is not None else None
            if a is not None and a.id==w.ability_id and w.remaining!=a.colossal_remaining:
                raise ValueError('Pending appendage refill changed its accepted reserve')
        if len(pending)!=len(set(pending)):raise ValueError('Waiting boundary duplicated an original appendage refill')
        if (ready and not frame.death_deferrals and not deathrattles_pending(game._state)and
                not any(w.source==MinionReference.capture(e)for e in ready for w in pending)):
            raise ValueError('Waiting boundary omitted its owed native appendage refill')
    elif (ready and game._state.action_number>0 and game._state.status=='playing'and
            not deathrattles_pending(game._state)):
        raise ValueError('Native appendage refill disappeared before resolution settled')


def register(mechanics):mechanics.register(RefillColossalAppendage,refill)
