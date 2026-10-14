"""Yodeler/Brann/Baron/Snowfall composition with genuine starship deaths."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.deathrattles import activated_deathrattles
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.starships import construction
from examples.colossal_appendages import submit


def run():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_03',hand=('AV_400','JAM_005'),board=('GDB_100','FP1_031','LOE_077'),deck=('CS2_182',)*10,mana=10,max_mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029','CS2_029'),deck=('CS2_182',)*10,mana=10,max_mana=10)),seed=98),build_registry())
    submit(game,'AV_400');snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        submit(match,'JAM_005','GDB_100')
        hero=match.state.players[1].hero_id
        assert match.state.entities[hero].armor==32
        assert len(activated_deathrattles(match.state,1,origin='effect'))==8
        assert not match.state.death_history and construction(match.state,1) is None
        submit(match);submit(match,'CS2_029','GDB_100');submit(match)
        ship=construction(match.state,1);assert ship.components==('GDB_100',)
        ship_id=ship.id;ship_card=match.state.entities[ship_id].card_id
        port=match.for_player(1);commands=port.legal_actions();action=next(a for a in commands['actions'] if a['type']=='launch_starship')
        assert port.submit({'revision':commands['revision'],'action':action})['accepted']
        submit(match);submit(match,'CS2_029',ship_card);submit(match)
        rows=activated_deathrattles(match.state,1)
        assert len(rows)==12 and all(d.completed for d in rows)
        assert [b.trigger_count for b in match.state.deathrattle_batches]==[2,2,1,1]
        assert all(b.plan.repetitions==2 for b in match.state.deathrattle_batches)
        assert len(match.state.death_history)==2 and match.state.entities[hero].armor==48
        assert sum(d.capture.carrier_id==ship_id for d in rows)==2
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('fixed-deathrattle-snapshot.json',snapshot),('fixed-deathrattle-replay.json',build_replay(game)),
                      ('fixed-deathrattle-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        activations=12,batches=4,effect_triggers=8,natural_triggers=4,deaths=2,armor=48,
        starship_components=1,restored_and_replayed=True)))


if __name__=='__main__':main()
