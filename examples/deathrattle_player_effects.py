"""Snowfall owner clock, end-boundary activations and expiry via player actions."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.deathrattles import activated_deathrattles
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit


def run():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_03',hand=('AV_400',),board=('CATA_150','CATA_150t','CATA_150t1'),deck=('CS2_182',)*12,mana=10,max_mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_182',)*12,mana=10,max_mana=10)),seed=97),build_registry())
    submit(game,'AV_400');submit(game)
    assert game.state.players[1].player_effects[0].remaining_turns==2
    assert len(activated_deathrattles(game.state,1,origin='effect'))==4
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        submit(match);submit(match)
        assert match.state.players[1].player_effects[0].remaining_turns==1
        submit(match);submit(match)
        assert not match.state.players[1].player_effects
        assert len(activated_deathrattles(match.state,1,origin='effect'))==12
        submit(match,'CS2_029','CATA_150t');submit(match);submit(match)
        rows=activated_deathrattles(match.state,1)
        assert len(rows)==14 and all(d.completed for d in rows)
        assert [b.plan.repetitions for b in match.state.deathrattle_batches]==[2]*6+[1,1]
        assert [b.plan.contributors[0].instance.remaining_turns for b in match.state.deathrattle_batches[:6]]==[3,3,2,2,1,1]
        assert len(match.state.death_history)==1
        assert match.state.entities[match.state.players[2].hero_id].health==2
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('deathrattle-player-snapshot.json',snapshot),('deathrattle-player-replay.json',build_replay(game)),
                      ('deathrattle-player-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        activations=14,batches=8,effect_triggers=13,natural_triggers=1,deaths=1,enemy_health=2,
        remaining_player_effects=0,restored_and_replayed=True)))


if __name__=='__main__':main()
