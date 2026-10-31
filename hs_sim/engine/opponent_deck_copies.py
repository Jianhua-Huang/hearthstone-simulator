"""Whole original opposing deck copies through existing copy and removal work."""
from dataclasses import dataclass
from .copy_materials import CapturedCardCopyMaterial,validate_captured_card_copy
from .deck_shuffles import ShuffleDeckCards
from .effects import Effect,_integer,_player
from .model import Zone
from .nondeath_removal import RemoveFromGame,remove_from_game
from .zones import CardReference,CopyCard,copy_physical_card,source_exists


@dataclass(frozen=True)
class CopyOpponentDeck(Effect):
    player_id:int
    source_id:int
    replace_deck:bool=False
    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'opponent deck-copy source',1)
        if type(self.replace_deck)is not bool:raise ValueError('Deck-copy replacement requires an exact boolean')


def copy(r,request):
    request.__post_init__();source_exists(r,request.source_id)
    originals=tuple(r.player(3-request.player_id).deck)
    materials=tuple(CapturedCardCopyMaterial.capture(r.state,r.state.entities[i])for i in originals)
    for material in materials:validate_captured_card_copy(r.state,r.registry,material)
    position='bottom'if request.replace_deck else'random'
    entries=tuple(CopyCard(material,request.player_id,Zone.DECK,mode='current',position=position,source_id=request.source_id)for material in materials)
    if not request.replace_deck:
        return(ShuffleDeckCards(request.player_id,request.player_id,entries,request.source_id),)if entries else()
    old=tuple(CardReference.capture(r.state.entities[i])for i in r.player(request.player_id).deck)
    # Replacement is not discard, deck destruction or an actual shuffle.
    work=remove_from_game(r,RemoveFromGame(old,request.source_id))
    if work:raise ValueError('Original deck replacement returned asynchronous removal work')
    for entry in entries:
        r.charge();copy_physical_card(r,entry)
        if r._choice_request is not None:raise ValueError('Synchronous deck copy opened a new choice')
    return()


def register(mechanics):mechanics.register(CopyOpponentDeck,copy)
