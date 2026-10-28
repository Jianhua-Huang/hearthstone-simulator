"""Original friendly death entries over the shared resurrection/copy pipelines."""
from dataclasses import dataclass,replace
from .effects import Effect,_integer
from .model import CardType,Zone
from .summon_quantities import SummonByCard,SummonCause,validate_cause
from .summon_sources import ResurrectMinion,death_record,resurrect_minion


def friendly_death(state,registry,death_id,cause):
    validate_cause(state,registry,cause)
    death=death_record(state,death_id)
    if (death.zone!=Zone.BOARD or death.controller!=cause.player_id or
            registry.card(death.card_id).kind!=CardType.MINION or death.copy_source is None or
            death.turn>cause.turn or death.copy_source.action>cause.action):
        raise ValueError('Entry requires its original friendly board minion death')
    from .resurrection_summons import validate_death
    from .death_self_copies import validate_death_source
    validate_death(state,registry,death)
    validate_death_source(death,state,registry)
    return death


def card_cause(cause):
    if type(cause)is not SummonCause:
        raise ValueError('Typed original death entry cause required')
    cause.__post_init__()
    if cause.origin!='card_effect' or cause.source.controller!=cause.player_id:
        raise ValueError('Death entry requires its original controlling card effect')


@dataclass(frozen=True)
class ResurrectOneHealth(ResurrectMinion):
    def __post_init__(self):
        super().__post_init__();card_cause(self.cause)
        if (self.source_id!=self.cause.source.entity_id or self.player_id!=self.cause.player_id or
                self.stats is not None or self.on_summon is not None or self.producer_link is not None):
            raise ValueError('One-health resurrection requires its unmodified original entry')

    def validate_in_state(self,state,registry):
        from .resurrection_summons import validate_effect
        validate_effect(state,registry,self)


@dataclass(frozen=True)
class SummonDormantDeathCopy(Effect):
    death_id:int
    cause:SummonCause

    def __post_init__(self):
        _integer(self.death_id,'original dormant-copy death',1);card_cause(self.cause)

    def validate_in_state(self,state,registry):
        self.__post_init__();friendly_death(state,registry,self.death_id,self.cause)


def summon_dormant(r,effect):
    effect.validate_in_state(r.state,r.registry)
    death=friendly_death(r.state,r.registry,effect.death_id,effect.cause)
    from .death_self_copies import entry_from_death
    material=replace(entry_from_death(death),entry_dormant_turns=1)
    return (SummonByCard(effect.cause.player_id,(material,),effect.cause,position=death.position),)


def register(mechanics):
    mechanics.register(ResurrectOneHealth,resurrect_minion)
    mechanics.register(SummonDormantDeathCopy,summon_dormant)
