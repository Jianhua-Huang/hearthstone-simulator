"""Two explicitly experimental 30-card decks, opening through terminal replay."""
import json
from pathlib import Path

from hs_sim.engine import Game, MatchSetup, SelectChoice
from hs_sim.engine.cli import choose_demo_action, summary
from hs_sim.engine.replay import build_replay, replay, save_replay
from hs_sim.engine.representative import build_registry


def play_match():
    root = Path(__file__).resolve().parents[1]
    config = MatchSetup.from_dict(json.loads((root / 'examples/matches/constructed.json').read_text(encoding='utf-8')))
    game = Game.from_decks(config, build_registry())
    # Restore while waiting for the first mulligan, using ordinary JSON only.
    game = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), build_registry())
    for _ in range(500):
        if game.state.status != 'playing':
            break
        choice = game.state.pending_choice
        if choice is not None:
            action = SelectChoice(choice.player_id, choice.id, tuple(o.id for o in choice.options[::2]))
        else:
            action = choose_demo_action(game)
        game.apply(action)
    if game.state.status == 'playing':
        raise RuntimeError('The demonstration reached its action limit before game end')
    assert replay(build_replay(game), build_registry()).snapshot() == game.snapshot()
    return game


def main():
    game = play_match()
    root = Path(__file__).resolve().parents[1]
    save_replay(game, root / 'outputs/constructed-complete-replay.json')
    print('Experimental deck validation, mulligans, full match and replay: passed.')
    print(json.dumps(summary(game), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
