"""Public inert board carriers, with one hand investment per actual owner turn."""
from dataclasses import dataclass, replace

from .actions import UseInteractable
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .model import CardDefinition, CardType, EndTurnSpec, InteractableSpec, PassiveBoardObjectSpec, TriggerSpec, Zone
from .nondeath_removal import RemoveFromGame, remove_from_game, removal_result
from .owner_turns import current_owner_turn
from .zones import CardReference


def validate_definition(card):
    if card.interactable is None:
        return
    if type(card.interactable) not in (InteractableSpec, PassiveBoardObjectSpec):
        raise ValueError('Expected an exact inert board object declaration')
    card.interactable.__post_init__()
    # Only identity, printed cost and metadata vary. Every ordinary lifecycle
    # field must stay at its default, including future fields on CardDefinition.
    inert = CardDefinition(card.id, card.name, CardType.MINION, cost=card.cost,
        health=1, corpse_value=0, metadata=card.metadata, interactable=card.interactable)
    if type(card.interactable) is PassiveBoardObjectSpec:
        inert = replace(inert, triggers=(TriggerSpec('turn_ended', card.interactable.behavior_id, EndTurnSpec()),))
    if card != inert:
        raise ValueError('Interactable carriers require an inert one-health minion definition')
    if card.metadata is not None and card.metadata.collectible:
        raise ValueError('Interactable carriers are not collectible physical hand cards')


@dataclass(frozen=True)
class InteractableUseRecord:
    id: int
    player_id: int
    entity_id: int
    card_id: str
    zone_epoch: int
    presence_id: int
    invested: CardReference
    hand_entry_id: int
    owner_turn_id: int
    turn: int
    action: int
    started_event: int
    finished_event: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        for name in ('id', 'entity_id', 'presence_id', 'hand_entry_id', 'owner_turn_id',
                     'turn', 'action', 'started_event'):
            _integer(getattr(self, name), 'interactable ' + name, 1)
        _integer(self.zone_epoch, 'interactable epoch', 0)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Interactable use requires the original carrier definition')
        if type(self.invested) is not CardReference:
            raise ValueError('Interactable investment requires a captured CardReference')
        self.invested.__post_init__()
        if (self.invested.zone, self.invested.player_id) != (Zone.HAND, self.player_id):
            raise ValueError('Interactable investment must come from its own hand')
        if self.finished_event is not None:
            _integer(self.finished_event, 'interactable finished event', self.started_event + 1)


def used_in_latest_owner_turn(state, entity):
    interval = next((r for r in reversed(state.owner_turn_history)
        if r.player_id == entity.controller), None)
    return interval is not None and any(r.entity_id == entity.id and
        r.owner_turn_id == interval.id for r in state.interactable_history)


def use_error(state, registry, player_id, entity_id, card_entity_id):
    obj = state.entities.get(entity_id)
    if (obj is None or not obj.interactable_object or obj.zone != Zone.BOARD or
            obj.controller != player_id or obj.id not in state.players[player_id].board or
            type(registry.card(obj.card_id).interactable) is not InteractableSpec):
        return 'No owned interactable carrier available'
    if used_in_latest_owner_turn(state, obj):
        return 'Interactable has already been used in this owner turn'
    card = state.entities.get(card_entity_id)
    if (card is None or card.controller != player_id or card.zone != Zone.HAND or
            card.id not in state.players[player_id].hand or not registry.card(card.card_id).hand_playable):
        return 'Investment requires a current owned hand card'
    return None


@dataclass(frozen=True)
class InstallInteractable(Effect):
    player_id: int
    card_id: str
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Interactable installation requires a definition')


@dataclass(frozen=True)
class ActivateInteractable(Effect):
    action: UseInteractable

    def __post_init__(self):
        if type(self.action) is not UseInteractable:
            raise ValueError('Interactable activation requires its exact action')
        self.action.__post_init__()


