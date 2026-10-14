"""Explicit Titan generation and two deferred Discover summons via player ports."""
import json
from pathlib import Path

from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def choose(game, card_id):
    port = game.for_player(1)
    listing = port.legal_actions()
    choice = listing['observation']['pending_choice']
    option = next(o['ref'] for o in choice['options'] if o['card_id'] == card_id)
    action = next(a for a in listing['actions']
                  if a['type'] == 'select_choice' and a['options'] == [option])
    assert port.submit({'revision': listing['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('WW_001t24', 'WW_001t27'), mana=10, max_mana=10),
        PlayerSetup('HERO_08')), seed=57,
        generation_context=GenerationContext('local-2026-09-23', 'experimental')), registry)
    submit(game, 'WW_001t24')
    titan = next(game.state.entities[i] for i in game.state.players[1].hand
                 if game.state.entities[i].card_id == 'TTN_903')
    assert titan.cost == 1
    submit(game, 'TTN_903')
    assert len([a for a in game.state.entities[titan.id].abilities if a.kind == 'activated']) == 3
    submit(game, 'WW_001t27')
    choose(game, 'TTN_724')
    assert len(game.state.players[1].board) == 3
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        choose(match, 'TTN_724')
        board = [match.state.entities[i] for i in match.state.players[1].board]
        giants = [c for c in board if c.card_id == 'TTN_724']
        assert len(board) == 5 and len(giants) == 2 and giants[0].id != giants[1].id
        assert match.state.players[1].mana == 1 and match.state.pending_choice is None
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    out = Path(__file__).resolve().parents[1] / 'outputs'
    out.mkdir(exist_ok=True)
    for name, value in (('generation-rewards-snapshot.json', snapshot),
                        ('generation-rewards-replay.json', build_replay(game)),
                        ('generation-rewards-view.json', game.observe(1))):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                     'state_hash': game.state_hash(), 'one_cost_titan': True,
                     'deferred_distinct_entities': True, 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
