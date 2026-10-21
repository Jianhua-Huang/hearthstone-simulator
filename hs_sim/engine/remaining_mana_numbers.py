"""Native hand numbers, with the original payment and Battlecry captures.

Only synchronous payment normalization excludes its already accepted source.
The resulting physical stats and ordinary frozen payload survive all waits.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
from .model import CardType,Zone


@dataclass(frozen=True)
class RemainingManaNumbersProfile:
    card_id:str


def validate_profile(registry,profile):
    if type(profile) is not RemainingManaNumbersProfile:raise ValueError('Typed native remaining-mana declaration required')
    card=registry.card(profile.card_id)
    minion = card.kind==CardType.MINION and (card.cost,card.attack,card.health)==(1,1,1) and card.battlecry is not None
    spell = (card.kind==CardType.SPELL and card.cost==1 and card.on_play is not None and
        card.id in registry.spell_source_cost_profiles)
    if not (minion or spell):
        raise ValueError('Native remaining numbers require the original minion or declared one-cost spell')


def sources(entity):
    return tuple(a for a in entity.abilities if a.kind=='remaining_mana_numbers' and not a.consumed)


def validate_carrier(registry,card_id,kind,abilities,components=()):
    for row in abilities:
        if row.kind!='remaining_mana_numbers':continue
        row.__post_init__()
        if (row.remaining_mana_card_id not in registry.remaining_mana_numbers_profiles or
                kind!=registry.card(row.remaining_mana_card_id).kind or row.remaining_mana_card_id not in (card_id,*components)):
            raise ValueError('Remaining numbers borrowed an undeclared native carrier')


def synchronize(state,registry,*,exclude_source=None):
    if registry is None or not registry.remaining_mana_numbers_profiles:return
    from .lifecycle import refresh_entity
    for player in state.players.values():
        amount=max(1,player.mana)
        for identity in player.hand:
            if identity==exclude_source:continue
            entity=state.entities[identity]
            if sources(entity):
                entity.base_cost=amount
                if entity.kind==CardType.MINION:entity.base_attack=entity.base_health=amount
                refresh_entity(entity)


def automatic_cost_input(state,registry,value):
    """Quote the actual caster's number without rewriting a foreign hand card."""
    if (value.kind==CardType.SPELL and value.card_id in registry.remaining_mana_numbers_profiles and
            sources_from_input(value)):
        return replace(value,base_cost=max(1,state.players[value.player_id].mana))
    return value


@contextmanager
def payment_window(resolver,source_id):
    previous=getattr(resolver,'_remaining_mana_payment_source',None)
    resolver._remaining_mana_payment_source=source_id
    try:yield
    finally:resolver._remaining_mana_payment_source=previous


def battlecry_number(entity,ability):
    rows=tuple(a for a in sources(entity) if a.remaining_mana_card_id==ability.battlecry_card_id)
    return entity.base_cost if rows else None


def before_silence(entity,registry):
    if sources(entity):
        card=registry.card(entity.card_id)
        entity.base_attack,entity.base_health=card.attack,card.health


def validate_payload(registry,payload):
    value=payload.remaining_mana_number
    declared=payload.card_id in registry.remaining_mana_numbers_profiles
    if declared!=(value is not None):
        raise ValueError('Native Battlecry number borrowed another declaration')


def validate_game(game):
    registry=game.registry
    if not registry.remaining_mana_numbers_profiles:return
    state=game._state
    for entity in state.entities.values():
        validate_carrier(registry,entity.card_id,entity.kind,entity.abilities,entity.components)
        if entity.zone==Zone.HAND and sources(entity):
            expected=max(1,state.players[entity.controller].mana)
            if (entity.base_cost!=expected or entity.kind==CardType.MINION and
                    (entity.base_attack,entity.base_health)!=(expected,expected)):
                raise ValueError('Native hand numbers differ from actual remaining mana')
    for play in state.play_history:
        for payload in play.battlecries:
            validate_payload(registry,payload)
            if payload.remaining_mana_number is not None and payload.remaining_mana_number!=max(1,play.mana_before):
                raise ValueError('Native hand Battlecry lost its original prepayment number')
        receipt=play.submitted_cost
        if receipt is not None and receipt.quote_origin=='current_hand' and sources_from_input(receipt.quote.quote_input):
            if receipt.quote.quote_input.base_cost!=max(1,play.mana_before):
                raise ValueError('Native submitted price lost its prepayment mana basis')
    for row in state.battlecry_history:validate_payload(registry,row.payload)


def sources_from_input(value):
    return tuple(a for a in value.abilities if a.kind=='remaining_mana_numbers')
