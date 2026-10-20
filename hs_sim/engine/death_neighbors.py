"""Original adjacent residences and execution-time buffs over surviving bodies."""
from dataclasses import dataclass
from .board_presence import resolve_board_presence
from .effects import Buff, Effect, _integer, _player
from .model import BoardPresenceReference, CardType, Zone


def capture(state, source):
    if source.zone != Zone.BOARD or source.kind != CardType.MINION: return ()
    board = state.players[source.controller].board
    if source.id not in board: raise ValueError('Neighbor source lost its original board slot')
    index = board.index(source.id)
    return tuple(BoardPresenceReference.capture(state, board[i]) for i in (index-1, index+1)
        if 0 <= i < len(board) and state.entities[board[i]].kind == CardType.MINION)


def references(context):
    execution = context.deathrattle
    if execution is not None and execution.death_id is not None:
        death = context.death
        if (death is None or death.id != execution.death_id or
                death.entity_id != context.source_id or execution.carrier_id != context.source_id):
            raise ValueError('Adjacent death effect borrowed another original carrier')
        refs = death.adjacent_minions
    else:
        refs = capture(context.state, context.source)
    return refs


@dataclass(frozen=True)
class BuffBoardPresence(Effect):
    reference: BoardPresenceReference
    player_id: int
    attack: int
    health: int
    source_id: int

    def __post_init__(self):
        if type(self.reference) is not BoardPresenceReference: raise ValueError('Buff requires original board presence')
        self.reference.__post_init__(); _player(self.player_id)
        _integer(self.attack, 'board presence buff attack'); _integer(self.health, 'board presence buff health', 0)
        _integer(self.source_id, 'original buff source', 1)


def apply_buff(r, effect):
    if effect.source_id not in r.state.entities: raise ValueError('Unknown original board buff source')
    entity = resolve_board_presence(r.state, effect.reference)
    if (entity is None or entity.controller != effect.player_id or not entity.active or entity.health <= 0 or
            entity.doomed or r.registry.card(entity.card_id).interactable is not None): return ()
    return (Buff(entity.id, effect.attack, effect.health, effect.source_id),)


def register(mechanics):
    mechanics.register(BuffBoardPresence, apply_buff)


def validate_record(state, record):
    for ref in record.adjacent_minions:
        if ref.entity_id not in state.entities or ref.presence_id >= state.next_order:
            raise ValueError('Death neighbor exceeds its original physical allocation')


def validate_events(state, events):
    """Bind saved neighbors to actual death facts; unsigned saves are not authenticated."""
    notifications = {}
    for event in events:
        if event.kind not in ('minion_died', 'location_destroyed'): continue
        data = dict(event.data)
        notifications[(event.source_id, data.get('death_id'), data.get('batch'), data.get('position'))] = data.get('_death_neighbors')
    for record in state.death_history:
        if record.zone != Zone.BOARD: continue
        expected = tuple((x.entity_id, x.presence_id) for x in record.adjacent_minions)
        if notifications.get((record.entity_id, record.id, record.batch, record.position)) != expected:
            raise ValueError('Saved death neighbors differ from their original death notification')
