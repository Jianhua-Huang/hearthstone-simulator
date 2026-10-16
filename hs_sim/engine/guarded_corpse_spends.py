"""Finite live-minion gates around the existing all-or-none corpse branch."""
from dataclasses import dataclass
from .effects import Effect,SpendResource,_integer
from .model import CardType,Keyword,Resource
from .sacrifice import MinionReference,live_minion,reference_value
from .successful_summons import BuffSummonedMinion,original_recipient


@dataclass(frozen=True)
class SpendCorpsesForMinion(Effect):
    source:MinionReference
    amount:int
    on_success:tuple[Effect,...]
    mode:str='source'
    summon_id:int|None=None

    def __post_init__(self):
        reference_value(self.source);_integer(self.amount,'guarded corpse threshold',1)
        if self.mode not in('source','free_space','missing_reborn','summon'):
            raise ValueError('Unknown live corpse payment gate')
        if self.mode=='summon':_integer(self.summon_id,'original summon gate',1)
        elif self.summon_id is not None:raise ValueError('Only the summon gate names an original successful entry')
        if type(self.on_success)is not tuple or any(not isinstance(x,Effect)for x in self.on_success):
            raise ValueError('Guarded corpse reward requires immutable typed effects')
        for x in self.on_success:
            validate=getattr(x,'__post_init__',None)
            if validate is not None:validate()


def validate_request(state,registry,effect):
    effect.__post_init__();ref=effect.source;entity=state.entities.get(ref.entity_id)
    if registry.card(ref.card_id).kind!=CardType.MINION or entity is None or ref.zone_epoch>entity.zone_epoch or ref.entered_order>=state.next_order:
        raise ValueError('Corpse payment gate lost its original known minion allocation')
    if effect.summon_id is not None:
        if effect.summon_id>len(state.successful_summon_history):raise ValueError('Corpse payment gate names an unknown original summon')
        row=state.successful_summon_history[effect.summon_id-1]
        BuffSummonedMinion(row.player_id,row.id,ref.entity_id).validate_in_state(state)


def spend(r,effect):
    validate_request(r.state,r.registry,effect);entity=live_minion(r.state,effect.source)
    if entity is None:return()
    if effect.mode=='free_space'and len(r.player(effect.source.player_id).board)>=r.rules.max_board:return()
    if effect.mode=='missing_reborn'and Keyword.REBORN in entity.keywords:return()
    if effect.mode=='summon':
        row=r.state.successful_summon_history[effect.summon_id-1]
        if original_recipient(r,BuffSummonedMinion(row.player_id,row.id,entity.id))is None:return()
    return(SpendResource(effect.source.player_id,Resource.CORPSES,effect.amount,on_success=effect.on_success),)


def register(mechanics):mechanics.register(SpendCorpsesForMinion,spend)
