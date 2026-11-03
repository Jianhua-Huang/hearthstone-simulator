"""Finite corpse summon/keyword profiles using original debit and entry facts."""
from .runtime_copy import deepcopy
from dataclasses import dataclass,fields,is_dataclass,replace
from .effects import Effect,SpendResource,_integer
from .model import CardType,GameState,Keyword,Resource,_name
from .registry import RuleContext
from .owner_turns import validate_accepted_prefix
from .original_summon_groups import recipients,root_prefix
from .resource_operations import SpendUpToResource
from .successful_summons import GrantSummonedKeyword,grant_summoned_keyword
from .summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial


@dataclass(frozen=True)
class CorpseSummonProfile:
    card_id:str
    token_id:str
    mode:str
    count:int
    corpse_cost:int=0
    keyword:Keyword|None=None
    def __post_init__(self):
        _name(self.card_id,'corpse summon root');_name(self.token_id,'corpse summon fixed token');_integer(self.count,'corpse summon maximum',1)
        _integer(self.corpse_cost,'corpse summon threshold',0)
        if self.mode=='grant':
            if self.corpse_cost<1 or type(self.keyword)is not Keyword or self.keyword not in(Keyword.RUSH,Keyword.REBORN):
                raise ValueError('Post-summon corpse profile needs a fixed threshold and Rush/Reborn')
        elif self.mode!='raise'or self.corpse_cost or self.keyword is not None:
            raise ValueError('Corpse raising needs one fixed bounded token recipe')


def validate_profile(registry,profile):
    if type(profile)is not CorpseSummonProfile:raise ValueError('Expected an exact corpse summon profile')
    profile.__post_init__();root=registry.card(profile.card_id);token=registry.card(profile.token_id)
    if token.kind!=CardType.MINION or token.choice_only or root.choice_only:
        raise ValueError('Corpse summon profile requires real physical cards')
    if root.kind==CardType.SPELL:
        if root.on_play is None or root.ongoing_effect_id is not None or root.secret is not None or root.quest is not None:
            raise ValueError('Corpse summon spell needs its ordinary native body')
    elif root.kind!=CardType.MINION or root.battlecry is None or profile.mode!='raise':
        raise ValueError('Corpse raising requires an ordinary spell or actual native Battlecry')


def caller(c):
    if type(c)is not RuleContext:raise ValueError('Corpse summon requires the original native context')
    record=c.cast if c.cast is not None else c.battlecry
    history=c.state.cast_history if c.cast is not None else c.state.battlecry_history
    if (record is None or record not in history or record.source_id!=c.source_id or record.player_id!=c.player_id or
            record.completed or record.interrupted or not record.payload_started):
        raise ValueError('Corpse summon lost its active original native body')
    return record.card_id


def profile_for(registry,c):
    cid=caller(c)
    try:profile=registry.corpse_summon_profiles[cid]
    except KeyError as e:raise ValueError('Unregistered corpse summon source')from e
    validate_profile(registry,profile)
    if (registry.card(cid).kind==CardType.SPELL)!=(c.cast is not None):raise ValueError('Corpse summon changed its native entry')
    return profile


@dataclass(frozen=True)
class ResolveCorpseSummons(Effect):
    original:RuleContext
    def __post_init__(self):caller(self.original)


@dataclass(frozen=True)
class FinishCorpseSummons(Effect):
    original:RuleContext
    accepted:RuleContext
    summon_ids:tuple[int,...]
    cap:int
    board_limit:int|None=None
    def __post_init__(self):
        if caller(self.original)!=caller(self.accepted)or(self.original.source_id,self.original.player_id)!=(self.accepted.source_id,self.accepted.player_id):
            raise ValueError('Corpse summon changed its original native caller')
        a=self.original.cast if self.original.cast is not None else self.original.battlecry
        b=self.accepted.cast if self.accepted.cast is not None else self.accepted.battlecry
        if type(a)is not type(b)or a.id!=b.id:raise ValueError('Corpse summon changed its original activation')
        _integer(self.cap,'accepted corpse cap',0)
        if self.board_limit is not None:_integer(self.board_limit,'accepted board capacity',1)
        if type(self.summon_ids)is not tuple or any(type(x)is not int or x<1 for x in self.summon_ids)or len(set(self.summon_ids))!=len(self.summon_ids):
            raise ValueError('Corpse summon requires its complete unique original recipients')


def validate_request(registry,effect):effect.__post_init__();profile_for(registry,effect.original)


