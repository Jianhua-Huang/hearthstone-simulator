"""Seat-bound JSON commands and information-safe legality for trusted hosts.

The port is not a Python sandbox or network authentication. Only its returned
DTOs cross the player boundary; keep the underlying Game inside the host.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import re

from .actions import UseMinionAbility, Attack, EndTurn, PlayCard, SelectChoice, UseHeroPower, UseHandAction, LaunchStarship, UseLocation
from .errors import IllegalAction, ResolutionError, ResolutionLimitExceeded
from .information import PUBLIC_ZONES, player_id
from .model import CardType, Zone
from .registry import PlayerRuleContext
from .serialization import canonical_hash
from .targeting import target_spec
from .play_history import play_definition
from .actions import UseInteractable, Concede


API_VERSION = 'player-actions-v13'
_HAND_KINDS = {CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO}


class UnsupportedPlayerRule(ValueError):
    """An explicit unsupported declaration, not a hidden-state eligibility test."""


def visible_entities(observation):
    """Index current public slots and hands, excluding historical graveyard refs."""
    result = {}
    for player in observation['players']:
        for zone, cards in (
                ('hero', [player['hero']]), ('hero_power', [player['hero_power'], *player['additional_hero_powers']]),
                ('weapon', [player['weapon']]), ('board', player['board']), ('quests', player['quests']), ('hand', player['hand'])):
            for card in cards:
                if card is not None:
                    result[card['ref']] = {**card, 'zone': zone, 'controller': player['id']}
    return result


def context_factory(game, viewer):
    """Lazily capture one public projection per query, copying for each predicate."""
    cached = []

    def context(source_id, target_id):
        if not cached:
            observation = game.observe(viewer)
            cached.append((observation, visible_entities(observation)))
        observation, visible = cached[0]
        refs = game._information.players[viewer].refs
        source = visible.get(refs.get(str(source_id)))
        if source is None:
            raise ValueError('Player predicate source must be visible')
        target = visible.get(refs.get(str(target_id))) if target_id is not None else None
        return PlayerRuleContext(viewer, deepcopy(observation), deepcopy(source), deepcopy(target))
    return context


def require_supported_source(game, entity_id, *, definition=None, check_use=False):
    """Check declarations before running predicates or inspecting target cards.

    A blind hand target cannot use a hidden card's type as an eligibility filter.
    Player predicates can only inspect the hand-back/known-face DTO. Deck and
    graveyard selection require a separate reveal/choice contract, not raw IDs.
    """
    source = game._state.entities[entity_id]
    definition = definition or game.registry.card(source.card_id)
    if definition.id in game.registry.spell_value_profiles:
        from .native_spell_values import bound_value
        from .retained_spell_damage import ReturningDamageProfile
        if bound_value(source)is None and type(game.registry.spell_value_profiles[definition.id]) is not ReturningDamageProfile:
            raise UnsupportedPlayerRule('unsupported_rule')
    if source.zone == Zone.HAND and definition.choose_one is None and definition == game.registry.card(source.card_id):
        definition = play_definition(game._state, game.registry, source)
    if definition.choose_one is not None:
        from .choose_one import effective
        for branch in (*definition.choose_one.branches,definition.choose_one.combined):
            require_supported_source(game,entity_id,definition=effective(definition,branch.id),check_use=check_use)
        return
    from .body_player_commands import bound_profiles,supported_profiles
    if source.zone==Zone.HAND and bound_profiles(game,source):
        supported_profiles(game,source)
        return
    spec = target_spec(definition)
    if spec is not None:
        if game.registry.target_visibility(definition.target_rule) not in ('builtin', 'player'):
            raise UnsupportedPlayerRule('unsupported_rule')
        if set(spec.zones) - (PUBLIC_ZONES | {Zone.HAND}):
            raise UnsupportedPlayerRule('unsupported_target_domain')
        if (Zone.HAND in spec.zones and spec.relation != 'friendly' and
                not _HAND_KINDS <= set(spec.kinds)):
            raise UnsupportedPlayerRule('unsupported_target_domain')
        from .target_predicates import player_domain_supported
        if not player_domain_supported(game.registry, definition.target_rule, spec):
            raise UnsupportedPlayerRule('unsupported_target_domain')
        # any_character rejects hands based solely on their public zone.
        # any_entity accepts every current hand kind; neither reads hidden stats.
    if (check_use or definition.kind in (CardType.SPELL, CardType.HERO_POWER) or
            definition.kind == CardType.LOCATION and source.zone == Zone.BOARD):
        if game.registry.use_visibility(definition.use_rule) not in ('builtin', 'player'):
            raise UnsupportedPlayerRule('unsupported_rule')


def require_supported_minion_ability(game, entity_id, ability_id):
    from dataclasses import replace
    from .minion_abilities import specification, ability_definition
    entity = game._state.entities[entity_id]
    ability = specification(entity, ability_id)
    if ability is not None:
        definition = replace(ability_definition(game.registry, entity, ability.activation),
                             use_rule=ability.activation.use_rule)
        require_supported_source(game, entity_id, definition=definition, check_use=True)


def require_supported_hand_action(game, entity_id, action_id):
    from .hand_actions import specification
    spec = specification(game.registry, game._state.entities[entity_id], action_id)
    if spec is not None and game.registry.use_visibility(spec.use_rule) not in ('builtin', 'player'):
        raise UnsupportedPlayerRule('unsupported_rule')


def _acting(game, viewer):
    state = game._state
    if state.status != 'playing':
        return False
    if state.pending_choice is not None:
        return state.pending_choice.player_id == viewer
    return state.active_player == viewer


def _encode(game, viewer, action):
    knowledge = game._information.players[viewer]

    def ref(entity_id):
        return None if entity_id is None else knowledge.refs[str(entity_id)]

    if isinstance(action, PlayCard):
        result={'type': 'play_card', 'card': ref(action.entity_id), 'target': ref(action.target_id), 'position': action.position}
        if action.target_ids:
            result['targets'] = [ref(i) for i in action.target_ids]
        if action.board_player_id is not None:
            result['side'] = 'friendly' if action.board_player_id == viewer else 'enemy'
        if action.branch_id is not None: result['branch'] = action.branch_id
        if action.body_target_profile_id is not None:
            from .body_player_commands import encode_entries,encode_empty_route
            result['body_targets']=encode_entries(game,viewer,action)
            if not action.body_targets:result['body_route']=encode_empty_route(game,viewer,action)
        source=game._state.entities[action.entity_id]
        if game.registry.card(source.card_id).magnetic_tribes:
            from .magnetic import host_at_position
            host=host_at_position(game._state,game.registry,source,action.position)
            result['magnetic_target']=ref(host.id) if host else None
        return result
    if isinstance(action, UseMinionAbility):
        return {'type': 'use_minion_ability', 'minion': ref(action.entity_id),
                'ability_id': action.ability_id, 'target': ref(action.target_id)}
    if isinstance(action, UseInteractable):
        return {'type': 'use_interactable', 'object': ref(action.entity_id),
                'card': ref(action.card_entity_id)}
    if isinstance(action, UseLocation):
        return {'type': 'use_location', 'location': ref(action.entity_id), 'target': ref(action.target_id)}
    if isinstance(action, LaunchStarship):
        return {'type': 'launch_starship', 'starship': ref(action.entity_id)}
    if isinstance(action, UseHandAction):
        return {'type': 'use_hand_action', 'card': ref(action.entity_id), 'action_id': action.action_id}
    if isinstance(action, UseHeroPower):
        return {'type': 'use_hero_power', 'power': ref(action.entity_id), 'target': ref(action.target_id),
                **({'branch':action.branch_id} if action.branch_id is not None else {})}
    if isinstance(action, Attack):
        return {'type': 'attack', 'attacker': ref(action.attacker_id), 'defender': ref(action.defender_id)}
    if isinstance(action, SelectChoice):
        pending = knowledge.pending
        return {'type': 'select_choice', 'choice': pending['ref'],
                'options': [f'o{pending["option_ids"].index(i) + 1}' for i in action.option_ids]}
    if type(action) is Concede:
        return {"type": "concede"}
    if isinstance(action, EndTurn):
        return {'type': 'end_turn'}
    raise ValueError('Unsupported player action')


_FIELDS = {
    "concede": ({"type"}, set()),
    'use_interactable': ({'type', 'object', 'card'}, set()),
    'use_minion_ability': ({'type', 'minion', 'ability_id'}, {'target'}),
    'use_location': ({'type', 'location'}, {'target'}),
    'launch_starship': ({'type', 'starship'}, set()),
    'use_hand_action': ({'type', 'card', 'action_id'}, set()),
    'play_card': ({'type', 'card'}, {'target', 'targets', 'position', 'magnetic_target', 'branch', 'body_targets', 'body_route', 'side'}),
    'use_hero_power': ({'type', 'power'}, {'target', 'branch'}),
    'attack': ({'type', 'attacker', 'defender'}, set()),
    'end_turn': ({'type'}, set()),
    'select_choice': ({'type', 'choice', 'options'}, set()),
}


def _decode(game, viewer, raw, observation):
    if type(raw) is not dict or type(raw.get('type')) is not str or raw['type'] not in _FIELDS:
        raise ValueError('Malformed player action')
    required, optional = _FIELDS[raw['type']]
    if not required <= set(raw) <= required | optional:
        raise ValueError('Malformed player action fields')
    if raw['type'] == 'concede':
        return Concede(viewer)
    knowledge = game._information.players[viewer]
    visible = visible_entities(observation)
    reverse = {ref: int(key) for key, ref in knowledge.refs.items() if ref in visible}

    def entity(ref, *, optional=False):
        if ref is None and optional:
            return None
        if type(ref) is not str or ref not in reverse:
            raise ValueError('Unavailable entity reference')
        return reverse[ref]

    kind = raw['type']
    player = game._state.players[viewer]
    if kind == 'play_card':
        source = entity(raw['card'])
        # Check ownership before looking at this entity's card definition. A
        # forged enemy hand ref must never reveal its predicate registration.
        if source not in player.hand:
            raise ValueError('Unavailable card')
        require_supported_source(game, source)
        board_player_id = None
        if 'side' in raw:
            if type(raw['side']) is not str or raw['side'] not in ('friendly', 'enemy'):
                raise ValueError('Unknown play board side')
            if not game.registry.card(game._state.entities[source].card_id).disguised:
                raise ValueError('Only Disguised cards can select a board side')
            board_player_id = 3 - viewer if raw['side'] == 'enemy' else None
        if 'magnetic_target' in raw:
            from .magnetic import host_at_position
            host=host_at_position(game._state,game.registry,game._state.entities[source],raw.get('position'))
            if entity(raw['magnetic_target'],optional=True)!=(host.id if host else None):
                raise ValueError('Magnetic target does not match its board position')
        profile=None;entries=()
        if 'body_route' in raw:
            from .body_player_commands import decode_empty_route
            profile,entries=decode_empty_route(game,viewer,game._state.entities[source],raw['body_route'],raw.get('body_targets'))
        elif 'body_targets' in raw:
            from .body_player_commands import decode_entries
            profile,entries=decode_entries(game,viewer,game._state.entities[source],raw['body_targets'],entity)
        target_ids = ()
        target = entity(raw.get('target'), optional=True)
        if 'targets' in raw:
            if type(raw['targets']) is not list or not raw['targets']:
                raise ValueError('Spell targets require a nonempty reference array')
            target_ids = tuple(entity(ref) for ref in raw['targets'])
            if 'target' in raw and target != target_ids[0]:
                raise ValueError('First spell target differs from its complete target vector')
            target = target_ids[0]
        return PlayCard(viewer, source, target, raw.get('position'), raw.get('branch'),profile,entries,board_player_id,target_ids)
    if kind == 'use_interactable':
        source, card = entity(raw['object']), entity(raw['card'])
        if source not in player.board or card not in player.hand:
            raise ValueError('Unavailable interactable or hand investment')
        return UseInteractable(viewer, source, card)
    if kind == 'use_minion_ability':
        source = entity(raw['minion'])
        if source not in player.board:
            raise ValueError('Unavailable minion')
        action = UseMinionAbility(viewer, source, raw['ability_id'], entity(raw.get('target'), optional=True))
        require_supported_minion_ability(game, source, action.ability_id)
        return action
    if kind == 'use_location':
        source = entity(raw['location'])
        if source not in player.board:
            raise ValueError('Unavailable location')
        require_supported_source(game, source)
        return UseLocation(viewer, source, entity(raw.get('target'), optional=True))
    if kind == 'launch_starship':
        return LaunchStarship(viewer, entity(raw['starship']))
    if kind == 'use_hand_action':
        source = entity(raw['card'])
        if source not in player.hand:
            raise ValueError('Unavailable card')
        action = UseHandAction(viewer, source, raw['action_id'])
        require_supported_hand_action(game, source, action.action_id)
        return action
    if kind == 'use_hero_power':
        source = entity(raw['power'])
        if source not in player.hero_power_ids:
            raise ValueError('Unavailable power')
        require_supported_source(game, source)
        return UseHeroPower(viewer, source, entity(raw.get('target'), optional=True), raw.get('branch'))
    if kind == 'attack':
        return Attack(viewer, entity(raw['attacker']), entity(raw['defender']))
    if kind == 'select_choice':
        pending = knowledge.pending
        if pending is None or type(raw['choice']) is not str or raw['choice'] != pending['ref']:
            raise ValueError('Unavailable choice')
        options = raw['options']
        if type(options) is not list or len(options) > len(pending['option_ids']):
            raise ValueError('Invalid choice options')
        available = {f'o{n}': option for n, option in enumerate(pending['option_ids'], 1)}
        if any(type(o) is not str or o not in available for o in options) or len(set(options)) != len(options):
            raise ValueError('Invalid choice options')
        return SelectChoice(viewer, pending['internal_id'], tuple(available[o] for o in options))
    return EndTurn(viewer)


@dataclass(frozen=True, slots=True)
class PlayerPort:
    _game: object
    viewer: int

    def __post_init__(self):
        player_id(self.viewer)

    def observe(self):
        observation = self._game.observe(self.viewer)
        # This is only an observable revision, never the full-state digest or a
        # secret capability. Identical player views intentionally hash equally.
        return {'version': API_VERSION, 'revision': canonical_hash(observation), 'observation': observation}

    def events(self, *, after=0):
        return self._game.player_events(self.viewer, after=after)

    def legal_actions(self):
        from .runtime_queries import query_materials
        with query_materials(self._game):
            return self._legal_actions_with_queries()

    def _legal_actions_with_queries(self):
        result = self.observe()
        result.update(actions=[], error=None)
        game = self._game
        if game._state.status != "playing":
            return result
        result["actions"] = [{"type": "concede"}]
        if not _acting(game, self.viewer):
            return result
        try:
            if game._state.pending_choice is None:
                player = game._state.players[self.viewer]
                for entity_id in player.board:
                    for ability in game._state.entities[entity_id].abilities:
                        if ability.kind == 'activated':
                            require_supported_minion_ability(game, entity_id, ability.activation.id)
                for entity_id in (*player.hand, *(i for i in player.board if game._state.entities[i].kind == CardType.LOCATION), *player.hero_power_ids):
                    require_supported_source(game, entity_id)
                    if entity_id in player.hand:
                        from .hand_actions import specifications
                        for spec in specifications(game.registry, game._state.entities[entity_id]):
                            require_supported_hand_action(game, entity_id, spec.id)
            actions = [_encode(game, self.viewer, action) for action in game.legal_actions() if action.player_id == self.viewer]
            # Engine enumeration uses internal entity IDs. Sort only after
            # projection so hidden creation order cannot change player ordering.
            result['actions'] = sorted(actions, key=lambda item: json.dumps(item, sort_keys=True))
        except UnsupportedPlayerRule as exc:
            result.update(actions=None, error=str(exc))
        except ResolutionLimitExceeded:
            result.update(actions=None, error='enumeration_limit')
        except (ResolutionError, ValueError, TypeError, KeyError):
            result.update(actions=None, error='rule_error')
        return result

    def independent_targets(self, card, *, position=None, branch=None):
        result=self.observe();result.update(choices=None,error=None)
        game=self._game
        try:
            if not _acting(game,self.viewer) or game._state.pending_choice is not None:
                raise ValueError('Independent target query requires actual active hand')
            visible=visible_entities(result['observation'])
            refs=game._information.players[self.viewer].refs
            source=next((game._state.entities[i] for i in game._state.players[self.viewer].hand if refs.get(str(i))==card),None)
            if type(card) is not str or card not in visible or source is None:raise ValueError('Unavailable card')
            from .body_player_commands import project_plans
            result['choices']=project_plans(game,self.viewer,source,position,branch)
        except UnsupportedPlayerRule as exc:result['error']=str(exc)
        except IllegalAction:result['error']='invalid_action'
        except (ResolutionError,ValueError,TypeError,KeyError):result['error']='invalid_action'
        return result

    def submit(self, command):
        before = self.observe()
        game = self._game
        error = None
        try:
            if type(command) is not dict or set(command) != {'revision', 'action'}:
                raise ValueError('Malformed command')
            revision = command['revision']
            if type(revision) is not str or re.fullmatch(r'[0-9a-f]{64}', revision) is None:
                raise ValueError('Malformed revision')
            if revision != before['revision']:
                error = 'stale_observation'
            elif not _acting(game, self.viewer) and not (
                    game._state.status == "playing" and type(command["action"]) is dict
                    and command["action"] == {"type": "concede"}):
                error = 'invalid_action'
            else:
                action = _decode(game, self.viewer, command['action'], before['observation'])
                # Uses exactly the same authoritative legality and transaction
                # as host actions. Raw ActionResult never crosses this boundary.
                game.apply(action)
        except UnsupportedPlayerRule as exc:
            error = str(exc)
        except IllegalAction:
            error = 'invalid_action'
        except ResolutionError:
            error = 'resolution_failed'
        except (ValueError, TypeError, KeyError):
            error = 'invalid_action'
        result = self.observe()
        result.update(accepted=error is None, error=error,
                      events=self.events(after=before['observation']['event_cursor']) if error is None else [])
        return result
