"""Brann/Okani private choices, Objection competition and suspended replay."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, Scenario, PlayerSetup
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.battlecry_activations import submit


def select(game, label):
    port=game.for_player(game.state.pending_choice.player_id)
    view=port.observe()['observation'];offer=view['pending_choice']
    option=next(o['ref'] for o in offer['options'] if o['label']==label)
    listing=port.legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='select_choice' and a['options']==[option])
    result=port.submit({'revision':listing['revision'],'action':action})
    assert result['accepted'],result


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_08',hand=('LOE_077','TSC_032','MAW_006'),deck=('CS2_182',)*6,mana=10,max_mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029','EX1_010','EX1_010','EX1_010'),deck=('CS2_182',)*6,mana=10,max_mana=10)),
        seed=77,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','LOE_077');submit(game,'play_card','TSC_032');select(game,'反制随从')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        select(match,'反制法术');submit(match,'play_card','MAW_006');submit(match,'end_turn')
        submit(match,'play_card','CS2_029')
        assert match.state.play_history[-1].countered
        submit(match,'play_card','EX1_010')
        assert len(match.state.players[1].secrets)==1
        submit(match,'play_card','EX1_010')
        assert not match.state.players[1].secrets
        submit(match,'play_card','EX1_010')
        assert not match.state.play_history[-1].countered
        assert len(match.state.players[2].board)==1
        assert sum(e.kind=='counter_policy_used' for e in match.events)==2
        assert len(match.state.battlecry_history)==2
        assert len(match.state.death_history)==0
        assert all('counter_policy_added'!=e['kind'] for e in match.player_events(2))
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('private-counter-snapshot.json',snapshot),('private-counter-replay.json',build_replay(game)),
        ('private-counter-view.json',game.for_player(2).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),battlecries=len(game.state.battlecry_history),
        countered=sum(p.countered for p in game.state.play_history),state_hash=game.state_hash(),restored_and_replayed=True)))


if __name__=='__main__':main()
