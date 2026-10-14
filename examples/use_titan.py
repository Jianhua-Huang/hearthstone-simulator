"""All three Eonar abilities using player commands, with mid-cycle restore."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def command(game, kind, ability_id=None):
    port = game.for_player(game.state.active_player)
    available = port.legal_actions()
    action = next(a for a in available['actions'] if a['type'] == kind and
                  (ability_id is None or a.get('ability_id') == ability_id))
    assert port.submit({'revision': available['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('TTN_903',), deck=('CS2_182',)*16, mana=10, max_mana=10),
        PlayerSetup('HERO_08', deck=('CS2_182',)*8),
    ), seed=83), registry)
    command(game, 'play_card')
    command(game, 'use_minion_ability', 'TTN_903t3')
    assert game.state.players[1].mana == 10
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        for ability in ('TTN_903t', 'TTN_903t2'):
            command(match, 'end_turn'); command(match, 'end_turn')
            command(match, 'use_minion_ability', ability)
        assert len(match.state.players[1].board) == 4
        source = match.state.entities[match.state.players[1].board[0]]
        assert all(a.consumed for a in source.abilities if a.kind == 'activated')
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for name, data in (('titan-snapshot.json', snapshot), ('titan-replay.json', build_replay(game)),
                       ('titan-view.json', game.observe(1))):
        (output/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
