"""Private hypothetical received cards using actual materialization and admission.

No Game, action execution, event emission, RNG, or caller-owned mutation is used.
The hypothetical hand can exceed capacity: real delivery still burns normally.
The original active player/turn and knowledge are preserved; the query asks only
the recipient's per-card admission, not whether that seat can act out of turn.
"""
from copy import copy
from .runtime_copy import deepcopy

from .body_player_commands import bound_profiles, independent_hand_play_actions
from .entity_materialization import create_entity
from .hand_admission import hand_plays, root_target_contract, validate_hand_play
from .information import Information, Knowledge
from .model import Entity, GameState, HandLifetime, PlayerState, Zone
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


def _preview_inputs(state, registry, information, *, readonly):
    """Fork the writes of HAND materialization and Information.sync only.

    Existing entities, histories and knowledge events are read-only here.
    Predicates still receive detached RuleContext/player DTOs through the
    ordinary admission API. This fork must never run effects or emit events.
    """
    from .registry import Registry
    if (not readonly or type(state) is not GameState or type(registry) is not Registry
            or type(information) is not Information or type(state.entities) is not dict
            or type(state.players) is not dict or type(state.hand_entries) is not list
            or any(type(e) is not Entity for e in state.entities.values())
            or any(type(p) is not PlayerState or type(p.hand) is not list for p in state.players.values())
            or any(type(k) is not Knowledge for k in information.players.values())):
        return deepcopy(state), deepcopy(information)
    projected = copy(state)
    projected.entities = dict(state.entities)
    projected.players = {pid: copy(player) for pid, player in state.players.items()}
    for player in projected.players.values():
        player.hand = list(player.hand)
    projected.hand_entries = list(state.hand_entries)
    knowledge = copy(information)
    knowledge.players = {pid: copy(row) for pid, row in information.players.items()}
    for row in knowledge.players.values():
        row.refs = dict(row.refs)
        row.known = dict(row.known)
        row.body_refs = dict(row.body_refs)
        row.pending = deepcopy(row.pending)
    return projected, knowledge


def can_receive_and_play(state, registry, rules, information, player_id, card_id, source_id, expires_turn,
                         *, readonly=False):
    projected, knowledge = _preview_inputs(state, registry, information, readonly=readonly)
    surface = PreviewSurface(projected, registry, rules, knowledge)
    entity = create_entity(surface._state, registry, player_id, card_id, Zone.HAND)
    entity.origin_entity_id = source_id
    entity.hand_lifetime = HandLifetime(source_id, state.turn, expires_turn, 0)
    surface._information.sync(surface)
    if bound_profiles(surface, entity):
        return bool(independent_hand_play_actions(surface, entity, first_only=True))
    return bool(hand_plays(surface, entity, validator=surface.validate, first_only=True))
