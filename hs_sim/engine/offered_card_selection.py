"""A real Discover source for the shared whole-card interpreter.

Menu slots belong to their actual discovery, never the paid PlayRecord ID
namespace. No sampling, payment, acquisition or fabricated historical play.
"""
from dataclasses import dataclass

from .model import CardDiscoveryRecord, CardType
from .whole_card_history import integer, rng_state


@dataclass(frozen=True)
class OfferedCardSlot:
    option_id: str
    card_id: str
    kind: CardType

    def __post_init__(self):
        if (any(type(s) is not str or not s for s in (self.option_id, self.card_id))
                or type(self.kind) is not CardType or self.kind == CardType.HERO_POWER):
            raise ValueError('Offered slot requires its exact original playable face')

    @property
    def occurrence(self): return self

    @property
    def face(self): return self


@dataclass(frozen=True)
class OfferedCardSelection:
    discovery: CardDiscoveryRecord
    rows: tuple[OfferedCardSlot, ...]
    captured_turn: int
    captured_action: int
    owner_turn_size: int
    rng_before: tuple
    rng_after: tuple
    origin: str = 'original_discovery_v1'

    def __post_init__(self):
        if type(self.discovery) is not CardDiscoveryRecord or self.origin != 'original_discovery_v1':
            raise ValueError('Offered selection requires its actual immutable discovery')
        self.discovery.__post_init__()
        for name, floor in (('captured_turn', 1), ('captured_action', 0), ('owner_turn_size', 1)):
            integer(getattr(self, name), name, floor)
        if (type(self.rows) is not tuple or any(type(r) is not OfferedCardSlot for r in self.rows)
                or tuple((r.option_id, r.card_id) for r in self.rows) !=
                tuple((o.id, o.card_id) for o in self.discovery.result.choice.options)):
            raise ValueError('Offered execution changed the complete ordered original menu')
        for row in self.rows: row.__post_init__()
        if self.discovery.turn > self.captured_turn or self.discovery.action > self.captured_action:
            raise ValueError('Offered execution borrowed a future discovery')
        rng_state(self.rng_before); rng_state(self.rng_after)
        if self.rng_before != self.rng_after:
            raise ValueError('Original offered execution cannot sample another menu')

    @property
    def frontier(self): return self

    @property
    def selected_ids(self):
        selected = self.discovery.result.selected_ids
        return tuple(i for i, row in enumerate(self.rows, 1) if row.option_id not in selected)

    @property
    def history_size(self): return 0


def capture(state, registry, discovery_id, rng):
    integer(discovery_id, 'actual offered discovery')
    if discovery_id > len(state.card_discovery_history):
        raise ValueError('Unknown offered-card discovery')
    original = state.card_discovery_history[discovery_id - 1]
    return OfferedCardSelection(original, tuple(OfferedCardSlot(o.id, o.card_id,
        registry.card(o.card_id).kind) for o in original.result.choice.options),
        state.turn, state.action_number, len(state.owner_turn_history), rng, rng)


def validate_registry(selection, registry):
    selection.__post_init__()
    for slot in selection.rows:
        card = registry.card(slot.card_id)
        if card.kind != slot.kind or not card.hand_playable or card.choice_only:
            raise ValueError('Offered execution changed its original registered playable kind')


def validate_origin(selection, state, registry, *, accepted_window=False):
    validate_registry(selection, registry)
    row = selection.discovery
    if row.id > len(state.card_discovery_history) or state.card_discovery_history[row.id - 1] != row:
        raise ValueError('Offered execution lost its exact original discovery and materials')
    if accepted_window and (selection.captured_turn, selection.captured_action, selection.owner_turn_size) != (
            state.turn, state.action_number, len(state.owner_turn_history)):
        raise ValueError('Offered execution changed its actual acceptance window')


def source_key(selection, slot_id):
    if type(selection) is OfferedCardSelection:
        return ('original_discovery', selection.discovery.id, selection.discovery.result.choice.id,
            selection.rows[slot_id - 1].option_id)
    return ('paid_play', slot_id)


def selection_from_dict(value):
    from .serialization import _row, _list
    from .card_discoveries import record_from_dict
    data = _row(value, OfferedCardSelection)
    data['discovery'] = record_from_dict(data['discovery'])
    data['rows'] = tuple(OfferedCardSlot(r['option_id'], r['card_id'], CardType(r['kind']))
        for r in (_row(v, OfferedCardSlot) for v in _list(data['rows'], 'offered slots')))
    for key in ('rng_before', 'rng_after'):
        raw = _list(data[key], 'original offered execution RNG')
        data[key] = (raw[0], tuple(raw[1]), raw[2])
    return OfferedCardSelection(**data)
