"""Whole SPELL budget, dynamic unit packets, and real interpreter tails.

The numeric profile is explicit local policy. CN multiplier/conversion timing
still needs calibration; no real-card adapter is supplied here.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
import json, random
from .effects import Damage, Effect, RequestChoice, _integer, _player
from .errors import ResolutionError
from .model import (AbilityInstance, CardType, DamageKind, GameState, Keyword,
    PlayerEffect, SpellCastRecord, SpellSchool, Zone, _name)
from .resource_operations import SourceAllocationFact

PROFILE = 'spell_bonus_once_unit_packets'
NON_SPELL_PROFILE = 'non_spell_unit_packets'

@dataclass(frozen=True)
class SplitDamageScope:
    relation: str = 'enemy'
    kinds: tuple[CardType, ...] = (CardType.HERO, CardType.MINION)
    def __post_init__(self):
        if self.relation not in ('any', 'friendly', 'enemy'): raise ValueError('Unsupported split relation')
        if (type(self.kinds) is not tuple or not self.kinds or len(set(self.kinds)) != len(self.kinds) or
                any(type(k) is not CardType or k not in (CardType.HERO, CardType.MINION) for k in self.kinds)):
            raise ValueError('Split candidates require unique character kinds')

@dataclass(frozen=True)
class RandomSplitDamage(Effect):
    player_id: int
    cast_id: int | None
    source_id: int
    amount: int
    scope: SplitDamageScope = SplitDamageScope()
    on_result: str | None = None
    on_complete: str | None = None
    profile: str = PROFILE
    kind: DamageKind = DamageKind.SPELL
    def __post_init__(self):
        _player(self.player_id)
        if type(self.kind)is not DamageKind:raise ValueError('Split damage requires an exact damage kind')
        _integer(self.source_id,'source_id',1)
        _integer(self.amount,'whole split base budget',0)
        if type(self.scope) is not SplitDamageScope: raise ValueError('Split scope requires exact typed declaration')
        self.scope.__post_init__()
        if self.profile == PROFILE:
            _integer(self.cast_id,'cast_id',1)
            if self.kind != DamageKind.SPELL: raise ValueError('SPELL split requires its real cast and damage kind')
        elif self.profile == NON_SPELL_PROFILE:
            if self.cast_id is not None or type(self.kind)is not DamageKind or self.kind not in (DamageKind.MINION_ABILITY,DamageKind.EFFECT):
                raise ValueError('Non-spell split requires its explicit non-cast minion/location profile')
        else: raise ValueError('Unsupported whole split profile')
        for name in ('on_result','on_complete'):
            if getattr(self,name) is not None: _name(getattr(self,name),'split callback')

@dataclass(frozen=True)
class SplitBonusContribution:
    allocation: SourceAllocationFact | None
    ability: AbilityInstance | None
    player_effect: PlayerEffect | None
    amount: int
    def __post_init__(self):
        _integer(self.amount,'split contribution',0)
        if self.player_effect is not None:
            if type(self.player_effect) is not PlayerEffect or self.ability is not None or self.allocation is not None:
                raise ValueError('Player bonus cannot borrow a physical ability')
        elif (type(self.allocation) is not SourceAllocationFact or type(self.ability) is not AbilityInstance or
                self.ability.kind != 'spell_damage' or self.ability.consumed or self.ability.spell_damage != self.amount):
            raise ValueError('Physical split bonus requires its original live ability')

@dataclass(frozen=True)
class SplitBudgetQuote:
    cast: SpellCastRecord | None
    source: SourceAllocationFact
    source_keywords: tuple[Keyword, ...]
    school: SpellSchool | None
    contributions: tuple[SplitBonusContribution, ...]
    spell_bonus: int
    budget: int
    action: int
    root_action: int
    event_cursor: int
    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact:
            raise ValueError('Split quote needs its allocated original source')
        self.source.__post_init__()
        if self.cast is None:
            if self.source.kind not in (CardType.MINION,CardType.LOCATION) or self.contributions or self.spell_bonus:
                raise ValueError('Non-spell quote cannot borrow a CAST or Spell Damage')
        elif type(self.cast)is not SpellCastRecord:
            raise ValueError('Split quote needs its exact original CAST')
        else:self.cast.__post_init__()
        if self.cast is not None and (self.source.kind != CardType.SPELL or self.cast.source_id != self.source.entity_id or
                self.cast.card_id != self.source.card_id or self.cast.player_id != self.source.controller or
                not self.cast.payload_started or self.cast.completed or self.cast.interrupted or self.cast.failure is not None):
            raise ValueError('Split quote is not an original active SPELL payload')
        if (type(self.source_keywords) is not tuple or len(set(self.source_keywords)) != len(self.source_keywords) or
                any(type(k) is not Keyword for k in self.source_keywords)):
            raise ValueError('Invalid original source keywords')
        if self.school is not None and type(self.school) is not SpellSchool: raise ValueError('Invalid original spell school')
        if type(self.contributions) is not tuple or any(type(c) is not SplitBonusContribution for c in self.contributions):
            raise ValueError('Split bonus requires ordered original contributors')
        for c in self.contributions:
            c.__post_init__()
            if c.ability is not None and c.ability.spell_damage_schools and self.school not in c.ability.spell_damage_schools:
                raise ValueError('Split original contribution does not match its accepted spell school')
        for n in ('spell_bonus','budget','action','root_action','event_cursor'): _integer(getattr(self,n),n,0)
        if self.spell_bonus != sum(c.amount for c in self.contributions) or self.root_action > self.action:
            raise ValueError('Split original numeric budget disagrees')

@dataclass(frozen=True)
class SplitCandidate:
    allocation: SourceAllocationFact
    health: int
    def __post_init__(self):
        if type(self.allocation) is not SourceAllocationFact: raise ValueError('Candidate requires exact original allocation')
        self.allocation.__post_init__(); _integer(self.health,'candidate live health',1)
        if self.allocation.kind not in (CardType.HERO,CardType.MINION) or self.allocation.zone != (
                Zone.HERO if self.allocation.kind == CardType.HERO else Zone.BOARD):
            raise ValueError('Split candidates must be original in-play characters')

@dataclass(frozen=True)
class SplitSelection:
    candidates: tuple[SplitCandidate, ...]
    selected: SplitCandidate | None
    rng_before: tuple
    rng_after: tuple
    def __post_init__(self):
        if type(self.candidates) is not tuple or any(type(c) is not SplitCandidate for c in self.candidates):
            raise ValueError('Split pool requires physical candidate rows')
        for c in self.candidates: c.__post_init__()
        ids = [c.allocation.entity_id for c in self.candidates]
        if ids != sorted(set(ids)): raise ValueError('Split pool must contain one sorted weight per physical target')
        if (self.selected is None) != (not self.candidates) or self.selected is not None and self.selected not in self.candidates:
            raise ValueError('Split selection is outside its recorded complete pool')
        probe=random.Random(); probe.setstate(self.rng_before)
        chosen=probe.choice(self.candidates) if self.candidates else None
        if chosen != self.selected or probe.getstate() != self.rng_after:
            raise ValueError('Split selection differs from exactly one recorded RNG choice')

@dataclass(frozen=True)
class SplitPacketLink:
    root_id: int
    index: int
    def __post_init__(self):
        _integer(self.root_id,'split root',1); _integer(self.index,'split packet index',1)

@dataclass(frozen=True)
class SplitPacketReceipt:
    link: SplitPacketLink
    selection: SplitSelection
    result_events: tuple[int, ...] = ()
    completed: bool = False
    source: SourceAllocationFact | None = None
    source_keywords: tuple[Keyword, ...] = ()
    def __post_init__(self):
        if type(self.link) is not SplitPacketLink or type(self.selection) is not SplitSelection:
            raise ValueError('Packet requires original link and selection')
        self.link.__post_init__(); self.selection.__post_init__()
        if self.selection.selected is None: raise ValueError('Empty pool cannot allocate a damage packet')
        if type(self.result_events) is not tuple or list(self.result_events) != sorted(set(self.result_events)):
            raise ValueError('Packet result identities must be ordered unique events')
        for i in self.result_events: _integer(i,'packet health result event',1)
        if type(self.completed) is not bool: raise ValueError('Packet completion must be boolean')
        if self.source is not None:
            if type(self.source)is not SourceAllocationFact:raise ValueError('Split unit needs an original physical source')
            self.source.__post_init__()
        if (type(self.source_keywords)is not tuple or len(set(self.source_keywords))!=len(self.source_keywords) or
                any(type(k)is not Keyword for k in self.source_keywords) or self.source is None and self.source_keywords):
            raise ValueError('Split unit source keywords need their original source fact')

@dataclass(frozen=True)
class SplitDamageRoot:
    id: int
    parent_id: int | None
    request: RandomSplitDamage
    quote: SplitBudgetQuote
    packets: tuple[SplitPacketReceipt, ...] = ()
    empty_selection: SplitSelection | None = None
    completed: bool = False
    interrupted: bool = False
    reason: str | None = None
    def __post_init__(self):
        _integer(self.id,'split root identity',1)
        if self.parent_id is not None:
            _integer(self.parent_id,'split parent',1)
            if self.parent_id >= self.id: raise ValueError('Split parent must precede child')
        if type(self.request) is not RandomSplitDamage or type(self.quote) is not SplitBudgetQuote:
            raise ValueError('Split root requires full original request and budget quote')
        self.request.__post_init__(); self.quote.__post_init__()
        spell = self.request.profile == PROFILE
        if (self.quote.budget != self.request.amount+self.quote.spell_bonus or
                self.request.source_id != self.quote.source.entity_id or
                spell and (self.quote.cast is None or (self.request.cast_id,self.request.player_id) !=
                (self.quote.cast.id,self.quote.cast.player_id)) or
                not spell and (self.quote.cast is not None or self.quote.source.kind != source_kind(self.request))):
            raise ValueError('Split root differs from its original total budget')
        if type(self.packets) is not tuple or len(self.packets)>self.quote.budget:
            raise ValueError('Split packets exceed original budget')
        for index,p in enumerate(self.packets,1):
            if type(p) is not SplitPacketReceipt or p.link != SplitPacketLink(self.id,index):
                raise ValueError('Split packet identity/order differs from its root')
            p.__post_init__()
            if spell and p.source is not None or not spell and (p.source is None or
                    p.source.entity_id!=self.request.source_id or p.source.kind!=source_kind(self.request)):
                raise ValueError('Split unit source differs from its declared damage profile')
            if index<len(self.packets) and not p.completed: raise ValueError('A later packet overtook original callbacks')
        for n in ('completed','interrupted'):
            if type(getattr(self,n)) is not bool: raise ValueError('Split status flags must be boolean')
        if self.completed and self.interrupted: raise ValueError('Split cannot be finished and interrupted')
        if self.reason not in (None,'exhausted','empty_pool','terminal'): raise ValueError('Unknown split stop reason')
        if self.empty_selection is not None:
            self.empty_selection.__post_init__()
            if self.empty_selection.selected is not None: raise ValueError('Empty split stop selected a target')
        if self.completed and (any(not p.completed for p in self.packets) or
                self.reason=='exhausted' and len(self.packets)!=self.quote.budget or
                self.reason=='empty_pool' and (self.empty_selection is None or len(self.packets)>=self.quote.budget)):
            raise ValueError('Completed split lost its original packet/stop obligations')
        if self.interrupted != (self.reason=='terminal') or self.completed != (self.reason in ('exhausted','empty_pool')):
            raise ValueError('Split completion and reason differ')

@dataclass(frozen=True)
class SplitAcceptanceProof:
    state: GameState
    request: RandomSplitDamage
    quote: SplitBudgetQuote

@dataclass(frozen=True)
class SplitPacketProof:
    state: GameState
    selection: SplitSelection
    root_id: int
    index: int

@dataclass(frozen=True)
class DeliverSplitPacket(Effect):
    root_id: int
    index: int
    def __post_init__(self): SplitPacketLink(self.root_id,self.index)

@dataclass(frozen=True)
class FinishSplitPacket(Effect):
    root_id: int
    index: int
    proof: SplitPacketProof
    def __post_init__(self):
        SplitPacketLink(self.root_id,self.index)
        if type(self.proof) is not SplitPacketProof or (self.proof.root_id,self.proof.index)!=(self.root_id,self.index):
            raise ValueError('Packet tail lost its original selection proof')

@dataclass(frozen=True)
class FinishRandomSplitRoot(Effect):
    root_id: int
    proof: SplitAcceptanceProof
    def __post_init__(self):
        _integer(self.root_id,'split completion root',1)
        if type(self.proof) is not SplitAcceptanceProof: raise ValueError('Root tail lost its original acceptance proof')

CONTROL=(DeliverSplitPacket,FinishSplitPacket,FinishRandomSplitRoot)

def split_candidates(state,registry,player_id,scope):
    _player(player_id)
    if type(scope) is not SplitDamageScope: raise ValueError('Expected typed split scope')
    scope.__post_init__(); rows=[]
    for p in state.players.values():
        if scope.relation=='friendly' and p.id!=player_id or scope.relation=='enemy' and p.id==player_id: continue
        for entity_id in (p.hero_id,*p.board):
            e=state.entities[entity_id]
            if (e.kind not in scope.kinds or not e.active or not e.is_character or e.doomed or e.health<=0 or
                    e.zone!=(Zone.HERO if e.kind==CardType.HERO else Zone.BOARD)): continue
            registry.card(e.card_id)
            rows.append(SplitCandidate(SourceAllocationFact.capture(state,e),e.health))
    return tuple(sorted(rows,key=lambda r:r.allocation.entity_id))

def quote_budget(state,registry,request,root_action,event_cursor):
    from .spell_casts import cast_record,active_cast
    from .health_rules import spell_damage_sources
    request.__post_init__()
    for name in ('on_result','on_complete'):
        if getattr(request,name) is not None: registry.behavior(getattr(request,name))
    source=state.entities.get(request.source_id)
    if request.profile == NON_SPELL_PROFILE:
        if source is None or source.kind!=source_kind(request):
            raise ResolutionError('Non-spell split requires its actual minion/location source')
        definition=registry.card(source.card_id)
        return SplitBudgetQuote(None,SourceAllocationFact.capture(state,source),
            tuple(sorted(source.keywords,key=lambda k:k.value)),definition.spell_school,(),0,
            request.amount,state.action_number,root_action,event_cursor)
    cast=cast_record(state,request.cast_id)
    if source is None or cast!=active_cast(state,request.source_id,request.player_id):
        raise ResolutionError('Split budget needs its real current active CAST')
    definition=registry.card(source.card_id)
    contributions=tuple(SplitBonusContribution(SourceAllocationFact.capture(state,e) if e is not None else None,a,p,amount)
        for e,a,p,amount in spell_damage_sources(state,request.player_id,registry,definition.spell_school,cast_id=cast.id))
    bonus=sum(c.amount for c in contributions)
    return SplitBudgetQuote(cast,SourceAllocationFact.capture(state,source),
        tuple(sorted(source.keywords,key=lambda k:k.value)),definition.spell_school,tuple(contributions),
        bonus,request.amount+bonus,state.action_number,root_action,event_cursor)

def root_record(state,root_id):
    _integer(root_id,'split root lookup',1)
    r=next((r for r in state.split_damage_history if r.id==root_id),None)
    if r is None: raise ValueError('Unknown original split root')
    return r


def closed_root(state,event):
    """The actual completed root for a callback, never a global death delta."""
    from .model import Event
    if type(event)is not Event or event.kind!='split_damage_closed':
        raise ValueError('Split result requires its original completion event')
    data=dict(event.data)
    if len(event.data)!=1 or set(data)!={'root'} or type(data['root'])is not str:
        raise ValueError('Split completion lost its original complete receipt')
    rows={'split_damage_history':[json.loads(data['root'])]};rows_from_dict(rows)
    root=rows['split_damage_history'][0]
    if (root!=root_record(state,root.id) or not root.completed or root.interrupted or
            (event.source_id,event.player_id)!=(root.request.source_id,root.request.player_id)):
        raise ValueError('Split callback borrowed an uncompleted or unrelated root')
    return root


def killed_minions(state,event):
    """Actual deaths whose first fatal transition belongs to this root's units."""
    root=closed_root(state,event);actual={}
    for row in state.damage_history:
        result=row.health_result;link=result.split_packet
        if link is not None and link.root_id==root.id:
            actual[link]=result
    deaths=[]
    for death in state.death_history:
        result=death.cause.health_result if death.cause is not None else None
        if (result is not None and result.damage_dealt>0 and result.split_packet in actual and
                actual[result.split_packet]==result):deaths.append(death)
    return tuple(deaths)

