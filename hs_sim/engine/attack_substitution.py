"""Finite native attack substitution; every member uses ordinary forced combat.

The original window remains open below its children. Physical member/target
references are accepted once; stale members never select substitutes. Receipts
check local history consistency, not authenticity of an unsigned external save.
"""
from dataclasses import dataclass, replace
import json

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, ForceAttack, _integer
from .model import (ActionWindow, BoardPresenceReference, CardType, CharacterAttackTerminalFact,
                    Event, Zone, _name)

ACCEPTED='attack_substitution_accepted'
ATTEMPT='attack_substitution_attempt'
FINISHED='attack_substitution_finished'
REPLACED='attack_replaced'


@dataclass(frozen=True)
class AttackSubstitutionProfile:
    id: str
    card_id: str
    behavior_id: str
    member_cards: tuple[str, ...]

    def __post_init__(self):
        for n in ('id','card_id','behavior_id'):_name(getattr(self,n),'attack substitution '+n)
        if type(self.member_cards)is not tuple or not self.member_cards or len(set(self.member_cards))!=len(self.member_cards):
            raise ValueError('Attack substitution requires its complete unique member identities')
        for cid in self.member_cards:_name(cid,'attack substitute card')


def validate_profile(registry, profile):
    if type(profile)is not AttackSubstitutionProfile:raise ValueError('Typed attack substitution profile required')
    profile.__post_init__();card=registry.card(profile.card_id)
    if card.kind!=CardType.MINION or sum(t.event=='attack_declared' and t.behavior_id==profile.behavior_id for t in card.triggers)!=1:
        raise ValueError('Attack substitution requires its actual printed attack listener')
    if any(registry.card(cid).kind!=CardType.MINION for cid in profile.member_cards):
        raise ValueError('Attack substitutes must have native minion definitions')


@dataclass(frozen=True)
class SubstituteCandidate:
    source: SourceAllocationFact
    presence: BoardPresenceReference
    active: bool
    health: int
    doomed: bool

    def __post_init__(self):
        if type(self.source)is not SourceAllocationFact or type(self.presence)is not BoardPresenceReference:
            raise ValueError('Attack candidate requires its original allocation and residence')
        self.source.__post_init__();self.presence.__post_init__()
        if self.source.kind!=CardType.MINION or self.source.zone!=Zone.BOARD or self.source.entity_id!=self.presence.entity_id:
            raise ValueError('Attack candidate changed its original board identity')
        if type(self.active)is not bool or type(self.doomed)is not bool or type(self.health)is not int:
            raise ValueError('Attack candidate requires its original presence facts')


@dataclass(frozen=True)
class SubstituteAttempt:
    index: int
    child_window_id: int | None
    action: int
    event_cursor: int

    def __post_init__(self):
        for n in ('index','action','event_cursor'):_integer(getattr(self,n),'attack substitute '+n,0)
        if self.child_window_id is not None:_integer(self.child_window_id,'substitute child window',1)


