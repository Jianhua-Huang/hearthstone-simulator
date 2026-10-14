"""Murmuring Elemental and Heart of Vir'naal: finite budget, turn expiry, discovery."""
import json
from pathlib import Path
from hs_sim.engine import Game,GenerationContext,Scenario,PlayerSetup
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_02',hero_power_card_id='ULD_291p',
        hand=('LOOT_517','LOE_029','LOE_029'),deck=('CS2_182',)*6,mana=10,max_mana=10),
        PlayerSetup('HERO_08',deck=('CS2_182',)*6)),seed=75,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','LOOT_517')
    assert len(game.state.players[1].battlecry_modifiers)==1
    submit(game,'play_card','LOE_029')
    assert game.state.pending_choice is not None and not game.state.players[1].battlecry_modifiers
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice');submit(match,'select_choice')
        submit(match,'use_hero_power')
        assert len(match.state.players[1].battlecry_modifiers)==1
        submit(match,'play_card','LOE_029')
        submit(match,'select_choice');submit(match,'select_choice')
        assert [b.card_id for b in match.state.battlecry_history]==['LOOT_517',*(['LOE_029']*4)]
        assert len(match.state.battlecry_batches)==3 and len(match.state.play_history)==3
        assert len(match.state.hero_power_history)==1 and match.state.players[1].mana==2
        assert sum(e.kind=='battlecry_modifier_used' for e in match.events)==1
        assert not match.state.players[1].player_effects
        submit(match,'end_turn')
        assert not match.state.players[1].battlecry_modifiers
        for p in (1,2):
            facts=next(p for p in match.observe(p)['players'] if p['id']==1)
            assert facts['battlecry_modifiers']==[]
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('battlecry-modifier-snapshot.json',snapshot),('battlecry-modifier-replay.json',build_replay(game)),
        ('battlecry-modifier-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),battlecries=len(game.state.battlecry_history),
        batches=len(game.state.battlecry_batches),state_hash=game.state_hash(),restored_and_replayed=True)))


if __name__=='__main__':main()
