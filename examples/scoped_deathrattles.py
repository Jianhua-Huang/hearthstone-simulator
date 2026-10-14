"""Granted-only self repeats, mixed neighbor payloads and board capacity."""
import json
from pathlib import Path
from hs_sim.engine import Game,Scenario,PlayerSetup
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.deathrattles import activated_deathrattles
from examples.colossal_appendages import submit


def run():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_06',hand=('EX1_158','JAM_005'),board=('RLK_912','EX1_096'),deck=('CS2_182',)*10,mana=10,max_mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029','CS2_029'),deck=('CS2_182',)*10,mana=10,max_mana=10)),seed=99),build_registry())
    submit(game,'EX1_158');snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        submit(match,'JAM_005','RLK_912')
        assert len(activated_deathrattles(match.state,1,origin='effect'))==4 and not match.state.death_history
        assert len(match.state.players[1].board)==7
        submit(match);submit(match,'CS2_029','RLK_912');submit(match,'CS2_029','EX1_096');submit(match)
        rows=activated_deathrattles(match.state,1);assert len(rows)==8 and all(d.completed for d in rows)
        assert [b.trigger_count for b in match.state.deathrattle_batches]==[2,1,1]
        assert [[p.plan.repetitions for p in b.payloads] for b in match.state.deathrattle_batches]==[[2],[2],[1,1]]
        assert len(match.state.death_history)==2
        cards=[match.state.entities[i].card_id for i in match.state.players[1].board]
        assert cards.count('EX1_158t')==6 and cards.count('JAM_005')==1
        assert len(match.state.players[1].hand)==2
    assert game.snapshot()==restored.snapshot();assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('scoped-deathrattle-snapshot.json',snapshot),('scoped-deathrattle-replay.json',build_replay(game)),('scoped-deathrattle-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),activations=8,batches=3,
        effect_triggers=4,natural_triggers=4,deaths=2,treants=6,hand=2,restored_and_replayed=True)))


if __name__=='__main__':main()