@dataclass(frozen=True)
class AttackSubstitutionPlan:
    profile_id: str
    source: SourceAllocationFact
    trigger_id: int
    declaration_sequence: int
    window: ActionWindow
    action: int
    event_cursor: int
    candidates: tuple[SubstituteCandidate, ...]
    members: tuple[BoardPresenceReference, ...]
    attempts: tuple[SubstituteAttempt, ...] = ()
    status: str = 'active'

    def __post_init__(self):
        _name(self.profile_id,'attack substitution profile')
        if type(self.source)is not SourceAllocationFact or type(self.window)is not ActionWindow:
            raise ValueError('Substitution requires its original source and accepted window')
        self.source.__post_init__();self.window.__post_init__()
        for n in ('trigger_id','declaration_sequence'):_integer(getattr(self,n),'attack substitution '+n,1)
        for n in ('action','event_cursor'):_integer(getattr(self,n),'attack substitution '+n,0)
        if (self.window.kind!='attack' or self.source.kind!=CardType.MINION or self.source.zone!=Zone.BOARD or
                (self.window.source_id,self.window.player_id)!=(self.source.entity_id,self.source.controller) or
                self.declaration_sequence>self.event_cursor or self.status not in ('active','completed','interrupted')):
            raise ValueError('Substitution changed its original window, source or chronology')
        for values,kind in ((self.candidates,SubstituteCandidate),(self.members,BoardPresenceReference),(self.attempts,SubstituteAttempt)):
            if type(values)is not tuple or any(type(v)is not kind for v in values):raise ValueError('Substitution requires complete immutable material')
            for v in values:v.__post_init__()
        if (not self.members or len(set(self.members))!=len(self.members) or
                len({c.source.entity_id for c in self.candidates})!=len(self.candidates) or
                any(c.source.controller!=self.source.controller for c in self.candidates) or
                len(self.attempts)>len(self.members) or
                tuple(a.index for a in self.attempts)!=tuple(range(len(self.attempts))) or
                self.status=='completed' and len(self.attempts)!=len(self.members)):
            raise ValueError('Substitution cropped or duplicated its accepted members or attempt prefix')
        previous=self.window.id;action=self.action;cursor=self.event_cursor
        for a in self.attempts:
            if a.action<action or a.event_cursor<cursor or a.child_window_id is not None and a.child_window_id<=previous:
                raise ValueError('Substitute attempt changed original chronology')
            if a.child_window_id is not None:previous=a.child_window_id
            action,cursor=a.action,a.event_cursor


@dataclass(frozen=True)
class CheckAttackSubstitutes(Effect):
    profile_id: str
    source: SourceAllocationFact
    trigger_id: int
    event: Event

    def __post_init__(self):
        _name(self.profile_id,'attack substitution profile');_integer(self.trigger_id,'original substitute listener',1)
        if type(self.source)is not SourceAllocationFact or type(self.event)is not Event or self.event.kind!='attack_declared':
            raise ValueError('Substitution requires its original physical attack listener')
        self.source.__post_init__()


@dataclass(frozen=True)
class ContinueAttackSubstitutes(Effect):
    window_id: int
    index: int

    def __post_init__(self):
        _integer(self.window_id,'substitution original window',1);_integer(self.index,'substitution next member',0)


@dataclass(frozen=True)
class SubstituteAttackLink:
    window_id: int
    index: int

    def __post_init__(self):
        _integer(self.window_id,'substitution parent window',1);_integer(self.index,'substitution member slot',0)


def original_listener(context, profile_id):
    """Capture the real printed trigger in the existing detached callback state."""
    if context.event is None or context.event.kind!='attack_declared' or context.event.source_id!=context.source_id:return ()
    from .lifecycle import active_abilities
    source=context.state.entities[context.source_id]
    triggers=[t for t in active_abilities(source,'trigger') if t.event=='attack_declared' and t.origin=='printed']
    # The adapter has exactly one printed attack listener, validated by its profile.
    if len(triggers)!=1:raise ValueError('Native substitution lost its original printed listener')
    return (CheckAttackSubstitutes(profile_id,SourceAllocationFact.capture(context.state,source),triggers[0].id,context.event),)


def eligible(candidate, profile):
    return candidate.source.card_id in profile.member_cards and candidate.active and candidate.health>0 and not candidate.doomed


