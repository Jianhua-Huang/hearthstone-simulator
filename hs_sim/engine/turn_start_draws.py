"""Native source suppression of only the scheduled normal turn-start draw."""
from collections import Counter
from dataclasses import dataclass
from .effects import Draw,Effect,_player
from .lifecycle import active_abilities
from .model import CardType,Zone,_name


@dataclass(frozen=True)
class TurnDrawSuppressionProfile:
    card_id:str
    def __post_init__(self):_name(self.card_id,'native turn draw provider')


def validate_profile(registry,profile):
    if type(profile)is not TurnDrawSuppressionProfile:raise ValueError('Expected native turn draw profile')
    profile.__post_init__();card=registry.card(profile.card_id)
    if card.kind!=CardType.MINION or card.starship_for or card.choice_only:
        raise ValueError('Turn draw suppression requires an ordinary native minion')


def validate_carrier(registry,card_id,kind,abilities,components=()):
    rows=tuple(a for a in abilities if a.kind=='turn_draw_suppression')
    if not rows:return
    if kind!=CardType.MINION:raise ValueError('Turn draw source requires its original minion carrier')
    allowed,counts=Counter((card_id,*components)),Counter()
    for ability in rows:
        ability.__post_init__();profile=registry.turn_draw_profiles.get(ability.turn_draw_card_id)
        if profile is None:raise ValueError('Turn draw source lost its native declaration')
        validate_profile(registry,profile);counts[profile.card_id]+=1
        if counts[profile.card_id]>allowed[profile.card_id]:raise ValueError('Duplicate or foreign native turn draw source')


def providers(state,registry,player_id):
    _player(player_id);found=[]
    for identity in state.players[player_id].board:
        entity=state.entities[identity]
        if entity.kind!=CardType.MINION or entity.zone!=Zone.BOARD or entity.controller!=player_id or not entity.active or entity.doomed or entity.health<=0:continue
        abilities=tuple(active_abilities(entity,'turn_draw_suppression'))
        validate_carrier(registry,entity.card_id,entity.kind,abilities,entity.components)
        if abilities:found.append(identity)
    return tuple(found)


@dataclass(frozen=True)
class DrawAtTurnStart(Effect):
    player_id:int
    def __post_init__(self):_player(self.player_id)


def draw(r,request):
    request.__post_init__()
    if request.player_id!=r.state.active_player:raise ValueError('Normal turn draw requires the active original seat')
    sources=providers(r.state,r.registry,request.player_id)
    if sources:
        r.emit('turn_draw_suppressed',player_id=request.player_id,source_ids=sources);return()
    return(Draw(request.player_id),)


def register(mechanics):mechanics.register(DrawAtTurnStart,draw)