def update(state,old,**values):
    new=replace(old,**values);new.__post_init__()
    state.split_damage_history[state.split_damage_history.index(old)]=new
    return new

def begin(r,request):
    original=deepcopy(r.state)
    quote=quote_budget(original,r.registry,request,r.root_action_number,len(r.game._events))
    parent=next((x.id for x in reversed(r.state.split_damage_history) if not x.completed and not x.interrupted),None)
    root=SplitDamageRoot(r.state.next_split_damage_root_id,parent,request,quote)
    root.__post_init__();r.state.next_split_damage_root_id+=1;r.state.split_damage_history.append(root)
    proof=SplitAcceptanceProof(original,request,quote)
    return ((DeliverSplitPacket(root.id,1),) if quote.budget else ())+(FinishRandomSplitRoot(root.id,proof),)

def packet_source(state,registry,link):
    if type(link) is not SplitPacketLink: raise ValueError('Internal split packet requires typed linkage')
    root=root_record(state,link.root_id);root.__post_init__()
    if (root.completed or root.interrupted or link.index!=len(root.packets) or not root.packets or
            root.packets[-1].completed or root.packets[-1].link!=link):
        raise ValueError('Internal split packet is not the unique active allocated unit')
    if root.request.profile == NON_SPELL_PROFILE:
        packet=root.packets[-1]
        return replace(root.quote,source=packet.source,source_keywords=packet.source_keywords,
            school=registry.card(packet.source.card_id).spell_school)
    if registry.card(root.quote.source.card_id).kind!=CardType.SPELL: raise ValueError('Original split source is not SPELL')
    return root.quote


