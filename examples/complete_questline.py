"""Real Druid questline and Shapeshift, in an explicit mechanism scenario."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def command(game, kind, card_id=None):
    port = game.for_player(game.state.active_player)
    listing = port.legal_actions()
    refs = {card['ref']: card['card_id'] for player in listing['observation']['players'] for card in player['hand']}
    action = next(a for a in listing['actions'] if a['type'] == kind and
                  (card_id is None or refs.get(a.get('card')) == card_id))
    assert port.submit({'revision': listing['revision'], 'action': action})['accepted']


def cycle(game):
    command(game, 'end_turn'); command(game, 'end_turn')


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('test.hero', hero_power_card_id='HERO_06bp', hand=('SW_428',),
                    deck=('CS2_182',)*30, mana=10, max_mana=10),
        PlayerSetup('test.hero', deck=('CS2_182',)*30)), seed=94), registry)
    command(game, 'play_card', 'SW_428')
    for index in range(4):
        if index: cycle(game)
        command(game, 'use_hero_power')
    quest = game.state.entities[game.state.players[1].quests[0]]
    assert (quest.quest_progress.stage, quest.quest_progress.value) == (1, 0)
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        for index in range(11):
            if index == 10:
                # Leave room for the next natural draw and the final reward.
                command(match, 'play_card', 'CS2_182')
                command(match, 'play_card', 'CS2_182')
            cycle(match); command(match, 'use_hero_power')
        assert not match.state.players[1].quests
        command(match, 'play_card', 'SW_428t4')
        hero = match.state.entities[match.state.players[1].hero_id]
        assert (hero.attack, hero.armor) == (9, 33)
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    for filename, data in (('questline-snapshot.json', snapshot), ('questline-replay.json', build_replay(game)),
                           ('questline-view.json', game.observe(1))):
        (output/filename).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                     'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
