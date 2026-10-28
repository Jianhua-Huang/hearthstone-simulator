"""Native untouchable objects share board residence, attachments and end turns."""
from dataclasses import dataclass, fields

from .effects import Effect, _player, _source
from .errors import ResolutionError
from .model import (AbilityInstance, BoardPresenceReference, CardType, Enchantment,
                    EndTurnSpec, PassiveBoardObjectSpec, Zone, _name)
from .sacrifice import MinionReference, live_minion, reference_value

BINDING = 'passive_object_binding.'
UNIT = 'passive_object_unit.'


def marker(enchantment):
    for prefix in (BINDING, UNIT):
        if type(enchantment.label) is str and enchantment.label.startswith(prefix):
            identity = enchantment.label[len(prefix):]
            _name(identity, 'passive object marker identity')
            return prefix, identity
    return None


def validate_marker_shape(enchantment):
    if marker(enchantment) is None:
        return
    if enchantment.source_id is None:
        raise ValueError('Passive object marker requires an original physical source')
    for field in fields(enchantment):
        if field.name not in ('id', 'label', 'source_id') and getattr(enchantment, field.name) != field.default:
            raise ValueError('Passive object units cannot mix combat, cost, expiry or silence policies')


def validate_carrier(registry, card_id, kind, enchantments):
    seen = set()
    for enchantment in enchantments:
        key = marker(enchantment)
        if key is None:
            continue
        validate_marker_shape(enchantment)
        prefix, identity = key
        if prefix == BINDING:
            declaration = registry.card(identity).interactable
            valid = (type(declaration) is PassiveBoardObjectSpec and
                     card_id == declaration.binding_card_id and key not in seen)
            seen.add(key)
        else:
            declaration = registry.card(card_id).interactable
            valid = type(declaration) is PassiveBoardObjectSpec and identity == declaration.unit_marker_id
        if kind != CardType.MINION or not valid:
            raise ValueError('Passive object marker borrowed an undeclared carrier or binding')


def validate_entity(registry, entity):
    spec = registry.card(entity.card_id).interactable
    if type(spec) is not PassiveBoardObjectSpec:
        return
    if len(entity.abilities) != 1:
        raise ValueError('Passive object requires exactly its printed owner-end trigger')
    ability = entity.abilities[0]
    expected = AbilityInstance(ability.id, 'trigger', source_id=entity.id, origin='printed',
        event='turn_ended', behavior_id=spec.behavior_id, end_turn=EndTurnSpec())
    if ability != expected or any(marker(e) is None or marker(e)[0] != UNIT for e in entity.enchantments):
        raise ValueError('Passive object contains a foreign ability or attachment')
    validate_carrier(registry, entity.card_id, entity.kind, entity.enchantments)


def validate_game(game):
    registry, state = game.registry, game._state
    for entity in state.entities.values():
        validate_carrier(registry, entity.card_id, entity.kind, entity.enchantments)
        for enchantment in entity.enchantments:
            key = marker(enchantment)
            if key is not None and key[0] == BINDING:
                original = state.entities.get(enchantment.source_id)
                if original is None or original.card_id != key[1] or not original.interactable_object:
                    raise ValueError('Passive binding lost its actual installed board object')
    for death in state.death_history:
        validate_carrier(registry, death.card_id, registry.card(death.card_id).kind, death.enchantments)


def units(registry, entity):
    validate_entity(registry, entity)
    return sum(marker(e) is not None and marker(e)[0] == UNIT for e in entity.enchantments)


def bound_object(state, registry, source, player_id, card_id):
    """A retained explicit link never falls back to a different friendly object."""
    spec = registry.card(card_id).interactable
    if type(spec) is not PassiveBoardObjectSpec or source.card_id != spec.binding_card_id:
        raise ValueError('Passive lookup requires its declared native source')
    validate_carrier(registry, source.card_id, source.kind, source.enchantments)
    bindings = [e for e in source.enchantments if marker(e) == (BINDING, card_id)]
    ids = (bindings[0].source_id,) if bindings else tuple(state.players[player_id].board)
    for eid in ids:
        obj = state.entities.get(eid)
        if (obj is not None and obj.card_id == card_id and obj.interactable_object and
                obj.zone == Zone.BOARD and obj.controller == player_id and eid in state.players[player_id].board):
            return obj
    return None


@dataclass(frozen=True)
class InstallPassiveObject(Effect):
    player_id: int
    card_id: str
    source: MinionReference

    def __post_init__(self):
        _player(self.player_id); _name(self.card_id, 'passive object face'); reference_value(self.source)


@dataclass(frozen=True)
class UpgradePassiveObject(Effect):
    target: BoardPresenceReference
    source_id: int

    def __post_init__(self):
        if type(self.target) is not BoardPresenceReference:
            raise ValueError('Passive object upgrade requires its captured residence')
        self.target.__post_init__(); _source(self.source_id)
        if self.source_id is None:
            raise ValueError('Passive object upgrade requires its native source')


def install(r, effect):
    effect.__post_init__()
    card = r.registry.card(effect.card_id); spec = card.interactable
    if (type(spec) is not PassiveBoardObjectSpec or spec.binding_card_id != effect.source.card_id or
            effect.source.entity_id not in r.state.entities):
        raise ResolutionError('Passive installation lost its declared original source')
    from .interactables import validate_definition
    validate_definition(card)
    if len(r.player(effect.player_id).board) >= r.rules.max_board:
        r.emit('passive_object_install_skipped', source_id=effect.source.entity_id,
            player_id=effect.player_id, reason='board_full')
        return ()
    obj = r.create_entity(effect.player_id, card.id, Zone.BOARD, interactable_object=True)
    source = live_minion(r.state, effect.source)
    if source is not None:
        from .lifecycle import attachment_id
        source.enchantments = [e for e in source.enchantments if marker(e) != (BINDING, card.id)]
        source.enchantments.append(Enchantment(attachment_id(r.state), source_id=obj.id, label=BINDING + card.id))
    r.emit('passive_object_installed', source_id=effect.source.entity_id, target_id=obj.id, player_id=effect.player_id)
    return ()


def upgrade(r, effect):
    effect.__post_init__()
    from .board_presence import resolve_board_presence
    from .lifecycle import attachment_id
    obj = resolve_board_presence(r.state, effect.target)
    if obj is None:
        r.stale(effect, effect.target.entity_id); return ()
    spec = r.registry.card(obj.card_id).interactable
    if type(spec) is not PassiveBoardObjectSpec or effect.source_id not in r.state.entities:
        raise ResolutionError('Passive upgrade requires an actual declared board object and source')
    validate_entity(r.registry, obj)
    obj.enchantments.append(Enchantment(attachment_id(r.state), source_id=effect.source_id, label=UNIT + spec.unit_marker_id))
    r.emit('passive_object_upgraded', source_id=effect.source_id, target_id=obj.id, player_id=obj.controller, amount=1)
    return ()


def register(mechanics):
    mechanics.register(InstallPassiveObject, install)
    mechanics.register(UpgradePassiveObject, upgrade)
