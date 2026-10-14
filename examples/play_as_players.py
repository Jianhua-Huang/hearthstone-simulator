"""A complete experimental match driven exclusively by per-seat JSON DTOs."""
import json
from pathlib import Path

from hs_sim.engine import Game, MatchSetup
from hs_sim.engine.cli import summary
from hs_sim.engine.player_api import visible_entities
from hs_sim.engine.replay import build_replay, replay, save_replay
from hs_sim.engine.representative import build_registry


def choose_action(message):
    """A deterministic exercise policy. No Game, registry, RNG or private IDs."""
    observation = message['observation']
    pending = observation['pending_choice']
    if pending is not None:
        if message['error'] not in (None, 'enumeration_limit'):
            raise ValueError('Unsupported player choice')
        options = pending['options'][::2]
        if len(options) < pending['min_count']:
            options = pending['options'][:pending['min_count']]
        options = options[:pending['max_count']]
        return {'type': 'select_choice', 'choice': pending['ref'], 'options': [o['ref'] for o in options]}
    if message['error'] is not None:
        raise ValueError(f'Cannot enumerate this player rules package: {message["error"]}')
    actions = message['actions']
    visible = visible_entities(observation)
    plays = [a for a in actions if a['type'] == 'play_card']
    if plays:
        return min(plays, key=lambda a: (visible.get(a['target'], {}).get('controller') == observation['viewer'],
                                        int(a['card'][1:]), -(a['position'] or 0), a['target'] or ''))
    attacks = [a for a in actions if a['type'] == 'attack']
    if attacks:
        enemy_hero = observation['players'][2-observation['viewer']]['hero']['ref']
        return min(attacks, key=lambda a: (a['defender'] != enemy_hero, int(a['attacker'][1:]), a['defender']))
    powers = [a for a in actions if a['type'] == 'use_hero_power']
    if powers:
        return powers[0]
    return next(a for a in actions if a['type'] == 'end_turn')


def play_match():
    root = Path(__file__).resolve().parents[1]
    config = MatchSetup.from_dict(json.loads((root / 'examples/matches/constructed.json').read_text(encoding='utf-8')))
    game = Game.from_decks(config, build_registry())
    ports = {viewer: game.for_player(viewer) for viewer in (1, 2)}
    traces = {viewer: [] for viewer in (1, 2)}
    cursors = {viewer: 0 for viewer in (1, 2)}

    def capture():
        for viewer, port in ports.items():
            message = port.observe()
            message['events'] = port.events(after=cursors[viewer])
            cursors[viewer] = message['observation']['event_cursor']
            traces[viewer].append(message)

    capture()
    for _ in range(500):
        routing = ports[1].observe()['observation']
        if routing['status'] != 'playing':
            break
        actor = routing['pending_choice']['player_id'] if routing['pending_choice'] else routing['active_player']
        listing = ports[actor].legal_actions()
        command = {'revision': listing['revision'], 'action': choose_action(listing)}
        traces[actor][-1]['command'] = command
        reply = ports[actor].submit(command)
        if not reply['accepted']:
            raise RuntimeError(f'Player command failed: {reply["error"]}')
        capture()
    if ports[1].observe()['observation']['status'] == 'playing':
        raise RuntimeError('Player demonstration reached its action budget before game end')
    # This verification belongs to the trusted host, after the player strategy
    # has finished. Transport traces contain only their respective seat's DTOs.
    restored = replay(build_replay(game), build_registry())
    assert restored.snapshot() == game.snapshot()
    for viewer in (1, 2):
        assert restored.for_player(viewer).observe() == ports[viewer].observe()
        assert restored.for_player(viewer).events() == ports[viewer].events()
    return game, traces


def main():
    game, traces = play_match()
    root = Path(__file__).resolve().parents[1]
    save_replay(game, root / 'outputs/players-complete-replay.json')
    for viewer, trace in traces.items():
        (root / f'outputs/player-api-{viewer}.json').write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Complete match using player DTOs, seat-bound commands and host replay: passed.')
    print(json.dumps(summary(game), ensure_ascii=False, indent=2))
    print(json.dumps({'player_events': {i: len(game.for_player(i).events()) for i in (1, 2)},
                      'observed_boundaries': {i: len(t) for i, t in traces.items()}}, indent=2))


if __name__ == '__main__':
    main()
