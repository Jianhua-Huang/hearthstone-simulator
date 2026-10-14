"""Prepare's dedicated mana investment and physical-card state.

The deck drag is a client gesture, not a draw or shuffle. The same hand
entity stays in place. Existing payment and local-cost records do the work.
"""
from dataclasses import replace

from .costs import CostQuote, pay_quote, quote_cost
from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import Enchantment, HandPreparation, PaymentType, Zone


def quote(state, registry, source):
    current_cost = quote_cost(state, registry, source).amount
    # A one-cost card still needs one mana. The bonus is lost at the zero floor.
    cap = max(1, current_cost - 1) if current_cost > 0 else 0
    amount = min(state.players[source.controller].mana, cap)
    return CostQuote(source.id, source.controller, amount, PaymentType.MANA)


def action_error(source, price):
    if source.preparation is not None:
        return 'This physical card has already been Prepared'
    if price.amount < 1:
        return 'Prepare requires remaining mana and a positive card cost'
    return None


def play_error(state, source):
    if source.preparation is not None and source.preparation.turn == state.turn:
        return 'A Prepared card cannot be played on the turn it was Prepared'
    return None


def activate(r, source, price):
    if reason := action_error(source, price):
        raise ResolutionError(reason)
    pay_quote(r, r.player(source.controller), source, price)
    discount = Enchantment(attachment_id(r.state), cost=-(price.amount + 1), label='prepare')
    source.enchantments.append(discount)
    source.preparation = HandPreparation(r.state.turn, price.amount, discount.id)
    refresh_entity(source)
    return r.emit('card_prepared', target_id=source.id,
                  player_id=source.controller, amount=price.amount)


def enter_deck(entity):
    """Prepare's discount and spent flag reset on deck entry, independently."""
    if entity.preparation is not None:
        entity.enchantments = [e for e in entity.enchantments if e.id != entity.preparation.cost_id]
        entity.preparation = None
        refresh_entity(entity)


def copy_state(source, destination, enchantment_ids):
    destination.preparation = None if source.preparation is None else replace(
        source.preparation, cost_id=enchantment_ids[source.preparation.cost_id])
    if destination.zone == Zone.DECK:
        enter_deck(destination)


def attachments_removed(entity):
    if entity.preparation is not None and not any(
            e.id == entity.preparation.cost_id for e in entity.enchantments):
        entity.preparation = None


def public_state(state, source):
    value = source.preparation
    return None if value is None else {'turn': value.turn, 'mana_spent': value.mana_spent,
                                      'playable': value.turn != state.turn}


def validate_boundary(game):
    for entity in game._state.entities.values():
        value = entity.preparation
        if value is None:
            continue
        if type(value) is not HandPreparation:
            raise ValueError('Preparation requires HandPreparation')
        value.__post_init__()
        if value.turn > game._state.turn or entity.zone == Zone.DECK:
            raise ValueError('Preparation has a future turn or survived deck entry')
        expected = Enchantment(value.cost_id, cost=-(value.mana_spent + 1), label='prepare')
        if next((e for e in entity.enchantments if e.id == value.cost_id), None) != expected:
            raise ValueError('Preparation discount does not match its physical-card state')
