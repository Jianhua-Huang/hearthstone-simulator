"""Opt-in Ranked spells: monotone 5/10 maximum-crystal forms in hand and deck.

The current physical face stores the rank. Static families live in the pinned
registry; no player account, attachment, event, or snapshot repair is introduced.
"""
from dataclasses import dataclass

from .construction import name
from .hand_upgrades import upgrade_face
from .model import CardType, Zone

VERSION = 'mana-ranks-v1'


@dataclass(frozen=True)
class ManaRankFamily:
    id: str
    forms: tuple[str, str, str]
    version: str = VERSION

    def __post_init__(self):
        name(self.id, 'mana rank family')
        if type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported mana rank policy version')
        if type(self.forms) is not tuple or len(self.forms) != 3:
            raise ValueError('Mana ranks require three distinct ordered spell forms')
        for card_id in self.forms:
            name(card_id, 'mana rank form')
        if len(set(self.forms)) != 3:
            raise ValueError('Mana ranks require three distinct ordered spell forms')


def rank_for_maximum(maximum):
    if type(maximum) is not int or maximum < 0:
        raise ValueError('Mana rank requires nonnegative maximum crystals')
    return 2 if maximum >= 10 else 1 if maximum >= 5 else 0


def validate_families(registry):
    for identity, family in registry.mana_rank_families.items():
        if type(family) is not ManaRankFamily or family.id != identity:
            raise ValueError('Mana rank family differs from its registered key')
        family.__post_init__()
        cards = tuple(registry.card(card_id) for card_id in family.forms)
        if any(card.kind != CardType.SPELL or not card.hand_playable or card.on_play is None for card in cards):
            raise ValueError('Mana ranks require complete physical spell bodies')
        if any((card.cost, card.metadata.classes, card.spell_school) !=
               (cards[0].cost, cards[0].metadata.classes, cards[0].spell_school) for card in cards[1:]):
            raise ValueError('Mana ranks must retain printed cost, class, and school')


def synchronize(resolution):
    """Settle genuine mutations before reactions; never called when restoring."""
    registry = resolution.registry
    if not registry.mana_rank_families or resolution.game._information is None:
        return
    for player in resolution.state.players.values():
        wanted = rank_for_maximum(player.max_mana)
        for identity in (*player.hand, *player.deck):
            entity = resolution.state.entities[identity]
            family = registry.mana_rank_family(entity.card_id)
            if family is not None and family.forms.index(entity.card_id) < wanted:
                upgrade_face(resolution, entity, family.forms[wanted])


def validate_state(state, registry):
    """Reject an unsettled saved face instead of upgrading an imported snapshot."""
    if not registry.mana_rank_families:
        return
    for entity in state.entities.values():
        if entity.zone not in (Zone.HAND, Zone.DECK):
            continue
        family = registry.mana_rank_family(entity.card_id)
        if family is not None and family.forms.index(entity.card_id) < rank_for_maximum(
                state.players[entity.controller].max_mana):
            raise ValueError('Unsettled mana rank in stored card')
