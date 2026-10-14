"""Six ordinary plays and two Coins exercising frozen conditions via player DTOs."""
import json
from pathlib import Path
from hs_sim.engine import Game, Keyword, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay


def play(game, card_id, target=None):
    port=game.for_player(1);listing=port.legal_actions();players=listing['observation']['players']
    ref=next(c['ref'] for c in players[0]['hand'] if c['card_id']==card_id)
    if target in ('own_hero','enemy_hero'):
        target_ref=players[int(target=='enemy_hero')]['hero']['ref']
    else:
        target_ref=next((c['ref'] for p in players for c in p['board'] if c['card_id']==target),None)
    action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref and a.get('target')==target_ref)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('BT_491','GAME_005','GAME_005','ETC_325','JAM_017','RLK_843'),
        deck=('WW_823','WW_434')+('CS2_182',)*8,max_mana=10,mana=9),
        PlayerSetup('HERO_08',deck=('CS2_182',)*10,max_mana=10,mana=10)),seed=113),registry)
    play(game,'BT_491');snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        play(match,'WW_823','own_hero');play(match,'WW_434','enemy_hero');play(match,'GAME_005')
        play(match,'ETC_325');play(match,'GAME_005');play(match,'RLK_843','enemy_hero');play(match,'JAM_017','ETC_325')
        state=match.state;own=state.players[1];medic=next(state.entities[i] for i in own.board if state.entities[i].card_id=='ETC_325')
        assert (medic.attack,medic.health)==(3,4) and Keyword.LIFESTEAL in medic.keywords
        assert own.mana==0 and state.entities[state.players[2].hero_id].health==21
        records={p.card_id:p for p in state.play_history}
        assert records['WW_823'].quickdraw and records['WW_434'].quickdraw
        assert records['ETC_325'].finale and records['JAM_017'].finale and records['RLK_843'].manathirst
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs';out.mkdir(exist_ok=True)
    for name,data in (('extra-conditions-snapshot.json',snapshot),('extra-conditions-replay.json',build_replay(game)),('extra-conditions-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