@dataclass(frozen=True)
class FinishInteractableUse(Effect):
    use_id: int

    def __post_init__(self):
        _integer(self.use_id, 'interactable use ID', 1)


def install(r, effect):
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Interactable installation source does not exist')
    card = r.registry.card(effect.card_id)
    if type(card.interactable) is not InteractableSpec:
        raise ResolutionError('Installation requires an interactable definition')
    validate_definition(card)
    if len(r.player(effect.player_id).board) >= r.rules.max_board:
        r.emit('interactable_install_skipped', source_id=effect.source_id,
            player_id=effect.player_id, reason='board_full')
        return
    obj = r.create_entity(effect.player_id, card.id, Zone.BOARD, interactable_object=True)
    r.emit('interactable_installed', source_id=effect.source_id, target_id=obj.id,
        player_id=effect.player_id)


def activate(r, effect):
    effect.__post_init__()
    a = effect.action
    if a.player_id != r.state.active_player:
        raise ResolutionError('Interactable activation requires the current actor')
    if reason := use_error(r.state, r.registry, a.player_id, a.entity_id, a.card_entity_id):
        raise ResolutionError(reason)
    interval = current_owner_turn(r.state)
    obj = r.state.entities[a.entity_id]
    from .native_active_targets import accept,FinishNativeActiveTarget
    native=accept(r,'interactable',a,(r.registry.card(obj.card_id).interactable.behavior_id,))
    selected=a.card_entity_id if native is None else native.selection.target_id
    if selected is None:
        raise ResolutionError('Validated investment lost its complete live hand target domain')
    card = r.state.entities[selected]
    captured = CardReference.capture(card)
    hand_entry = card.hand_entry_id
    use_id = len(r.state.interactable_history) + 1
    # Commitment is one checkpoint: retirement and once-per-interval consumption
    # precede every resulting reaction. Neither is an ordinary card play.
    remove_from_game(r, RemoveFromGame((captured,), obj.id, reveal=True))
    event = r.emit('interactable_use_started', source_id=obj.id, player_id=a.player_id,
        use_id=use_id)
    record = InteractableUseRecord(use_id, a.player_id, obj.id, obj.card_id,
        obj.zone_epoch, obj.board_presence_id, captured, hand_entry, interval.id,
        r.state.turn, r.state.action_number, event.sequence)
    r.state.interactable_history.append(record)
    return (r.call(r.registry.card(obj.card_id).interactable.behavior_id, obj.id,
        a.player_id, captured.entity_id, event=event), FinishInteractableUse(use_id),
        *(()if native is None else(FinishNativeActiveTarget(native),)))


def finish(r, effect):
    effect.__post_init__()
    if effect.use_id > len(r.state.interactable_history):
        raise ResolutionError('Unknown interactable use')
    record = r.state.interactable_history[effect.use_id - 1]
    if record.finished_event is not None:
        raise ResolutionError('Interactable use is already completed')
    event = r.emit('interactable_used', source_id=record.entity_id,
        player_id=record.player_id, use_id=record.id)
    r.state.interactable_history[record.id - 1] = replace(record, finished_event=event.sequence)


