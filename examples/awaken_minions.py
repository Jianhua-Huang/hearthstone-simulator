"""Observer and Pelican awaken, then Maiev sends Observer dormant again."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def command(game, kind, card_id=None, target_card=None):
    player = game.state.active_player
    port = game.for_player(player)
    available = port.legal_actions()
    view = game.observe(player)
    visible = {c['ref']: c['card_id'] for p in view['players'] for c in (*p['hand'], *p['board'])}
    action = next(a for a in available['actions'] if a['type'] == kind and
        (card_id is None or visible.get(a.get('card')) == card_id) and
        (target_card is None or visible.get(a.get('target')) == target_card))
    assert port.submit({'revision': available['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('BT_004', 'TSC_647', 'BT_737'), deck=('CS2_182',)*6, mana=10, max_mana=10),
        PlayerSetup('HERO_08', board=('CS2_182',), deck=('CS2_182',)*6),
    ), seed=79), registry)
    command(game, 'play_card', 'BT_004'); command(game, 'play_card', 'TSC_647')
    command(game, 'end_turn'); command(game, 'end_turn')
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        command(match, 'end_turn'); command(match, 'end_turn')
        command(match, 'play_card', 'BT_737', 'BT_004')
        for _ in range(4): command(match, 'end_turn')
        assert all(match.state.entities[i].active for i in match.state.players[1].board)
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for name, data in (('dormancy-snapshot.json', snapshot), ('dormancy-replay.json', build_replay(game)),
                       ('dormancy-view.json', game.observe(1))):
        (output/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
