"""Alternative hand actions, their own prices, and transactional resolution.

Trade commits random insertion and drawing a different physical card in one
checkpoint. Forge changes the printed face in place and preserves attachments.
Neither operation calls PlayFromHand or consumes ordinary play-cost modifiers.
Fine event windows and private-face policies remain explicit M6 contracts.
"""
from .runtime_copy import deepcopy
from dataclasses import dataclass

from .actions import UseHandAction
from .costs import CostQuote, payment_error, pay_quote
from .effects import Effect
from .errors import ResolutionError
from .model import HandActionSpec, PaymentType, Zone
from .registry import RuleContext
from .zones import CardReference, MoveCard, move_card


PREPARE = HandActionSpec('prepare', 'prepare', 1)


def specifications(registry, source):
    """Printed actions plus Prepare granted to this physical card."""
    declared = registry.card(source.card_id).hand_actions
    if (not any(a.kind == 'prepare' and not a.consumed for a in source.abilities) or
            any(s.kind == 'prepare' for s in declared)):
        return declared
    if any(s.id == PREPARE.id for s in declared):
        raise ResolutionError('Granted Prepare conflicts with an existing hand action ID')
    return (*declared, PREPARE)


def specification(registry, source, action_id):
    return next((s for s in specifications(registry, source) if s.id == action_id), None)


def quote_hand_action(state, registry, source, spec):
    if spec.kind == 'prepare':
        from .prepare import quote
        return quote(state, registry, source)
    # A dedicated fee; card enchantments, spell discounts, and alternate PLAY
    # payment accounts must never affect it. Action-specific modifiers are M5.
    return CostQuote(source.id, source.controller, spec.cost, PaymentType.MANA)


def hand_action_error(state, registry, player, source, action_id, *, context_factory=None):
    if source.controller != player.id or source.zone != Zone.HAND or source.id not in player.hand:
        return 'Hand action requires an owned hand card'
    spec = specification(registry, source, action_id)
    if spec is None:
        return 'This card has no such hand action'
    price = quote_hand_action(state, registry, source, spec)
    if spec.kind == 'prepare':
        from .prepare import action_error
        if reason := action_error(source, price):
            return reason
    if reason := payment_error(state, price):
        return reason
    if spec.kind == 'trade' and not player.deck:
        return 'Trade requires another card in the deck'
    try:
        visibility = registry.use_visibility(spec.use_rule)
        if visibility == 'player':
            if context_factory is None:
                raise ValueError('Player hand rules require an observation context')
            context = context_factory(source.id, None)
        else:
            context = RuleContext(state if visibility == 'builtin' else deepcopy(state), source.id, player.id)
        allowed = registry.use_rule(spec.use_rule)(context)
    except Exception as exc:
        raise ResolutionError(f'Hand action use rule failed: {exc}') from exc
    if type(allowed) is not bool:
        raise ResolutionError('Hand action use rule must return bool')
    return None if allowed else 'Hand action use condition is not satisfied'


@dataclass(frozen=True)
class ActivateHandAction(Effect):
    action: UseHandAction


def forge_face(r, source, card_id):
    from .hand_upgrades import upgrade_face
    upgrade_face(r, source, card_id)


def activate_hand_action(r, effect):
    action = effect.action
    player, source = r.player(action.player_id), r.state.entities[action.entity_id]
    if source.id not in player.hand or source.zone != Zone.HAND:
        raise ResolutionError('Hand action source has left the hand')
    spec = specification(r.registry, source, action.action_id)
    if spec is None or (spec.kind == 'trade' and not player.deck):
        raise ResolutionError('Hand action no longer available')
    price = quote_hand_action(r.state, r.registry, source, spec)
    if spec.kind == 'prepare':
        from .prepare import activate
        activate(r, source, price)
        return ()
    pay_quote(r, player, source, price)
    continuation = ()
    if spec.kind == 'trade':
        # Reveal the traded card at its last hand slot, before deck entry retires
        # that handle. The drawn card keeps its ordinary private draw policy.
        for knowledge in r.game._information.players.values():
            knowledge.remember(source)
        r.emit('trade_started', source_id=source.id, player_id=player.id)
        move_card(r, MoveCard(CardReference.capture(source), player.id, Zone.DECK, position='random'))
        drawn_id = next(i for i in player.deck if i != source.id)
        continuation = move_card(r, MoveCard(CardReference.capture(r.state.entities[drawn_id]),
            player.id, Zone.HAND, draw=True, source_id=source.id))
        event = r.emit('card_traded', source_id=source.id, player_id=player.id)
    else:
        forge_face(r, source, spec.upgrade_card_id)
        event = r.emit('card_forged', target_id=source.id, player_id=player.id)
    # Special "after you trade/forge this" behavior is explicit and captured,
    # not a hidden-zone trigger accidentally running all printed on_play rules.
    return [*continuation, *([] if spec.on_use is None else [r.call(spec.on_use, source.id, player.id, event=event)])]


def register_hand_actions(mechanics):
    mechanics.register(ActivateHandAction, activate_hand_action)
