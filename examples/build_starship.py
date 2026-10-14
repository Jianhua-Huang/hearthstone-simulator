"""Construct, restore, launch and destroy a Starship using real card adapters."""
import json
from pathlib import Path

from hs_sim.engine import EndTurn, Game, LaunchStarship, PlayCard, PlayerSetup, Scenario, UseHeroPower
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.starships import construction


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', board=('GDB_100', 'GDB_101', 'GDB_109', 'GDB_111'),
                    hand=('CS2_024', 'CS2_024', 'CS2_029', 'CS2_029'), max_mana=10, mana=10),
        PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=('CS2_029', 'CS2_029'), max_mana=10, mana=10),
    ), seed=41), registry)

    def board(card_id):
        return next(i for i in game.state.players[1].board if game.state.entities[i].card_id == card_id)

    def card(player, card_id, target):
        i = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == card_id)
        return PlayCard(player, i, target)

    game.apply(card(1, 'CS2_024', board('GDB_111')))
    game.apply(card(1, 'CS2_024', board('GDB_109')))
    game.apply(card(1, 'CS2_029', board('GDB_100')))
    game.apply(UseHeroPower(1, game.state.players[1].hero_power_id, board('GDB_101')))
    game.apply(EndTurn(1)); game.apply(EndTurn(2))
    game.apply(card(1, 'CS2_029', board('GDB_101')))
    building_snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(building_snapshot)), registry)
    ship = construction(game.state, 1)
    assert (ship.attack, ship.health, len(ship.components)) == (10, 10, 4)

    def both(action):
        game.apply(action); restored.apply(action)
        assert game.snapshot() == restored.snapshot()

    both(LaunchStarship(1, ship.id))
    both(EndTurn(1))
    both(UseHeroPower(2, game.state.players[2].hero_power_id, ship.id))
    both(card(2, 'CS2_029', ship.id)); both(card(2, 'CS2_029', ship.id))
    assert game.state.entities[ship.id].zone.value == 'graveyard'
    assert game.state.entities[game.state.players[2].hero_id].health == 15
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, building_snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for filename, payload in (('starship-building-snapshot.json', snapshot),
                              ('starship-complete-replay.json', build_replay(game)),
                              ('starship-player-view.json', game.observe(1))):
        (output / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'components': 4, 'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
