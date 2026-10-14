"""Current hand copies, a private deck choice and discard, using player commands."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay, save_replay


def play(game, card_id, *, target_hero=False):
    port = game.for_player(1)
    choices = port.legal_actions()
    own, opponent = choices['observation']['players']
    card = next(c['ref'] for c in own['hand'] if c['card_id'] == card_id)
    action = next(a for a in choices['actions'] if a['type'] == 'play_card' and a['card'] == card
        and (not target_hero or a.get('target') == opponent['hero']['ref']))
    result = port.submit({'revision': choices['revision'], 'action': action})
    assert result['accepted'], result['error']


def choose(game):
    port = game.for_player(1)
    choices = port.legal_actions()
    assert port.submit({'revision': choices['revision'], 'action': choices['actions'][0]})['accepted']


def main():
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('ICC_091', 'UNG_029', 'EX1_308', 'CS2_029'),
                    deck=('CS2_179', 'CS2_024'), mana=10, max_mana=10),
        PlayerSetup('HERO_01'),
    ), seed=29, name='experimental cross-class zone operations'), build_registry())
    play(game, 'ICC_091')
    assert len(game.state.players[1].deck) == 5
    play(game, 'UNG_029')
    pending = game.snapshot()
    (output / 'zones-pending-snapshot.json').write_text(json.dumps(pending, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save_replay(game, output / 'zones-pending-replay.json')
    assert replay(build_replay(game), build_registry()).snapshot() == pending
    restored = Game.from_snapshot(json.loads(json.dumps(pending)), build_registry())
    offered = [o['card_id'] for o in game.observe(1)['pending_choice']['options']]
    assert game.observe(2)['pending_choice'] == {'player_id': 1}
    for branch in (game, restored):
        choose(branch)
        play(branch, 'EX1_308', target_hero=True)
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), build_registry()).snapshot() == game.snapshot()
    save_replay(game, output / 'zones-complete-replay.json')
    print(json.dumps({'actions': game.state.action_number, 'events': len(game.events),
        'offered': offered, 'hand_count': len(game.state.players[1].hand), 'deck_count': len(game.state.players[1].deck),
        'mana': game.state.players[1].mana, 'enemy_health': game.state.entities[game.state.players[2].hero_id].health,
        'discarded': [game.state.entities[e.target_id].card_id for e in game.events if e.kind == 'card_discarded'],
        'state_hash': game.state_hash()}, indent=2))


if __name__ == '__main__':
    main()
