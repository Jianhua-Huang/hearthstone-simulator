"""Finite manual-play prerequisites over original equipment and hand state."""

from .equipment import equipped_weapon


def weapon_requirement_error(state, registry, source):
    definition = registry.card(source.card_id)
    if definition.requires_weapon and equipped_weapon(state, state.players[source.controller]) is None:
        return 'This card requires an equipped weapon'
    return None


def manual_requirement_error(state, registry, source):
    from .hand_play_locks import play_error
    return play_error(state,source) or weapon_requirement_error(state,registry,source)
