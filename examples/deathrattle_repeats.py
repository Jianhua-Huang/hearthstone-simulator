"""Native Baron/Ragnaros composition with natural and effect-triggered repeats."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.deathrattles import activated_deathrattles
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit


def run():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',board=('CATA_150','CATA_150t','CATA_150t1','FP1_031'),deck=('CS2_182',)*8,mana=10,max_mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_182',)*8,mana=10,max_mana=10)),seed=96),build_registry())
    submit(game)
    assert len(activated_deathrattles(game.state,1,origin='effect'))==4
    assert not game.state.death_history
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        submit(match,'CS2_029','CATA_150t');submit(match);submit(match)
        rows=activated_deathrattles(match.state,1)
        assert len(rows)==8 and all(d.completed for d in rows)
        assert [d.capture.repeat_index for d in rows]==[1,2]*4
        assert len(match.state.deathrattle_batches)==4
        assert all(b.plan.repetitions==2 and b.plan.contributors[0].card_id=='FP1_031' for b in match.state.deathrattle_batches)
        assert len(match.state.death_history)==1
        assert match.state.entities[match.state.players[2].hero_id].health==14
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('deathrattle-repeat-snapshot.json',snapshot),('deathrattle-repeat-replay.json',build_replay(game)),
                      ('deathrattle-repeat-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        activations=8,batches=4,effect_triggers=6,natural_triggers=2,deaths=1,enemy_health=14,restored_and_replayed=True)))


if __name__=='__main__':main()
