"""Snake integration: permanent maxima across turns, restore and terminal replay."""
import json
from pathlib import Path
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',
        hand=('WW_001t25',)*3,deck=('CS2_182',)*3,mana=10,max_mana=10),
        PlayerSetup('HERO_01',armor=99,deck=('CS2_182',)*3)),seed=59),registry)
    submit(game,'WW_001t25')
    submit(game,'WW_001t25')
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match)
        submit(match)
        submit(match,'WW_001t25')
        state=match.state
        own=state.entities[state.players[1].hero_id];enemy=state.entities[state.players[2].hero_id]
        assert (own.health,own.max_health,enemy.health,enemy.max_health,enemy.armor)==(60,60,0,0,99)
        assert state.status=='finished' and state.winner==1
        assert not any(e.kind in ('damage_dealt','healed','health_lost') for e in match.events)
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('health-transfer-snapshot.json',snapshot),('health-transfer-replay.json',build_replay(game)),
                       ('health-transfer-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
                      'winner':game.state.winner,'restored_and_replayed':True}))


if __name__=='__main__':main()