def validate_finish(registry,effect,state=None,rules=None):
    effect.__post_init__();old,c=effect.original,effect.accepted;profile=profile_for(registry,old)
    validate_accepted_prefix(old.state,c.state,registry);root_prefix(old.state,c.state)
    if profile.mode=='grant':
        if effect.board_limit is not None or effect.cap!=profile.corpse_cost or c.state.players[c.player_id].resources[Resource.CORPSES]<effect.cap:
            raise ValueError('Summon keyword changed its original full threshold')
        if effect.summon_ids!=recipients(old,c,registry,profile.token_id,profile.count):
            raise ValueError('Summon keyword truncated or changed its original complete group')
    else:
        if effect.board_limit is None or effect.summon_ids or effect.cap!=min(profile.count,max(0,effect.board_limit-len(c.state.players[c.player_id].board))):
            raise ValueError('Corpse raising changed its original physical capacity')
        if rules is not None and effect.board_limit!=rules.max_board:raise ValueError('Corpse raising changed the actual rules capacity')
    if state is None:return
    validate_accepted_prefix(c.state,state,registry);root_prefix(c.state,state)
    history=c.state.corpse_spend_history;index=len(history)
    if state.corpse_spend_history[:index]!=history or len(state.corpse_spend_history)<=index:
        raise ValueError('Corpse summon lost its exact original debit prefix')
    row=state.corpse_spend_history[index];row.__post_init__();bank=c.state.players[c.player_id].resources[Resource.CORPSES]
    if(row.id,row.player_id,row.turn,row.action,row.origin,row.amount,row.balance_before,row.source_id,row.source_card_id,row.operation_id)!=(
        index+1,c.player_id,c.state.turn,c.state.action_number,'capped',min(bank,effect.cap),bank,c.source_id,c.source.card_id,c.state.next_resource_operation_id):
        raise ValueError('Corpse summon borrowed another original debit, source or amount')
    if state.successful_summon_history[:len(c.state.successful_summon_history)]!=c.state.successful_summon_history:
        raise ValueError('Corpse summon changed its original successful entries')


def capture_current(r,old):
    if old.cast is not None:
        c=replace(old,state=deepcopy(r.state),cast=r.state.cast_history[old.cast.id-1])
    else:c=replace(old,state=deepcopy(r.state),battlecry=r.state.battlecry_history[old.battlecry.id-1])
    caller(c);return c


def resolve(r,effect):
    validate_request(r.registry,effect);old=effect.original;profile=profile_for(r.registry,old);accepted=capture_current(r,old)
    if profile.mode=='grant':
        ids=recipients(old,accepted,r.registry,profile.token_id,profile.count)
        if r.player(old.player_id).resources[Resource.CORPSES]<profile.corpse_cost:
            from .resources import resource_effect
            resource_effect(r,SpendResource(old.player_id,Resource.CORPSES,profile.corpse_cost));return()
        cap=profile.corpse_cost;limit=None
    else:
        ids=();limit=r.rules.max_board;cap=min(profile.count,max(0,limit-len(r.player(old.player_id).board)))
    return(SpendUpToResource(old.player_id,Resource.CORPSES,cap,old.source_id),FinishCorpseSummons(old,accepted,ids,cap,limit))


def finish(r,effect):
    validate_finish(r.registry,effect,r.state,r.rules);profile=profile_for(r.registry,effect.original)
    if profile.mode=='grant':
        for identity in effect.summon_ids:
            grant_summoned_keyword(r,GrantSummonedKeyword(effect.original.player_id,identity,effect.original.source_id,profile.keyword))
        return()
    row=r.state.corpse_spend_history[len(effect.accepted.state.corpse_spend_history)]
    request=SummonByCard(effect.original.player_id,(SummonEntryMaterial(profile.token_id),),SummonCause.capture(effect.accepted))
    return tuple(request for _ in range(row.amount))


def validate_boundary(game):
    frame=game._frame
    if frame is None:return
    def visit(value,depth=0):
        if depth>64:raise ValueError('Corpse summon frame nesting exceeds limit')
        if type(value)is FinishCorpseSummons:
            validate_finish(game.registry,value,game._state,game.ruleset);return
        if type(value)is ResolveCorpseSummons:validate_request(game.registry,value);return
        if type(value)in(GameState,RuleContext):return
        if isinstance(value,(list,tuple)):
            for x in value:visit(x,depth+1)
        elif isinstance(value,dict):
            for x in value.values():visit(x,depth+1)
        elif is_dataclass(value)and not isinstance(value,type):
            for f in fields(value):visit(getattr(value,f.name),depth+1)
    visit((*frame.prefix,*frame.continuation,frame.options,frame.paid_hand_choice_boundary))


def register(mechanics):
    mechanics.register(ResolveCorpseSummons,resolve).register(FinishCorpseSummons,finish)
