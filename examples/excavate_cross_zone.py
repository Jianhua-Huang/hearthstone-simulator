"""Dragon buffs three zones; Murloc resets faces and retains captured costs."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_01',
        hand=('DEEP_999t4','DEEP_999t5','CS2_182'),board=('CS2_182',),deck=('CS2_182',),mana=10,max_mana=10),
        PlayerSetup('HERO_08')),seed=58,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'DEEP_999t4')
    player=game.state.players[1]
    yeti=next(i for i in player.board if game.state.entities[i].card_id=='CS2_182')
    for eid in (player.hand[-1],player.deck[0],yeti):
        entity=game.state.entities[eid]
        assert (entity.card_id,entity.attack,entity.health)==('CS2_182',7,8)
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'DEEP_999t5')
        state=match.state;player=state.players[1]
        transformed=[i for i in player.board if state.entities[i].card_id!='DEEP_999t5']
        for eid in (player.hand[0],player.deck[0],*transformed):
            entity=state.entities[eid]
            assert (entity.card_id,entity.cost)==('CS2_222',4)
        assert state.entities[player.hand[0]].attack==registry.card('CS2_222').attack
        source=next(state.entities[i] for i in player.board if state.entities[i].card_id=='DEEP_999t5')
        assert source.attack==10
        assert player.mana==2 and len(player.board)==3 and not state.death_history
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('cross-zone-snapshot.json',snapshot),('cross-zone-replay.json',build_replay(game)),
                       ('cross-zone-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
                      'three_zones_transformed':True,'costs_retained':True,'restored_and_replayed':True}))


if __name__=='__main__':main()
