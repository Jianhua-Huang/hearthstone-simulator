"""Two real Heralds, upgraded Colossal appendages and forced deathrattles."""
import json
from pathlib import Path
from hs_sim.engine import Game, PlayerSetup, Scenario, herald_count
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',hand=('CATA_580','CATA_580','CATA_150'),deck=('CS2_182',)*10,max_mana=10,mana=10),
        PlayerSetup('HERO_08',deck=('CS2_182',)*10,max_mana=10,mana=10)),seed=119),registry)
    submit(game,'CATA_580');submit(game,'CATA_580')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match);submit(match);submit(match,'CATA_150');submit(match)
        state=match.state
        assert herald_count(state,1)==2
        assert [state.entities[r.soldier_id].attack for r in state.herald_history]==[2,2]
        assert [state.entities[i].attack for i in state.colossal_history[0].limbs]==[4,4]
        assert state.entities[state.players[2].hero_id].health==18
        assert len(state.death_history)==1  # Replaced first weapon, no minion deaths.
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs';out.mkdir(exist_ok=True)
    for name,data in (('herald-snapshot.json',snapshot),('herald-replay.json',build_replay(game)),('herald-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
