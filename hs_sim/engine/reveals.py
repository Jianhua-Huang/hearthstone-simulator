"""Guarded public hand disclosure using existing knowledge and physical refs."""
from dataclasses import dataclass

from .effects import Effect, RevealHandCard
from .model import Zone
from .zones import CardReference, reference_entity


@dataclass(frozen=True)
class RevealCapturedHandCard(Effect):
    card: CardReference
    viewers: tuple[int, ...] = (1, 2)

    def __post_init__(self):
        if type(self.card) is not CardReference:
            raise ValueError('Hand disclosure requires an exact physical reference')
        self.card.__post_init__()
        if self.card.zone != Zone.HAND:
            raise ValueError('Captured hand disclosure requires the hand zone')
        RevealHandCard(self.card.entity_id, self.viewers).__post_init__()


def reveal(r, effect):
    effect.__post_init__()
    if reference_entity(r, effect.card) is None:
        return
    from .information import reveal_hand_card
    return reveal_hand_card(r, RevealHandCard(effect.card.entity_id, effect.viewers))


def register(mechanics):
    mechanics.register(RevealCapturedHandCard, reveal)