def source_kind(request):
    return CardType.SPELL if request.kind==DamageKind.SPELL else CardType.MINION if request.kind==DamageKind.MINION_ABILITY else CardType.LOCATION


def unit_source(state,request):
    if request.profile == PROFILE:return None,()
    source=state.entities.get(request.source_id)
    if source is None or source.kind!=source_kind(request):
        raise ResolutionError('Non-spell split unit lost its actual damage source kind')
    return SourceAllocationFact.capture(state,source),tuple(sorted(source.keywords,key=lambda k:k.value))

def deliver(r,effect):
    from .resolver import settle_health_batch
    from .health_outcomes import health_result
    root=root_record(r.state,effect.root_id)
    if (root.completed or root.interrupted or effect.index!=len(root.packets)+1 or
            effect.index>root.quote.budget or any(not p.completed for p in root.packets)):
        raise ResolutionError('Split delivery duplicated or overtook original packet')
    window=deepcopy(r.state);pool=split_candidates(window,r.registry,root.request.player_id,root.request.scope)
    before=r.game._rng.getstate();chosen=r.game._rng.choice(pool) if pool else None
    selection=SplitSelection(pool,chosen,before,r.game._rng.getstate());selection.__post_init__()
    if chosen is None:
        update(r.state,root,empty_selection=selection);return ()
    link=SplitPacketLink(root.id,effect.index)
    source,keywords=unit_source(window,root.request)
    update(r.state,root,packets=(*root.packets,SplitPacketReceipt(link,selection,source=source,source_keywords=keywords)))
    start=len(r.game._events)
    calls=settle_health_batch(r,(Damage(chosen.allocation.entity_id,1,root.request.source_id,root.request.kind,
        on_result=root.request.on_result),),split_link=link)
    event_ids=tuple(e.sequence for e in r.game._events[start:] if
        (v:=health_result(e)) is not None and v.split_packet==link)
    if len(event_ids)!=1: raise ResolutionError('Allocated split unit lost its unique health result')
    root=root_record(r.state,root.id);packet=replace(root.packets[-1],result_events=event_ids)
    update(r.state,root,packets=(*root.packets[:-1],packet))
    return (*calls,FinishSplitPacket(root.id,effect.index,SplitPacketProof(window,selection,root.id,effect.index)))

