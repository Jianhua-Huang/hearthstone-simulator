"""Save before Choose One, restore, choose branches, and verify both replays."""
import json
from pathlib import Path

from hs_sim.engine import Game, Scenario, PlayCard
from hs_sim.engine.actions import action_from_dict
from hs_sim.engine.replay import build_replay, replay, save_replay
from hs_sim.engine.representative import build_registry


def main():
    root = Path(__file__).resolve().parents[1]
    scenario = Scenario.from_dict(json.loads((root / 'examples/scenarios/choices.json').read_text(encoding='utf-8')))
    actions = json.loads((root / 'examples/actions/choices.json').read_text(encoding='utf-8'))
    game = Game.from_scenario(scenario, build_registry())
    snapshot = game.snapshot()
    save_replay(game, root / 'outputs/choices-ready-replay.json')
    destination = root / 'outputs/choices-ready-snapshot.json'
    destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert replay(build_replay(game), build_registry()).snapshot() == snapshot

    restored = Game.from_snapshot(json.loads(destination.read_text(encoding='utf-8')), build_registry())
    branch = restored.clone()
    branch.apply(PlayCard(1,branch.state.players[1].hand[0],branch_id='draw'))
    assert len(branch.state.players[1].hand) == 4
    assert branch.state.players[1].mana == 3
    save_replay(branch, root / 'outputs/choices-draw-branch-replay.json')
    assert replay(build_replay(branch), build_registry()).snapshot() == branch.snapshot()

    for raw in actions:
        action = action_from_dict(raw)
        game.apply(action)
        restored.apply(action)
    assert restored.snapshot() == game.snapshot()
    assert replay(build_replay(restored), build_registry()).snapshot() == restored.snapshot()
    save_replay(restored, root / 'outputs/choices-resumed-replay.json')
    print('Pre-play snapshot/replay, independent branch, restored sequence and replay: passed.')
    print(json.dumps({'actions': game.state.action_number, 'events': len(game.events),
                      'mana': game.state.players[1].mana, 'max_mana': game.state.players[1].max_mana,
                      'hand': len(game.state.players[1].hand), 'state_hash': game.state_hash()}, indent=2))


if __name__ == '__main__':
    main()
