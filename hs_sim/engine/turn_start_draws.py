"""Native source suppression of only the scheduled normal turn-start draw."""
from collections import Counter
from dataclasses import dataclass
from .effects import Draw,Effect,_player,_source
from .lifecycle import active_abilities
from .model import CardType,Zone,_name


@dataclass(frozen=True)
class TurnDrawSuppressionProfile:
    card_id:str
    def __post_init__(self):_name(self.card_id,'native turn draw provider')


@dataclass(frozen=True)
class TurnDrawReplacementProfile:
    spec_id: str
    behavior_id: str

    def __post_init__(self):
        _name(self.spec_id, 'turn draw player program')
        _name(self.behavior_id, 'turn draw replacement behavior')


def validate_replacement_profile(registry, profile):
    from .model import PlayerEffectSpec
    if type(profile) is not TurnDrawReplacementProfile:
        raise ValueError('Expected a native turn draw replacement profile')
    profile.__post_init__()
    spec = registry.player_effect(profile.spec_id)
    registry.behavior(profile.behavior_id)
    if spec != PlayerEffectSpec(spec.id, spec.card_id):
        raise ValueError('Turn draw replacement requires one independent permanent player program')
    card=registry.card(spec.card_id)
    if (card.kind not in (CardType.MINION,CardType.SPELL) or card.choice_only or
            card.kind==CardType.SPELL and card.on_play is None):
        raise ValueError('Native turn draw replacement requires its printed minion or executable spell source')


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


@dataclass(frozen=True)
class DrawDeckEdge(Effect):
    """A single real draw at the current edge, using the ordinary draw engine."""
    player_id:int
    edge:str
    source_id:int|None=None

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id)
        if type(self.edge)is not str or self.edge not in ('top','bottom'):
            raise ValueError('Deck edge draw requires top or bottom')


def draw_edge(r,request):
    request.__post_init__()
    if request.edge=='top':return (Draw(request.player_id,source_id=request.source_id),)
    from .draw_casts import draw_one
    from .zones import CardReference
    deck=r.player(request.player_id).deck
    card=CardReference.capture(r.state.entities[deck[-1]]) if deck else None
    return draw_one(r,request.player_id,card=card,source_id=request.source_id)


def draw(r,request):
    request.__post_init__()
    if request.player_id!=r.state.active_player:raise ValueError('Normal turn draw requires the active original seat')
    sources=providers(r.state,r.registry,request.player_id)
    if sources:
        r.emit('turn_draw_suppressed',player_id=request.player_id,source_ids=sources);return()
    # Existing duplicate program instances retain their own identity. A single
    # scheduled draw has one replacement; the most recently installed wins.
    for instance in reversed(r.player(request.player_id).player_effects):
        profile = r.registry.turn_draw_replacement_profiles.get(instance.spec_id)
        if profile is not None:
            validate_replacement_profile(r.registry, profile)
            return (r.call(profile.behavior_id, instance.source_id, request.player_id,
                player_effect=instance),)
    return(Draw(request.player_id),)


def register(mechanics):
    mechanics.register(DrawAtTurnStart,draw)
    mechanics.register(DrawDeckEdge,draw_edge)
