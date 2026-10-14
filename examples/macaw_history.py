"""Brann, Scarab and two Macaws: explicit experimental played-history policy."""
import json
from pathlib import Path
from hs_sim.engine import Game, Scenario, PlayerSetup, GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.battlecry_activations import submit


def run():
    r=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_08',board=('LOE_077',),
        hand=('LOE_029','DED_509','DED_509'),deck=('CS2_182',)*6,mana=10,max_mana=10),
        PlayerSetup('HERO_01',deck=('CS2_182',)*6)),seed=81,
        generation_context=GenerationContext('local-2026-09-23','experimental')),r)
    submit(game,'play_card','LOE_029')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),r)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        submit(match,'select_choice');submit(match,'select_choice')
        submit(match,'play_card','DED_509');submit(match,'play_card','DED_509')
        assert match.state.pending_choice is None
        assert len(match.state.players[1].hand)==6 and match.state.players[1].mana==2
        assert len(match.state.play_history)==3 and len(match.state.battlecry_history)==12
        assert [b.history_play_id for b in match.state.battlecry_history if b.origin=='played_history']==[1,1,2,1,2,1]
        assert sum(e.kind=='battlecry_choice_randomized' for e in match.events)==4
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),r).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('macaw-history-snapshot.json',snapshot),('macaw-history-replay.json',build_replay(game)),
        ('macaw-history-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        battlecries=len(game.state.battlecry_history),hand_plays=len(game.state.play_history),restored_and_replayed=True)))


if __name__=='__main__':main()
