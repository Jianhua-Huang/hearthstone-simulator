"""Real Colossal bodies and distinct limbs through player actions and save/replay."""
import json
from pathlib import Path
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay


def submit(game,card=None,target=None):
    port=game.for_player(game.state.active_player);listing=port.legal_actions()
    if card is None:action=next(a for a in listing['actions'] if a['type']=='end_turn')
    else:
        players=listing['observation']['players'];own=next(p for p in players if p['id']==game.state.active_player)
        ref=next(x['ref'] for x in own['hand'] if x['card_id']==card)
        target_ref=next((x['ref'] for p in players for x in p['board'] if x['card_id']==target),None)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref and a.get('target')==target_ref)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',hand=('TSC_639','CS2_029'),deck=('CS2_182',)*10,max_mana=10,mana=10),
        PlayerSetup('HERO_08',hand=('TSC_216',),deck=('CS2_182',)*10,max_mana=10,mana=10)),seed=117),registry)
    submit(game,'TSC_639');snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match);submit(match,'TSC_216');submit(match)
        submit(match,'CS2_029','TSC_639t2' if any(match.state.entities[i].card_id=='TSC_639t2' for i in match.state.players[1].board) else 'TSC_639t3')
        state=match.state;glugg=next(state.entities[i] for i in state.players[1].board if state.entities[i].card_id=='TSC_639')
        assert (glugg.attack,glugg.health)==(7,9)
        assert len(state.colossal_history)==2 and all(r.completed for r in state.colossal_history)
        assert len(state.players[1].board)==2 and len(state.death_history)==2
        assert [state.entities[i].card_id for i in state.players[2].board]==['TSC_216t','TSC_216']
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs';out.mkdir(exist_ok=True)
    for name,data in (('colossal-snapshot.json',snapshot),('colossal-replay.json',build_replay(game)),('colossal-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
