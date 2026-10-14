"""Real Terran draw, full token list, Raven construction and replayable launch."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayCard, PlayerSetup, Scenario
from hs_sim.engine.bonus_effects import BONUS_EFFECTS
from hs_sim.engine.representative import build_registry, TERRAN_LAUNCH_PIECES
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starships import construction


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('SC_410',)+('SC_411',)*3,
                    deck=('SC_403t','SC_401'), board=('SC_403c','SC_403a'), max_mana=10, mana=10),
        PlayerSetup('HERO_01'),
    ), seed=11), registry)

    def play(card_id, target=None):
        entity = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == card_id)
        game.apply(PlayCard(1, entity, target))

    play('SC_410')
    generated = game.state.entities[game.state.players[1].board[-1]].card_id
    assert generated in TERRAN_LAUNCH_PIECES
    assert {game.state.entities[i].card_id for i in game.state.players[1].hand} == {'SC_411','SC_403t','SC_401'}
    for entity_id in tuple(game.state.players[1].board):
        play('SC_411', entity_id)
    ship_id = construction(game.state, 1).id
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        port = match.for_player(1); commands = port.legal_actions()
        action = next(a for a in commands['actions'] if a['type'] == 'launch_starship')
        assert port.submit({'revision': commands['revision'], 'action': action})['accepted']
    assert game.snapshot() == restored.snapshot()
    assert len(game.state.entities[ship_id].keywords.intersection(BONUS_EFFECTS)) >= 2
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for name, data in (('raven-pending-launch.json',snapshot), ('raven-replay.json',build_replay(game)),
                       ('raven-player-view.json',game.observe(1))):
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
                      'restored_and_replayed':True}))


if __name__ == '__main__': main()
