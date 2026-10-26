"""A real until-hero-death instruction reuses ordinary automatic spell casting.

The normal interpreter owns targets, choices, reactions and terminal stopping.
A nonterminating loop exhausts the existing engineering budget and rolls back;
it never invents a winner or a successful fixed-count completion.
"""
from dataclasses import dataclass
from .effects import Effect,_behavior,_integer,_player
from .model import CardType


@dataclass(frozen=True)
class CastSpellUntilHeroDies(Effect):
    player_id:int
    card_id:str
    source_id:int

    def __post_init__(self):
        _player(self.player_id);_behavior(self.card_id);_integer(self.source_id,'terminal-loop source',1)

    def validate_in_state(self,state,registry):
        self.__post_init__()
        if self.source_id not in state.entities:raise ValueError('Terminal spell loop lost its original allocated source')
        card=registry.card(self.card_id)
        if card.kind!=CardType.SPELL or not card.hand_playable:
            raise ValueError('Terminal spell loop requires an ordinary physical spell')


def cast(r,effect):
    effect.validate_in_state(r.state,r.registry)
    if r.state.status!='playing':return()
    from .spell_casts import CastSpell
    return(CastSpell(effect.player_id,effect.card_id,effect.source_id,targeting='random',choices='random'),effect)


def register(mechanics):mechanics.register(CastSpellUntilHeroDies,cast)
