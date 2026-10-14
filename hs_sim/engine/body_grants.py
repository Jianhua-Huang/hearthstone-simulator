"""Physical Battlecry/Combo grants using registered declarations and lifecycle.

This component installs complete registered bodies. Unbound carriers keep the
common target contract. Bound carriers require complete prospective authority
for the connected manual paid dispatcher before any attachment is allocated.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _source
from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import AbilityInstance, CardType, Zone


@dataclass(frozen=True)
class BodyReference:
    entity_id: int
    player_id: int
    zone: Zone
    card_id: str
    zone_epoch: int

    def __post_init__(self):
        from .effects import _player, _behavior
        _integer(self.entity_id, 'body entity', 1)
        _player(self.player_id)
        if type(self.zone) is not Zone or self.zone not in (
                Zone.HAND, Zone.DECK, Zone.BOARD, Zone.HERO, Zone.WEAPON):
            raise ValueError('Body reference requires a stored or installed physical carrier')
        _behavior(self.card_id)
        _integer(self.zone_epoch, 'body zone epoch', 0)

    @classmethod
    def capture(cls, entity):
        return cls(entity.id, entity.controller, entity.zone, entity.card_id, entity.zone_epoch)


def reference_value(reference):
    if type(reference) is not BodyReference:
        raise ValueError('Expected a captured BodyReference')
    reference.__post_init__()


def grant_value(effect):
    from .effects import _behavior
    reference_value(effect.card)
    _behavior(effect.declaration_card_id)
    _source(effect.source_id)
    if effect.expires_turn is not None:
        _integer(effect.expires_turn, 'body expiry', 1)


@dataclass(frozen=True)
class GrantBattlecry(Effect):
    card: BodyReference
    declaration_card_id: str
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        grant_value(self)


@dataclass(frozen=True)
class GrantCombo(Effect):
    card: BodyReference
    declaration_card_id: str
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        grant_value(self)


def mutation_value(effect):
    reference_value(effect.card)
    _integer(effect.ability_id, 'granted body identity', 1)
    if type(effect.family) is not str or effect.family not in ('battlecry', 'combo'):
        raise ValueError('Granted body family must be battlecry or combo')
    _source(effect.source_id)


@dataclass(frozen=True)
class RemoveGrantedBody(Effect):
    card: BodyReference
    ability_id: int
    family: str
    source_id: int | None = None

    def __post_init__(self):
        mutation_value(self)


@dataclass(frozen=True)
class ConsumeGrantedBody(Effect):
    card: BodyReference
    ability_id: int
    family: str
    source_id: int | None = None

    def __post_init__(self):
        mutation_value(self)


def target(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, getattr(effect, 'expires_turn', None))
    definition = r.registry.card(effect.card.card_id)
    if definition.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
        raise ResolutionError('Battlecry and Combo bodies require minion, weapon or hero carriers')
    installed = {Zone.BOARD: CardType.MINION, Zone.WEAPON: CardType.WEAPON, Zone.HERO: CardType.HERO}
    if effect.card.zone in installed and installed[effect.card.zone] != definition.kind:
        raise ResolutionError('Body carrier kind and installed zone disagree')
    entity = r.state.entities.get(effect.card.entity_id)
    if entity is None or (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) != (
            effect.card.player_id, effect.card.zone, effect.card.card_id, effect.card.zone_epoch):
        r.emit('zone_target_skipped', target_id=effect.card.entity_id, reason='captured_body_departed')
        return None
    return entity


def grant(r, effect):
    family = 'battlecry' if type(effect) is GrantBattlecry else 'combo'
    declaration = r.registry.card(effect.declaration_card_id)
    behavior_id = getattr(declaration, family)
    if behavior_id is None:
        raise ResolutionError('Registered declaration does not provide the requested body family')
    r.registry.behavior(behavior_id)
    entity = target(r, effect)
    if entity is None:
        return
    carrier = r.registry.card(entity.card_id)
    from .targeting import target_spec
    declaration_targets, carrier_targets = target_spec(declaration), target_spec(carrier)
    heterogeneous = declaration_targets != carrier_targets or (declaration_targets is not None and (
            declaration.target_rule != carrier.target_rule or
            declaration.target_condition != carrier.target_condition or
            declaration.target_condition == 'manathirst' and declaration.manathirst != carrier.manathirst))
    from .indirect_body_targets import connected_carrier
    bound = connected_carrier(r.registry,entity.card_id)
    if heterogeneous and not bound:
        raise ResolutionError('Independent body target contracts require the pending heterogeneous target dispatcher')
    fields = {family + '_card_id': declaration.id}
    ability = AbilityInstance(r.state.next_attachment_id, family, behavior_id=behavior_id,
        source_id=effect.source_id, expires_turn=effect.expires_turn, **fields)
    if bound:
        from .body_grant_authority import authorize_grant
        authorize_grant(r.state, r.registry, entity, ability)
    if attachment_id(r.state) != ability.id:
        raise ResolutionError('Body grant authority changed its prospective attachment identity')
    entity.abilities.append(ability)
    refresh_entity(entity)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
        ability_id=ability.id, ability_kind=family)


def mutate(r, effect):
    entity = target(r, effect)
    if entity is None:
        return
    ability = next((a for a in entity.abilities if a.id == effect.ability_id), None)
    if ability is None:
        return
    if ability.kind != effect.family or ability.origin != 'granted':
        raise ResolutionError('Granted body mutation requires its exact family and granted identity')
    if type(effect) is RemoveGrantedBody:
        entity.abilities.remove(ability)
        event = 'ability_removed'
    else:
        if ability.consumed:
            return
        entity.abilities[entity.abilities.index(ability)] = replace(ability, consumed=True)
        event = 'ability_consumed'
    refresh_entity(entity)
    r.emit(event, target_id=entity.id, source_id=effect.source_id,
        ability_id=ability.id, ability_kind=effect.family)


def register(mechanics):
    mechanics.register_payload_type(BodyReference)
    mechanics.register(GrantBattlecry, grant)
    mechanics.register(GrantCombo, grant)
    mechanics.register(RemoveGrantedBody, mutate)
    mechanics.register(ConsumeGrantedBody, mutate)
