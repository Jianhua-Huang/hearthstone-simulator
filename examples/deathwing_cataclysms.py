"""Real Heralds, persistent discount, four choices and a mid-Battlecry save."""
import json
from pathlib import Path

from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario, herald_count
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def choose(game, card_id):
    port = game.for_player(1)
    view = port.observe()
    choice = view['observation']['pending_choice']
    option = next(o for o in choice['options'] if o['card_id'] == card_id)
    assert port.submit({'revision': view['revision'], 'action': {
        'type': 'select_choice', 'choice': choice['ref'], 'options': [option['ref']]}})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('CATA_580', 'CATA_580', 'CATA_497', 'CATA_160', 'CATA_190h'),
                    deck=('CS2_182',)*8, max_mana=10, mana=10),
        PlayerSetup('HERO_08', board=('FP1_007', 'CS2_182'), deck=('CS2_182',)*8,
                    max_mana=10, mana=10)), seed=127,
        generation_context=GenerationContext('local-2026-09-23', 'experimental')), registry)
    submit(game, 'CATA_580'); submit(game, 'CATA_580'); submit(game); submit(game)
    submit(game, 'CATA_497'); submit(game, 'CATA_160'); submit(game); submit(game)
    assert herald_count(game.state, 1) == 4
    submit(game, 'CATA_190h')
    assert game.state.players[1].mana == 3
    choose(game, 'CATA_190t10'); choose(game, 'CATA_190t12')
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        choose(match, 'CATA_190t11'); choose(match, 'CATA_190t13')
        port = match.for_player(1); listing = port.legal_actions()
        action = next(a for a in listing['actions'] if a['type'] == 'use_hero_power')
        assert port.submit({'revision': listing['revision'], 'action': action})['accepted']
        state = match.state
        assert state.pending_choice is None
        assert len(state.players[1].board) == 7
        assert [(state.entities[i].card_id, state.entities[i].health)
                for i in state.players[2].board] == [('CS2_182', 1)]
        assert len(state.players[1].deck) == 11  # Two draws, then five generated Dragons.
        assert state.entities[state.players[1].hero_id].attack == 5 + state.entities[state.players[1].weapon_id].attack
        assert state.players[1].mana == 1
    assert restored.snapshot() == game.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    out = Path(__file__).resolve().parents[1] / 'outputs'
    for name, data in (('deathwing-snapshot.json', snapshot), ('deathwing-replay.json', build_replay(game)),
                       ('deathwing-view.json', game.observe(1))):
        (out/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
