"""Native extra stats observe actual local attachments, never aura refreshes.

An effect window stores temporary operands only until its handler returns. The
accepted rewards are typed interpreter work; no hidden progress survives waits.
"""
from dataclasses import dataclass,replace
from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Buff,Effect,_integer,_behavior
from .model import AbilityInstance,CardType,Enchantment,Zone

EVENT='native_stat_gain_rewarded'
LABEL='native_stat_gain_reward'


@dataclass(frozen=True)
class NativeStatGainProfile:
    card_id:str
    def __post_init__(self):_behavior(self.card_id)


def validate_profile(registry,profile):
    if type(profile) is not NativeStatGainProfile:raise ValueError('Typed native stat-gain profile required')
    profile.__post_init__()
    if registry.card(profile.card_id).kind!=CardType.MINION:raise ValueError('Native stat gain requires a real minion')


def validate_carrier(registry,card_id,kind,abilities,components=()):
    rows=tuple(a for a in abilities if a.kind=='native_stat_gain')
    if not rows:return
    if kind!=CardType.MINION:raise ValueError('Native stat gain requires a physical minion carrier')
    for row in rows:
        row.__post_init__()
        if row.native_stat_gain_card_id not in registry.native_stat_gain_profiles or row.native_stat_gain_card_id not in (card_id,*components):
            raise ValueError('Native stat gain borrowed an undeclared printed carrier')


def rows(entity):
    if entity.kind!=CardType.MINION or entity.zone==Zone.BOARD and not entity.active:return ()
    return tuple(a for a in entity.abilities if a.kind=='native_stat_gain' and not a.consumed)


def begin(r,work):
    r._native_stat_gain_window={} if r.registry.native_stat_gain_profiles and type(work) is not RewardNativeStatGain else None
    if r._native_stat_gain_window is not None:
        for entity in r.state.entities.values():seed(r,entity)


def seed(r,entity,*,replace_existing=False):
    window=getattr(r,'_native_stat_gain_window',None)
    if window is None:return
    native=rows(entity)
    if native and (replace_existing or entity.id not in window):
        window[entity.id]=(native,frozenset(e.id for e in entity.enchantments))


def values(attack,health,enchantment):
    return (attack+enchantment.attack if enchantment.set_attack is None else enchantment.set_attack,
        health+enchantment.health if enchantment.set_health is None else enchantment.set_health)


@dataclass(frozen=True)
class RewardNativeStatGain(Effect):
    target:SourceAllocationFact
    abilities:tuple[AbilityInstance,...]
    original:Enchantment
    before_attack:int
    before_health:int

    def __post_init__(self):
        if type(self.target) is not SourceAllocationFact or self.target.kind!=CardType.MINION:
            raise ValueError('Stat reward requires its actual physical minion')
        self.target.__post_init__()
        if type(self.abilities) is not tuple or not self.abilities or any(type(a) is not AbilityInstance or a.kind!='native_stat_gain' for a in self.abilities):
            raise ValueError('Stat reward requires its original native ability inventory')
        for a in self.abilities:a.__post_init__()
        ids=tuple(a.id for a in self.abilities)
        if ids!=tuple(sorted(set(ids))):raise ValueError('Reordered or duplicate native stat gain abilities')
        if type(self.original) is not Enchantment or self.original.label==LABEL:raise ValueError('Stat reward cannot reward its own extra')
        self.original.__post_init__();_integer(self.before_attack,'original local Attack');_integer(self.before_health,'original local Health')
        after=values(self.before_attack,self.before_health,self.original)
        if not(after[0]>self.before_attack or after[1]>self.before_health):raise ValueError('Native extra requires an actual positive stat operation')


def finish(r):
    window=getattr(r,'_native_stat_gain_window',None);r._native_stat_gain_window=None
    if window is None:return ()
    result=[]
    for eid,(native,previous) in window.items():
        entity=r.state.entities.get(eid)
        if entity is None:continue
        current=rows(entity);eligible=tuple(a for a in native if a in current)
        if not eligible:continue
        attack,health=entity.base_attack,entity.base_health
        for enchantment in entity.enchantments:
            before=(attack,health);attack,health=values(attack,health,enchantment)
            if enchantment.id not in previous and enchantment.label!=LABEL and (attack>before[0] or health>before[1]):
                result.append(RewardNativeStatGain(SourceAllocationFact.capture(r.state,entity),eligible,enchantment,*before))
    return tuple(result)


def validate_request(state,registry,request):
    request.__post_init__();validate_allocation(state,registry,request.target)
    validate_carrier(registry,request.target.card_id,request.target.kind,request.abilities,
        state.entities[request.target.entity_id].components)
    if request.original.id>=state.next_attachment_id or any(a.id>=state.next_attachment_id for a in request.abilities):
        raise ValueError('Native stat reward borrowed a future attachment')


def receipts(events):
    from .hero_health_history import effective_events
    return {(dict(e.data)['original_id'],dict(e.data)['ability_id']) for e in effective_events(events) if e.kind==EVENT}


def reward(r,request):
    validate_request(r.state,r.registry,request)
    entity=r.state.entities[request.target.entity_id]
    from .resolver import _buff_to
    for ability in request.abilities:
        key=(request.original.id,ability.id)
        if key in receipts(r.game._events):raise ValueError('Native stat gain was already rewarded')
        if ability not in rows(entity):continue
        enchantment=_buff_to(r,Buff(entity.id,1,1,entity.id),entity,notify=False)
        entity.enchantments[-1]=replace(enchantment,label=LABEL)
        r.emit(EVENT,source_id=entity.id,target_id=entity.id,player_id=entity.controller,_capture=False,
            original_id=request.original.id,ability_id=ability.id,card_id=ability.native_stat_gain_card_id,reward_id=enchantment.id)
        kind='stats_changed' if entity.zone==Zone.BOARD else 'stored_card_buffed'
        data=dict(attack_delta=1,health_delta=1)
        if kind=='stats_changed':data['enchantment_id']=enchantment.id
        r.emit(kind,source_id=entity.id,target_id=entity.id,player_id=entity.controller,**data)


def validate_boundary(game):
    from .hero_health_history import effective_events
    seen=set()
    for event in effective_events(game._events):
        if event.kind!=EVENT:continue
        data=dict(event.data)
        if set(data)!={'original_id','ability_id','card_id','reward_id'}:raise ValueError('Incomplete native stat gain receipt')
        for key in ('original_id','ability_id','reward_id'):_integer(data[key],'native stat receipt '+key,1)
        if data['card_id'] not in game.registry.native_stat_gain_profiles or event.source_id!=event.target_id:
            raise ValueError('Native stat gain lost its declared self reward')
        key=(data['original_id'],data['ability_id'])
        if key in seen:raise ValueError('Duplicated committed native stat reward')
        seen.add(key)
    if game._frame is not None:
        pending=set()
        for work in (*game._frame.prefix,*game._frame.continuation):
            if type(work) is not RewardNativeStatGain:continue
            validate_request(game._state,game.registry,work)
            for a in work.abilities:
                key=(work.original.id,a.id)
                if key in seen or key in pending:raise ValueError('Duplicated pending native stat reward')
                pending.add(key)


def register(mechanics):mechanics.register(RewardNativeStatGain,reward)
