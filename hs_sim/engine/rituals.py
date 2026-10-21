"""Actual original-instance ritual completion facts; the old timer still ticks.

The owner-start clock and completion-before-expiry-observers window are explicit
internal policy, pending CN calibration. Cancellation is not completion.
"""
from dataclasses import asdict, dataclass
import json

from .effects import _integer, _player
from .model import PlayerEffect

KEY = '_ritual_completion'


@dataclass(frozen=True)
class RitualCompletion:
    id: int
    player_id: int
    instance: PlayerEffect
    turn: int
    action: int
    owner_index: int
    event_sequence: int

    def __post_init__(self):
        _player(self.player_id)
        for name in ('id', 'turn', 'owner_index', 'event_sequence'):
            _integer(getattr(self, name), 'ritual completion '+name, 1)
        _integer(self.action, 'ritual completion action', 0)
        if type(self.instance) is not PlayerEffect:
            raise ValueError('Ritual completion requires its complete original player instance')
        self.instance.__post_init__()
        if self.instance.remaining_turns != 1:
            raise ValueError('Ritual completion must consume the last actual original tick')


def prepare(r, player_id, instance):
    """Called only after the original timer consumes an actual last instance."""
    from .owner_turns import current_owner_turn
    spec = r.registry.player_effect(instance.spec_id)
    if spec.kind != 'ritual':
        raise ValueError('Only actual ritual expiry publishes a ritual completion')
    interval = current_owner_turn(r.state)
    if (interval.player_id, interval.origin) != (player_id, 'actual'):
        raise ValueError('Ritual completion needs its actual owner-start interval')
    row = RitualCompletion(r.state.next_ritual_completion_id, player_id, instance,
        r.state.turn, r.state.action_number, interval.owner_index, len(r.game._events)+1)
    if any(old.instance.id == instance.id for old in r.state.ritual_completions):
        raise ValueError('An original ritual instance cannot complete twice')
    r.state.ritual_completions.append(row)
    r.state.next_ritual_completion_id += 1
    return {KEY: json.dumps(asdict(row), ensure_ascii=False, sort_keys=True, separators=(',', ':'))}


def completed_rituals(state, player_id):
    """Pure State query, including genuinely completed empty/full-board rituals."""
    _player(player_id)
    if type(state.ritual_completions) is not list or any(type(row) is not RitualCompletion
            for row in state.ritual_completions):
        raise ValueError('Complete immutable ritual facts required')
    return tuple(row for row in state.ritual_completions if row.player_id == player_id)


def validate_history(state, registry):
    _integer(state.next_ritual_completion_id, 'next ritual completion identity', 1)
    if (type(state.ritual_completions) is not list or
            len(state.ritual_completions) != state.next_ritual_completion_id-1):
        raise ValueError('Ritual completion history lost its complete allocation prefix')
    seen = set(); previous = 0
    active = {effect.id for player in state.players.values() for effect in player.player_effects}
    intervals = {(r.player_id, r.owner_index): r for r in state.owner_turn_history}
    for index, row in enumerate(state.ritual_completions, 1):
        if type(row) is not RitualCompletion:
            raise ValueError('Typed original ritual completion required')
        row.__post_init__(); effect = row.instance; spec = registry.player_effect(effect.spec_id)
        interval = intervals.get((row.player_id, row.owner_index))
        if (row.id != index or row.event_sequence <= previous or effect.id in seen or effect.id in active or
                spec.kind != 'ritual' or effect.created_turn > row.turn or row.turn > state.turn or
                row.action > state.action_number or effect.entered_order >= state.next_order or
                effect.id >= state.next_attachment_id or effect.source_id not in state.entities or
                interval is None or interval.origin != 'actual' or interval.turn != row.turn):
            raise ValueError('Ritual completion changed original instance, clock or chronology')
        seen.add(effect.id); previous = row.event_sequence


def from_dict(value):
    from .serialization import _row, player_effect_from_dict
    row = _row(value, RitualCompletion)
    row['instance'] = player_effect_from_dict(row['instance'])
    return RitualCompletion(**row)


def rows_from_dict(value):
    from .serialization import _list
    value['ritual_completions'] = [from_dict(row) for row in
        _list(value['ritual_completions'], 'actual ritual completions')]


def validate_boundary(game):
    from .hero_health_history import effective_events
    rows = game._state.ritual_completions
    events = [e for e in effective_events(game._events) if e.kind == 'player_effect_expired'
        and dict(e.data).get('effect_kind') == 'ritual']
    if len(rows) != len(events):
        raise ValueError('Ritual completions lost their complete original expiry inventory')
    for row, event in zip(rows, events):
        data = dict(event.data); encoded = data.pop(KEY, None)
        if type(encoded) is not str or from_dict(json.loads(encoded)) != row:
            raise ValueError('Ritual completion changed its original published fact')
        spec = game.registry.player_effect(row.instance.spec_id)
        if (event.sequence, event.source_id, event.player_id, event.action) != (
                row.event_sequence, row.instance.source_id, row.player_id, row.action) or data != dict(
                effect_key=spec.id, card_id=spec.card_id, effect_kind='ritual', remaining_turns=0):
            raise ValueError('Ritual completion borrowed another actual expiry')


def from_expiry(context):
    if (context.event is None or context.event.kind != 'player_effect_expired' or
            context.player_effect is None):
        raise ValueError('Ritual payload requires its actual original completed instance')
    rows = [row for row in completed_rituals(context.state, context.player_id)
        if row.event_sequence == context.event.sequence and row.instance == context.player_effect]
    if len(rows) != 1:
        raise ValueError('Ritual payload lost its original completion')
    return rows[0]
