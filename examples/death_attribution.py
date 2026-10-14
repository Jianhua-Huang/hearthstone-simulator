"""Real Korrak: excess death, resummon, paused recovery, then exact death."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario, was_honorably_killed
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def submit(game,kind,card=None,target=None):
    port=game.for_player(game.state.active_player);listing=port.legal_actions();own,enemy=listing['observation']['players']
    actions=[a for a in listing['actions'] if a['type']==kind]
    if kind=='play_card':
        ref=next(e['ref'] for e in own['hand'] if e['card_id']==card)
        target_ref=next((e['ref'] for p in (own,enemy) for e in p['board'] if e['card_id']==target),None)
        actions=[a for a in actions if a['card']==ref and a.get('target')==target_ref]
    assert actions,(kind,card,target)
    assert port.submit({'revision':listing['revision'],'action':actions[0]})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_09',hero_power_card_id='EDR_449p',
        hand=('CS2_029','CS2_024','CS1_112'),board=('CS2_182',),deck=('CS2_182',)*3,mana=10,max_mana=10),
        PlayerSetup('HERO_08',board=('AV_143',),deck=('CS2_182',)*3)),seed=70,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    old=game.state.players[2].board[0]
    submit(game,'play_card','CS2_029','AV_143')
    assert game.state.players[2].board[0]!=old
    assert not was_honorably_killed(game.state.death_history[0])
    submit(game,'use_hero_power');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice')
        submit(match,'play_card','CS2_024','AV_143')
        submit(match,'end_turn');submit(match,'end_turn')
        submit(match,'play_card','CS1_112')
        records=[d for d in match.state.death_history if d.card_id=='AV_143']
        assert len(records)==2 and was_honorably_killed(records[-1])
        assert not match.state.players[2].board
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('death-attribution-snapshot.json',snapshot),('death-attribution-replay.json',build_replay(game)),
                      ('death-attribution-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
