"""Representative Inspire: equip before trigger, paused power, repeat next turn."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from .death_attribution import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hero_power_card_id='HERO_03bp',
        board=('AT_082','AT_066'),deck=('CS2_182',)*4,mana=10,max_mana=10),
        PlayerSetup('HERO_09',hero_power_card_id='EDR_449p',board=('AT_082',),
                    deck=('CS2_182',)*4,mana=10,max_mana=10)),seed=71,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'use_hero_power')
    assert game.state.entities[game.state.players[1].weapon_id].attack==2
    submit(game,'end_turn');submit(game,'use_hero_power')
    assert game.state.pending_choice is not None
    assert game.state.entities[game.state.players[2].board[0]].attack==1
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice')
        assert match.state.entities[match.state.players[2].board[0]].attack==2
        submit(match,'end_turn');submit(match,'use_hero_power')
        assert match.state.entities[match.state.players[1].board[0]].attack==3
        assert match.state.entities[match.state.players[1].weapon_id].attack==2
        assert len(match.state.hero_power_history)==3
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('inspire-snapshot.json',snapshot),('inspire-replay.json',build_replay(game)),
                      ('inspire-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
