"""Original physical material for each actual Discover menu slot.

This is preparation for playing offered cards, not another acquisition or
card executor. The original option still owns its complete delivery recipe.
Selected-only rewards are deliberately not applied to the other slots here.
"""
from dataclasses import dataclass

from .copy_materials import CapturedCardCopyMaterial, CopyEntryMaterial
from .model import DeathRecord
from .discard_history import DiscardRecord


@dataclass(frozen=True)
class OfferedCardMaterial:
    option_id: str
    card_id: str
    route: str
    physical: CapturedCardCopyMaterial | None = None
    copied: CopyEntryMaterial | None = None
    death: DeathRecord | None = None
    discard: DiscardRecord | None = None

    def __post_init__(self):
        if any(type(v) is not str or not v for v in (self.option_id, self.card_id)):
            raise ValueError('Offered material requires its exact original menu slot')
        if self.route not in ('printed', 'physical', 'copied', 'death', 'discard', 'unavailable'):
            raise ValueError('Unknown original offered material route')
        values = ((self.physical, CapturedCardCopyMaterial, 'physical'),
                  (self.copied, CopyEntryMaterial, 'copied'),
                  (self.death, DeathRecord, 'death'),
                  (self.discard, DiscardRecord, 'discard'))
        for value, kind, route in values:
            if (value is not None) != (self.route == route):
                raise ValueError('Offered material lost or invented its original producer')
            if value is None:
                continue
            if type(value) is not kind:
                raise ValueError('Offered material requires its complete typed original')
            value.__post_init__()
            face = value.origin.card_id if kind is CapturedCardCopyMaterial else value.card_id
            if face != self.card_id:
                raise ValueError('Offered material borrowed another card face')


def _physical(r, option, card):
    """Capture an exact reference now; a later same-name card is irrelevant."""
    from .zones import CardReference, reference_entity
    from .sacrifice import MinionReference, live_minion
    if type(card) is CapturedCardCopyMaterial:
        return OfferedCardMaterial(option.id, option.card_id, 'physical', physical=card)
    if type(card) is CopyEntryMaterial:
        return OfferedCardMaterial(option.id, option.card_id, 'copied', copied=card)
    if type(card) is DeathRecord:
        if card.id > len(r.state.death_history) or r.state.death_history[card.id - 1] != card:
            raise ValueError('Offered death is not the actual original death')
        return OfferedCardMaterial(option.id, option.card_id, 'death', death=card)
    if type(card) is DiscardRecord:
        if card.id > len(r.state.discard_history) or r.state.discard_history[card.id - 1] != card:
            raise ValueError('Offered discard is not the actual original occurrence')
        return OfferedCardMaterial(option.id, option.card_id, 'discard', discard=card)
    if type(card) is CardReference:
        entity = reference_entity(r, card)
    elif type(card) is MinionReference:
        entity = live_minion(r.state, card)
    else:
        raise ValueError('Unknown physical offered-card reference')
    if entity is None:
        return OfferedCardMaterial(option.id, option.card_id, 'unavailable')
    return OfferedCardMaterial(option.id, option.card_id, 'physical',
        physical=CapturedCardCopyMaterial.capture(r.state, entity))


def capture(r, option):
    """Read original producer work. Never run it, sample, allocate or move."""
    from .effects import AddToHand
    from .sideboards import _TakeSideboardCard
    from .zones import AddToDeck, CopyCard, MoveCard, DiscardCard
    from .temporary_cards import CreateTemporaryCard
    from .discovery import ResolvePoolDiscovery
    from .stored_gift_discovery import SelectGiftedDeckCard
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer
    from .hand_choice_followups import ResolveHandFollowupChoice, record
    from .summon_sources import ResurrectMinion
    # All currently supported genuine discovery producers have one original
    # delivery operation. Do not infer hidden material from a CardPreview.
    if len(option.effects) > 1:
        raise ValueError('Offered card requires one explicit original producer')
    if not option.effects:
        return OfferedCardMaterial(option.id, option.card_id, 'printed')
    work = option.effects[0]
    if type(work) in (AddToHand, AddToDeck, CreateTemporaryCard, ResolvePoolDiscovery, _TakeSideboardCard):
        card_id = work.selection.card_id if type(work) is ResolvePoolDiscovery else work.card_id
        if card_id != option.card_id:
            raise ValueError('Offered printed recipe differs from its menu face')
        return OfferedCardMaterial(option.id, option.card_id, 'printed')
    if type(work) in (CopyCard, MoveCard, DiscardCard):
        return _physical(r, option, work.card)
    if type(work) is SelectGiftedDeckCard:
        return _physical(r, option, work.offered[work.index].card)
    if type(work)is CopyOpponentDeckOffer:
        return _physical(r,option,work.offered[work.index].material)
    if type(work) is ResolveHandFollowupChoice:
        root = record(r.state, work.followup_id)
        original = next((o for o in root.offers if o.id == work.option_id), None)
        if original is None or original.card_id != option.card_id:
            raise ValueError('Offered followup lost its actual original slot')
        return (_physical(r, option, original.card) if original.card is not None else
                OfferedCardMaterial(option.id, option.card_id, 'printed'))
    if type(work) is ResurrectMinion:
        if not 1 <= work.death_id <= len(r.state.death_history):
            raise ValueError('Offered resurrection lost its actual death')
        return _physical(r, option, r.state.death_history[work.death_id - 1])
    raise ValueError('Unsupported original offered-card producer: ' + type(work).__name__)


def validate_material(state, registry, value):
    """Closed original facts may outlive source movement, transformation or death."""
    value.__post_init__()
    registry.card(value.card_id)
    if value.physical is not None:
        from .copy_materials import validate_captured_card_copy
        validate_captured_card_copy(state, registry, value.physical)
    if value.copied is not None:
        from .copy_materials import validate_scope
        validate_scope(state, registry, value.copied, closed=True, hand_copy=True)
    for row, history in ((value.death, state.death_history), (value.discard, state.discard_history)):
        if row is not None and (row.id > len(history) or history[row.id - 1] != row):
            raise ValueError('Offered material lost its original committed occurrence')


def register(mechanics):
    mechanics.register_payload_type(OfferedCardMaterial)