def validate_acceptance(proof,registry):
    if type(proof) is not SplitAcceptanceProof or type(proof.state) is not GameState: raise ValueError('Invalid split acceptance domain')
    expected=quote_budget(proof.state,registry,proof.request,proof.quote.root_action,proof.quote.event_cursor)
    if expected!=proof.quote: raise ValueError('Split quote differs from full original budget window')

def validate_packet_proof(proof,registry):
    if type(proof) is not SplitPacketProof or type(proof.state) is not GameState: raise ValueError('Invalid split packet window')
    old=root_record(proof.state,proof.root_id)
    if proof.index!=len(old.packets)+1 or any(not p.completed for p in old.packets):
        raise ValueError('Packet proof differs from original ordered allocated prefix')
    proof.selection.__post_init__()
    if split_candidates(proof.state,registry,old.request.player_id,old.request.scope)!=proof.selection.candidates:
        raise ValueError('Split selection truncated or changed its complete original candidate pool')


def validate_unit_source(proof,packet):
    request=root_record(proof.state,proof.root_id).request
    if (packet.source,packet.source_keywords)!=unit_source(proof.state,request):
        raise ValueError('Split unit borrowed source material outside its original delivery window')

def finish_packet(r,effect):
    validate_packet_proof(effect.proof,r.registry)
    root=root_record(r.state,effect.root_id)
    if len(root.packets)!=effect.index or root.packets[-1].completed or root.packets[-1].selection!=effect.proof.selection:
        raise ResolutionError('Split packet tail duplicated or borrowed selection')
    validate_unit_source(effect.proof,root.packets[-1])
    packet=replace(root.packets[-1],completed=True)
    root=update(r.state,root,packets=(*root.packets[:-1],packet))
    return (DeliverSplitPacket(root.id,effect.index+1),) if effect.index<root.quote.budget else ()

