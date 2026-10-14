"""Native representative scenario separating effect-triggered and natural deaths."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.deathrattles import activated_deathrattles
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit


def run():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',board=('CATA_150','CATA_150t','CATA_150t1'),deck=('CS2_182',)*8,mana=10,max_mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_182',)*8,mana=10,max_mana=10)),seed=95),build_registry())
    submit(game)
    assert len(activated_deathrattles(game.state,1,origin='effect'))==2
    assert not game.state.death_history
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        submit(match,'CS2_029','CATA_150t');submit(match);submit(match)
        rows=activated_deathrattles(match.state,1)
        assert len(rows)==4 and all(d.completed for d in rows)
        assert [d.capture.origin for d in rows]==['effect','effect','death','effect']
        assert all(d.capture.trigger_source_card_id=='CATA_150' for d in rows if d.capture.origin=='effect')
        assert len(match.state.death_history)==1
        assert match.state.entities[match.state.players[2].hero_id].health==22
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('deathrattle-activation-snapshot.json',snapshot),('deathrattle-activation-replay.json',build_replay(game)),
                      ('deathrattle-activation-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        activations=4,effect_triggers=3,natural_triggers=1,deaths=1,restored_and_replayed=True)))


if __name__=='__main__':main()