def validate_plan(state, registry, row):
    p=row.substitution
    if p is None:return
    p.__post_init__();profile=registry.attack_substitution_profiles.get(p.profile_id)
    if profile is None or profile.card_id!=p.source.card_id:raise ValueError('Unknown native substitution source policy')
    validate_profile(registry,profile);validate_allocation(state,registry,p.source)
    if (p.window.id,p.window.source_id,p.window.player_id,p.source.zone_epoch,p.source.entered_order,p.declaration_sequence)!=(
            row.declaration.id,row.declaration.source_id,row.declaration.player_id,row.source_zone_epoch,row.source_entered_order,row.declaration_event_cursor+1):
        raise ValueError('Substitution borrowed another original declaration or source')
    from .character_attacks import selected_window
    if selected_window(row,p.window)!=p.window or p.action>state.action_number or p.trigger_id>=state.next_attachment_id:
        raise ValueError('Substitution changed its selected window or allocator bounds')
    for c in p.candidates:
        validate_allocation(state,registry,c.source)
        if c.presence.presence_id>=state.next_order:raise ValueError('Substitute borrowed a future board residence')
    if p.members!=tuple(c.presence for c in p.candidates if eligible(c,profile)):
        raise ValueError('Substitution cropped or changed its complete accepted candidate selection')
    if (row.terminal is not None and row.terminal.status not in ('replaced','interrupted') or
            p.status=='interrupted' and (row.terminal is None or row.terminal.status!='interrupted')):
        raise ValueError('Substitution changed its original terminal phase')


def check(r, effect):
    from .native_attack_targets import original_event
    from .lifecycle import active_abilities
    from .interrupts import find_window
    from .character_attacks import update
    effect.__post_init__();row=original_event(r.state,effect.event)
    profile=r.registry.attack_substitution_profiles.get(effect.profile_id)
    if profile is None:raise ValueError('Unknown attack substitution policy')
    validate_allocation(r.state,r.registry,effect.source)
    if (row.declaration.source_id,row.source_card_id,row.source_zone_epoch,row.source_entered_order)!=(
            effect.source.entity_id,profile.card_id,effect.source.zone_epoch,effect.source.entered_order):
        raise ValueError('Substitution listener borrowed a different original attacker')
    source=r.state.entities[effect.source.entity_id];window=find_window(r.state,row.declaration.id)
    if row.substitution is not None:raise ValueError('An attack can accept only one substitution')
    if (window is None or source.zone!=Zone.BOARD or not source.active or source.doomed or source.health<=0 or
            (source.card_id,source.zone_epoch,source.entered_order,source.controller)!=(
                effect.source.card_id,effect.source.zone_epoch,effect.source.entered_order,effect.source.controller) or
            not any(t.id==effect.trigger_id and t.origin=='printed' and t.event=='attack_declared' and
                t.behavior_id==profile.behavior_id for t in active_abilities(source,'trigger'))):return ()
    candidates=tuple(SubstituteCandidate(SourceAllocationFact.capture(r.state,e),BoardPresenceReference.capture(r.state,e.id),
        e.active,e.health,e.doomed) for eid in r.state.players[source.controller].board
        for e in (r.state.entities[eid],) if e.kind==CardType.MINION)
    members=tuple(c.presence for c in candidates if eligible(c,profile))
    if not members:return ()
    plan=AttackSubstitutionPlan(profile.id,SourceAllocationFact.capture(r.state,source),effect.trigger_id,effect.event.sequence,
        window,r.state.action_number,len(r.game._events),candidates,members)
    update(r.state,row,substitution=plan)
    from .native_target_acceptance import encode
    r.emit(ACCEPTED,source_id=source.id,target_id=window.target_id,player_id=window.player_id,
           window_id=window.id,plan=encode(r,plan),_capture=False)
    return (ContinueAttackSubstitutes(window.id,0),)


def plan_record(state, window_id):
    from .character_attacks import record
    row=record(state,window_id)
    if row.substitution is None:raise ValueError('Unknown accepted attack substitution')
    return row,row.substitution


def member_request(plan,index):
    target=plan.window.attack_target_presence or plan.window.target_id
    return ForceAttack(plan.members[index],target,plan.window.combat_relation,
        plan.window.excess_to_hero,SubstituteAttackLink(plan.window.id,index))


