"""Export player DTOs from a trusted host; never export its snapshot to a player."""
import json
from pathlib import Path

from hs_sim.engine import Game, MatchSetup, SelectChoice
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry


def main():
    root = Path(__file__).resolve().parents[1]
    config = MatchSetup.from_dict(json.loads((root / 'examples/matches/constructed.json').read_text(encoding='utf-8')))
    game = Game.from_decks(config, build_registry())
    exports = {viewer: [] for viewer in (1, 2)}

    def capture():
        for viewer in (1, 2):
            cursor = exports[viewer][-1]['observation']['event_cursor'] if exports[viewer] else 0
            exports[viewer].append({'observation': game.observe(viewer), 'events': game.player_events(viewer, after=cursor)})

    capture()
    while game.state.pending_choice is not None:
        # This example focuses on observation using a trusted host driver.
        # play_as_players demonstrates the restricted command API; never send
        # the host's legal_actions() or ActionResult to a player.
        pending = game.state.pending_choice
        game.apply(SelectChoice(pending.player_id, pending.id, (pending.options[0].id,)))
        capture()
    restored = replay(build_replay(game), build_registry())
    for viewer in (1, 2):
        assert restored.observe(viewer) == game.observe(viewer)
        assert restored.player_events(viewer) == game.player_events(viewer)
        destination = root / f'outputs/player-{viewer}-observations.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(exports[viewer], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Player {viewer}: {len(exports[viewer])} boundaries, {len(game.player_events(viewer))} filtered events.')
    print('Event-time player observations and replay: passed.')


if __name__ == '__main__':
    main()