def validate_state(state, registry):
    if type(state.interactable_history) is not list:
        raise ValueError('Interactable history requires a list')
    used = set()
    for entity in state.entities.values():
        if type(entity.interactable_object) is not bool:
            raise ValueError('Interactable marker must be boolean')
        definition = registry.card(entity.card_id)
        passive = type(definition.interactable) is PassiveBoardObjectSpec
        if entity.interactable_object != (definition.interactable is not None):
            raise ValueError('Interactable marker disagrees with the original definition')
        if entity.interactable_object and (entity.zone != Zone.BOARD or entity.kind != CardType.MINION or
                entity.base_attack or entity.base_health != 1 or entity.damage or entity.armor or
                entity.doomed or entity.death_cause is not None or entity.silenced or entity.frozen or
                entity.attacks_this_turn or (not passive and (entity.enchantments or entity.abilities)) or entity.components or
                entity.starship_building or entity.dormancy is not None or entity.corpse_value or
                entity.aura_attack or entity.aura_health or entity.aura_keywords or entity.hand_aura_keywords or
                entity.durability or entity.uses_this_turn or entity.use_limit != 1):
            raise ValueError('Interactable carrier contains ordinary combat or attachment state')
        if passive:
            from .passive_objects import validate_entity
            validate_entity(registry, entity)
    for i, record in enumerate(state.interactable_history, 1):
        if type(record) is not InteractableUseRecord:
            raise ValueError('Interactable history requires its exact typed record')
        record.__post_init__()
        obj = state.entities.get(record.entity_id)
        if (record.id != i or obj is None or not obj.interactable_object or
                type(registry.card(obj.card_id).interactable) is not InteractableSpec or
                (obj.controller, obj.card_id, obj.zone_epoch, obj.board_presence_id) !=
                (record.player_id, record.card_id, record.zone_epoch, record.presence_id) or
                record.action > state.action_number or record.turn > state.turn or
                record.owner_turn_id > len(state.owner_turn_history)):
            raise ValueError('Interactable history lost its physical carrier or actual action')
        interval = state.owner_turn_history[record.owner_turn_id - 1]
        if (interval.player_id, interval.turn) != (record.player_id, record.turn):
            raise ValueError('Interactable use belongs to another owner interval')
        key = record.entity_id, record.owner_turn_id
        if key in used:
            raise ValueError('An interactable can be used only once per actual owner interval')
        used.add(key)
        if record.hand_entry_id > len(state.hand_entries):
            raise ValueError('Investment lacks an actual successful hand acquisition')
        entry = state.hand_entries[record.hand_entry_id - 1]
        registry.card(record.invested.card_id)
        if ((entry.entity_id, entry.player_id) != (record.invested.entity_id, record.player_id) or
                entry.zone_epoch > record.invested.zone_epoch):
            raise ValueError('Investment differs from the original hand acquisition')


def validate_boundary(game):
    state = game._state
    validate_state(state, game.registry)
    pending = []
    for record in state.interactable_history:
        if record.started_event > len(game._events):
            raise ValueError('Interactable acceptance event is missing')
        started = game._events[record.started_event - 1]
        if (started.kind, started.source_id, started.player_id, started.action,
                dict(started.data)) != ('interactable_use_started', record.entity_id,
                record.player_id, record.action, {'use_id': record.id}):
            raise ValueError('Interactable acceptance event disagrees with history')
        removed = game._events[record.started_event - 2] if record.started_event > 1 else None
        if (removed is None or (removed.source_id, removed.action) != (record.entity_id, record.action) or
                removal_result(removed) != (((record.invested.entity_id,
                record.player_id, Zone.HAND.value, record.invested.card_id),), True)):
            raise ValueError('Interactable investment lacks its complete removal receipt')
        if record.finished_event is None:
            pending.append(record.id)
        else:
            if record.finished_event > len(game._events):
                raise ValueError('Interactable completion event is missing')
            event = game._events[record.finished_event - 1]
            if ((event.kind, event.source_id, event.player_id, dict(event.data)) != (
                    'interactable_used', record.entity_id, record.player_id,
                    {'use_id': record.id}) or not record.action <= event.action <= state.action_number):
                raise ValueError('Interactable completion disagrees with its original root')
    if state.status != 'playing':
        return
    queued = [] if game._frame is None else [e.use_id for e in
        (*game._frame.prefix, *game._frame.continuation)
        if type(e) is FinishInteractableUse]
    if pending != queued or len(pending) > 1:
        raise ValueError('Pending interactable use lost its executable completion')
    if pending and game._frame.root_action_number != state.interactable_history[pending[0] - 1].action:
        raise ValueError('Pending interactable use belongs to another original action')


def register(mechanics):
    mechanics.register(InstallInteractable, install)
    mechanics.register(ActivateInteractable, activate)
    mechanics.register(FinishInteractableUse, finish)
