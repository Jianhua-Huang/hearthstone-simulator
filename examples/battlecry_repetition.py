"""Brann + two independent Scarab discoveries + repeated weapon Battlecry."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.battlecry_activations import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('LOE_077',),
        hand=('LOE_029','CATA_580'),deck=('CS2_182',)*6,mana=10,max_mana=10),
        PlayerSetup('HERO_08',deck=('CS2_182',)*6)),seed=74,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','LOE_029')
    assert game.state.pending_choice is not None
    submit(game,'select_choice')
    assert game.state.pending_choice is not None
    assert [(b.repeat_index,b.completed) for b in game.state.battlecry_history]==[(1,True),(2,False)]
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice')
        submit(match,'play_card','CATA_580')
        assert [(b.card_id,b.repeat_index) for b in match.state.battlecry_history]==[
            ('LOE_029',1),('LOE_029',2),('CATA_580',1),('CATA_580',2)]
        assert all(b.completed for b in match.state.battlecry_history)
        assert len(match.state.play_history)==2 and len(match.state.battlecry_batches)==2
        assert match.state.players[1].mana==10-registry.card('LOE_029').cost-registry.card('CATA_580').cost
        assert match.state.cast_history==[]
        for p in (1,2):assert 'battlecry_batches' not in json.dumps(match.observe(p))
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('battlecry-repeat-snapshot.json',snapshot),('battlecry-repeat-replay.json',build_replay(game)),
        ('battlecry-repeat-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        battlecries=len(game.state.battlecry_history),batches=len(game.state.battlecry_batches),restored_and_replayed=True)))


if __name__=='__main__':main()
