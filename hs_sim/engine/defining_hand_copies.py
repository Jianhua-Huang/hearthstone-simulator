"""A native owner-turn source changes its own face to opposing hand material."""
from copy import deepcopy
from dataclasses import dataclass

from .construction import integer, name
from .effects import Effect
from .errors import ResolutionError
from .model import CardType, Zone, validate_defining_hand_spec
from .zones import CardReference, HAND_TYPES, reference_entity


def validate_declaration(registry, card_id):
    card = registry.card(card_id)
    if card.kind != CardType.MINION or card.defining_hand_source is None or not card.hand_playable:
        raise ValueError('Native opposing-hand shifter requires its printed minion declaration')
    validate_defining_hand_spec(card.defining_hand_source)


@dataclass(frozen=True)
class TransformDefiningHandCardFromHand(Effect):
    target: CardReference
    defining_card_id: str
    source_ability_id: int

    def __post_init__(self):
        if type(self.target) is not CardReference or self.target.zone != Zone.HAND:
            raise ValueError('Native hand selection requires its original physical hand card')
        self.target.__post_init__()
        name(self.defining_card_id, 'original opposing-hand shifter')
        integer(self.source_ability_id, 'original opposing-hand source ability', 1)


def binding(registry, entity, effect):
    effect.__post_init__()
    if effect.defining_card_id not in registry.defining_hand_copy_ids:
        raise ResolutionError('Undeclared native opposing-hand shifter')
    validate_declaration(registry, effect.defining_card_id)
    native = next((a for a in entity.abilities if a.kind == 'defining_hand_source' and
        (a.id, a.defining_card_id) == (effect.source_ability_id, effect.defining_card_id)), None)
    if native is None:
        raise ResolutionError('Native hand selection borrowed another original source')
    registry.validate_defining_hand_binding(entity, native)
    if not native.progress_keys:
        raise ResolutionError('Native hand selection requires its accepted owner-turn witness')
    return native


def transform(r, effect):
    effect.__post_init__()
    if effect.defining_card_id not in r.registry.defining_hand_copy_ids:
        raise ResolutionError('Undeclared native opposing-hand shifter')
    target = reference_entity(r, effect.target)
    if target is None:
        return ()
    native = binding(r.registry, target, effect)
    # Each actual physical card has one chance, including identical faces.
    cards = tuple(r.state.entities[i] for i in r.player(3-target.controller).hand)
    for card in cards:
        if card.kind not in HAND_TYPES or not r.registry.card(card.card_id).hand_playable or card.components:
            raise ResolutionError('Opposing hand material requires a supported physical copy policy')
    if not cards:
        return ()
    material = deepcopy(r.game._rng.choice(cards))
    # The recipient retains its own native source, never the sampled card's
    # original shifter. All ordinary current material uses the existing copier.
    material.abilities = [a for a in material.abilities if a.kind != 'defining_hand_source']
    from .cross_zone import reset_stored_entity, announce_stored_transform
    from .zones import copy_current_stored_state
    from .lifecycle import refresh_entity
    old_card = target.card_id
    reset_stored_entity(r, target, r.registry.card(material.card_id))
    copy_current_stored_state(r.state, material, target)
    target.abilities = [a for a in target.abilities if a.kind != 'defining_hand_source']
    target.abilities.append(native)
    refresh_entity(target)
    announce_stored_transform(r, target, old_card, source_id=target.id)
    return ()


def validate_pending(game, effect):
    effect.__post_init__()
    if effect.defining_card_id not in game.registry.defining_hand_copy_ids:
        raise ValueError('Pending native hand selection has no declared original source')
    validate_declaration(game.registry, effect.defining_card_id)
    ref = effect.target
    entity = game._state.entities.get(ref.entity_id)
    if entity is None:
        raise ValueError('Pending native hand selection references a missing entity')
    if (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) == (
            ref.player_id, ref.zone, ref.card_id, ref.zone_epoch):
        binding(game.registry, entity, effect)


def register(mechanics):
    mechanics.register(TransformDefiningHandCardFromHand, transform)
