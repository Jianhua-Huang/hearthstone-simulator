"""Capture each actual hand minion at its stored transformation checkpoint."""
from dataclasses import dataclass

from .copy_materials import CopyEntryMaterial
from .cross_zone import transform_stored_entity
from .effects import Effect, _player, _source, _behavior
from .errors import ResolutionError
from .model import CardType, DeathrattleMemory, NativeDeathrattleSpec, Zone
from .zones import CardReference, reference_entity, source_exists


PROFILE = NativeDeathrattleSpec('copy_summon')


@dataclass(frozen=True)
class EncloseHandMinions(Effect):
    player_id: int
    jar_card_id: str
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _behavior(self.jar_card_id); _source(self.source_id)


@dataclass(frozen=True)
class EncloseHandMinion(Effect):
    card: CardReference
    jar_card_id: str
    source_id: int | None = None

    def __post_init__(self):
        if type(self.card) is not CardReference or self.card.zone != Zone.HAND:
            raise ValueError('A captive requires its original hand reference')
        self.card.__post_init__(); _behavior(self.jar_card_id); _source(self.source_id)


def jar_definition(registry, card_id):
    card = registry.card(card_id)
    if (card.kind != CardType.MINION or not card.hand_playable or card.choice_only or
            card.native_deathrattle != PROFILE or (card.cost, card.attack, card.health) != (1, 0, 1)):
        raise ResolutionError('Enclosing requires the complete printed1mana0/1 native Jar')
    return card


def enclose_many(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id); jar_definition(r.registry, effect.jar_card_id)
    cards = tuple(CardReference.capture(r.state.entities[eid]) for eid in r.player(effect.player_id).hand
        if r.state.entities[eid].kind == CardType.MINION)
    return tuple(EncloseHandMinion(card, effect.jar_card_id, effect.source_id) for card in cards)


def enclose(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    definition = jar_definition(r.registry, effect.jar_card_id)
    entity = reference_entity(r, effect.card)
    if entity is None: return ()
    if entity.kind != CardType.MINION:
        raise ResolutionError('A Jar can enclose only an original hand minion')
    material = CopyEntryMaterial.capture(r.state, entity, 'remembered_hand_copy', 'current',
        registry=r.registry, player_id=entity.controller)
    return transform_stored_entity(r, entity, definition, source_id=effect.source_id,
        deathrattle_memory=DeathrattleMemory(PROFILE, summon_copy=material))


def register(mechanics):
    mechanics.register(EncloseHandMinions, enclose_many)
    mechanics.register(EncloseHandMinion, enclose)
