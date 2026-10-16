"""Finite native Battlecry target gating over genuine current-turn transitions."""
from dataclasses import dataclass
from .effects import _player
from .model import CardType,TargetMode,Zone,_name


@dataclass(frozen=True)
class HeroHealthChangedTargetProfile:
    card_id:str
    def __post_init__(self):_name(self.card_id,'native hero-health Battlecry')


def changed_this_turn(state,player_id):
    """Actual remaining-health changes, including opponent-turn invocations."""
    _player(player_id)
    return any(row.player_id==player_id and row.turn==state.turn
               for row in state.hero_health_change_history)


def validate_profile(registry,profile):
    if type(profile)is not HeroHealthChangedTargetProfile:raise ValueError('Expected native hero-health target profile')
    profile.__post_init__();card=registry.card(profile.card_id)
    from .targeting import target_spec
    spec=target_spec(card)
    if(card.kind!=CardType.MINION or not card.hand_playable or card.battlecry is None or
            card.choose_one is not None or card.combo is not None or card.target_condition is not None or
            spec is None or spec.mode!=TargetMode.IF_AVAILABLE or spec.zones!=(Zone.BOARD,)or
            spec.kinds!=(CardType.MINION,)or spec.relation!='enemy' or card.target_rule!='any_entity'):
        raise ValueError('Hero-health targets require an ordinary native enemy-minion Battlecry domain')


def effective_spec(state,registry,source,definition,spec):
    profile=registry.hero_health_target_profiles.get(definition.id)
    if profile is None:return spec
    validate_profile(registry,profile)
    return spec if changed_this_turn(state,source.controller)else None
