"""Equipped passive skills contribute to existing price and Battlecry plans."""
from collections import Counter
from dataclasses import dataclass

from .effects import _integer
from .model import (BattlecryRepeatSpec,CardType,CostAuraSpec,CostSpec,Zone)


@dataclass(frozen=True)
class PassiveHeroPowerProfile:
    card_id:str
    unlock_owner_turn:int=1
    battlecry_period:int|None=None

    def __post_init__(self):
        from .model import _name
        _name(self.card_id,'passive hero power')
        _integer(self.unlock_owner_turn,'passive power unlock owner turn',1)
        if self.battlecry_period is not None:_integer(self.battlecry_period,'passive minion play period',2)


def profiles(registry):return getattr(registry,'passive_hero_power_profiles',{})


def validate_native_face(card):
    if (card.kind!=CardType.HERO_POWER or not card.passive_hero_power or card.triggers or
            bool(card.cost_auras)==bool(card.battlecry_repeats)):
        raise ValueError('Native passive policy requires one independent price or Battlecry declaration')
    if card.cost_auras:
        aura=card.cost_auras[0]
        if (len(card.cost_auras)!=1 or aura.cost.delta>=0 or aura!=CostAuraSpec(
                CostSpec(delta=aura.cost.delta,card_types=(CardType.MINION,)),first_per_turn=True)):
            raise ValueError('Passive price policy requires its ordinary first-minion reduction')
    elif card.battlecry_repeats!=(BattlecryRepeatSpec(2,(CardType.MINION,)),):
        raise ValueError('Passive Battlecry policy requires one minion-only double declaration')


def validate_profile(registry,profile):
    if type(profile)is not PassiveHeroPowerProfile:raise ValueError('Typed passive power profile required')
    profile.__post_init__();card=registry.card(profile.card_id);validate_native_face(card)
    if bool(card.battlecry_repeats)!=(profile.battlecry_period is not None):
        raise ValueError('Passive policy lost its original minion count qualifier')


def validate_declared_card(registry,card):
    if card.kind==CardType.HERO_POWER and(card.cost_auras or card.battlecry_repeats):
        validate_native_face(card)
        if card.id not in profiles(registry):raise ValueError('Passive numeric policy requires its original eligibility profile')


def validate_carrier(registry,card_id,kind,abilities,components=()):
    profile=profiles(registry).get(card_id)
    if profile is None:raise ValueError('Unknown native passive power policy carrier')
    validate_profile(registry,profile);card=registry.card(card_id)
    rows=tuple(a for a in abilities if a.kind in('cost_aura','battlecry_repeat'))
    if kind!=CardType.HERO_POWER or components:raise ValueError('Passive policies require a physical skill carrier')
    expected=Counter([('cost_aura',x)for x in card.cost_auras]+[('battlecry_repeat',x)for x in card.battlecry_repeats])
    actual=Counter()
    for a in rows:
        a.__post_init__()
        if a.origin!='printed'or a.consumed or a.expires_turn is not None or a.magnetic_id is not None:
            raise ValueError('Passive policy lost its unconsumed native declaration')
        actual[(a.kind,a.cost_aura if a.kind=='cost_aura'else a.battlecry_repeat)]+=1
    if actual!=expected:raise ValueError('Passive power changed its complete native price/repeat policy')


def enabled(state,registry,entity):
    profile=profiles(registry).get(entity.card_id)
    if (profile is None or entity.kind!=CardType.HERO_POWER or entity.zone!=Zone.HERO_POWER or
            entity.id not in state.players[entity.controller].hero_power_ids):return False
    from .hero_powers import hero_powers_can_activate
    if not hero_powers_can_activate(state):return False
    latest=next((t for t in reversed(state.owner_turn_history)if t.player_id==entity.controller),None)
    return latest is not None and latest.owner_index>=profile.unlock_owner_turn


def cost_sources(state,registry):
    if not profiles(registry):return ()
    return tuple(i for player in state.players.values()for i in player.hero_power_ids
        if registry.card(state.entities[i].card_id).cost_auras and enabled(state,registry,state.entities[i]))


def repeat_source_matches(state,registry,entity,recipient):
    profile=profiles(registry).get(entity.card_id)
    if profile is None or profile.battlecry_period is None or not enabled(state,registry,entity):return False
    from .play_history import played_cards
    play=next((p for p in reversed(state.play_history)if p.source_id==recipient.carrier_id),None)
    if (play is None or play.player_id!=entity.controller or play.kind!=CardType.MINION or
            play.completed or play.interrupted or play.countered):return False
    roots=played_cards(state,entity.controller,before_id=play.id+1,kind=CardType.MINION)
    return len(roots)%profile.battlecry_period==0


def validate_state(state,registry):
    if not profiles(registry):return
    for entity in state.entities.values():
        if entity.card_id not in profiles(registry):continue
        validate_carrier(registry,entity.card_id,entity.kind,entity.abilities,entity.components)
        if any(a.source_id!=entity.id for a in entity.abilities if a.kind in('cost_aura','battlecry_repeat')):
            raise ValueError('Passive policy borrowed a different physical skill source')
