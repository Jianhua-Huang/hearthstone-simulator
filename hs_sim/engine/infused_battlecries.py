"""Native endless-Infuse damage, retained as physical printed card material.

Death witnesses and partial progress belong to hand_progress. This module only
advances the declared number once per completed stage and freezes it at Battlecry
acceptance. Ordinary copies, resets and damage retain their existing executors.
"""
from dataclasses import dataclass
from .model import CardType, Enchantment, Zone, _int

LABEL = 'infused_battlecry_damage'


@dataclass(frozen=True)
class InfusedBattlecryProfile:
    card_id: str
    initial_damage: int
    period: int
    upgrade_card_id: str | None = None


def validate_profile(registry, profile):
    if type(profile) is not InfusedBattlecryProfile:
        raise ValueError('Typed native Infuse damage declaration required')
    _int(profile.initial_damage, 'initial infused damage', 1)
    _int(profile.period, 'native Infuse period', 1)
    card = registry.card(profile.card_id)
    spec = card.hand_progress
    if (card.kind != CardType.MINION or card.battlecry is None or spec is None or
            spec.kind != 'infuse' or spec.goal != profile.period or spec.zone != Zone.HAND or
            spec.condition_id != 'always' or spec.amount_basis != 'one' or
            spec.upgrade_card_id != profile.upgrade_card_id or
            spec.repeat != (profile.upgrade_card_id is None)):
        raise ValueError('Infused damage requires its actual native hand progress and Battlecry')
    if profile.upgrade_card_id is not None:
        target = registry.card(profile.upgrade_card_id)
        if target.kind != CardType.MINION or target.battlecry != card.battlecry:
            raise ValueError('Infused upgrade must retain its native Battlecry program')


def validate_value(amount):
    if amount is not None:
        _int(amount, 'intrinsic infused damage', 1)


def value(carrier):
    stored = getattr(carrier, 'infused_damage', None)
    validate_value(stored)
    rows = tuple(e for e in getattr(carrier, 'enchantments', ()) if e.label == LABEL)
    if len(rows) > 1:
        raise ValueError('A physical card has one intrinsic Infuse damage value')
    if rows:
        rows[0].__post_init__()
        amount = rows[0].infused_damage
        if stored is not None and stored != amount:
            raise ValueError('Infused copy material disagrees with its original number')
        return amount
    return stored


def imprint(state, entity, amount, source_id=None):
    validate_value(amount)
    if amount is None:
        return
    if entity.kind != CardType.MINION or entity.components or entity.starship_building:
        raise ValueError('Native Infuse number requires an ordinary physical minion')
    from .lifecycle import attachment_id
    rows = [(i,e) for i,e in enumerate(entity.enchantments) if e.label == LABEL]
    if len(rows) > 1:
        raise ValueError('A physical card has one intrinsic Infuse parameter')
    identity = rows[0][1].id if rows else attachment_id(state)
    updated = Enchantment(identity, source_id=source_id,
        label=LABEL, remove_on_silence=False, infused_damage=amount)
    if rows:
        entity.enchantments[rows[0][0]] = updated
    else:
        entity.enchantments.append(updated)


def initialize(state, registry, entity):
    profile = registry.infused_battlecry_profiles.get(entity.card_id)
    if profile is not None and value(entity) is None:
        imprint(state, entity, profile.initial_damage, entity.id)


def inherit(state, source, destination, amount=None):
    if source.card_id == destination.card_id:
        amount = value(source) if amount is None else amount
        if amount is not None:
            if state is None:
                raise ValueError('Infused copies require the actual attachment allocator')
            imprint(state, destination, amount, getattr(source, 'entity_id', getattr(source, 'id', None)))


def completed_number(registry, entity, ability, completed):
    profile = registry.infused_battlecry_profiles.get(entity.card_id)
    if profile is None:
        return None
    if ability.hand_progress != registry.card(entity.card_id).hand_progress:
        raise ValueError('Infused damage borrowed another progress declaration')
    amount = value(entity)
    validate_recipe(registry, entity.card_id, amount)
    return amount + 1 if completed else None


def payload_value(entity, ability):
    return value(entity) if ability.battlecry_card_id == entity.card_id else None


def validate_recipe(registry, card_id, amount):
    validate_value(amount)
    profile = registry.infused_battlecry_profiles.get(card_id)
    if (profile is None) != (amount is None) or profile is not None and amount < profile.initial_damage:
        raise ValueError('Infused number lost its native declaration or original printed minimum')
    if profile is not None and profile.upgrade_card_id is not None and amount != profile.initial_damage:
        raise ValueError('An uninfused native face cannot borrow an upgraded damage value')


def validate_payload(registry, payload):
    validate_recipe(registry, payload.card_id, payload.infused_damage)


def validate_game(game):
    registry, state = game.registry, game._state
    for entity in state.entities.values():
        amount = value(entity)
        validate_recipe(registry, entity.card_id, amount)
        if amount is not None and (entity.kind != CardType.MINION or entity.components or entity.starship_building):
            raise ValueError('Infused number borrowed a non-native physical body')
    for death in state.death_history:
        validate_recipe(registry, death.card_id, value(death))
    for discard in state.discard_history:
        validate_recipe(registry, discard.card_id, value(discard))
    for play in state.play_history:
        material = play.minion_copy_material
        if material is not None:
            validate_recipe(registry, play.card_id, value(material))
        for payload in play.battlecries:
            validate_payload(registry, payload)
            if payload.infused_damage is not None:
                if material is None or payload.infused_damage != value(material):
                    raise ValueError('Infused Battlecry lost its submitted physical damage value')
                receipt = play.submitted_cost
                if receipt is not None and receipt.quote_origin == 'current_hand' and (
                        value(receipt.quote.quote_input) != payload.infused_damage):
                    raise ValueError('Infused Battlecry differs from its original prepayment material')
    for row in state.battlecry_history:
        validate_payload(registry, row.payload)