def finish_root(r,effect):
    validate_acceptance(effect.proof,r.registry)
    root=root_record(r.state,effect.root_id)
    if root.completed or root.interrupted or root.request!=effect.proof.request or root.quote!=effect.proof.quote or any(not p.completed for p in root.packets):
        raise ResolutionError('Split root finished before its original complete packet tails')
    reason='exhausted' if len(root.packets)==root.quote.budget else 'empty_pool'
    root=update(r.state,root,completed=True,reason=reason)
    event=r.emit('split_damage_closed',source_id=root.request.source_id,player_id=root.request.player_id,
        root=json.dumps(asdict(root),ensure_ascii=False,sort_keys=True,separators=(',',':')),_capture=False)
    return (r.call(root.request.on_complete,root.request.source_id,root.request.player_id,event=event),) if root.request.on_complete else ()

def reject_choice_control(options):
    def scan(effect):
        if type(effect) in CONTROL: raise ValueError('Choice cannot inject split interpreter controls')
        if type(effect) is RequestChoice:
            for option in effect.options:
                for e in option.effects: scan(e)
    for option in options:
        for effect in option.effects: scan(effect)

def validate_state(state,registry):
    _integer(state.next_split_damage_root_id,'split allocator',1)
    if type(state.split_damage_history) is not list: raise ValueError('Split history must be a list')
    previous=0;known={}
    for root in state.split_damage_history:
        if type(root) is not SplitDamageRoot: raise ValueError('Split history needs typed roots')
        root.__post_init__()
        if not previous<root.id<state.next_split_damage_root_id: raise ValueError('Split root exceeds its allocation domain')
        if root.parent_id is not None and root.parent_id not in known: raise ValueError('Split history lost its original parent')
        validate_compact_facts(state,registry,root)
        from .spell_casts import cast_record
        if root.request.profile == PROFILE:
            actual_cast=cast_record(state,root.request.cast_id)
            if replace(actual_cast,completed=False,interrupted=False)!=root.quote.cast:
                raise ValueError('Split quote differs from its real allocated original CAST record')
        a=root.quote.source
        if a.next_entity_id>state.next_entity_id or a.next_order>state.next_order: raise ValueError('Split source exceeds original physical allocation')
        if registry.card(a.card_id).kind!=source_kind(root.request): raise ValueError('Split quote changed original source kind')
        if root.quote.action>state.action_number:
            raise ValueError('Split quote is newer than its original state domain')
        current=state.entities.get(a.entity_id)
        if current is not None and current.owner!=a.owner: raise ValueError('Split source borrowed a different immutable owner')
        if root.interrupted and state.status=='playing': raise ValueError('Playing split root cannot be terminal interrupted')
        for name in ('on_result','on_complete'):
            if getattr(root.request,name) is not None: registry.behavior(getattr(root.request,name))
        previous=root.id;known[root.id]=root

