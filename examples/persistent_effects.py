"""Player commands: Dawngrasp dies, Bridge buffs, Sigil resolves, Bridge expires."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def command(game, kind, card_id=None, target_card=None):
    port = game.for_player(game.state.active_player)
    listing = port.legal_actions()
    cards = {c['ref']: c['card_id'] for p in listing['observation']['players']
             for c in (*p['hand'], *p['board']) if 'card_id' in c}
    action = next(a for a in listing['actions'] if a['type'] == kind and
                  (card_id is None or cards.get(a.get('card')) == card_id) and
                  (target_card is None or cards.get(a.get('target')) == target_card))
    assert port.submit({'revision': listing['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('SW_450t4', 'AV_344', 'BAR_306', 'CS2_182'),
                    deck=('CS2_182',)*10, mana=10, max_mana=10),
        PlayerSetup('HERO_08', hand=('CS2_029',)*2, board=('CS2_182',),
                    deck=('CS2_182',)*10, mana=10, max_mana=10)), seed=95), registry)
    command(game, 'play_card', 'SW_450t4')
    command(game, 'play_card', 'AV_344')
    command(game, 'end_turn')
    for _ in range(2):
        command(game, 'play_card', 'CS2_029', 'SW_450t4')
    command(game, 'end_turn')
    command(game, 'play_card', 'BAR_306')
    command(game, 'play_card', 'CS2_182')
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        command(match, 'end_turn'); command(match, 'end_turn')
        assert not match.state.players[2].board
        yeti = match.state.entities[match.state.players[1].board[0]]
        assert (yeti.attack, yeti.health) == (6, 1)
        command(match, 'end_turn'); command(match, 'end_turn')
        assert [e.spec_id for e in match.state.players[1].player_effects] == ['m4.dawngrasp']
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for filename, data in (('player-effects-snapshot.json', snapshot),
                           ('player-effects-replay.json', build_replay(game)),
                           ('player-effects-view.json', game.observe(1))):
        (output/filename).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                     'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
