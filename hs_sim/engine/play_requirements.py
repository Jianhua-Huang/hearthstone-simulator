"""Finite manual-play prerequisites over original equipment and hand state."""

from .equipment import equipped_weapon


def weapon_requirement_error(state, registry, source):
    definition = registry.card(source.card_id)
    if definition.requires_weapon and equipped_weapon(state, state.players[source.controller]) is None:
        return 'This card requires an equipped weapon'
    return None


def manual_requirement_error(state, registry, source):
    from .hand_play_locks import play_error
    reason = play_error(state,source) or weapon_requirement_error(state,registry,source)
    if reason:
        return reason
    if source.card_id in registry.historical_deathrattle_spells:
        from .historical_deathrattles import eligible_deaths
        if not eligible_deaths(state, registry, source.controller):
            return 'This spell requires a friendly minion with a printed Deathrattle that died this game'
    return None


def manual_use_error(state, registry, source, *, context_factory=None):
    """Dynamic spell admission, like target predicates, never a payment requery."""
    from .runtime_copy import deepcopy
    from .errors import ResolutionError
    from .model import CardType
    from .registry import RuleContext
    definition = registry.card(source.card_id)
    if definition.kind != CardType.SPELL or definition.use_rule == 'always':
        return None
    try:
        if registry.use_visibility(definition.use_rule) == 'player':
            if context_factory is None:
                raise ValueError('Player spell use rules require an observation context')
            context = context_factory(source.id, None)
        else:
            context = RuleContext(deepcopy(state), source.id, source.controller)
        allowed = registry.use_rule(definition.use_rule)(context)
    except Exception as exc:
        raise ResolutionError(f'Spell use rule failed: {exc}') from exc
    if type(allowed) is not bool:
        raise ResolutionError('Spell use rule must return bool')
    return None if allowed else 'Spell use condition is not satisfied'
