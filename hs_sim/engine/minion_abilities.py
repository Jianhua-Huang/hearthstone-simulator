"""Finite minion actions. Titan is the first explicit activation policy."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .actions import UseMinionAbility
from .effects import Effect
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import CardType, Keyword, Zone
from .registry import RuleContext
from .targeting import target_error
from .attack_policies import current_policies, has_action_remaining


def remaining_abilities(entity):
    if not entity.keywords & {Keyword.TITAN,Keyword.OLD_GOD}:
        return ()
    return active_abilities(entity, 'activated')


def specification(entity, ability_id):
    return next((a for a in remaining_abilities(entity) if a.activation.id == ability_id), None)


def ability_definition(registry, entity, spec):
    # The descriptor is never a spell being played: the source is this minion.
    return replace(registry.card(entity.card_id), requires_target=False,
                   targeting=spec.targeting, target_rule=spec.target_rule)


def action_opportunity(entity, *, ignore_frozen=False, state=None, registry=None):
    return (entity.kind == CardType.MINION and entity.zone == Zone.BOARD and entity.active and
            entity.health > 0 and not entity.doomed and (ignore_frozen or not entity.frozen) and
            bool(remaining_abilities(entity)) and
            not any(policy.mode == 'cannot_attack_or_use_minion_abilities'
                    for policy in current_policies(state, entity, registry)) and
            ((Keyword.OLD_GOD in entity.keywords and not entity.old_god_free_used) or
             has_action_remaining(state, entity, registry)))


def ability_error(state, registry, rules, player_id, entity_id, ability_id, target_id, *, context_factory=None):
    entity = state.entities.get(entity_id)
    if entity is None or entity.controller != player_id or not action_opportunity(entity, state=state, registry=registry):
        return 'No minion ability action available'
    ability = specification(entity, ability_id)
    if ability is None:
        return 'Ability is missing or exhausted'
    spec = ability.activation
    if spec.requires_board_space and len(state.players[player_id].board) >= rules.max_board:
        return 'Board is full'
    try:
        if registry.use_visibility(spec.use_rule) == 'player':
            if context_factory is None:
                raise ValueError('Player use rule requires observation context')
            context = context_factory(entity.id, target_id)
        else:
            context = RuleContext(deepcopy(state), entity.id, player_id, target_id)
        allowed = registry.use_rule(spec.use_rule)(context)
    except Exception as exc:
        raise ResolutionError(f'Minion ability use rule failed: {exc}') from exc
    if type(allowed) is not bool:
        raise ResolutionError('Minion ability use rule must return bool')
    if not allowed:
        return 'Minion ability use condition is not satisfied'
    return target_error(state, registry, entity, ability_definition(registry, entity, spec),
                        target_id, context_factory=context_factory)


@dataclass(frozen=True)
class ActivateMinionAbility(Effect):
    action: UseMinionAbility


@dataclass(frozen=True)
class FinishMinionAbility(Effect):
    source_id: int
    player_id: int
    ability_id: str
    card_id: str | None
    target_id: int | None


def activate(r, effect):
    action = effect.action
    source = r.state.entities[action.entity_id]
    ability = specification(source, action.ability_id)
    if ability is None:
        raise ResolutionError('Validated minion ability disappeared')
    if Keyword.OLD_GOD in source.keywords and not source.old_god_free_used:
        source.old_god_free_used = True
    else:
        source.attacks_this_turn += 1
    source.abilities = [replace(a, consumed=True) if a.id == ability.id else a for a in source.abilities]
    event = r.emit('minion_ability_started', source_id=source.id, player_id=source.controller,
                   target_id=action.target_id, ability_id=action.ability_id, ability_card_id=ability.activation.card_id)
    return [r.call(ability.activation.behavior_id, source.id, source.controller, action.target_id, event=event),
            FinishMinionAbility(source.id, source.controller, action.ability_id, ability.activation.card_id, action.target_id)]


def finish(r, effect):
    r.emit('minion_ability_used', source_id=effect.source_id, player_id=effect.player_id,
           target_id=effect.target_id, ability_id=effect.ability_id, ability_card_id=effect.card_id)


def register_minion_abilities(mechanics):
    mechanics.register(ActivateMinionAbility, activate)
    mechanics.register(FinishMinionAbility, finish)
