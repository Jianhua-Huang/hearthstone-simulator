"""Hidden secret instances and live, ordered eligibility checks."""
from copy import deepcopy
from dataclasses import dataclass

from .effects import Effect
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import Event, Zone, _int, _name
from .registry import RuleContext


def area_count(player, registry):
    return len(player.secrets) + len(player.quests) + sum(
        registry.player_effect(e.spec_id).duration is not None for e in player.player_effects)


def activation_error(state, registry, rules, player_id, card_id):
    spec = registry.card(card_id).secret
    if spec is None:
        return None
    player = state.players[player_id]
    if area_count(player, registry) >= rules.max_secret_zone:
        return 'Secret/quest/ongoing area is full'
    if any(registry.card(state.entities[i].card_id).secret.key == spec.key for i in player.secrets):
        return 'This secret is already active'
    return None


def activate(r, entity):
    reason = activation_error(r.state, r.registry, r.rules, entity.controller, entity.card_id)
    if reason:
        r.emit('secret_set_failed', player_id=entity.controller, reason=reason)
        return
    entity.secret_instance_id = attachment_id(r.state)
    r.move(entity, Zone.SECRET)
    r.emit('secret_set', source_id=entity.id, player_id=entity.controller)


@dataclass(frozen=True)
class SetSecret(Effect):
    player_id: int
    card_id: str

    def __post_init__(self):
        _int(self.player_id, 'secret player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid secret player')
        _name(self.card_id, 'secret card')


@dataclass(frozen=True)
class RemoveSecret(Effect):
    target_id: int

    def __post_init__(self):
        _int(self.target_id, 'secret target', 1)


@dataclass(frozen=True)
class CheckSecret(Effect):
    target_id: int
    instance_id: int
    event: Event

    def __post_init__(self):
        _int(self.target_id, 'secret target', 1)
        _int(self.instance_id, 'secret instance', 1)
        if type(self.event) is not Event:
            raise ValueError('Secret checks require a captured event')


def set_secret(r, effect):
    if r.registry.card(effect.card_id).secret is None:
        raise ResolutionError('SetSecret requires a secret definition')
    if reason := activation_error(r.state, r.registry, r.rules, effect.player_id, effect.card_id):
        r.emit('secret_set_failed', player_id=effect.player_id, reason=reason)
        return
    # A generated secret never passes through a revealed hand or public summon.
    entity = r.create_entity(effect.player_id, effect.card_id, Zone.GRAVEYARD)
    activate(r, entity)


def consume(r, entity, event_kind):
    entity.secret_instance_id = None
    r.move(entity, Zone.GRAVEYARD)
    r.emit(event_kind, source_id=entity.id, player_id=entity.controller)


def remove(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if entity is not None and entity.zone == Zone.SECRET:
        consume(r, entity, 'secret_removed')


def check(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.zone != Zone.SECRET or entity.secret_instance_id != effect.instance_id:
        return
    spec = r.registry.card(entity.card_id).secret
    own_turn = entity.controller == r.state.active_player
    if (spec.turn == 'opponent' and own_turn) or (spec.turn == 'owner' and not own_turn):
        return
    if spec.requires_board_space and len(r.player(entity.controller).board) >= r.rules.max_board:
        return
    from .interrupts import find_window
    window_id = dict(effect.event.data).get('window_id')
    window = find_window(r.state, window_id) if window_id is not None else None
    if window_id is not None and window is None:
        return
    context = RuleContext(deepcopy(r.state), entity.id, entity.controller,
        target_id=window.target_id if window else effect.event.target_id, event=effect.event, window=window)
    eligible = r.registry.secret_condition(spec.condition_id)(context)
    if type(eligible) is not bool:
        raise ResolutionError('Secret condition must return a boolean')
    if not eligible:
        return
    # Mark consumed before publishing reveal or running any behavior. A nested
    # event cannot consume this instance again, even across a pending choice.
    consume(r, entity, 'secret_revealed')
    return [r.call(spec.behavior_id, entity.id, entity.controller, context.target_id,
                   event=effect.event, window=window)]


def register_secrets(mechanics):
    for effect, handler in ((SetSecret, set_secret), (RemoveSecret, remove), (CheckSecret, check)):
        mechanics.register(effect, handler)
