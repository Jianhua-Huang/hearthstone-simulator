"""A real Terran ship, Jim Raynor and Stimpack with player commands and replay."""
import json
from pathlib import Path

from hs_sim.engine import CardClass, EndTurn, Game, PlayCard, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def play(game, card_id, target=None):
    source = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == card_id)
    game.apply(PlayCard(1, source, target))


def command(game, kind, card_id=None):
    port = game.for_player(1)
    available = port.legal_actions()
    cards = {c['ref']: c['card_id'] for c in game.observe(1)['players'][0]['hand']}
    action = next(a for a in available['actions'] if a['type'] == kind and
                  (card_id is None or cards.get(a.get('card')) == card_id))
    assert port.submit({'revision': available['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hero_power_card_id='HERO_01bp', hand=('SC_411','SC_411','SC_400'),
                    board=('SC_403a','SC_403c'), deck=('SC_403t',)*4, max_mana=10, mana=10),
        PlayerSetup('HERO_08', deck=('CS2_182',)*4),
    ), seed=43), registry)
    for i in tuple(game.state.players[1].board):
        play(game, 'SC_411', i)
    command(game, 'launch_starship')
    game.apply(EndTurn(1)); game.apply(EndTurn(2))
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        command(match, 'play_card', 'SC_400')
        command(match, 'use_hero_power')
        assert match.state.players[1].hero_class == CardClass.WARRIOR
        assert len(match.state.starship_history) == 1
        assert sum(e.kind == 'starship_relaunched' for e in match.events) == 1
        assert len(match.state.players[1].board) == 3
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for name, data in (('raynor-ready-snapshot.json', snapshot), ('raynor-replay.json', build_replay(game)),
                       ('raynor-view.json', game.observe(1))):
        (output/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions':len(game.history), 'events':len(game.events), 'state_hash':game.state_hash(),
                     'restored_and_replayed':True}))


if __name__ == '__main__':
    main()
