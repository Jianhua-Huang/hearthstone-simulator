"""Committed armor grants, without maintaining a second armor balance."""
from dataclasses import dataclass, fields

from .effects import _player
from .model import CardType, _int

EVENT = 'armor_gain_recorded'
ORIGINS = ('gain_armor', 'hero_card', 'replacement', 'generated_hero')


@dataclass(frozen=True)
class ArmorGainRecord:
    id: int
    player_id: int
    hero_id: int
    active_player: int
    turn: int
    action: int
    owner_turn_id: int
    before: int
    amount: int
    after: int
    event_sequence: int
    origin: str

    def __post_init__(self):
        _player(self.player_id); _player(self.active_player)
        for key in ('id', 'hero_id', 'event_sequence'):
            _int(getattr(self, key), 'armor grant '+key, 1)
        for key in ('turn', 'action', 'owner_turn_id', 'before', 'amount', 'after'):
            _int(getattr(self, key), 'armor grant '+key, 0)
        if type(self.origin) is not str or self.origin not in ORIGINS or self.after != self.before+self.amount:
            raise ValueError('Armor grant lost its original operation or committed delta')

    def payload(self):
        return tuple((f.name, getattr(self, f.name)) for f in fields(self))


def commit(r, hero, before, amount, origin):
    """Original mutators call after assignment and just before their public event."""
    owner = r.state.owner_turn_history[-1] if r.state.owner_turn_history else None
    if owner is not None and (owner.closed or (owner.turn, owner.player_id) != (r.state.turn, r.state.active_player)):
        raise ValueError('Armor grant has no actual active owner interval')
    row = ArmorGainRecord(len(r.state.armor_gain_history)+1, hero.controller, hero.id,
        r.state.active_player, r.state.turn, r.state.action_number, owner.id if owner else 0,
        before, amount, hero.armor, len(r.game._events)+1, origin)
    if hero.kind != CardType.HERO or r.state.players[row.player_id].hero_id != hero.id:
        raise ValueError('Armor grant must belong to the installed physical Hero')
    r.state.armor_gain_history.append(row)
    r.emit(EVENT, player_id=row.player_id, target_id=row.hero_id, amount=row.amount, record=row.payload())


def validate_state(state, registry=None):
    rows = state.armor_gain_history
    if type(rows) is not list:
        raise ValueError('Armor gain history requires its complete immutable facts')
    previous_event = previous_action = previous_turn = 0
    for index, row in enumerate(rows, 1):
        if type(row) is not ArmorGainRecord:
            raise ValueError('Armor gain history requires ArmorGainRecord')
        row.__post_init__()
        if (row.id != index or row.event_sequence <= previous_event or
                not previous_action <= row.action <= state.action_number or
                not previous_turn <= row.turn <= state.turn):
            raise ValueError('Armor gain history changed its original chronology')
        hero = state.entities.get(row.hero_id)
        if (hero is None or hero.id >= state.next_entity_id or
                (hero.kind, hero.owner, hero.controller) != (CardType.HERO, row.player_id, row.player_id) or
                registry is not None and registry.card(hero.card_id).kind != CardType.HERO):
            raise ValueError('Armor gain history changed its original physical Hero')
        if row.owner_turn_id:
            if row.owner_turn_id > len(state.owner_turn_history):
                raise ValueError('Armor grant borrowed an unknown owner interval')
            owner = state.owner_turn_history[row.owner_turn_id-1]
            if ((owner.turn, owner.player_id) != (row.turn, row.active_player) or
                    row.action < owner.start_action or row.event_sequence <= owner.start_event or
                    owner.closed_action is not None and row.action > owner.closed_action or
                    owner.closed_event is not None and row.event_sequence > owner.closed_event):
                raise ValueError('Armor grant is outside its original owner interval')
        elif (row.turn != 1 or state.owner_turn_history and
                (row.event_sequence > state.owner_turn_history[0].start_event or
                 row.action > state.owner_turn_history[0].start_action)):
            raise ValueError('Pre-first armor grant borrowed a later actual turn')
        previous_event, previous_action, previous_turn = row.event_sequence, row.action, row.turn


def gained_this_turn(state, player_id):
    """Pure native predicate; does not read host logs, current armor or a cache."""
    _player(player_id)
    validate_state(state)
    return any(row.player_id == player_id and row.turn == state.turn and row.amount > 0
        for row in state.armor_gain_history)


def validate_boundary(game):
    validate_state(game._state, game.registry)
    from .hero_health_history import effective_events
    timeline = tuple(effective_events(game._events))
    recorded = tuple(e for e in timeline if e.kind == EVENT)
    if len(recorded) != len(game._state.armor_gain_history):
        raise ValueError('Armor gain history lost its complete original event inventory')
    by_sequence = {e.sequence: e for e in timeline}
    paired = set()
    for row, event in zip(game._state.armor_gain_history, recorded):
        if (len(event.data) != 1 or dict(event.data).get('record') != row.payload() or
                (event.sequence, event.action, event.source_id, event.target_id, event.player_id, event.amount) !=
                (row.event_sequence, row.action, None, row.hero_id, row.player_id, row.amount)):
            raise ValueError('Armor grant differs from its complete original event')
        following = by_sequence.get(event.sequence+1)
        kind = 'armor_gained' if row.origin == 'gain_armor' else 'hero_replaced'
        if (following is None or following.kind != kind or
                (following.action, following.player_id, following.target_id) != (row.action, row.player_id, row.hero_id) or
                kind == 'armor_gained' and following.amount != row.amount):
            raise ValueError('Armor grant lost its original public operation')
        paired.add(following.sequence)
    if paired != {e.sequence for e in timeline if e.kind in ('armor_gained', 'hero_replaced')}:
        raise ValueError('Armor gain history omitted an actual gain or Hero installation')


def register(mechanics):
    mechanics.register_payload_type(ArmorGainRecord)
