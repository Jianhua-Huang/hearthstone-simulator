"""Accepted end-turn bodies survive a preceding source death; clocks run once."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.end_turns import activated_end_turns
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def run():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',board=('CATA_725t','BOT_107'),deck=('CS2_182',)*3),
        PlayerSetup('HERO_08',board=('CS2_182',),deck=('CS2_182',)*3)),seed=142),build_registry())
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        submit(match);submit(match)
        state=match.state;subjects=activated_end_turns(state,1,completed=True)
        assert [len(b.subjects) for b in state.end_turn_batches]==[2,0]
        assert all(b.completed for b in state.end_turn_batches)
        assert [row.capture.subject.card_id for row in subjects]==['CATA_725t','BOT_107']
        assert [row.execution_order for row in subjects]==[1,2]
        assert all(row.capture.subject.spec.turn_scope=='controller' for row in subjects)
        assert not activated_end_turns(state,2)
        assert [d.card_id for d in state.death_history]==['BOT_107']
        assert len(state.players[1].board)==1
        assert all(state.entities[p.hero_id].health==29 for p in state.players.values())
        assert sum(e.kind=='turn_ended' for e in match.events)==2
        assert sum(e.kind=='turn_started' for e in match.events)==2
        assert sum(e.kind=='card_drawn' for e in match.events)==2
        assert state.turn==3 and state.active_player==1
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('end-turn-subjects-snapshot.json',snapshot),
                       ('end-turn-subjects-replay.json',build_replay(game)),
                       ('end-turn-subjects-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),
        'end_turn_batches':len(game.state.end_turn_batches),
        'end_turn_activations':len(game.state.end_turn_history),
        'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__': main()
