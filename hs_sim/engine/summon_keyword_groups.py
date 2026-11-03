"""Original fixed summon receipts followed by the actual Outcast group reward."""
from .runtime_copy import deepcopy
from dataclasses import dataclass, replace
from .effects import Effect, GrantKeyword, _integer
from .model import CardType, Keyword, _name
from .original_summon_groups import recipients
from .owner_turns import validate_accepted_prefix
from .registry import RuleContext
from .successful_summons import BuffSummonedMinion, original_recipient

FINISHED='outcast_summon_group_finished'


@dataclass(frozen=True)
class OutcastSummonProfile:
    card_id: str
    token_id: str
    count: int

    def __post_init__(self):
        _name(self.card_id,'original Outcast spell');_name(self.token_id,'original Outcast token')
        _integer(self.count,'original fixed summon requests',1)


def validate_profile(registry,profile):
    if type(profile)is not OutcastSummonProfile:raise ValueError('Typed Outcast summon profile required')
    profile.__post_init__();card=registry.card(profile.card_id);token=registry.card(profile.token_id)
    if(card.kind!=CardType.SPELL or card.on_play is None or card.choice_only or
            card.ongoing_effect_id is not None or card.secret is not None or card.quest is not None or
            Keyword.OUTCAST not in card.keywords or token.kind!=CardType.MINION or token.choice_only):
        raise ValueError('Outcast summon reward requires a native Outcast spell and physical minion')


def profile_for(registry,context):
    if type(context)is not RuleContext:raise ValueError('Original summon reward requires its native context')
    cast=context.cast
    if(cast is None or cast not in context.state.cast_history or cast.source_id!=context.source_id or
            cast.player_id!=context.player_id or cast.completed or cast.interrupted or not cast.payload_started):
        raise ValueError('Original summon reward lost its active original cast')
    profile=registry.outcast_summon_profiles.get(cast.card_id)
    if profile is None:raise ValueError('Unregistered original Outcast summon source')
    validate_profile(registry,profile);return profile


@dataclass(frozen=True)
class GrantOutcastSummonedGroup(Effect):
    original: RuleContext

    def __post_init__(self):
        if type(self.original)is not RuleContext:raise ValueError('Original summon reward needs typed native context')


def validate_request(registry,effect,state=None):
    effect.__post_init__();old=effect.original;profile_for(registry,old)
    if state is not None:
        validate_accepted_prefix(old.state,state,registry)
        cast=state.cast_history[old.cast.id-1]
        if cast.completed or cast.interrupted or not cast.payload_started:
            raise ValueError('Original summon reward cannot follow a finished cast')


def execute(r,effect):
    validate_request(r.registry,effect,r.state);old=effect.original;profile=profile_for(r.registry,old)
    current=replace(old,state=deepcopy(r.state),cast=r.state.cast_history[old.cast.id-1])
    ids=recipients(old,current,r.registry,profile.token_id,profile.count)
    from .resolver import grant_ability
    # One accepted group reward, like the existing corpse group grant. The
    # zero-valued reference reuses its original-entry guard without executing a buff.
    grants=[]
    for identity in ids if old.spell_conditions.outcast else ():
        target=original_recipient(r,BuffSummonedMinion(old.player_id,identity,old.source_id))
        if target is None:
            r.stale(effect,r.state.successful_summon_history[identity-1].entity_id)
        else:
            attachment_id=r.state.next_attachment_id
            grant_ability(r,GrantKeyword(target.id,Keyword.IMMUNE_WHILE_ATTACKING,old.source_id,
                expires_turn=current.state.turn))
            grants.append((identity,attachment_id))
    r.emit(FINISHED,source_id=old.source_id,player_id=old.player_id,amount=len(ids),_capture=False,
        cast_id=old.cast.id,token_id=profile.token_id,requests=profile.count,summon_ids=ids,
        grants=tuple(grants),outcast=old.spell_conditions.outcast)
    return()


def _roots(state,cast,profile):
    from .summon_quantities import SummonEntryMaterial
    material=(SummonEntryMaterial(profile.token_id),)
    roots=[row for row in state.card_summon_history if row.request.cause.cast_id==cast.id]
    for row in roots:
        cause=row.request.cause
        if(row.request.materials!=material or cause.origin!='spell_cast'or
                (cause.source.entity_id,cause.player_id,cause.cast_card_id)!=(cast.source_id,cast.player_id,cast.card_id)):
            raise ValueError('Original Outcast group borrowed another request or source')
    return roots


