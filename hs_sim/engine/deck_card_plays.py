"""Sequential physical deck-top execution through the existing five executors."""
from dataclasses import dataclass, replace

from .effects import Draw, Effect, _integer, _player
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardType, Zone
from .registry import UnsupportedDefinitionError
from .summon_quantities import SummonCause, validate_cause
from .zones import CardReference


@dataclass(frozen=True)
class PlayTopDeckCards(Effect):
    player_id: int
    source_id: int
    cause: SummonCause
    count: int = 3

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.source_id,'deck-top issuer',1)
        _integer(self.count,'remaining deck-top attempts',0)
        if type(self.cause) is not SummonCause:
            raise ValueError('Deck-top execution requires its original typed card cause')
        self.cause.__post_init__()
        if (self.cause.player_id,self.cause.source.entity_id)!=(self.player_id,self.source_id):
            raise ValueError('Deck-top continuation changed its original player or issuer')

    def validate_in_state(self,state,registry):
        self.__post_init__()
        validate_cause(state,registry,self.cause)
        if self.source_id not in state.entities:
            raise ValueError('Deck-top continuation has an unknown issuer')


def play_top(r,effect):
    effect.validate_in_state(r.state,r.registry)
    if effect.count>r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Deck-top attempts exceed the resolution budget')
    player=r.player(effect.player_id)
    if not effect.count or not player.deck:
        return ()
    entity=r.state.entities[player.deck[0]]
    if (entity.controller,entity.zone)!=(player.id,Zone.DECK):
        raise ResolutionError('Deck-top execution lost its actual physical source')
    card=r.registry.card(entity.card_id)
    if card.choice_only or card.kind not in (
            CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO):
        raise UnsupportedDefinitionError('Unknown physical deck-top card kind: '+entity.card_id)
    remaining=() if effect.count==1 else (replace(effect,count=effect.count-1),)
    if card.kind in (CardType.MINION,CardType.LOCATION) and len(player.board)>=r.rules.max_board:
        return (Draw(player.id,1,effect.source_id),*remaining)
    reference=CardReference.capture(entity)
    if card.kind==CardType.SPELL:
        from .spell_casts import CastStoredSpell
        return (CastStoredSpell(reference,player.id,effect.source_id),*remaining)
    if card.kind==CardType.MINION:
        from .colossal import SummonStoredCard
        return (SummonStoredCard(reference,player.id,cause=effect.cause),*remaining)
    if card.kind==CardType.WEAPON:
        from .equipment import equip_entity
        equip_entity(r,entity)
    elif card.kind==CardType.LOCATION:
        r.move(entity,Zone.BOARD)
        r.emit('location_placed',source_id=entity.id,target_id=entity.id,player_id=player.id)
    else:
        from .hero_powers import play_hero
        play_hero(r,entity,origin=Zone.DECK)
    return remaining


def register(mechanics):
    mechanics.register(PlayTopDeckCards,play_top)
