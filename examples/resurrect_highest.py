"""Azerite Rat: highest-cost death, guarded enhancement, then dynamic Reborn."""
import json
from pathlib import Path
from hs_sim.engine import Game, PlayerSetup, Scenario, Keyword, Zone
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit
from examples.excavate_treasures import end_turn


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hero_power_card_id='HERO_01bp',
        board=('CS2_182','CS2_179'),hand=('CS2_029','CS2_029','WW_001t26'),
        deck=('CS2_182',)*3,mana=10,max_mana=10),PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',
        hand=('CS2_029','CS2_029'),deck=('CS2_182',)*3,mana=10,max_mana=10)),seed=56),registry)
    for name in ('CS2_182','CS2_179'):
        submit(game,'CS2_029',name)
    end_turn(game,1);end_turn(game,2)
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'WW_001t26')
        record=match.state.resurrection_history[-1];body=match.state.entities[record.entity_id]
        assert (body.card_id,body.attack,body.health)==('CS2_182',6,7)
        assert {Keyword.REBORN,Keyword.LIFESTEAL}<=body.keywords
        end_turn(match,1)
        submit(match,'CS2_029','CS2_182');submit(match,'CS2_029','CS2_182')
        assert match.state.entities[body.id].zone==Zone.GRAVEYARD
        reborn=[match.state.entities[i] for i in match.state.players[1].board if match.state.entities[i].card_id=='CS2_182']
        assert len(reborn)==1 and (reborn[0].attack,reborn[0].health)==(4,1) and not reborn[0].keywords
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('resurrection-snapshot.json',snapshot),('resurrection-replay.json',build_replay(game)),
                       ('resurrection-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'highest_cost_resurrected':True,'reborn_verified':True,'restored_and_replayed':True}))


if __name__=='__main__':main()
