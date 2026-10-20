"""Board locations: free activation, durability, cooldown and explicit effects."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .actions import UseLocation
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import CardType, Zone
from .registry import RuleContext
from .zones import CardReference


def location_error(state, registry, rules, player_id, entity_id, *, context_factory=None):
    source = state.entities.get(entity_id)
    if (source is None or source.controller != player_id or source.zone != Zone.BOARD or
            source.kind != CardType.LOCATION or not source.active or source.durability <= 0 or source.doomed):
        return 'Activation requires a controlled location in play'
    if source.location_cooldown:
        return 'Location is cooling down'
    definition = registry.card(source.card_id)
    # The last durability frees its slot at the activation checkpoint (R-037).
    if definition.requires_board_space and source.durability > 1 and len(state.players[player_id].board) >= rules.max_board:
        return 'Board is full'
    try:
        if registry.use_visibility(definition.use_rule) == 'player':
            if context_factory is None:
                raise ValueError('Player use rule requires an observation context')
            context = context_factory(source.id, None)
        else:
            context = RuleContext(deepcopy(state), source.id, player_id)
        allowed = registry.use_rule(definition.use_rule)(context)
    except Exception as exc:
        raise ResolutionError(f'Location use rule failed: {exc}') from exc
    if type(allowed) is not bool:
        raise ResolutionError('Location use rule must return bool')
    return None if allowed else 'Location use condition is not satisfied'


@dataclass(frozen=True)
class ActivateLocation(Effect):
    action: UseLocation


@dataclass(frozen=True)
class FinishLocation(Effect):
    source_id: int
    player_id: int
    target_id: int | None


@dataclass(frozen=True)
class PlaceLocation(Effect):
    player_id: int
    card_id: str
    position: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Location card ID must be nonempty')
        if self.position is not None:
            _integer(self.position, 'position', 0)


@dataclass(frozen=True)
class ModifyLocation(Effect):
    target_id: int
    durability: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1); _source(self.source_id)
        if type(self.durability) is not int:
            raise ValueError('Durability delta must be an integer')


@dataclass(frozen=True)
class RefreshLocation(Effect):
    target_id: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1); _source(self.source_id)


@dataclass(frozen=True)
class DestroyLocation(Effect):
    target_id: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1); _source(self.source_id)


@dataclass(frozen=True)
class RandomDestroyLocation(Effect):
    candidate_ids: tuple[int, ...]
    source_id: int | None = None

    def __post_init__(self):
        if type(self.candidate_ids) is not tuple:
            raise ValueError('Random location candidates require an immutable tuple')
        for identity in self.candidate_ids: _integer(identity, 'location candidate', 1)
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError('Duplicate random location candidates')
        _source(self.source_id)


def random_destroy_location(r, effect):
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Random location destruction source does not exist')
    candidates = tuple(sorted(i for i in effect.candidate_ids if (e := r.state.entities.get(i)) is not None
        and e.kind == CardType.LOCATION and e.zone == Zone.BOARD and e.active and e.durability > 0 and not e.doomed))
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_candidates')
        return ()
    target = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=effect.source_id, target_id=target, candidates=candidates)
    return (DestroyLocation(target, effect.source_id),)


def activate_location(r, effect):
    a = effect.action
    source = r.state.entities[a.entity_id]
    from .native_active_targets import accept, FinishNativeActiveTarget
    bodies=tuple(a.behavior_id for a in active_abilities(source,'on_use'))
    native=accept(r,'location',a,bodies)
    target_id=a.target_id if native is None else native.selection.target_id
    source.durability -= 1
    from .death_causes import dying, mark
    if dying(source): mark(r, source, 'durability', 'location_use', source.id)
    source.location_cooldown = 2
    source.uses_this_turn += 1
    # Capture before a last-use destruction moves the source out of play.
    work = [r.call(behavior, source.id, a.player_id, target_id) for behavior in bodies
            if native is None or native.selection.failure is None]
    from .composed_locations import PREFIX as composed_prefix
    composed = dict(composed_recipe=source.card_id, composed_body=bool(work),
        composed_turn=r.state.turn) if source.card_id.startswith(composed_prefix) else {}
    r.emit('location_activated', source_id=source.id, target_id=target_id, player_id=a.player_id,
           durability=source.durability, cooldown=source.location_cooldown, **composed)
    return [*work, FinishLocation(source.id, a.player_id, target_id),
            *(()if native is None else(FinishNativeActiveTarget(native),))]


def finish_location(r, effect):
    r.emit('location_used', source_id=effect.source_id, target_id=effect.target_id, player_id=effect.player_id)


def place_location(r, effect):
    card = r.registry.card(effect.card_id)
    if card.kind != CardType.LOCATION:
        raise ResolutionError('PlaceLocation requires a location definition')
    player = r.player(effect.player_id)
    if len(player.board) >= r.rules.max_board:
        r.emit('summon_failed', player_id=player.id, card_id=card.id, reason='board_full')
        return
    entity = r.create_entity(player.id, card.id, Zone.BOARD, effect.position)
    r.emit('location_placed', source_id=entity.id, target_id=entity.id, player_id=player.id)


def modify_location(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Location effect source does not exist')
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id)
        return
    if entity.kind != CardType.LOCATION:
        raise ResolutionError('Location effect requires a location')
    if isinstance(effect, DestroyLocation):
        entity.doomed = True
    elif isinstance(effect, ModifyLocation):
        entity.durability += effect.durability
        r.emit('location_durability_changed', source_id=effect.source_id, target_id=entity.id,
               player_id=entity.controller, amount=effect.durability, durability=entity.durability)
    else:
        entity.location_cooldown = 0
        r.emit('location_opened', source_id=effect.source_id, target_id=entity.id, player_id=entity.controller)


def begin_location_turn(r, player):
    for entity_id in tuple(player.board):
        entity = r.state.entities[entity_id]
        if entity.kind == CardType.LOCATION and entity.location_cooldown:
            entity.location_cooldown -= 1
            r.emit('location_opened' if not entity.location_cooldown else 'location_cooldown_changed',
                   target_id=entity.id, player_id=player.id, cooldown=entity.location_cooldown)


def register_locations(mechanics):
    mechanics.register_payload_type(LocationFaceReference)
    mechanics.register(AdvanceLocationFace, advance_location_face)
    mechanics.register(RandomDestroyLocation, random_destroy_location)
    mechanics.register(DestroyCapturedLocation, destroy_captured_location)
    mechanics.register(AdvanceStoredLocationFace, advance_stored_location_face)
    for kind, handler in ((ActivateLocation, activate_location), (FinishLocation, finish_location),
                          (PlaceLocation, place_location), (ModifyLocation, modify_location),
                          (RefreshLocation, modify_location), (DestroyLocation, modify_location)):
        mechanics.register(kind, handler)


@dataclass(frozen=True)
class LocationFaceReference:
    """A captured original board location face, never a minion residence."""
    entity_id: int
    controller_id: int
    card_id: str
    zone_epoch: int
    entered_order: int

    def __post_init__(self):
        _integer(self.entity_id, 'location entity ID', 1)
        _player(self.controller_id)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Location face card ID must be nonempty')
        _integer(self.zone_epoch, 'location face epoch', 0)
        _integer(self.entered_order, 'location entry order', 1)

    @classmethod
    def capture(cls, state, entity_id):
        _integer(entity_id, 'location entity ID', 1)
        entity = state.entities.get(entity_id)
        if entity is None or entity.zone != Zone.BOARD or entity.kind != CardType.LOCATION:
            raise ValueError('Capture requires a known board location')
        # A last-use body is captured after decrement, before its checkpoint.
        # Its reference is valid evidence even though execution will be stale.
        return cls(entity.id, entity.controller, entity.card_id, entity.zone_epoch, entity.entered_order)


@dataclass(frozen=True)
class AdvanceLocationFace(Effect):
    target: LocationFaceReference
    card_id: str
    source_id: int | None = None

    def __post_init__(self):
        if type(self.target) is not LocationFaceReference:
            raise ValueError('Advance requires a captured LocationFaceReference')
        self.target.__post_init__()
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Destination location card ID must be nonempty')
        _source(self.source_id)


@dataclass(frozen=True)
class DestroyCapturedLocation(Effect):
    target: LocationFaceReference
    source_id: int | None = None

    def __post_init__(self):
        if type(self.target) is not LocationFaceReference:
            raise ValueError('Location destruction requires its original face reference')
        self.target.__post_init__(); _source(self.source_id)


@dataclass(frozen=True)
class AdvanceStoredLocationFace(Effect):
    target: CardReference
    card_id: str
    source_id: int | None = None

    def __post_init__(self):
        if type(self.target) is not CardReference:
            raise ValueError('Stored location advance requires its original card reference')
        self.target.__post_init__(); _source(self.source_id)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Stored location destination must be known')


def location_face_definition(registry, card_id):
    card = registry.card(card_id)
    if card.kind != CardType.LOCATION or card.choice_only:
        raise ValueError('Location face requires a physical location definition')
    return card


def validate_location_face_reference(state, registry, reference):
    if type(reference) is not LocationFaceReference:
        raise ValueError('Expected LocationFaceReference')
    reference.__post_init__()
    location_face_definition(registry, reference.card_id)
    entity = state.entities.get(reference.entity_id)
    if entity is None or reference.entity_id >= state.next_entity_id:
        raise ValueError('Unknown original location face entity')
    if (reference.zone_epoch > entity.zone_epoch or reference.entered_order >= state.next_order
            or reference.entered_order > entity.entered_order):
        raise ValueError('Location face reference has not been allocated')
    for other in state.entities.values():
        if other.id != reference.entity_id and other.entered_order == reference.entered_order:
            raise ValueError('Location entry belongs to another physical entity')
    for death in state.death_history:
        if death.entity_id != reference.entity_id and death.cause.target_entered_order == reference.entered_order:
            raise ValueError('Location entry belongs to another historical physical entity')
    if reference.zone_epoch == entity.zone_epoch and (
            entity.zone != Zone.BOARD or entity.kind != CardType.LOCATION or
            (entity.controller, entity.card_id, entity.entered_order) !=
            (reference.controller_id, reference.card_id, reference.entered_order)):
        raise ValueError('Current location face reference differs from its captured identity')
    return entity


def validate_location_face_frame_references(state, registry, value):
    """Validate every frozen reference using live work or its original context."""
    from dataclasses import fields, is_dataclass
    from .model import GameState
    from .continuations import FrameCodec
    def visit(item, scope, depth):
        if depth > FrameCodec.MAX_DEPTH:
            raise ValueError('Location face frame references exceed codec depth')
        if type(item) in (AdvanceLocationFace, AdvanceStoredLocationFace, DestroyCapturedLocation):
            item.__post_init__()
            if type(item) is not DestroyCapturedLocation:
                location_face_definition(registry, item.card_id)
            if type(item) is AdvanceStoredLocationFace:
                location_face_definition(registry, item.target.card_id)
                entity = scope.entities.get(item.target.entity_id)
                if entity is None or item.target.zone_epoch > entity.zone_epoch:
                    raise ValueError('Stored location face has an unknown or future reference')
            if item.source_id is not None and item.source_id not in scope.entities:
                raise ValueError('Unknown location face effect source')
        if type(item) is LocationFaceReference:
            validate_location_face_reference(scope, registry, item)
            return
        if type(item) is RuleContext:
            for field in fields(item):
                if field.name != 'state':
                    visit(getattr(item, field.name), item.state, depth + 1)
            return
        if type(item) is GameState:
            return  # Model invariants validate the captured state separately.
        if isinstance(item, (tuple, list)):
            for child in item: visit(child, scope, depth + 1)
        elif isinstance(item, dict):
            for child in item.values(): visit(child, scope, depth + 1)
        elif is_dataclass(item) and not isinstance(item, type):
            for field in fields(item): visit(getattr(item, field.name), scope, depth + 1)
    visit(value, state, 0)


def advance_location_face(r, effect):
    # Static unknowns fail before stale handling, including a stale target.
    destination = location_face_definition(r.registry, effect.card_id)
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Unknown location face effect source')
    entity = validate_location_face_reference(r.state, r.registry, effect.target)
    ref = effect.target
    if (entity.zone != Zone.BOARD or entity.kind != CardType.LOCATION or not entity.active
            or entity.doomed or entity.durability <= 0 or
            (entity.controller, entity.card_id, entity.zone_epoch, entity.entered_order) !=
            (ref.controller_id, ref.card_id, ref.zone_epoch, ref.entered_order)):
        r.stale(effect, entity.id)
        return
    if entity.card_id == destination.id:
        return  # No row renewal, clock change, epoch or gameplay event.
    old_card_id = entity.card_id
    from .lifecycle import advance_location_printed
    advance_location_printed(r.state, entity, destination)
    r.emit('location_face_changed', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller, old_card_id=old_card_id, new_card_id=entity.card_id)


def destroy_captured_location(r, effect):
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Unknown location destruction source')
    entity = validate_location_face_reference(r.state, r.registry, effect.target)
    ref = effect.target
    if (entity.zone != Zone.BOARD or entity.kind != CardType.LOCATION or not entity.active
            or entity.doomed or entity.durability <= 0 or
            (entity.controller, entity.card_id, entity.zone_epoch, entity.entered_order) !=
            (ref.controller_id, ref.card_id, ref.zone_epoch, ref.entered_order)):
        r.stale(effect, entity.id)
        return
    modify_location(r, DestroyLocation(entity.id, effect.source_id))


def advance_stored_location_face(r, effect):
    from .zones import reference_entity, source_exists
    from .cross_zone import announce_stored_transform
    from .lifecycle import advance_location_printed
    effect.__post_init__(); source_exists(r, effect.source_id)
    location_face_definition(r.registry, effect.target.card_id)
    destination = location_face_definition(r.registry, effect.card_id)
    entity = reference_entity(r, effect.target)
    if entity is None or entity.card_id == destination.id:
        return
    old_card_id = entity.card_id
    advance_location_printed(r.state, entity, destination)
    announce_stored_transform(r, entity, old_card_id, source_id=effect.source_id)
