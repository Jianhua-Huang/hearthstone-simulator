"""Restore one real Exodar choice and execute all three player-visible branches."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayCard, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',board=('SC_403a','SC_405'),
            hand=('SC_411','SC_411','GDB_120'),max_mana=10,mana=10),
        PlayerSetup('HERO_01'),
    ),seed=47),registry)
    for card_id in ('SC_403a','SC_405'):
        card=next(i for i in game.state.players[1].hand if game.state.entities[i].card_id=='SC_411')
        target=next(i for i in game.state.players[1].board if game.state.entities[i].card_id==card_id)
        game.apply(PlayCard(1,card,target))
    game.apply(PlayCard(1,game.state.players[1].hand[0]))
    assert game.state.pending_choice is not None
    assert game.state.players[1].mana==1
    snapshot=game.snapshot();branches={}
    for protocol in ('GDB_100a','GDB_100b','GDB_100c'):
        branch=game.clone()
        restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
        for match in (branch,restored):
            port=match.for_player(1);view=port.observe();choice=view['observation']['pending_choice']
            option=next(o for o in choice['options'] if o['card_id']==protocol)
            result=port.submit({'revision':view['revision'],'action':{
                'type':'select_choice','choice':choice['ref'],'options':[option['ref']]}})
            assert result['accepted']
        assert branch.snapshot()==restored.snapshot()
        assert replay(build_replay(branch),registry).snapshot()==branch.snapshot()
        branches[protocol]=branch
    repairs,offense,crew=(branches[i] for i in ('GDB_100a','GDB_100b','GDB_100c'))
    assert repairs.state.entities[repairs.state.players[1].hero_id].armor==15
    assert offense.state.entities[offense.state.players[2].hero_id].health==26
    assert [(crew.state.entities[i].card_id,crew.state.entities[i].cost)
        for i in crew.state.players[1].hand]==[('SC_403a',1),('SC_405',1)]
    return snapshot,branches


def main():
    snapshot,branches=run()
    output=Path(__file__).resolve().parents[1]/'outputs'
    output.mkdir(exist_ok=True)
    (output/'exodar-pending-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    results={}
    for name,game in branches.items():
        (output/f'exodar-{name}-replay.json').write_text(json.dumps(build_replay(game),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        results[name]={'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash()}
    print(json.dumps({'restored_and_replayed':True,'branches':results},indent=2))


if __name__=='__main__':main()
