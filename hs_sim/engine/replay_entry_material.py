"""Printed primary entry linked to one accepted whole-card occurrence.

Ordinary generic summons retain their existing non-composite restriction.
This recipe adds no copying, historical enchantments or magnetic hand merge.
Common entity creation, dormancy, Herald and Colossal entry remain responsible.
"""
from dataclasses import dataclass
from .model import CardType, _int


@dataclass(frozen=True)
class PhysicalReplayEntryMaterial:
    card_id: str
    root_id: int
    child_id: int
    profile: str = 'whole_card_printed_primary_v1'

    def __post_init__(self):
        if type(self.card_id) is not str or not self.card_id or self.profile not in (
                'whole_card_printed_primary_v1', 'whole_card_original_offer_primary_v1'):
            raise ValueError('Whole-card primary entry lost its explicit printed recipe')
        _int(self.root_id, 'original whole-card entry root', 1); _int(self.child_id, 'original whole-card entry child', 1)

    @property
    def stats(self): return None

    @property
    def deathrattles(self): return ()

    @property
    def keywords(self): return ()


def validate_material(registry, material):
    material.__post_init__(); card = registry.card(material.card_id)
    if card.kind != CardType.MINION or not card.hand_playable or card.choice_only:
        raise ValueError('Whole-card primary requires a registered physical hand minion')


def validate_scope(state, registry, request, material):
    validate_material(registry, material)
    ledger = state.whole_card_replay_ledger
    if material.root_id > len(ledger.roots) or material.child_id > len(ledger.children):
        raise ValueError('Whole-card entry borrowed an unknown or future accepted invocation')
    root = ledger.roots[material.root_id - 1]; child = ledger.children[material.child_id - 1]
    from .offered_card_selection import OfferedCardSelection
    if (material.profile == 'whole_card_original_offer_primary_v1') != (type(root.selection) is OfferedCardSelection):
        raise ValueError('Primary material changed its actual history or offered-card source')
    if (root.runtime_route != 'cards_v1' or child.root_id != root.id or child.card_id != material.card_id
            or child.kind != CardType.MINION or request.player_id != root.player_id
            or request.cause.source.entity_id != root.caster.entity_id
            or request.cause.action < root.accepted_action or request.cause.turn < root.accepted_turn
            or request.selection != 'first' or request.materials != (material,)
            or request.capacity != 'selection_requires_space' or request.producer_link is not None):
        raise ValueError('Whole-card entry differs from its exact original selected primary')
    matches = tuple(r for r in state.card_summon_history if r.request.materials == (material,))
    if len(matches) > 1: raise ValueError('Whole-card primary entry allocated more than one original summon root')
