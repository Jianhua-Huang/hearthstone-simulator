"""Starport cooldown and last use feed a real, replayable Terran Starship."""
import json
from pathlib import Path

from hs_sim.engine import CardType, EndTurn, Game, PlayCard, PlayerSetup, Scenario
from hs_sim.engine.model import Resource
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starships import construction


def play(game, card_id, target=None):
    source = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == card_id)
    game.apply(PlayCard(1, source, target))


def command(game, kind):
    port = game.for_player(1); available = port.legal_actions()
    action = next(a for a in available['actions'] if a['type'] == kind)
    assert port.submit({'revision': available['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('SC_403',)+('SC_411',)*3, board=('SC_403c',),
                    deck=('SC_403t',)*4, max_mana=10, mana=10),
        PlayerSetup('HERO_01', deck=('CS2_182',)*4),
    ), seed=11), registry)
    play(game, 'SC_403'); command(game, 'use_location')
    for i in tuple(game.state.players[1].board):
        if game.state.entities[i].kind == CardType.MINION:
            play(game, 'SC_411', i)
    for _ in range(2):
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        command(match, 'use_location')
        target = next(i for i in match.state.players[1].board if not match.state.entities[i].starship_building)
        play(match, 'SC_411', target)
        assert len(construction(match.state, 1).components) == 3
        command(match, 'launch_starship')
        assert match.state.players[1].resources[Resource.CORPSES] == 3
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for name, data in (('starport-ready-snapshot.json', snapshot), ('starport-replay.json', build_replay(game)),
                       ('starport-view.json', game.observe(1))):
        (output/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions':len(game.history), 'events':len(game.events), 'state_hash':game.state_hash(),
                      'restored_and_replayed':True}))


if __name__ == '__main__': main()
