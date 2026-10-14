"""Scarab -> Shudderwock -> Macaw -> Shudderwock, experimental R-126."""
import json
from pathlib import Path
from hs_sim.engine import Game,Scenario,PlayerSetup,GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit


def run():
    r=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('LOE_029','GIL_820','DED_509','GIL_820'),
        deck=('CS2_182',)*12,mana=10,max_mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*12)),
        seed=85,generation_context=GenerationContext('local-2026-09-23','experimental')),r)
    submit(game,'play_card','LOE_029');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),r)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        submit(match,'select_choice')
        for cid in ('GIL_820','DED_509','GIL_820'):
            submit(match,'end_turn');submit(match,'end_turn');submit(match,'play_card',cid)
            assert match.state.pending_choice is None
        assert len(match.state.play_history)==4 and len(match.state.battlecry_history)==11
        assert all(b.completed and not b.interrupted for b in match.state.battlecry_history)
        assert sum(e.kind=='battlecry_choice_randomized' for e in match.events)==4
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),r).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('shudderwock-snapshot.json',snapshot),('shudderwock-replay.json',build_replay(game)),
        ('shudderwock-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),battlecries=len(game.state.battlecry_history),
        restored_and_replayed=True)))


if __name__=='__main__':main()
