"""Bind one all-Mana debit to the actual deliveries of an original summon pair."""
from dataclasses import dataclass
from .effects import Effect,SpendMana
from .model import CardType,_name
from .registry import RuleContext
from .owner_turns import validate_accepted_prefix
from .summon_quantities import SummonCause,SummonEntryMaterial
from .successful_summons import BuffSummonedMinion,buff_summoned_minion
from .original_summon_groups import root_prefix,recipients


def caller(value):
    if type(value)is not RuleContext or value.cast is None or value.cast.source_id!=value.source_id or value.cast.player_id!=value.player_id:
        raise ValueError('Summon/Mana reward requires its original actual spell context')
    if value.cast not in value.state.cast_history or value.cast.completed or value.cast.interrupted or not value.cast.payload_started:
        raise ValueError('Summon/Mana reward lost its active original cast')


@dataclass(frozen=True)
class SpendManaForSummonedPair(Effect):
    original:RuleContext
    card_id:str
    def __post_init__(self):caller(self.original);_name(self.card_id,'original summoned pair')


@dataclass(frozen=True)
class BuffManaSummonedPair(Effect):
    original:RuleContext
    accepted:RuleContext
    card_id:str
    summon_ids:tuple[int,...]
    def __post_init__(self):
        caller(self.original);caller(self.accepted);_name(self.card_id,'original summoned pair')
        if type(self.summon_ids)is not tuple or any(type(x)is not int or x<1 for x in self.summon_ids)or len(set(self.summon_ids))!=len(self.summon_ids):
            raise ValueError('Summon/Mana reward requires complete unique original recipients')
        if(self.accepted.source_id,self.accepted.player_id,self.accepted.cast.id)!=(self.original.source_id,self.original.player_id,self.original.cast.id):
            raise ValueError('Summon/Mana reward changed its original causing spell')


def validate_request(registry,effect):
    effect.__post_init__();c=effect.original
    if registry.card(c.cast.card_id).kind!=CardType.SPELL or registry.card(effect.card_id).kind!=CardType.MINION:
        raise ValueError('Summon/Mana reward requires an actual spell and explicit fixed minion')


def validate_reward(registry,effect,state=None):
    validate_request(registry,effect);old,accepted=effect.original,effect.accepted
    if effect.summon_ids!=recipients(old,accepted,registry,effect.card_id):raise ValueError('Summon/Mana reward truncated or changed its complete original recipients')
    if state is None:return
    validate_accepted_prefix(accepted.state,state,registry);root_prefix(accepted.state,state)
    history=accepted.state.mana_consumption_history;index=len(history)
    if state.mana_consumption_history[:index]!=history or len(state.mana_consumption_history)<=index:
        raise ValueError('Summon/Mana reward lost its exact original debit prefix')
    row=state.mana_consumption_history[index];row.__post_init__()
    if(row.id,row.player_id,row.source_id,row.source_card_id,row.source_kind,row.cast_id,row.requested,row.mana_before,row.actual)!=(
        index+1,old.player_id,old.source_id,old.cast.card_id,CardType.SPELL,old.cast.id,None,
        accepted.state.players[old.player_id].mana,accepted.state.players[old.player_id].mana):
        raise ValueError('Summon/Mana reward borrowed another debit, cast or amount')
    if state.successful_summon_history[:len(accepted.state.successful_summon_history)]!=accepted.state.successful_summon_history:
        raise ValueError('Summon/Mana reward changed its complete successful entry prefix')


def spend(r,effect):
    validate_request(r.registry,effect);old=effect.original
    from .spell_casts import active_cast
    cast=active_cast(r.state,old.source_id,old.player_id)
    if cast is None or cast.id!=old.cast.id:raise ValueError('Summon/Mana reward lost the original actual cast')
    accepted=r.call(r.registry.card(cast.card_id).on_play,old.source_id,old.player_id,old.target_id,cast=cast).context
    ids=recipients(old,accepted,r.registry,effect.card_id)
    return(SpendMana(old.player_id,None,old.source_id),BuffManaSummonedPair(old,accepted,effect.card_id,ids))


def reward(r,effect):
    validate_reward(r.registry,effect,r.state);row=r.state.mana_consumption_history[len(effect.accepted.state.mana_consumption_history)]
    # One group reward is accepted before its notifications. Every receiver
    # still resolves through the shared original-entry/residence guard.
    if row.actual:
        for identity in effect.summon_ids:
            buff_summoned_minion(r,BuffSummonedMinion(effect.original.player_id,identity,effect.original.source_id,row.actual,row.actual))
    return()


def register(mechanics):
    mechanics.register(SpendManaForSummonedPair,spend)
    mechanics.register(BuffManaSummonedPair,reward)
