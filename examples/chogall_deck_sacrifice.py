"""Cho'gall redirects both Arms, then removal restores ordinary sacrifices.

This is an explicit existing-state mechanics scenario, not a legal deck list.
"""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Resource, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit
from examples.herald_sacrifice import play_rightmost


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('CATA_726', 'CS2_182'), deck=('CS2_182',)*8, max_mana=10, mana=10),
        PlayerSetup('HERO_08', hand=('CS2_029',), deck=('FP1_007', 'ULD_205', 'CATA_190h', 'CS2_029'),
                    max_mana=10, mana=10)), seed=139), registry)
    submit(game, 'CATA_726'); submit(game)
    assert len([e for e in game.events if e.kind == 'card_destroyed_in_deck']) == 2
    assert not game.state.death_history
    assert [game.state.entities[i].attack for i in game.state.players[1].board] == [3, 6, 3]
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        submit(match, 'CS2_029', 'CATA_726'); submit(match)
        play_rightmost(match, 'CS2_182'); submit(match)
        state = match.state
        assert [(state.entities[i].card_id, state.entities[i].attack, state.entities[i].health)
                for i in state.players[1].board] == [('CATA_726t', 5, 5), ('CS2_182', 4, 5)]
        assert len(state.death_history) == 2  # Body, then right Arm; no deck deaths.
        assert state.players[1].resources[Resource.CORPSES] == 2
        assert state.players[2].resources[Resource.CORPSES] == 0
        assert not state.players[2].board
        assert len([e for e in match.events if e.kind == 'card_destroyed_in_deck']) == 2
        visible = [e for e in match.player_events(1) if e['kind'] == 'card_destroyed_in_deck']
        assert {e['target']['card_id'] for e in visible} == {'FP1_007', 'ULD_205'}
    assert restored.snapshot() == game.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    out = Path(__file__).resolve().parents[1] / 'outputs'
    for name, data in (('chogall-snapshot.json', snapshot), ('chogall-replay.json', build_replay(game)),
                       ('chogall-view.json', game.observe(1))):
        (out/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                     'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