def member_live(state, plan, index):
    from .board_presence import resolve_board_presence
    from .combat import combat_relation_matches
    ref=plan.members[index];candidate=next(c for c in plan.candidates if c.presence==ref)
    source=resolve_board_presence(state,ref)
    target=(resolve_board_presence(state,plan.window.attack_target_presence) if plan.window.attack_target_presence is not None
            else state.entities.get(plan.window.target_id))
    return (source is not None and target is not None and
        (source.card_id,source.zone_epoch,source.controller)==(candidate.source.card_id,candidate.source.zone_epoch,plan.window.player_id) and
        source.active and target.active and source.health>0 and target.health>0 and not source.doomed and not target.doomed and
        target.zone in (Zone.BOARD,Zone.HERO) and combat_relation_matches(source,target,plan.window.combat_relation))


def continue_members(r, effect):
    from .character_attacks import record,update
    row,p=plan_record(r.state,effect.window_id)
    if p.status!='active' or len(p.attempts)!=effect.index:raise ValueError('Substitution lost its next original member')
    if p.attempts and p.attempts[-1].child_window_id is not None and record(r.state,p.attempts[-1].child_window_id).terminal is None:
        raise ValueError('Substitution advanced before its prior ordinary attack completed')
    if effect.index==len(p.members):
        update(r.state,row,substitution=replace(p,status='completed'))
        r.emit(FINISHED,source_id=p.source.entity_id,target_id=p.window.target_id,player_id=p.window.player_id,
               window_id=p.window.id,_capture=False)
        return ()
    request=member_request(p,effect.index)
    if not member_live(r.state,p,effect.index):
        bind_attempt(r,request,None)
        return (ContinueAttackSubstitutes(effect.window_id,effect.index+1),)
    return (request,ContinueAttackSubstitutes(effect.window_id,effect.index+1))


def validate_link(state, effect):
    if effect.producer_link is None:return
    link=effect.producer_link;row,p=plan_record(state,link.window_id)
    if p.status!='active' or len(p.attempts)!=link.index or link.index>=len(p.members) or effect!=member_request(p,link.index):
        raise ValueError('Forced substitute attack borrowed another producer or accepted member')


def bind_attempt(r, effect, child_window):
    if effect.producer_link is None:return
    from .character_attacks import update
    validate_link(r.state,effect);row,p=plan_record(r.state,effect.producer_link.window_id)
    if child_window is not None and not member_live(r.state,p,effect.producer_link.index):
        raise ValueError('Substitution changed its physical member before attack delivery')
    # A successful child declaration is emitted immediately after this atomic update.
    cursor=len(r.game._events)+(1 if child_window is not None else 0)
    attempt=SubstituteAttempt(effect.producer_link.index,None if child_window is None else child_window.id,r.state.action_number,cursor)
    update(r.state,row,substitution=replace(p,attempts=(*p.attempts,attempt)))
    if child_window is None:emit_attempt(r,p.window.id,attempt)


def emit_attempt(r, parent_id, attempt):
    _,p=plan_record(r.state,parent_id)
    from .native_target_acceptance import encode
    r.emit(ATTEMPT,source_id=p.members[attempt.index].entity_id,target_id=p.window.target_id,player_id=p.window.player_id,
           window_id=parent_id,attempt=encode(r,attempt),_capture=False)


def replace_combat(r, window):
    from .character_attacks import update
    row,p=plan_record(r.state,window.id)
    if p.status!='completed' or row.combat is not None or row.terminal is not None:raise ValueError('Substitution lost its completed original member sequence')
    update(r.state,row,terminal=CharacterAttackTerminalFact('replaced','native_substitution',r.state.action_number,len(r.game._events)))
    r.emit(REPLACED,source_id=window.source_id,target_id=window.target_id,player_id=window.player_id,window_id=window.id,_capture=False)


