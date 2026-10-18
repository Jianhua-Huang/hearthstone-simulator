"""Immutable original Discover work, before selected producer binding.

This preserves the actual offered recipes; it does not play unselected cards.
The private acceptance publication is a boundary witness, never a gameplay
search or authentication of an unsigned imported save.
"""
from dataclasses import dataclass
import json

from .effects import ChoiceOption, _behavior
from .model import PendingChoice
from .card_discoveries import PURPOSES, require_original_result
from .offered_card_materials import OfferedCardMaterial

ACCEPTED = 'card_discovery_offer_accepted'


@dataclass(frozen=True)
class OriginalDiscoveryOffer:
    choice: PendingChoice
    options: tuple[ChoiceOption, ...]
    on_select: str | None = None
    materials: tuple[OfferedCardMaterial, ...] = ()

    def __post_init__(self):
        if type(self.choice) is not PendingChoice or self.choice.purpose not in PURPOSES:
            raise ValueError('Original offered work requires an actual card discovery')
        self.choice.__post_init__()
        if type(self.options) is not tuple or any(type(o) is not ChoiceOption for o in self.options):
            raise ValueError('Original offered work requires complete typed options')
        for option in self.options:
            option.__post_init__()
        if tuple(o.item for o in self.options) != self.choice.options:
            raise ValueError('Original offered work changed its complete ordered menu')
        if self.on_select is not None:
            _behavior(self.on_select)
        if (type(self.materials) is not tuple or len(self.materials) != len(self.options)
                or any(type(m) is not OfferedCardMaterial for m in self.materials)):
            raise ValueError('Original offer requires every ordered original card material')
        for option, material in zip(self.options, self.materials):
            material.__post_init__()
            if (material.option_id, material.card_id) != (option.id, option.card_id):
                raise ValueError('Original offer material differs from its exact menu slot')


def encode_offer(game, offer):
    from .continuations import FrameCodec
    if type(offer) is not OriginalDiscoveryOffer:
        raise ValueError('Expected complete typed original offered work')
    offer.__post_init__()
    return json.dumps(FrameCodec(game.mechanics, game.registry).encode(offer),
        ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def decode_offer(game, value):
    from .continuations import FrameCodec
    if type(value) is not str:
        raise ValueError('Original offered work requires its complete encoded value')
    offer = FrameCodec(game.mechanics, game.registry).decode(json.loads(value))
    if type(offer) is not OriginalDiscoveryOffer or encode_offer(game, offer) != value:
        raise ValueError('Original offered work lost its canonical complete typed value')
    return offer


def capture(r, choice, options, on_select):
    if choice.purpose not in PURPOSES:
        return
    from .offered_card_materials import capture as capture_material
    offer = OriginalDiscoveryOffer(choice, tuple(options), on_select,
        tuple(capture_material(r, option) for option in options))
    r.emit(ACCEPTED, source_id=choice.source_id, player_id=choice.player_id,
        choice_id=choice.id, original_offer=encode_offer(r.game, offer), _capture=False)
    return offer


def offer_for_result(game, result):
    """Read the exact committed row, not a later hand or diagnostic scan."""
    row = require_original_result(game._state, result)
    offer = decode_offer(game, row.original_offer)
    if offer.choice != result.choice:
        raise ValueError('Original offered work borrowed another committed selection')
    return offer


def unselected_options(game, result):
    return tuple(o for o in offer_for_result(game, result).options if o.id not in result.selected_ids)


def unselected_materials(game, result):
    return tuple(m for m in offer_for_result(game, result).materials if m.option_id not in result.selected_ids)


def validate_boundary(game, events):
    publications = [e for e in events if e.kind == ACCEPTED]
    rows = game._state.card_discovery_history
    pending = game._state.pending_choice
    if not publications and not rows and (pending is None or pending.purpose not in PURPOSES):
        return
    accepted = {}
    for event in publications:
        data = dict(event.data)
        if set(data) != {'choice_id', 'original_offer'} or data['choice_id'] in accepted:
            raise ValueError('Original discovery offer was lost or accepted twice')
        offer = decode_offer(game, data['original_offer'])
        from .offered_card_materials import validate_material
        for material in offer.materials:
            validate_material(game._state, game.registry, material)
        if ((offer.choice.id, offer.choice.source_id, offer.choice.player_id) !=
                (data['choice_id'], event.source_id, event.player_id)):
            raise ValueError('Original discovery offer changed its actual actor/source')
        accepted[offer.choice.id] = (event, offer)
    committed = set()
    for row in rows:
        choice = row.result.choice
        original = accepted.get(choice.id)
        if original is None:
            raise ValueError('Committed discovery lost its original accepted offer')
        event, offer = original
        if (event.sequence >= row.selection_event or event.action > row.action or
                offer.choice != choice or row.original_offer != dict(event.data)['original_offer']):
            raise ValueError('Committed discovery changed its original accepted offer')
        committed.add(choice.id)
    open_ids = set(accepted) - committed
    expected = set()
    if pending is not None and pending.purpose in PURPOSES:
        expected.add(pending.id)
        original = accepted.get(pending.id)
        frame = game._frame
        if (original is None or frame is None or original[1].choice != pending or
                original[1].options != frame.options or original[1].on_select != frame.on_select or
                original[1] != frame.original_discovery_offer):
            raise ValueError('Waiting discovery changed its original accepted offer')
        # The paid choice witness is the original request window, including
        # physical material before reactions or later same-ID re-entry.
        from types import SimpleNamespace
        from .offered_card_materials import capture as capture_material
        origin = SimpleNamespace(state=frame.paid_hand_choice_boundary.state, registry=game.registry)
        if tuple(capture_material(origin, option) for option in frame.options) != original[1].materials:
            raise ValueError('Waiting discovery changed its actual original physical material')
    elif game._frame is not None and game._frame.original_discovery_offer is not None:
        raise ValueError('Ordinary choice cannot borrow another discovery offer')
    if game._state.status == 'playing' and open_ids != expected:
        raise ValueError('Original discovery offer lost its committed or waiting selection')


def register(mechanics):
    from .offered_card_materials import register as register_materials
    register_materials(mechanics)
    mechanics.register_payload_type(OriginalDiscoveryOffer)
