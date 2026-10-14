"""Guarded, simultaneous removal, outside death, discard and deck destruction."""
from dataclasses import dataclass

from .effects import Effect, _source
from .errors import ResolutionError
from .model import CardType, Zone
from .sacrifice import MinionReference, same_instance
from .zones import CardReference, HAND_TYPES, source_exists


@dataclass(frozen=True)
class RemoveFromGame(Effect):
    targets: tuple[CardReference | MinionReference, ...]
    source_id: int | None = None
    reveal: bool = False

    def __post_init__(self):
        _source(self.source_id)
        if type(self.targets) is not tuple or type(self.reveal) is not bool:
            raise ValueError('Removal requires an immutable target tuple and boolean reveal policy')
        ids = []
        for target in self.targets:
            if type(target) not in (CardReference, MinionReference):
                raise ValueError('Removal requires a captured hand/deck card or board minion')
            target.__post_init__()
            ids.append(target.entity_id)
        if len(ids) != len(set(ids)):
            raise ValueError('A removal batch cannot repeat a physical entity')


def removal_result(event):
    """Validate the host receipt without trusting arbitrary event dictionaries."""
    if event.kind != 'cards_removed_from_game':
        return None
    data = dict(event.data)
    if (set(data) != {'removed', 'reveal'} or type(data['reveal']) is not bool or
            type(data['removed']) not in (tuple, list) or not data['removed'] or
            type(event.amount) is not int or event.amount != len(data['removed']) or
            event.target_id is not None or event.player_id is not None):
        raise ValueError('Invalid removal receipt')
    ids = []
    for row in data['removed']:
        if type(row) not in (tuple, list) or len(row) != 4:
            raise ValueError('Invalid removed entity fact')
        entity_id, player_id, zone, card_id = row
        if (type(entity_id) is not int or entity_id < 1 or type(player_id) is not int or
                player_id not in (1, 2) or type(zone) is not str or
                zone not in (Zone.HAND.value, Zone.DECK.value, Zone.BOARD.value) or
                type(card_id) is not str or not card_id.strip()):
            raise ValueError('Invalid original removal identity')
        ids.append(entity_id)
    if len(ids) != len(set(ids)):
        raise ValueError('A removal receipt cannot repeat a physical entity')
    return tuple(tuple(row) for row in data['removed']), data['reveal']


def remove_from_game(r, effect):
    effect.__post_init__()
    source_exists(r, effect.source_id)
    accepted, stale = [], []
    # Validate all definitions and capture all applicable entities before any
    # movement or diagnostic event can normalize the board's auras.
    for target in effect.targets:
        definition = r.registry.card(target.card_id)
        if type(target) is MinionReference:
            if definition.kind != CardType.MINION:
                raise ResolutionError('Board removal requires a minion definition')
            entity = same_instance(r.state, target)
        else:
            if (definition.kind not in HAND_TYPES or
                    definition.kind == CardType.HERO and not definition.hero_card):
                raise ResolutionError('Stored removal requires a playable card definition')
            entity = r.state.entities.get(target.entity_id)
            if entity is not None and (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) != (
                    target.player_id, target.zone, target.card_id, target.zone_epoch):
                entity = None
        if entity is None:
            stale.append(target.entity_id)
        else:
            accepted.append(entity)
    removed = tuple((e.id, e.controller, e.zone.value, e.card_id) for e in accepted)
    for entity in accepted:
        r.move(entity, Zone.SETASIDE)
    # One event after the whole batch leaves: removed listeners and auras no
    # longer participate. The ordinary scheduler owns the next death checkpoint.
    if removed:
        r.emit('cards_removed_from_game', source_id=effect.source_id, amount=len(removed),
               removed=removed, reveal=effect.reveal)
    for entity_id in stale:
        r.emit('zone_target_skipped', target_id=entity_id, reason='captured_card_departed')


def register(mechanics):
    mechanics.register(RemoveFromGame, remove_from_game)
