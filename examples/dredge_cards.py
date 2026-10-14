"""Opponent Dredge, physical summon and revealed damage through player ports."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def choose(game, card_id):
    port=game.for_player(1);listing=port.legal_actions()
    view=port.observe()['observation']['pending_choice']
    option=next(o['ref'] for o in view['options'] if o['card_id']==card_id)
    action=next(a for a in listing['actions'] if a['type']=='select_choice' and a['options']==[option])
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_08',hand=('TID_700','TID_099','TID_703'),
                    deck=('CS2_188','CS2_182','CS2_029'),max_mana=10,mana=10),
        PlayerSetup('HERO_01',deck=('CS2_182','CS2_029','EX1_019'),board=('CS2_182',))),seed=54),registry)
    submit(game,'TID_700');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.observe(2)['pending_choice']=={'player_id':1}
        choose(match,'EX1_019')
        assert match.state.entities[match.state.players[2].deck[0]].cost==6
        submit(match,'TID_099');choose(match,'CS2_188')
        assert len(match.state.players[1].board)==3
        submit(match,'TID_703');choose(match,'CS2_182')
        assert not match.state.players[1].board
        assert match.state.entities[match.state.players[2].board[0]].health==1
        assert match.state.players[1].mana==0
        assert len(match.state.draw_history)==0
        assert sum(e.kind=='card_dredged' for e in match.events)==3
        assert next(e for e in match.player_events(2) if e['kind']=='card_dredged')['dredge']['selected'] is None
        assert [e for e in match.player_events(2) if e['kind']=='card_dredged'][-1]['dredge']['selected']['card_id']=='CS2_182'
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('dredge-snapshot.json',snapshot),('dredge-replay.json',build_replay(game)),('dredge-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
                      'dredges':3,'restored_and_replayed':True}))


if __name__=='__main__':main()
