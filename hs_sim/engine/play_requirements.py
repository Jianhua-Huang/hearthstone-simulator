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
