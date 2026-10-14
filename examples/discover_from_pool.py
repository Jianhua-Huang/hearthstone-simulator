"""Experimental Jeweled Scarab: player DTOs, saved offers, branch and replay."""
import json
from pathlib import Path

from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay, save_replay


def submit_first(game, kind):
    port = game.for_player(1)
    available = port.legal_actions()
    action = next(a for a in available['actions'] if a['type'] == kind)
    result = port.submit({'revision': available['revision'], 'action': action})
    assert result['accepted'], result['error']


def main():
    output = Path(__file__).resolve().parents[1] / 'outputs'
    output.mkdir(exist_ok=True)
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('LOE_029',), mana=3, max_mana=3),
        PlayerSetup('HERO_01'),
    ), seed=29, generation_context=GenerationContext('local-2026-09-23', 'experimental')), registry)
    submit_first(game, 'play_card')
    pending = game.snapshot()
    destination = output / 'discover-pending-snapshot.json'
    destination.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save_replay(game, output / 'discover-pending-replay.json')
    assert replay(build_replay(game), build_registry()).snapshot() == pending
    offers = game.observe(1)['pending_choice']['options']
    assert game.observe(2)['pending_choice'] == {'player_id': 1}
    restored = Game.from_snapshot(json.loads(destination.read_text('utf-8')), build_registry())
    assert restored.observe(1) == game.observe(1)
    branch = restored.clone()
    available = branch.for_player(1).legal_actions()
    assert branch.for_player(1).submit({'revision': available['revision'], 'action': available['actions'][-1]})['accepted']
    assert replay(build_replay(branch), build_registry()).snapshot() == branch.snapshot()
    save_replay(branch, output / 'discover-alternate-replay.json')
    for match in (game, restored): submit_first(match, 'select_choice')
    assert game.snapshot() == restored.snapshot()
    assert game.snapshot()['rng_state'] == pending['rng_state']
    assert replay(build_replay(game), build_registry()).snapshot() == game.snapshot()
    assert game.observe(2)['players'][0]['hand'][0]['card_id'] is None
    save_replay(game, output / 'discover-complete-replay.json')
    print(json.dumps({'sample_pool': 'representative-generation-v1', 'formal_pool_complete': False,
        'offered_cards': [o['card_id'] for o in offers], 'hand': game.observe(1)['players'][0]['hand'][0]['card_id'],
        'actions': game.state.action_number, 'events': len(game.events), 'state_hash': game.state_hash()}, indent=2))


if __name__ == '__main__':
    main()