def validate_boundary(game):
    pending=[r for r in game._state.split_damage_history if not r.completed and not r.interrupted]
    queue=(*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    if game._frame is not None: reject_choice_control(game._frame.options)
    if any(type(w) in CONTROL and w.root_id not in {r.id for r in pending} for w in queue):
        raise ValueError('Split continuation contains an orphan/settled interpreter control')
    tails=[w for w in queue if type(w) is FinishRandomSplitRoot]
    if [w.root_id for w in tails]!=[r.id for r in reversed(pending)]:
        raise ValueError('Split original roots and unique real completion tails differ')
    for tail in tails:
        validate_acceptance(tail.proof,game.registry);root=root_record(game._state,tail.root_id)
        if root.request!=tail.proof.request or root.quote!=tail.proof.quote: raise ValueError('Split tail borrowed original root budget')
        old_parent=next((x.id for x in reversed(tail.proof.state.split_damage_history) if not x.completed and not x.interrupted),None)
        if tail.root_id!=tail.proof.state.next_split_damage_root_id or root.parent_id!=old_parent:
            raise ValueError('Split root changed its original allocator or accepting parent')
    for root in pending:
        packets=[w for w in queue if type(w) is FinishSplitPacket and w.root_id==root.id]
        delivery=[w for w in queue if type(w) is DeliverSplitPacket and w.root_id==root.id]
        unfinished=root.packets and not root.packets[-1].completed
        if unfinished:
            if len(packets)!=1 or packets[0].index!=len(root.packets) or delivery:
                raise ValueError('Split pending packet lost its unique finish or has premature next delivery')
            validate_packet_proof(packets[0].proof,game.registry)
            validate_unit_source(packets[0].proof,root.packets[-1])
            if packets[0].proof.selection!=root.packets[-1].selection: raise ValueError('Split pending packet borrowed selection')
            if queue.index(packets[0])>queue.index(next(t for t in tails if t.root_id==root.id)):
                raise ValueError('Split packet follows root completion')
        elif packets or len(delivery)!=1 or delivery[0].index!=len(root.packets)+1:
            raise ValueError('Split root lost its ordered next delivery')

def interrupt(r,queue):
    pending=[x for x in r.state.split_damage_history if not x.completed and not x.interrupted]
    tails=[w for w in queue if type(w) is FinishRandomSplitRoot]
    if [w.root_id for w in tails]!=[x.id for x in reversed(pending)]: raise ResolutionError('Terminal split lost complete original tails')
    for tail in tails:
        validate_acceptance(tail.proof,r.registry);root=root_record(r.state,tail.root_id)
        if root.request!=tail.proof.request or root.quote!=tail.proof.quote:
            raise ResolutionError('Terminal split borrowed another accepted root')
        root=update(r.state,root,interrupted=True,reason='terminal')
        r.emit('split_damage_closed',source_id=root.request.source_id,player_id=root.request.player_id,
            root=json.dumps(asdict(root),ensure_ascii=False,sort_keys=True,separators=(',',':')),_capture=False)

def validate_closed_events(game):
    """The complete outer event domain, never a captured state/earlier proof."""
    from .health_outcomes import health_result
    state,registry,events=game._state,game.registry,game._events
    current={r.id:r for r in state.split_damage_history};closed={};closing_sequence={}
    for event in events:
        if event.kind!='split_damage_closed': continue
        data=dict(event.data)
        if len(event.data)!=1 or set(data)!={'root'} or type(data['root']) is not str:
            raise ValueError('Closed split event requires one compact original root')
        rows={'split_damage_history':[json.loads(data['root'])]};rows_from_dict(rows);root=rows['split_damage_history'][0]
        root.__post_init__()
        if (not(root.completed or root.interrupted) or root.id in closed or root.id>=state.next_split_damage_root_id or
                (event.source_id,event.player_id)!=(root.request.source_id,root.request.player_id) or
                root.quote.event_cursor>=event.sequence or root.quote.action>event.action or
                root.quote.root_action>root.quote.action):
            raise ValueError('Closed split changed original identity, status or event domain')
        if root.id in current and current[root.id]!=root:
            raise ValueError('Closed split event differs from its current complete original receipt')
        if root.id not in current and not any(e.kind=='timeline_rewound' and e.sequence>event.sequence and
                type(dict(e.data).get('event_start')) is int and dict(e.data)['event_start']<=root.quote.event_cursor
                for e in events):
            raise ValueError('Closed split vanished without an actual later Rewind')
        validate_compact_facts(state,registry,root)
        closed[root.id]=root;closing_sequence[root.id]=event.sequence
    all_roots={**closed,**current};observed={}
    for root in all_roots.values():
        active=[old.id for old in all_roots.values() if old.id<root.id and
            old.quote.event_cursor<=root.quote.event_cursor and
            closing_sequence.get(old.id,len(events)+1)>root.quote.event_cursor]
        if root.parent_id!=(max(active) if active else None):
            raise ValueError('Split parent differs from its original active event interval')
    for event in events:
        result=health_result(event)
        if result is None or result.split_packet is None: continue
        link=result.split_packet
        if link.root_id not in all_roots or link.root_id>=state.next_split_damage_root_id:
            raise ValueError('Health result references a missing/future original split root')
        root=all_roots[link.root_id]
        if link.index>len(root.packets): raise ValueError('Health result references an unallocated split packet')
        packet=root.packets[link.index-1];source=packet.source or root.quote.source;selected=packet.selection.selected.allocation
        controller=root.request.player_id if root.request.profile==PROFILE else source.controller
        if ((result.source_id,result.source_card_id,result.source_controller,result.source_zone_epoch,result.source_entered_order)!=
                (source.entity_id,source.card_id,controller,source.zone_epoch,source.entered_order) or
                result.damage_kind!=root.request.kind.value or
                root.request.profile==NON_SPELL_PROFILE and result.spell_bonus!=0 or
                result.original_target_id!=selected.entity_id or event.sequence not in packet.result_events or
                event.sequence<=root.quote.event_cursor or link.root_id in closing_sequence and event.sequence>=closing_sequence[link.root_id]):
            raise ValueError('Split result differs from its original packet/source/event association')
        key=(link.root_id,link.index);observed.setdefault(key,[]).append(event.sequence)
    for root in all_roots.values():
        if root.id in current and (root.completed or root.interrupted) and root.id not in closed:
            raise ValueError('Settled split root lost its original compact closing event')
        for p in root.packets:
            if tuple(observed.get((root.id,p.link.index),()))!=p.result_events or len(p.result_events)!=1:
                raise ValueError('Allocated split packet lost or duplicated its actual health delivery')

def validate_compact_facts(state,registry,root):
    """Bound all original rows, including unselected candidates, in this domain.

    Later face/controller/consumption changes do not rewrite original facts.
    This validates structure and registered semantics, not unsigned provenance.
    """
    def allocation(a):
        a.__post_init__()
        if a.next_entity_id>state.next_entity_id or a.next_order>state.next_order:
            raise ValueError('Split physical fact exceeds original allocation domain')
        if registry.card(a.card_id).kind!=a.kind:
            raise ValueError('Split physical fact changed original registered kind')
        entity=state.entities.get(a.entity_id)
        if entity is not None and entity.owner!=a.owner:
            raise ValueError('Split physical fact borrowed immutable owner')
    allocation(root.quote.source)
    if registry.card(root.quote.source.card_id).spell_school!=root.quote.school:
        raise ValueError('Split quote changed its original registered spell school')
    seen=set()
    for c in root.quote.contributions:
        c.__post_init__()
        if c.allocation is not None:
            allocation(c.allocation);c.ability.__post_init__()
            if c.allocation.kind==CardType.SPELL:
                from .spell_casts import cast_record
                actual=cast_record(state,root.quote.cast.id)
                if (c.allocation!=root.quote.source or c.ability not in root.quote.cast.local_spell_damage or
                        actual.local_spell_damage!=root.quote.cast.local_spell_damage):
                    raise ValueError('Split bonus differs from its original local CAST ability')
            elif (c.allocation.controller!=root.request.player_id or
                    c.allocation.kind not in (CardType.HERO,CardType.MINION) or
                    c.allocation.zone!=(Zone.HERO if c.allocation.kind==CardType.HERO else Zone.BOARD)):
                raise ValueError('Split bonus borrowed another original carrier scope')
            identity=c.ability.id
        else:
            e=c.player_effect;e.__post_init__()
            spec=registry.player_effect(e.spec_id)
            if (spec.spell_damage!=c.amount or
                    spec.kind=='next_spell_damage' and e not in root.quote.cast.spell_damage_effects or
                    e.source_id>=state.next_entity_id or e.entered_order>=state.next_order or
                    e.created_turn>state.turn):
                raise ValueError('Split bonus changed its original registered player effect')
            registry.card(e.source_card_id);identity=e.id
        if identity>=state.next_attachment_id or identity in seen:
            raise ValueError('Split bonus duplicated or exceeded original attachment allocation')
        seen.add(identity)
    for p in root.packets:
        if p.source is not None:allocation(p.source)
        for row in p.selection.candidates:
            a=row.allocation;allocation(a)
            if (a.kind not in root.request.scope.kinds or
                    root.request.scope.relation=='friendly' and a.controller!=root.request.player_id or
                    root.request.scope.relation=='enemy' and a.controller==root.request.player_id):
                raise ValueError('Split candidate changed its original declared scope')
    for name in ('on_result','on_complete'):
        if getattr(root.request,name) is not None:registry.behavior(getattr(root.request,name))

def rows_from_dict(value):
    from .serialization import _row,_list,end_turn_rng_from_json,_spell_cast_from_dict
    def allocation(v):
        row=_row(v,SourceAllocationFact);row['kind']=CardType(row['kind']);row['zone']=Zone(row['zone'])
        return SourceAllocationFact(**row)
    def scope(v):
        row=_row(v,SplitDamageScope);row['kinds']=tuple(CardType(k) for k in row['kinds']);return SplitDamageScope(**row)
    def selection(v):
        row=_row(v,SplitSelection)
        def candidate(v):
            c=_row(v,SplitCandidate);c['allocation']=allocation(c['allocation']);return SplitCandidate(**c)
        row['candidates']=tuple(candidate(v) for v in row['candidates']);row['selected']=candidate(row['selected']) if row['selected'] is not None else None
        row['rng_before']=end_turn_rng_from_json(row['rng_before']);row['rng_after']=end_turn_rng_from_json(row['rng_after']);return SplitSelection(**row)
    result=[]
    for v in _list(value['split_damage_history'],'split history'):
        row=_row(v,SplitDamageRoot);request=_row(row['request'],RandomSplitDamage);request['scope']=scope(request['scope']);request['kind']=DamageKind(request['kind']);row['request']=RandomSplitDamage(**request)
        quote=_row(row['quote'],SplitBudgetQuote)
        quote['cast']=_spell_cast_from_dict(quote['cast']) if quote['cast'] is not None else None;quote['source']=allocation(quote['source']);quote['source_keywords']=tuple(Keyword(k) for k in quote['source_keywords'])
        if quote['school'] is not None:quote['school']=SpellSchool(quote['school'])
        contributions=[]
        for c in quote['contributions']:
            c=_row(c,SplitBonusContribution)
            if c['allocation'] is not None:c['allocation']=allocation(c['allocation'])
            if c['ability'] is not None:
                from .serialization import _ability_from_dict
                c['ability']=_ability_from_dict(c['ability'])
            if c['player_effect'] is not None:
                from .serialization import player_effect_from_dict
                c['player_effect']=player_effect_from_dict(c['player_effect'])
            contributions.append(SplitBonusContribution(**c))
        quote['contributions']=tuple(contributions);row['quote']=SplitBudgetQuote(**quote);packets=[]
        for v in row['packets']:
            p=_row(v,SplitPacketReceipt);p['link']=SplitPacketLink(**_row(p['link'],SplitPacketLink));p['selection']=selection(p['selection']);p['result_events']=tuple(p['result_events']);p['source']=allocation(p['source']) if p['source'] is not None else None;p['source_keywords']=tuple(Keyword(k) for k in p['source_keywords']);packets.append(SplitPacketReceipt(**p))
        row['packets']=tuple(packets)
        if row['empty_selection'] is not None:row['empty_selection']=selection(row['empty_selection'])
        result.append(SplitDamageRoot(**row))
    value['split_damage_history']=result

def register(mechanics):
    for effect,handler in ((RandomSplitDamage,begin),(DeliverSplitPacket,deliver),(FinishSplitPacket,finish_packet),(FinishRandomSplitRoot,finish_root)):
        mechanics.register(effect,handler)
    for kind in (SplitDamageScope,SplitBonusContribution,SplitBudgetQuote,SplitCandidate,SplitSelection,
            SplitPacketLink,SplitPacketReceipt,SplitDamageRoot,SplitAcceptanceProof,SplitPacketProof):
        mechanics.register_payload_type(kind)
