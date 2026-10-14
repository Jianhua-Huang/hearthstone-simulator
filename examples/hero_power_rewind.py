"""Bronze retries once, then Morchie retains both outcomes next turn."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario,GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit
from examples.imbue_growth import use_power


def select(game,index=0):
    port=game.for_player(1);listing=port.legal_actions()
    choices=[a for a in listing['actions'] if a['type']=='select_choice']
    assert port.submit({'revision':listing['revision'],'action':choices[index]})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=('EDR_852','END_036'),
        deck=('CS2_182',)*3,mana=10,max_mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*3)),
        seed=62,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'EDR_852');use_power(game);snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        select(match,1)  # Public choice order: keep, then retry.
        submit(match,'END_036');select(match)
        submit(match);submit(match);use_power(match)
        assert match.state.pending_choice is None
        assert len(match.state.hero_power_history)==2
        assert match.state.players[1].hero_power_uses_this_turn==1
        assert match.state.players[1].mana==9
        assert match.state.rewind_outcomes[0].power_id==2
        assert match.state.rewind_outcomes[0].completed==2
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('power-rewind-snapshot.json',snapshot),('power-rewind-replay.json',build_replay(game)),
                       ('power-rewind-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),
        'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
