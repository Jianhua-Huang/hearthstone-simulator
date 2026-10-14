"""Starship construction, composite bases and the independent launch operation.

An inactive board entity is the single source of construction state. It occupies
a slot but does not participate as a minion until launched. Components are
definition IDs, not the mutable stats/attachments of their dying instances.
"""
from dataclasses import dataclass, replace

from .actions import LaunchStarship
from .costs import CostQuote, apply_cost, pay_quote, payment_error
from .effects import Effect
from .errors import ResolutionError
from .lifecycle import active_abilities, install_base, refresh_entity
from .model import CardClass, CostScope, Event, Keyword, PaymentType, StarshipLaunchRecord, Zone
from .registry import UnsupportedDefinitionError


LAUNCH_COST = 5


def construction(state, player_id):
    return next((state.entities[i] for i in state.players[player_id].board
                 if state.entities[i].starship_building), None)


def launch_quote(state, entity):
    # A launch is not a card play; ordinary minion discounts do not apply.
    amount, applied, consumed = LAUNCH_COST, [], []
    for modifier in state.players[entity.controller].cost_modifiers:
        if modifier.scope != CostScope.STARSHIP_LAUNCH:
            continue
        spec = modifier.spec
        amount = apply_cost(amount, spec.delta, spec.set_to, spec.minimum)
        applied.append(modifier.id)
        if modifier.uses_remaining is not None:
            consumed.append(modifier.id)
    return CostQuote(entity.id, entity.controller, amount, PaymentType.MANA, tuple(applied), tuple(consumed))


def launch_error(state, player_id, entity_id):
    ship = construction(state, player_id)
    if ship is None or ship.id != entity_id:
        return 'No matching Starship under construction'
    return payment_error(state, launch_quote(state, ship))


def body_definition(state, registry, player_id):
    player = state.players[player_id]
    hero_class = player.hero_class or player.deck_class or CardClass.NEUTRAL
    bodies = {c: card for card in registry.cards.values() for c in card.starship_for}
    body = bodies.get(hero_class, bodies.get(CardClass.NEUTRAL))
    if body is None:
        raise UnsupportedDefinitionError(f'No Starship body for {hero_class}')
    return body


def contribute(r, records):
    """Called once the whole death batch has left play, before death reactions."""
    for record in records:
        if record.zone != Zone.BOARD or Keyword.STARSHIP_PIECE not in record.keywords:
            continue
        # A composite granted Starship Piece contributes its composed base. This
        # flattens definitions, preventing recursive/cyclic runtime templates.
        parts = record.components or (record.card_id,)
        ship = construction(r.state, record.controller)
        if ship is None:
            player = r.player(record.controller)
            if len(player.board) >= r.rules.max_board:
                raise ResolutionError('A dying Starship Piece must leave a construction slot')
            body = body_definition(r.state, r.registry, player.id)
            ship = r.create_entity(player.id, body.id, Zone.BOARD, record.position, components=parts)
            ship.starship_building = True
            # Construction is not an entered minion. Printed durations start on launch.
            ship.abilities = [replace(a, keyword_expiry=None) if a.timed_keyword is not None else a
                              for a in ship.abilities]
            refresh_entity(ship)
            r.emit('starship_started', source_id=record.entity_id, target_id=ship.id,
                   player_id=player.id, card_id=body.id)
        else:
            install_base(r.state, ship, r.registry.card(ship.card_id), r.registry, ship.components + parts)
        r.emit('starship_piece_added', source_id=record.entity_id, target_id=ship.id,
               player_id=record.controller, amount=1, death_id=record.id, component_card_ids=parts)


@dataclass(frozen=True)
class LaunchStarshipEffect(Effect):
    """Launch a specific construction without paying its manual activation fee."""
    player_id: int
    entity_id: int
    followup: tuple[Effect, ...] = ()

    def __post_init__(self):
        LaunchStarship(self.player_id, self.entity_id)
        if type(self.followup) is not tuple or any(not isinstance(e, Effect) for e in self.followup):
            raise ValueError('Launch followup must be an immutable tuple of effects')


@dataclass(frozen=True)
class ActivateStarship(Effect):
    action: LaunchStarship


@dataclass(frozen=True)
class RelaunchStarships(Effect):
    """Replay the player's captured launch inventory, without extending it."""
    player_id: int

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid relaunch player')


