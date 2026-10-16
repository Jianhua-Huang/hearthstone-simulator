"""Finite native spell target requirements over original played-card facts."""
from dataclasses import dataclass
from .model import CardType,TargetMode,_name


@dataclass(frozen=True)
class UnplayedCopyTargetProfile:
    card_id:str
    def __post_init__(self):_name(self.card_id,'native first-copy spell')


def validate_profile(registry,profile):
    if type(profile)is not UnplayedCopyTargetProfile:raise ValueError('Expected a native first-copy target profile')
    profile.__post_init__();card=registry.card(profile.card_id)
    from .targeting import target_spec
    spec=target_spec(card)
    if(card.kind!=CardType.SPELL or not card.hand_playable or spec is None or spec.mode!=TargetMode.REQUIRED or
            card.target_condition is not None or card.choose_one is not None or card.secret is not None or card.quest is not None):
        raise ValueError('First-copy targets require an ordinary native spell and mandatory original domain')


def no_prior_copy(state,player_id,source_id,card_id):
    from .play_history import played_cards
    rows=played_cards(state,player_id)
    # A committed hand root is already in history during its counter/payload
    # windows. It is this cast's own play, not the required earlier other copy.
    current={p.id for p in rows if p.source_id==source_id and not p.completed and not p.interrupted}
    return not any(p.card_id==card_id and p.id not in current for p in rows)


def effective_spec(state,registry,source,definition,spec):
    profile=registry.spell_target_profiles.get(definition.id)
    if profile is None:return spec
    validate_profile(registry,profile)
    return spec if no_prior_copy(state,source.controller,source.id,profile.card_id)else None
