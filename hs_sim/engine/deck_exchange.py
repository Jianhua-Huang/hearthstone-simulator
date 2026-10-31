"""Atomic physical whole-deck exchange; no draw, shuffle or card creation."""
from dataclasses import dataclass
from .effects import Effect,_source,_player,_integer
from .model import Zone


@dataclass(frozen=True)
class SwapPlayerDecks(Effect):
    source_id:int|None=None

    def __post_init__(self):_source(self.source_id)


def exchange(r,request):
    from .zones import source_exists
    from .prepare import enter_deck
    from .lifecycle import renew_hand_progress
    from .deck_capacity import MAX_DECK_SIZE
    from .errors import ResolutionError
    request.__post_init__();source_exists(r,request.source_id)
    original={p:tuple(r.player(p).deck)for p in(1,2)}
    if set(original[1])&set(original[2]):raise ValueError('Deck exchange duplicated physical membership')
    for p in(1,2):
        if len(original[3-p])>max(MAX_DECK_SIZE,len(original[p])):
            raise ResolutionError('Whole-deck exchange cannot grow an already oversized experimental recipient')
        for eid in original[p]:
            e=r.state.entities[eid];card=r.registry.card(e.card_id)
            if(e.controller,e.zone)!=(p,Zone.DECK)or not card.hand_playable or card.choice_only:
                raise ValueError('Whole-deck exchange requires complete original physical decks')
    # Commit both final inventories before exposing even the first notification.
    for p in(1,2):r.player(p).deck[:]=original[3-p]
    for p in(1,2):
        for eid in original[3-p]:
            e=r.state.entities[eid];enter_deck(e);e.controller=p;e.zone_epoch+=1
            renew_hand_progress(r.state,e,previous_zone=Zone.DECK)
            r.game._information.conceal(eid)
    r.refresh_auras()
    r.emit('decks_exchanged',source_id=request.source_id,first_size=len(original[2]),second_size=len(original[1]))
    return()


@dataclass(frozen=True)
class TakeRandomDeckMinion(Effect):
    player_id:int
    owner_id:int
    source_id:int

    def __post_init__(self):
        _player(self.player_id);_player(self.owner_id);_integer(self.source_id,'physical deck take source',1)


def take(r,request):
    from .zones import MoveCard,zone_candidates,source_exists
    from .pools import PoolQuery
    from .model import CardType
    request.__post_init__();source_exists(r,request.source_id)
    candidates=zone_candidates(r,request.owner_id,Zone.DECK,PoolQuery(kinds=(CardType.MINION,)),request.player_id,request.source_id)
    if not candidates:return()
    selected=r.game._rng.choice(candidates)
    # Candidate count/order and the sampled identity are private deck facts.
    return(MoveCard(selected,request.player_id,Zone.HAND,source_id=request.source_id),)


def register(mechanics):
    mechanics.register(SwapPlayerDecks,exchange)
    mechanics.register(TakeRandomDeckMinion,take)