@dataclass(frozen=True)
class RelaunchRecordedStarship(Effect):
    player_id: int
    record_id: int

    def __post_init__(self):
        RelaunchStarships(self.player_id)
        if type(self.record_id) is not int or self.record_id < 1:
            raise ValueError('Invalid launch record ID')


@dataclass(frozen=True)
class ResolveLaunchAbility(Effect):
    behavior_id: str
    source_id: int
    player_id: int
    event: Event


@dataclass(frozen=True)
class FinishStarshipLaunch(Effect):
    """Close a persisted death-deferral scope after every launch reaction."""
    pass


def resolve_launch_ability(r, effect):
    # Freeze eligibility/order at launch, but read the board when this ability
    # executes. Earlier launch effects can change stats, capacity and targets.
    return [r.call(effect.behavior_id, effect.source_id, effect.player_id, event=effect.event)]


def finish_launch(r, effect):
    if r.death_deferrals < 1:
        raise ResolutionError('Unbalanced Starship launch boundary')
    r.death_deferrals -= 1


def launch(r, effect, *, paid=False):
    ship = construction(r.state, r.player(effect.player_id).id)
    if ship is None or ship.id != effect.entity_id:
        r.stale(effect, effect.entity_id)
        return
    if not paid:
        from .payment_projection import consume_quoted_modifiers
        consume_quoted_modifiers(r.state, launch_quote(r.state, ship), origin='effect_launch')
    r.state.starship_history.append(StarshipLaunchRecord(len(r.state.starship_history) + 1,
        ship.controller, ship.id, ship.card_id, ship.components, r.state.turn, r.state.action_number))
    return launch_ready_ship(r, ship, 'starship_launched', effect.followup)


def launch_ready_ship(r, ship, event_kind, followup=()):
    """Shared activation phase for a construction and a fresh historical copy."""
    r.death_deferrals += 1
    ship.starship_building = False
    from .timed_keywords import arm
    arm(r.state, ship)
    ship.summoned_turn = r.state.turn
    ship.entered_order = r.state.next_order
    r.state.next_order += 1
    r.refresh_auras()
    event = r.emit(event_kind, source_id=ship.id, target_id=ship.id,
                   player_id=ship.controller, amount=len(ship.components))
    r.emit('minion_summoned', source_id=ship.id, target_id=ship.id, player_id=ship.controller)
    abilities = list(active_abilities(ship, 'on_launch'))
    r.game._rng.shuffle(abilities)
    return [*(ResolveLaunchAbility(a.behavior_id, ship.id, ship.controller, event) for a in abilities),
            FinishStarshipLaunch(), *followup]


def relaunch_starships(r, effect):
    records = [record for record in r.state.starship_history if record.player_id == effect.player_id]
    # Freeze and shuffle once; each launch rechecks capacity after earlier effects.
    r.game._rng.shuffle(records)
    return [RelaunchRecordedStarship(effect.player_id, record.id) for record in records]


def relaunch_recorded(r, effect):
    record = next((record for record in r.state.starship_history if record.id == effect.record_id), None)
    if record is None or record.player_id != effect.player_id:
        raise ResolutionError('Relaunch requires a matching historical launch')
    player = r.player(effect.player_id)
    if len(player.board) >= r.rules.max_board:
        r.emit('summon_failed', player_id=player.id, card_id=record.card_id, reason='board_full')
        return
    ship = r.create_entity(player.id, record.card_id, Zone.BOARD, components=record.components)
    ship.origin_entity_id = record.entity_id
    return launch_ready_ship(r, ship, 'starship_relaunched')


def activate(r, effect):
    action = effect.action
    if reason := launch_error(r.state, action.player_id, action.entity_id):
        raise ResolutionError(reason)
    ship = construction(r.state, action.player_id)
    pay_quote(r, r.player(action.player_id), ship, launch_quote(r.state, ship))
    return launch(r, LaunchStarshipEffect(action.player_id, action.entity_id), paid=True)


def register_starships(mechanics):
    mechanics.register(ActivateStarship, activate)
    mechanics.register(LaunchStarshipEffect, launch)
    mechanics.register(ResolveLaunchAbility, resolve_launch_ability)
    mechanics.register(FinishStarshipLaunch, finish_launch)
    mechanics.register(RelaunchStarships, relaunch_starships)
    mechanics.register(RelaunchRecordedStarship, relaunch_recorded)