def validate_queue(state, work):
    from .character_attacks import record
    continuations={};pending={}
    for item in work:
        if type(item)is ContinueAttackSubstitutes:continuations.setdefault(item.window_id,[]).append(item.index)
        if type(item)is ForceAttack and item.producer_link is not None:
            validate_link(state,item);pending.setdefault(item.producer_link.window_id,[]).append(item)
    known={r.declaration.id for r in state.character_attack_history if r.substitution is not None}
    if (set(continuations)|set(pending))-known:raise ValueError('Unknown substitution control tail')
    for row in state.character_attack_history:
        p=row.substitution
        if p is None:continue
        n=len(p.attempts);requests=pending.get(p.window.id,[])
        expected=[n+1 if requests else n] if p.status=='active' else []
        if len(requests)>1 or continuations.get(p.window.id,[])!=expected:
            raise ValueError('Substitution lost its unique original continuation or forced member')
        for a in p.attempts:
            if a.child_window_id is not None:
                child=record(state,a.child_window_id)
                if (a.index<n-1 or requests or p.status=='completed') and child.terminal is None:
                    raise ValueError('Substitution skipped an unfinished child')
        if requests:
            position=next(i for i,x in enumerate(work)if x is requests[0])
            follow=next(i for i,x in enumerate(work)if type(x)is ContinueAttackSubstitutes and x.window_id==p.window.id)
            if position>=follow:raise ValueError('Substitution reordered its member and continuation')


def interrupt(r, queue):
    from .character_attacks import update
    for row in tuple(r.state.character_attack_history):
        if row.substitution is not None and row.substitution.status=='active':
            update(r.state,row,substitution=replace(row.substitution,status='interrupted'))


def validate_boundary(game):
    from .character_attacks import record
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    events=effective_events(game._events);by_seq={e.sequence:e for e in events}
    codec=FrameCodec(game.mechanics,game.registry);accepted={};attempts={};finished=set();children=set()
    for event in events:
        if event.kind not in (ACCEPTED,ATTEMPT,FINISHED):continue
        data=dict(event.data);ident=data.get('window_id');row,p=plan_record(game._state,ident)
        if (event.target_id,event.player_id)!=(p.window.target_id,p.window.player_id):raise ValueError('Substitution receipt changed target or owner')
        if event.kind==ACCEPTED:
            initial=codec.decode(json.loads(data['plan']))
            if ident in accepted or initial!=replace(p,attempts=(),status='active') or (event.sequence,event.action,event.source_id)!=(p.event_cursor+1,p.action,p.source.entity_id):
                raise ValueError('Substitution changed its original acceptance receipt')
            # Only redirections accepted before this listener may enter its target.
            target,reference,relation=row.declaration.target_id,row.declaration.attack_target_presence,row.declaration.combat_relation
            for changed in events:
                if changed.sequence>=event.sequence:break
                if changed.kind=='attack_redirected' and dict(changed.data).get('window_id')==ident:
                    target=changed.target_id;presence=dict(changed.data).get('target_presence_id')
                    reference=None if presence is None else BoardPresenceReference(target,presence)
                    if dict(changed.data).get('native_random_target')is True:relation='opponent'
            if (p.window.target_id,p.window.attack_target_presence,p.window.combat_relation)!=(target,reference,relation):
                raise ValueError('Substitution borrowed a later or unannounced target')
            accepted[ident]=event.sequence
        elif event.kind==ATTEMPT:
            a=codec.decode(json.loads(data['attempt']))
            if ident not in accepted or a.index!=len(attempts.get(ident,[])) or a not in p.attempts or (event.sequence,event.action,event.source_id)!=(a.event_cursor+1,a.action,p.members[a.index].entity_id):
                raise ValueError('Substitution changed its actual ordered attempt receipt')
            if a.child_window_id is not None:
                child=record(game._state,a.child_window_id);w=child.declaration
                candidate=next(c for c in p.candidates if c.presence==p.members[a.index])
                if a.child_window_id in children or (w.source_id,w.player_id,w.target_id,w.forced,w.combat_relation,w.attack_source_presence,w.attack_target_presence,w.excess_to_hero,
                        child.source_card_id,child.source_zone_epoch,child.source_entered_order)!=(
                        p.members[a.index].entity_id,p.window.player_id,p.window.target_id,True,p.window.combat_relation,p.members[a.index],p.window.attack_target_presence,p.window.excess_to_hero,
                        candidate.source.card_id,candidate.source.zone_epoch,candidate.source.entered_order):
                    raise ValueError('Substitution borrowed or changed an ordinary child attack')
                if child.declaration_event_cursor+1!=a.event_cursor or by_seq[a.event_cursor].kind!='attack_declared':
                    raise ValueError('Substitute child lost its exact original declaration')
                children.add(a.child_window_id)
            attempts.setdefault(ident,[]).append(a)
        else:
            if ident not in accepted or ident in finished or len(attempts.get(ident,[]))!=len(p.members) or p.status!='completed':
                raise ValueError('Substitution lost its complete finish receipt')
            finished.add(ident)
    for row in game._state.character_attack_history:
        p=row.substitution
        if p is None:continue
        validate_plan(game._state,game.registry,row)
        if row.declaration.id not in accepted or tuple(attempts.get(p.window.id,()))!=p.attempts or (p.status=='completed')!=(p.window.id in finished):
            raise ValueError('Substitution history lost an acceptance, attempt or finish')
        if row.terminal is not None and row.terminal.status=='replaced' and p.status!='completed':raise ValueError('Unfinished substitution cannot replace combat')
    frame=game._frame;work=()if frame is None else(*frame.prefix,*frame.continuation)
    if frame is not None:reject_choice_control(frame.options)


