"""Mixed-class Spellburst/Frenzy scenario using only the restricted player port."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def play(game, card_id, target_card=None):
    port=game.for_player(1);listing=port.legal_actions();players=listing['observation']['players']
    ref=next(c['ref'] for c in players[0]['hand'] if c['card_id']==card_id)
    target=next((c['ref'] for p in players for c in p['board'] if c['card_id']==target_card),None)
    action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref and a.get('target')==target)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',hand=('SCH_248','GAME_005','EX1_124','GAME_005'),
            board=('SCH_242','SCH_182','BAR_021'),deck=('CS2_182',)*10,max_mana=10,mana=10),
        PlayerSetup('HERO_08',board=('BAR_024',),deck=('CS2_182',)*10,max_mana=10,mana=10)),seed=108),registry)
    play(game,'SCH_248','BAR_024')
    play(game,'EX1_124','BAR_021')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        play(match,'SCH_248','BAR_024');play(match,'GAME_005');play(match,'GAME_005')
        state=match.state;own=state.players[1];hero=state.entities[own.hero_id]
        assert (hero.health,hero.armor)==(27,4)
        gidra=next(state.entities[i] for i in own.board if state.entities[i].card_id=='SCH_182')
        assert (gidra.attack,gidra.health)==(3,6)
        assert sum(state.entities[i].card_id=='SCH_242' for i in own.board)==4
        assert any(state.entities[i].card_id=='SCH_248' for i in own.hand)
        assert state.entities[state.players[2].board[0]].health==1
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();output=Path(__file__).resolve().parents[1]/'outputs';output.mkdir(exist_ok=True)
    for name,data in (('limited-triggers-snapshot.json',snapshot),('limited-triggers-replay.json',build_replay(game)),
                      ('limited-triggers-view.json',game.observe(1))):
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