def _entry_ids(state,roots):
    ids=[]
    for root in roots:
        for delivery in root.deliveries:
            if delivery.entity is None:continue
            entity=delivery.entity
            matches=[row.id for row in state.successful_summon_history if
                (row.entity_id,row.minion.zone_epoch,row.minion.entered_order)==
                (entity.entity_id,entity.zone_epoch,entity.entered_order)]
            if len(matches)!=1:raise ValueError('Original Outcast group lost its successful entry')
            ids.extend(matches)
    if len(ids)!=len(set(ids)):raise ValueError('Original Outcast group duplicated an entry')
    return tuple(ids)


def validate_boundary(game):
    """Original active casts owe a complete tail; finished groups have private publications."""
    profiles=game.registry.outcast_summon_profiles
    if not profiles:return
    from .hero_health_history import effective_events
    from .resolver import BehaviorCall
    from .spell_casts import FinishSpellCast
    from .summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
    state=game._state;queue=(*game._frame.prefix,*game._frame.continuation)if game._frame else()
    casts={c.id:c for c in state.cast_history if c.card_id in profiles and c.payload_started and c.failure is None}
    if not casts and not any(e.kind==FINISHED for e in game._events):return
    markers={};events=effective_events(game._events)
    for event in events:
        if event.kind!=FINISHED:continue
        data=dict(event.data);identity=data.get('cast_id')
        if type(identity)is not int or identity not in casts or identity in markers:
            raise ValueError('Outcast group publication lost its unique actual cast')
        cast=casts[identity];profile=profiles[cast.card_id];roots=_roots(state,cast,profile)
        if(set(data)!=set(('cast_id','token_id','requests','summon_ids','grants','outcast'))or
                len(roots)!=profile.count or any(r.status not in('completed','skipped')for r in roots)or
                (event.source_id,event.player_id,data['token_id'],data['requests'])!=(cast.source_id,cast.player_id,profile.token_id,profile.count)or
                type(data['outcast'])is not bool or data['outcast']!=cast.outcast or
                data['summon_ids']!=_entry_ids(state,roots)or event.amount!=len(data['summon_ids'])or
                event.sequence<=cast.recorded_event):
            raise ValueError('Outcast group publication changed its full original request/delivery proof')
        grants=data['grants']
        if(type(grants)is not tuple or any(type(x)is not tuple or len(x)!=2 or
                any(type(i)is not int or i<1 for i in x)for x in grants)or
                len({x[0]for x in grants})!=len(grants)or len({x[1]for x in grants})!=len(grants)or
                any(x[0]not in data['summon_ids']for x in grants)or not data['outcast']and grants):
            raise ValueError('Outcast group publication changed its actual granted entries')
        for summon_id,ability_id in grants:
            target=state.successful_summon_history[summon_id-1].entity_id
            matches=[e for e in events if e.kind=='ability_granted'and
                (e.source_id,e.target_id,dict(e.data).get('ability_id'),dict(e.data).get('ability_kind'))==
                (cast.source_id,target,ability_id,'keyword')and cast.recorded_event<e.sequence<event.sequence]
            if len(matches)!=1:raise ValueError('Outcast group lost its actual keyword grant publication')
        markers[identity]=event
    for identity,cast in casts.items():
        tails=[(i,w)for i,w in enumerate(queue)if type(w)is GrantOutcastSummonedGroup and w.original.cast.id==identity]
        calls=[w for w in queue if type(w)is BehaviorCall and w.context.cast is not None and
            w.context.cast.id==identity and w.behavior_id==game.registry.card(cast.card_id).on_play]
        roots=_roots(state,cast,profiles[cast.card_id])
        if identity in markers:
            if tails or calls or any(type(w)is SummonByCard and w.cause.cast_id==identity for w in queue):
                raise ValueError('Finished Outcast group retained duplicate work')
            continue
        if cast.interrupted:continue
        if cast.completed:raise ValueError('Completed Outcast cast lost its group publication')
        if calls:
            if len(calls)!=1 or tails or roots:raise ValueError('Original Outcast body has conflicting work')
            continue
        if len(tails)!=1:raise ValueError('Active Outcast cast lost its complete original group tail')
        position,tail=tails[0];validate_request(game.registry,tail,state);profile=profiles[cast.card_id]
        cause=SummonCause.capture(tail.original);material=(SummonEntryMaterial(profile.token_id),)
        pending=[(i,w)for i,w in enumerate(queue)if type(w)is SummonByCard and w.cause==cause]
        if(len(roots)+len(pending)!=profile.count or any(w.materials!=material or i>=position for i,w in pending)or
                any(row.request.cause!=cause for row in roots)):
            raise ValueError('Original Outcast group truncated or reordered its pending fixed requests')
        closers=[i for i,w in enumerate(queue)if type(w)is FinishSpellCast and w.cast_id==identity]
        if len(closers)!=1 or position>=closers[0]:raise ValueError('Outcast group follows its original cast completion')


def register(mechanics):mechanics.register(GrantOutcastSummonedGroup,execute)
