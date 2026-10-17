"""Private hypothetical received cards using actual materialization and admission.

No Game, action execution, event emission, RNG, or caller-owned mutation is used.
The hypothetical hand can exceed capacity: real delivery still burns normally.
The original active player/turn and knowledge are preserved; the query asks only
the recipient's per-card admission, not whether that seat can act out of turn.
"""
from copy import deepcopy

from .body_player_commands import bound_profiles, independent_hand_play_actions
from .entity_materialization import create_entity
from .hand_admission import hand_plays, root_target_contract, validate_hand_play
from .information import Information
from .model import HandLifetime, Zone
from .player_api import context_factory


class PreviewSurface:
    def __init__(self, state, registry, rules, information=None):
        self._state, self.registry, self.ruleset = state, registry, rules
        self._information = information

    @property
    def state(self):
        return deepcopy(self._state)

    def _require_boundary(self):
        # This is an isolated query surface, never the executing Game.
        return

    def observe(self, viewer):
        return deepcopy(self._information.observe(self, viewer))

    def _validate_action(self, action, *, play_target_definition=None):
        return validate_hand_play(self._state, self.registry, self.ruleset, action,
            context=context_factory(self, action.player_id), play_target_definition=play_target_definition)

    def validate(self, action):
        return self._validate_action(action, play_target_definition=root_target_contract(self, action))


def original_information(state, registry, rules, value):
    surface = PreviewSurface(state, registry, rules)
    surface._information = Information.from_dict(value, surface)
    return surface._information


def can_receive_and_play(state, registry, rules, information, player_id, card_id, source_id, expires_turn):
    surface = PreviewSurface(deepcopy(state), registry, rules, deepcopy(information))
    entity = create_entity(surface._state, registry, player_id, card_id, Zone.HAND)
    entity.origin_entity_id = source_id
    entity.hand_lifetime = HandLifetime(source_id, state.turn, expires_turn, 0)
    surface._information.sync(surface)
    if bound_profiles(surface, entity):
        return bool(independent_hand_play_actions(surface, entity, first_only=True))
    return bool(hand_plays(surface, entity, validator=surface.validate, first_only=True))
