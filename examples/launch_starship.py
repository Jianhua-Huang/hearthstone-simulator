"""Real Terran launch: four pieces, SCV discounts, fixed-seat command and replay."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayCard, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.starships import construction, launch_quote


def run():
    registry = build_registry()
    pieces = ('SC_403a', 'SC_403b', 'SC_403f', 'SC_405')
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', board=pieces, hand=('SC_401',) + ('SC_411',)*4,
                    max_mana=10, mana=10),
        PlayerSetup('HERO_01', board=('CS2_179',)),
    ), seed=41), registry)

    def play(card_id, target=None):
        hand = game.state.players[1].hand
        entity_id = next(i for i in hand if game.state.entities[i].card_id == card_id)
        game.apply(PlayCard(1, entity_id, target))

    play('SC_401')
    for card_id in pieces:
        target = next(i for i in game.state.players[1].board if game.state.entities[i].card_id == card_id)
        play('SC_411', target)
    ship = construction(game.state, 1)
    # SCV plus four Concussive Shells each reduce the next launch by two.
    assert launch_quote(game.state, ship).amount == 0
    assert (ship.attack, ship.health, ship.components) == (7, 4, pieces)
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        port = match.for_player(1)
        commands = port.legal_actions()
        action = next(a for a in commands['actions'] if a['type'] == 'launch_starship')
        assert port.submit({'revision': commands['revision'], 'action': action})['accepted']
    assert game.snapshot() == restored.snapshot()
    assert not game.state.players[1].cost_modifiers
    assert game.state.players[1].mana == 5
    assert game.state.entities[game.state.players[1].hero_id].armor == 13
    assert sum(game.state.entities[i].card_id == 'SC_403t' for i in game.state.players[1].board) == 2
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for filename, payload in (('terran-launch-snapshot.json', snapshot),
                              ('terran-launch-replay.json', build_replay(game)),
                              ('terran-launch-view.json', game.observe(1))):
        (output / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__': main()