def reject_choice_control(options):
    from dataclasses import fields,is_dataclass
    def walk(value):
        if type(value)in (CheckAttackSubstitutes,ContinueAttackSubstitutes) or type(value)is ForceAttack and value.producer_link is not None:
            raise ValueError('Attack substitution control cannot be offered as a new choice effect')
        if is_dataclass(value):
            for f in fields(value):walk(getattr(value,f.name))
        elif type(value)in (tuple,list):
            for item in value:walk(item)
    walk(options)


def plan_from_dict(raw):
    if raw is None:return None
    from .serialization import _row,_list
    from .model import TriggerCandidate
    values=_row(raw,AttackSubstitutionPlan);values['source']=allocation_from_dict(values['source'])
    w=_row(values['window'],ActionWindow)
    for n in ('attack_source_presence','attack_target_presence'):
        if w[n]is not None:w[n]=BoardPresenceReference(**_row(w[n],BoardPresenceReference))
    w['spellburst_candidates']=tuple(TriggerCandidate(**_row(c,TriggerCandidate))for c in _list(w['spellburst_candidates'],'substitution original spellburst candidates'))
    values['window']=ActionWindow(**w)
    candidates=[]
    for c in _list(values['candidates'],'substitution original candidates'):
        c=_row(c,SubstituteCandidate);c['source']=allocation_from_dict(c['source']);c['presence']=BoardPresenceReference(**_row(c['presence'],BoardPresenceReference));candidates.append(SubstituteCandidate(**c))
    values['candidates']=tuple(candidates)
    values['members']=tuple(BoardPresenceReference(**_row(c,BoardPresenceReference))for c in _list(values['members'],'substitution original members'))
    values['attempts']=tuple(SubstituteAttempt(**_row(c,SubstituteAttempt))for c in _list(values['attempts'],'substitution original attempts'))
    return AttackSubstitutionPlan(**values)


def register(mechanics):
    for kind in (SubstituteCandidate,SubstituteAttempt,AttackSubstitutionPlan,SubstituteAttackLink):mechanics.register_payload_type(kind)
    mechanics.register(CheckAttackSubstitutes,check);mechanics.register(ContinueAttackSubstitutes,continue_members)
