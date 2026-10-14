"""Morchie, Sands of Time and Portal through player choices and saved results."""
import json
from pathlib import Path

from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def choose(game):
    port=game.for_player(1);listing=port.legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='select_choice')
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_08',hand=('END_036','TIME_EVENT_999'),max_mana=10,mana=10),
        PlayerSetup('HERO_01')),seed=53,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'END_036');choose(game);submit(game,'TIME_EVENT_999');choose(game)
    # The first discovered spell is already retained while the second waits.
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert len(match.state.players[1].hand)==2
        choose(match);submit(match,'TIME_000')
        assert match.state.pending_choice is None
        assert len(match.state.players[1].hand)==4
        assert match.state.players[1].mana==3
        assert len(match.state.play_history)==3
        assert len(match.state.cast_history)==2
        assert len(match.state.rewind_outcomes)==2
        assert all(r.finished and r.completed==2 for r in match.state.rewind_outcomes)
        assert not any(e.kind=='timeline_rewound' for e in match.events)
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs';out.mkdir(exist_ok=True)
    for name,value in (('morchie-snapshot.json',snapshot),('morchie-replay.json',build_replay(game)),
                       ('morchie-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'retained_outcomes':sum(r.completed for r in game.state.rewind_outcomes),'restored_and_replayed':True}))


if __name__=='__main__':main()
