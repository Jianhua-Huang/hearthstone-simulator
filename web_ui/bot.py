"""Small random demo opponent. Inputs are only one player's detached JSON DTO.

The caller owns this policy's Random instance, separately from engine randomness.
This module has no Game, registry, state, snapshot, or replay access.
"""
from copy import deepcopy


class BotError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def actor_for(observation):
    pending = observation['pending_choice']
    return pending['player_id'] if pending is not None else observation['active_player']


def choose_action(message, rng, *, force_end=False):
    observation = message['observation']
    if observation['status'] != 'playing' or actor_for(observation) != observation['viewer']:
        raise BotError('opponent_not_acting')
    pending = observation['pending_choice']
    error = message.get('error')
    if error is not None and not (error == 'enumeration_limit' and pending is not None):
        raise BotError('enumeration_failed')
    if pending is not None:
        # Choices are private to their actor. The DTO contains the complete
        # options even when enumerating all combinations exceeds the budget.
        if pending['player_id'] != observation['viewer']:
            raise BotError('opponent_not_acting')
        if error == 'enumeration_limit':
            options = pending.get('options')
            count = pending.get('min_count')
            maximum = pending.get('max_count')
            if (type(options) is not list or type(count) is not int or type(maximum) is not int
                    or not 0 <= count <= maximum <= len(options) or type(pending.get('ref')) is not str):
                raise BotError('choice_unavailable')
            indices = sorted(rng.sample(range(len(options)), count))
            chosen = [options[i] for i in indices]
            if any(type(o) is not dict or type(o.get('ref')) is not str for o in options):
                raise BotError('choice_unavailable')
            if len({o['ref'] for o in options}) != len(options):
                raise BotError('choice_unavailable')
            return {'type': 'select_choice', 'choice': pending['ref'], 'options': [o['ref'] for o in chosen]}
        actions = [a for a in message.get('actions') or []
                   if a.get('type') == 'select_choice' and a.get('choice') == pending['ref']]
        if not actions:
            raise BotError('choice_unavailable')
        return deepcopy(rng.choice(actions))
    actions = message.get('actions')
    if type(actions) is not list:
        raise BotError('enumeration_failed')
    ending = [a for a in actions if a.get('type') == 'end_turn']
    if force_end:
        if ending: return deepcopy(ending[0])
        raise BotError('action_budget_exhausted')
    ordinary = [a for a in actions if a.get('type') not in ('concede', 'end_turn', 'select_choice')]
    if ordinary: return deepcopy(rng.choice(ordinary))
    if ending: return deepcopy(ending[0])
    raise BotError('no_legal_actions')
