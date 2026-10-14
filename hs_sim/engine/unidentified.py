"""Fixed bonus forms acquired in hand; the selected physical face stores identity.

This opt-in policy reuses the normal RNG, stored-card lifecycle and information
boundary. It never samples while restoring, while in deck, or during mulligan.
"""
from dataclasses import dataclass

from .construction import name
from .hand_upgrades import upgrade_face
from .model import CardType, Zone

VERSION = 'unidentified-v1'


@dataclass(frozen=True)
class UnidentifiedFamily:
    id: str
    base: str
    forms: tuple[str, str, str, str]
    version: str = VERSION

    def __post_init__(self):
        name(self.id, 'unidentified family')
        name(self.base, 'unidentified base')
        if type(self.version) is not str or self.version != VERSION:
            raise ValueError('Unsupported unidentified policy version')
        if type(self.forms) is not tuple or len(self.forms) != 4:
            raise ValueError('Unidentified items require four distinct bonus forms')
        for card_id in self.forms:
            name(card_id, 'unidentified bonus form')
        if len(set((self.base, *self.forms))) != 5:
            raise ValueError('Unidentified items require a separate base and four distinct bonus forms')


def validate_families(registry):
    for identity, family in registry.unidentified_families.items():
        if type(family) is not UnidentifiedFamily or family.id != identity:
            raise ValueError('Unidentified family differs from its registered key')
        family.__post_init__()
        cards = tuple(registry.card(card_id) for card_id in (family.base, *family.forms))
        if any(card.kind not in (CardType.SPELL, CardType.WEAPON) or not card.hand_playable
               or card.kind == CardType.SPELL and card.on_play is None for card in cards):
            raise ValueError('Unidentified items require complete physical spell or weapon bodies')
        if any((card.kind, card.cost, card.metadata.classes, card.spell_school) !=
               (cards[0].kind, cards[0].cost, cards[0].metadata.classes, cards[0].spell_school)
               for card in cards[1:]):
            raise ValueError('Unidentified forms must retain printed type, cost, class, and school')


def ready(state):
    return state.opening is None or state.opening.stage == 'complete'


def synchronize(resolution):
    """Settle real mutations after materialization, before their event reactions."""
    if (not resolution.registry.unidentified_families or resolution.game._information is None
            or not ready(resolution.state)):
        return
    for player in resolution.state.players.values():
        for identity in player.hand:
            entity = resolution.state.entities[identity]
            family = resolution.registry.unidentified_family(entity.card_id)
            if family is not None:
                upgrade_face(resolution, entity, resolution.game._rng.choice(family.forms))


def validate_state(state, registry):
    """Imported boundaries must already be settled; never repair or reroll them."""
    if registry.unidentified_families and ready(state):
        if any(entity.zone == Zone.HAND and registry.unidentified_family(entity.card_id) is not None
               for entity in state.entities.values()):
            raise ValueError('Unsettled unidentified card in hand')
