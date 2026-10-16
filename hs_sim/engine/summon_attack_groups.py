"""A fixed original summon group followed by ordinary bound forced attacks."""
from copy import deepcopy
from dataclasses import dataclass,replace

from .effects import Effect,ForceAttack,_integer
from .model import BoardPresenceReference,CardType,_name
from .original_summon_groups import recipients
from .owner_turns import validate_accepted_prefix
from .registry import RuleContext


@dataclass(frozen=True)
class SummonAttackProfile:
    card_id:str
    token_id:str
    count:int

    def __post_init__(self):
        _name(self.card_id,'summon attack spell');_name(self.token_id,'summon attack token')
        _integer(self.count,'original summon attack requests',1)


def validate_profile(registry,profile):
    if type(profile)is not SummonAttackProfile:raise ValueError('Typed fixed summon attack profile required')
    profile.__post_init__();card=registry.card(profile.card_id);token=registry.card(profile.token_id)
    if(card.kind!=CardType.SPELL or card.on_play is None or card.choice_only or card.ongoing_effect_id is not None or
            card.secret is not None or card.quest is not None or token.kind!=CardType.MINION or token.choice_only):
        raise ValueError('Fixed summon attacks require an ordinary native spell and physical minion')


def profile_for(registry,c):
    if type(c)is not RuleContext:raise ValueError('Original summon attacks require their original native context')
    cast=c.cast
    if(cast is None or cast not in c.state.cast_history or cast.source_id!=c.source_id or cast.player_id!=c.player_id or
            cast.completed or cast.interrupted or not cast.payload_started):
        raise ValueError('Original summon attacks lost the active physical spell')
    profile=registry.summon_attack_profiles.get(cast.card_id)
    if profile is None:raise ValueError('Unregistered original summon attack source')
    validate_profile(registry,profile);return profile


@dataclass(frozen=True)
class AttackSummonedGroup(Effect):
    original:RuleContext
    target:BoardPresenceReference

    def __post_init__(self):
        if type(self.original)is not RuleContext or type(self.target)is not BoardPresenceReference:
            raise ValueError('Original summon attacks require native context and target residence')
        self.target.__post_init__()


def validate_request(registry,effect,state=None):
    effect.__post_init__();old=effect.original;profile_for(registry,old)
    if old.target_id!=effect.target.entity_id or BoardPresenceReference.capture(old.state,old.target_id)!=effect.target:
        raise ValueError('Summon attacks changed their original accepted target')
    if state is not None:validate_accepted_prefix(old.state,state,registry)


def execute(r,effect):
    validate_request(r.registry,effect,r.state);old=effect.original;profile=profile_for(r.registry,old)
    current=replace(old,state=deepcopy(r.state),cast=r.state.cast_history[old.cast.id-1])
    ids=recipients(old,current,r.registry,profile.token_id,profile.count)
    return tuple(ForceAttack(BoardPresenceReference(r.state.successful_summon_history[i-1].entity_id,
        r.state.successful_summon_history[i-1].minion.entered_order),effect.target)for i in ids)


def register(mechanics):mechanics.register(AttackSummonedGroup,execute)
