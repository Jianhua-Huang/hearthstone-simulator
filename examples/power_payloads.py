"""Existing Wisprider and mage power: one root and one ability per activation."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.power_payloads import activated_power_payloads
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit
from examples.imbue_growth import use_power


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('EDR_519',), hero_power_card_id='HERO_08bp',
                    mana=10, max_mana=10),
        PlayerSetup('HERO_01')), seed=61), registry)
    submit(game, 'EDR_519')
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), build_registry())
    for match in (game, restored):
        use_power(match)
        roots = match.state.hero_power_history
        subjects = activated_power_payloads(match.state, 1, completed=True)
        assert [p.origin for p in roots] == ['effect', 'manual']
        assert [p.capture.power_id for p in subjects] == [1, 2]
        assert [p.execution_order for p in subjects] == [1, 2]
        assert all(len(p.payloads) == 1 for p in roots)
        assert all(p.capture.ability == roots[p.capture.power_id-1].payloads[0] for p in subjects)
        assert len(match.state.hero_power_payload_batches) == 2
        assert match.state.players[1].hero_power_uses_this_turn == 1
        assert match.state.players[1].mana == 3
        assert match.state.entities[match.state.players[2].hero_id].health == 28
        assert sum(e.kind == 'hero_power_triggered' for e in match.events) == 1
        assert sum(e.kind == 'hero_power_used' for e in match.events) == 1
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), build_registry()).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    out = Path(__file__).resolve().parents[1] / 'outputs'
    for name, value in (
            ('power-payloads-snapshot.json', snapshot),
            ('power-payloads-replay.json', build_replay(game)),
            ('power-payloads-view.json', game.observe(1))):
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'root_activations': len(game.state.hero_power_history),
        'payload_batches': len(game.state.hero_power_payload_batches),
        'payload_activations': len(game.state.hero_power_payload_history),
        'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__': main()
