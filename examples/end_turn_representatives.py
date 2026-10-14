"""Necessary real sources on a public scenario; not a legal constructed deck."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario, Zone
from hs_sim.engine.end_turns import activated_end_turns
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_04', board=('BOT_107',), hand=('ICC_901', 'CATA_480'),
                    deck=('CS2_182',) * 8, mana=10, max_mana=10),
        PlayerSetup('HERO_08', deck=('CS2_182',) * 8)), seed=145), build_registry())
    submit(game, 'ICC_901')
    submit(game, 'CATA_480')
    assert game.state.players[1].mana == 4
    icc_id = next(i for i in game.state.players[1].board
                  if game.state.entities[i].card_id == 'ICC_901')
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), build_registry())
    for match in (game, restored):
        owner_checks = []
        for _ in range(7):
            owner = match.state.active_player
            submit(match)
            if owner == 1:
                state = match.state
                effects = [e for e in state.players[1].player_effects
                           if e.spec_id == 'm5.sandfury_aura']
                owner_checks.append((state.entities[icc_id].health,
                                     effects[0].remaining_turns if effects else None))
        state = match.state
        records = activated_end_turns(state, 1, completed=True)
        assert [batch.total for batch in state.end_turn_batches] == [2, 0, 2, 0, 2, 0, 1]
        assert all(batch.completed for batch in state.end_turn_batches)
        assert len(records) == 7 and len(state.end_turn_history) == 7
        assert [row.capture.repeat_index for row in records] == [0, 1, 0, 1, 0, 1, 0]
        assert [row.execution_order for row in records] == list(range(1, 8))
        assert all(row.capture.subject.card_id == 'BOT_107' for row in records)
        for batch in state.end_turn_batches[:5:2]:
            plan = batch.plans[0]
            assert plan.repetitions == 2
            assert {source.card_id for source in plan.contributors} == {'ICC_901', 'CATA_480'}
            assert len(plan.contributors) == 2
        assert not state.end_turn_batches[-1].plans[0].contributors
        assert owner_checks[:2] == [(3, 2), (1, 1)]
        assert owner_checks[2:] == [(0, None), (0, None)]
        assert state.entities[icc_id].zone == Zone.GRAVEYARD
        assert [row.card_id for row in state.death_history] == ['ICC_901']
        assert not state.players[1].player_effects
        assert [state.entities[p.hero_id].health for p in state.players.values()] == [23, 23]
        assert [state.entities[i].card_id for i in state.players[1].board] == ['BOT_107']
        assert state.entities[state.players[1].board[0]].health == 4
        assert sum(e.kind == 'card_played' for e in match.events) == 2
        assert sum(e.kind == 'player_effect_added' for e in match.events) == 1
        assert sum(e.kind == 'player_effect_ticked' for e in match.events) == 2
        assert sum(e.kind == 'player_effect_expired' for e in match.events) == 1
        assert sum(e.kind == 'turn_ended' for e in match.events) == 7
        assert sum(e.kind == 'turn_started' for e in match.events) == 7
        assert sum(e.kind == 'card_drawn' for e in match.events) == 7
        assert state.turn == 8 and state.active_player == 2
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), build_registry()).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    for name, value in (('end-turn-representatives-snapshot.json', snapshot),
                        ('end-turn-representatives-replay.json', build_replay(game)),
                        ('end-turn-representatives-view.json', game.observe(1))):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                      'end_turn_batches': len(game.state.end_turn_batches),
                      'end_turn_activations': len(game.state.end_turn_history),
                      'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__':
    main()
