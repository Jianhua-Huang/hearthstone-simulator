"""Scarab discovery -> SI:7 Agent -> Edwin through fixed-seat player commands."""
import json
from pathlib import Path
from hs_sim.engine import Game,Scenario,PlayerSetup,GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=('LOE_029','EX1_134','EX1_613'),
        deck=('CS2_182',)*4,mana=10,max_mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*4)),
        seed=86,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','LOE_029');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        submit(match,'select_choice')
        port=match.for_player(1);listing=port.legal_actions();players=listing['observation']['players']
        own=next(p for p in players if p['id']==1);enemy=next(p for p in players if p['id']==2)
        ref=next(c['ref'] for c in own['hand'] if c['card_id']=='EX1_134')
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref and a.get('target')==enemy['hero']['ref'])
        assert port.submit({'revision':listing['revision'],'action':action})['accepted']
        submit(match,'play_card','EX1_613')
        assert [b.card_id for b in match.state.combo_history]==['EX1_134','EX1_613']
        assert all(b.completed and not b.interrupted for b in match.state.combo_history)
        assert len(match.state.play_history)==3 and len(match.state.battlecry_history)==1
        assert match.state.players[1].mana==2
        assert match.state.entities[match.state.players[2].hero_id].health==27
        edwin=next(match.state.entities[i] for i in match.state.players[1].board if match.state.entities[i].card_id=='EX1_613')
        assert (edwin.attack,edwin.health)==(6,6)
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('combo-snapshot.json',snapshot),('combo-replay.json',build_replay(game)),
        ('combo-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),combos=len(game.state.combo_history),
        battlecries=len(game.state.battlecry_history),restored_and_replayed=True)))


if __name__=='__main__':main()
