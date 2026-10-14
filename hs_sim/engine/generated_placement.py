"""Generated weapon/location installation with a typed trusted host result.

Preparation only: this does not execute weapon battlecries, activate a location,
create replay roots, or forge paid hand history. It inherits existing local
equipment/PlaceLocation policies; exact CN timing remains uncalibrated.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact
from .effects import Effect, _behavior, _integer, _player
from .equipment import equip_entity
from .errors import ResolutionError
from .model import CardType, GameState, Zone
from .zones import source_exists


@dataclass(frozen=True)
class InstallGeneratedPlacement(Effect):
    player_id: int
    card_id: str
    source_id: int
    position: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _behavior(self.card_id)
        _integer(self.source_id, 'generated placement issuer', 1)
        if self.position is not None:
            _integer(self.position, 'generated placement position', 0)


@dataclass(frozen=True)
class GeneratedPlacementResult:
    """Original physical installation or explicit failed attempt, host only.

    The fingerprint supports stale-installation checks. It does not authenticate
    where an unsigned receipt or saved GameState originally came from.
    """
    player_id: int
    card_id: str
    kind: CardType
    source_id: int
    installation: SourceAllocationFact | None
    failure: str | None = None

    def __post_init__(self):
        _player(self.player_id)
        _behavior(self.card_id)
        _integer(self.source_id, 'placement result issuer', 1)
        if type(self.kind) is not CardType or self.kind not in (CardType.WEAPON, CardType.LOCATION):
            raise ValueError('Generated placement results require WEAPON or LOCATION')
        if self.failure is not None:
            if (self.kind != CardType.LOCATION or self.failure != 'board_full' or
                    self.installation is not None):
                raise ValueError('Only an unallocated full-board location attempt may fail')
            return
        fact = self.installation
        if type(fact) is not SourceAllocationFact:
            raise ValueError('Successful placement requires its full original allocation')
        fact.__post_init__()
        zone = Zone.WEAPON if self.kind == CardType.WEAPON else Zone.BOARD
        if ((fact.card_id, fact.kind, fact.owner, fact.controller, fact.zone) !=
                (self.card_id, self.kind, self.player_id, self.player_id, zone) or
                fact.entered_order == 0 or fact.entity_id <= self.source_id):
            raise ValueError('Placement result disagrees with its original physical installation')


def install_generated_placement(r, effect):
    """Resolver-only helper returning the actual created entity's identity."""
    if type(effect) is not InstallGeneratedPlacement:
        raise ValueError('Generated placement requires its typed effect')
    effect.__post_init__()
    source_exists(r, effect.source_id)
    player = r.player(effect.player_id)
    card = r.registry.card(effect.card_id)
    if card.kind not in (CardType.WEAPON, CardType.LOCATION) or not card.hand_playable:
        raise ResolutionError('Generated placement requires a playable weapon or location')
    if card.kind == CardType.WEAPON:
        if effect.position is not None:
            raise ResolutionError('A weapon installation cannot have a board position')
        # Same actual lifecycle as equip_weapon, retaining the created entity
        # directly rather than guessing a last allocated or last equipped ID.
        entity = r.create_entity(player.id, card.id, Zone.GRAVEYARD)
        equip_entity(r, entity)
    else:
        # Same local PlaceLocation capacity/position/event policy. A failed
        # attempt has no physical allocation, hand entry, or hidden payment.
        if len(player.board) >= r.rules.max_board:
            r.emit('summon_failed', player_id=player.id, card_id=card.id, reason='board_full')
            return GeneratedPlacementResult(player.id, card.id, card.kind, effect.source_id, None, 'board_full')
        entity = r.create_entity(player.id, card.id, Zone.BOARD, effect.position)
        r.emit('location_placed', source_id=entity.id, target_id=entity.id, player_id=player.id)
    return GeneratedPlacementResult(player.id, card.id, card.kind, effect.source_id,
                                    SourceAllocationFact.capture(r.state, entity))


def placement_still_current(state, result):
    """Check exact physical installation, never substitute a later same-face card."""
    if type(state) is not GameState or type(result) is not GeneratedPlacementResult:
        raise ValueError('Placement check requires GameState and its typed host result')
    result.__post_init__()
    if result.failure is not None:
        return False
    fact = result.installation
    entity = state.entities.get(fact.entity_id)
    player = state.players[result.player_id]
    if (entity is None or entity.doomed or not entity.active or entity.durability <= 0 or
            (entity.card_id, entity.kind, entity.owner, entity.controller, entity.zone,
             entity.zone_epoch, entity.entered_order) !=
            (fact.card_id, fact.kind, fact.owner, fact.controller, fact.zone,
             fact.zone_epoch, fact.entered_order)):
        return False
    return (player.weapon_id == entity.id if result.kind == CardType.WEAPON else entity.id in player.board)


def handle_generated_placement(r, effect):
    install_generated_placement(r, effect)
    return ()


def register(mechanics):
    for kind in (SourceAllocationFact, GeneratedPlacementResult):
        if kind not in mechanics.payload_types:
            mechanics.register_payload_type(kind)
    mechanics.register(InstallGeneratedPlacement, handle_generated_placement)
    return mechanics
