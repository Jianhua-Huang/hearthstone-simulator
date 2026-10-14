"""DK Imbue first-Undead trigger, midturn save, growth and next-turn reset."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit


def run():
    registry=build_registry()
    # A mechanism scenario: the unadapted default Ghoul Charge is not substituted.
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_11',
        hand=('EDR_852','ULD_205','EDR_852','ULD_205'),deck=('ULD_205',)*3,mana=10,max_mana=10),
        PlayerSetup('HERO_01',deck=('CS2_182',)*3)),seed=63),registry)
    submit(game,'EDR_852');submit(game,'ULD_205');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'EDR_852');submit(match,'ULD_205');submit(match);submit(match);submit(match,'ULD_205')
        base=registry.card('ULD_205').attack
        played=[p.source_id for p in match.state.play_history if p.card_id=='ULD_205']
        assert [match.state.entities[i].attack for i in played]==[base+1,base,base+2]
        assert not match.state.hero_power_history
        assert not any(a['type']=='use_hero_power' for a in match.for_player(1).legal_actions()['actions'])
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('passive-power-snapshot.json',snapshot),('passive-power-replay.json',build_replay(game)),
                       ('passive-power-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
