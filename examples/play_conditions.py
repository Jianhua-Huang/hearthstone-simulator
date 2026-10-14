"""Mixed-class mechanism scenario: conditional targeting, Outcast and Combo."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay


def play(game,card_id):
    port=game.for_player(1);listing=port.legal_actions();players=listing['observation']['players']
    ref=next(c['ref'] for c in players[0]['hand'] if c['card_id']==card_id)
    target=players[1]['board'][0]['ref']
    action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref and a.get('target') in (None,target))
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',hand=('GAME_005','BT_491','EX1_134','EX1_613','BT_480'),
                    deck=('CS2_182',)*10,max_mana=10,mana=10),
        PlayerSetup('HERO_08',board=('CS2_182',),deck=('CS2_182',)*10,max_mana=10,mana=10)),seed=104),registry)
    play(game,'GAME_005');play(game,'EX1_134');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        play(match,'BT_491');play(match,'BT_480');play(match,'EX1_613')
        history=match.state.play_history
        assert history[2].outcast and not history[3].outcast
        assert history[-1].prior_turn_plays==4
        edwin=match.state.entities[history[-1].source_id]
        assert (edwin.attack,edwin.health)==(10,10)
        assert len(match.state.players[1].deck)==8
        assert match.state.entities[match.state.players[2].board[0]].health==2
        assert all(p.completed for p in history)
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();output=Path(__file__).resolve().parents[1]/'outputs';output.mkdir(exist_ok=True)
    for name,data in (('play-conditions-snapshot.json',snapshot),('play-conditions-replay.json',build_replay(game)),
                      ('play-conditions-view.json',game.observe(1))):
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
