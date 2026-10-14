"""Brann/Snapdragon deck filtering, physical draw, restored repeated discovery."""
import json
from pathlib import Path
from hs_sim.engine import Game, Scenario, PlayerSetup, GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.battlecry_activations import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_08',hand=('TID_710','BT_491'),deck=('LOE_029','CS2_182','CS2_182'),
            board=('LOE_077',),mana=10,max_mana=10),
        PlayerSetup('HERO_08',deck=('CS2_182',)*4,mana=10,max_mana=10)),
        seed=79,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','TID_710')
    deck=[game.state.entities[i] for i in game.state.players[1].deck]
    assert [(e.attack,e.health) for e in deck]==[(3,3),(4,5),(4,5)]
    assert len(game.state.battlecry_history)==2
    submit(game,'play_card','BT_491');submit(game,'play_card','LOE_029')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        for _ in range(2):
            assert match.state.pending_choice is not None
            submit(match,'select_choice')
        beetle=next(match.state.entities[i] for i in match.state.players[1].board if match.state.entities[i].card_id=='LOE_029')
        assert (beetle.attack,beetle.health)==(3,3)
        assert match.state.players[1].mana==3
        assert [b.card_id for b in match.state.battlecry_history]==['TID_710','TID_710','LOE_029','LOE_029']
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('ability-filter-snapshot.json',snapshot),('ability-filter-replay.json',build_replay(game)),
                       ('ability-filter-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),battlecries=len(game.state.battlecry_history),
        state_hash=game.state_hash(),restored_and_replayed=True)))


if __name__=='__main__':main()
