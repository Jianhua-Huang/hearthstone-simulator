"""Information-safe local Practice-like policy; exact CN ranking is uncalibrated."""
from .errors import ResolutionError

POLICY = 'yogg-practice-like-v1'
ASCENT, DOMAIN = 'BE_009t3', 'BE_009t4'


def visible(observation):
    result = {}
    for p in observation['players']:
        for values in ([p['hero']], [p['hero_power'], *p['additional_hero_powers']],
                       [p['weapon']], p['board'], p['hand'], p['quests']):
            result.update((v['ref'], v) for v in values if v is not None)
    return result


def choose(message, actor_ref=None, planned=()):
    """Only detached player DTOs enter this function; never a Game or registry."""
    if message['error'] is not None or message['actions'] is None:
        raise ResolutionError('Controlled turn cannot substitute for unsupported player rules')
    actions = [a for a in message['actions'] if a['type'] != 'concede']
    if not actions:
        raise ResolutionError('Controlled turn has no supported legal action')
    for ability in planned:
        selected = [a for a in actions if a['type'] == 'use_minion_ability' and
            a.get('minion') == actor_ref and a['ability_id'] == ability]
        if selected:
            actions = selected
            break
    entities = visible(message['observation'])
    viewer = message['observation']['viewer']

    def score(a):
        kind = a['type']
        target = entities.get(a.get('target', a.get('defender')), {})
        enemy = target.get('controller') == 3-viewer
        if kind == 'select_choice':
            return 10000
        if kind == 'use_minion_ability':
            return 700+int(enemy)*50+int(enemy and target.get('health', 100)>0 and target.get('health', 100)<=10)*20
        if kind == 'attack':
            source = entities.get(a['attacker'], {})
            attack = source.get('attack', 0)
            if enemy and target.get('kind') == 'hero' and attack >= target.get('health', 0)+target.get('armor', 0):
                return 100000
            kill = enemy and attack >= target.get('health', 100)
            survive = source.get('health', 0) > target.get('attack', 0)
            return 200+int(kill)*50+int(survive)*20+int(enemy and target.get('kind') == 'hero')*5
        if kind == 'play_card':
            source = entities.get(a['card'], {})
            return 400+source.get('cost', {}).get('amount', 0)*10+int(enemy)*5
        scores = {'use_location': 300, 'launch_starship': 250, 'use_hero_power': 100,
                  'use_hand_action': 50, 'use_interactable': 30, 'end_turn': -1000}
        if kind not in scores:
            raise ResolutionError('Controlled turn encountered an unknown player command')
        return scores[kind]+int(enemy)*5

    # Legal DTO order is canonical and information-safe. Ties keep that order.
    return max(actions, key=score)
