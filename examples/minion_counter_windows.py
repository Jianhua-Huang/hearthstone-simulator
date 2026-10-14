"""Objection cancels one Scarab; Heart of Vir'naal still repeats the next."""
import json
from pathlib import Path
from hs_sim.engine import Game,GenerationContext,Scenario,PlayerSetup
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_08',hand=('MAW_006',),deck=('CS2_182',)*6,max_mana=10,mana=10),
        PlayerSetup('HERO_02',hero_power_card_id='ULD_291p',hand=('LOE_029','LOE_029'),
            deck=('CS2_182',)*6,max_mana=10,mana=10)),seed=76,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','MAW_006');submit(game,'end_turn')
    submit(game,'use_hero_power');submit(game,'play_card','LOE_029')
    assert game.state.play_history[-1].countered and not game.state.battlecry_history
    assert not game.state.players[2].board and len(game.state.players[2].battlecry_modifiers)==1
    assert not game.state.death_history
    submit(game,'play_card','LOE_029')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice');submit(match,'select_choice')
        assert len(match.state.battlecry_history)==2 and len(match.state.battlecry_batches)==1
        assert match.state.players[2].mana==4
        assert sum(e.kind=='minion_countered' for e in match.events)==1
        assert sum(e.kind=='minion_summoned' for e in match.events)==1
        submit(match,'end_turn');assert not match.state.players[2].battlecry_modifiers
        for viewer in (1,2):
            assert all(not p['pending_plays'] for p in match.observe(viewer)['players'])
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('minion-counter-snapshot.json',snapshot),('minion-counter-replay.json',build_replay(game)),
        ('minion-counter-view.json',game.observe(2))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),battlecries=len(game.state.battlecry_history),
        batches=len(game.state.battlecry_batches),countered=sum(p.countered for p in game.state.play_history),
        state_hash=game.state_hash(),restored_and_replayed=True)))


if __name__=='__main__':main()
