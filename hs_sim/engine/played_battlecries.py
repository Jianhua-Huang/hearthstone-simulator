"""Frozen declarations of committed cards, separate from activation history.

R-121: counter eligibility and selection windows are explicit policy. A borrowed
payload does not acquire the original PlayRecord as its current hand play.
"""
from dataclasses import dataclass
from .effects import Effect, _integer, _player
from .errors import ResolutionLimitExceeded
from .model import BattlecryRecord, CardType
from .targeting import effect_policies


@dataclass(frozen=True)
class PlayedBattlecryQuery:
    turn: int | None = None
    before_id: int | None = None
    exclude_ids: tuple[int, ...] = ()
    countered: str = 'exclude'
    kinds: tuple[CardType, ...] = (CardType.MINION,CardType.WEAPON,CardType.HERO)

    def __post_init__(self):
        for value in (self.turn,self.before_id):
            if value is not None: _integer(value,'played Battlecry query bound',1)
        if type(self.exclude_ids) is not tuple or len(set(self.exclude_ids)) != len(self.exclude_ids):
            raise ValueError('Played Battlecry exclusions require unique immutable IDs')
        for value in self.exclude_ids: _integer(value,'excluded Battlecry play',1)
        if self.countered not in ('exclude','include','only'):
            raise ValueError('Unknown played Battlecry counter policy')
        if (type(self.kinds) is not tuple or not self.kinds or len(set(self.kinds)) != len(self.kinds) or
                any(type(k) is not CardType or k not in (CardType.MINION,CardType.WEAPON,CardType.HERO) for k in self.kinds)):
            raise ValueError('Invalid played Battlecry kinds')


def played_battlecry_candidates(state,player_id,query=PlayedBattlecryQuery()):
    """One candidate per completed play, preserving each frozen payload's order."""
    _player(player_id)
    if type(query) is not PlayedBattlecryQuery: raise ValueError('Expected PlayedBattlecryQuery')
    query.__post_init__()
    return tuple(p for p in state.play_history if p.player_id == player_id and p.completed and
        p.battlecries and p.kind in query.kinds and p.id not in query.exclude_ids and
        (query.turn is None or p.turn == query.turn) and (query.before_id is None or p.id < query.before_id) and
        (query.countered == 'include' or p.countered == (query.countered == 'only')))


def played_source(state,play_id,player_id):
    from .play_history import play_record
    play=play_record(state,play_id)
    if play.player_id != player_id or not play.completed or not play.battlecries:
        raise ValueError('Played Battlecry source must be a completed play with captured declarations of this player')
    return play


def validate_played_payload(state,play_id,player_id,payload):
    play=played_source(state,play_id,player_id)
    if payload not in play.battlecries: raise ValueError('Played Battlecry payload differs from captured declaration')
    return play


def battlecry_play_window(state,battlecry):
    """Original execution's exclusive play bound, including nested borrowed cards.

This is a reusable historical-window policy, not a global definition of every
card that says 'last'. Effect activations use the plays committed by their start.
"""
    from .battlecries import battlecry_record
    if type(battlecry) is not BattlecryRecord or battlecry not in state.battlecry_history:
        raise ValueError('Battlecry window requires an existing captured activation')
    record=battlecry
    while record.origin == 'history':
        parent=battlecry_record(state,record.history_id)
        if parent.id >= record.id: raise ValueError('Cyclic Battlecry history source')
        record=parent
    if record.origin == 'hand': return record.play_id
    if record.origin == 'played_history': return record.history_play_id
    return max((p.id for p in state.play_history if p.action <= record.action),default=0)+1


@dataclass(frozen=True)
class RepeatPlayedBattlecry(Effect):
    player_id: int
    source_id: int
    play_id: int
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    profile_id: str | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id,'played Battlecry carrier',1)
        _integer(self.play_id,'Battlecry source play',1)
        effect_policies(self.targeting,self.target_id,self.choices)
        if self.profile_id is not None:
            from .effects import _behavior
            _behavior(self.profile_id)


@dataclass(frozen=True)
class RepeatPlayedBattlecries(Effect):
    player_id: int
    source_id: int
    query: PlayedBattlecryQuery = PlayedBattlecryQuery()
    selection: str = 'last'
    order: str = 'chronological'
    choices: str = 'random'
    profile_id: str | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id,'played Battlecry carrier',1)
        if type(self.query) is not PlayedBattlecryQuery: raise ValueError('Expected PlayedBattlecryQuery')
        self.query.__post_init__()
        if self.selection not in ('first','last','all') or self.order not in ('chronological','random'):
            raise ValueError('Invalid played Battlecry history selection')
        effect_policies('random',None,self.choices)
        if self.profile_id is not None:
            from .effects import _behavior
            _behavior(self.profile_id)


def repeat(r,effect):
    from .battlecry_sources import BeginIndirectBattlecry, carrier_card
    effect.__post_init__()
    play=played_source(r.state,effect.play_id,effect.player_id)
    card=carrier_card(r.state,r.registry,effect.source_id)
    return tuple(BeginIndirectBattlecry(effect.source_id,effect.player_id,card,p,'played_history',
        caster_id=effect.source_id,target_id=effect.target_id,targeting=effect.targeting,
        choices=effect.choices,history_play_id=play.id,history_player_id=effect.player_id,
        historical_profile_id=effect.profile_id) for p in play.battlecries)


def repeat_many(r,effect):
    from .battlecry_sources import carrier_card
    effect.__post_init__(); carrier_card(r.state,r.registry,effect.source_id)
    records=played_battlecry_candidates(r.state,effect.player_id,effect.query)
    if effect.selection == 'first': records=records[:1]
    elif effect.selection == 'last': records=records[-1:]
    if sum(len(p.battlecries) for p in records) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Played Battlecry sequence exceeds resolution budget')
    if effect.order == 'random': records=tuple(r.game._rng.sample(records,len(records)))
    return tuple(RepeatPlayedBattlecry(effect.player_id,effect.source_id,p.id,choices=effect.choices,
        profile_id=effect.profile_id) for p in records)


def validate_boundary(game):
    from .battlecry_sequences import validate_boundary as validate_sequences
    validate_sequences(game)
    from .battlecry_sources import carrier_card
    queue=(*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    for work in queue:
        if type(work) is RepeatPlayedBattlecry:
            work.__post_init__(); played_source(game._state,work.play_id,work.player_id)
            carrier_card(game._state,game.registry,work.source_id)


def register(mechanics):
    from .battlecry_sequences import register as register_sequences
    register_sequences(mechanics)
    mechanics.register_payload_type(PlayedBattlecryQuery)
    mechanics.register(RepeatPlayedBattlecry,repeat)
    mechanics.register(RepeatPlayedBattlecries,repeat_many)
