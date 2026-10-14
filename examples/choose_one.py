"""Fandral with War, Wrath and Nourish through atomic player branch commands."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario, Keyword
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def submit(game,kind,card=None,branch=None,target=None):
    port=game.for_player(game.state.active_player);listing=port.legal_actions()
    own=next(p for p in listing['observation']['players'] if p['id']==game.state.active_player)
    actions=[a for a in listing['actions'] if a['type']==kind]
    if kind=='play_card':
        ref=next(e['ref'] for e in own['hand'] if e['card_id']==card)
        target_ref=next((e['ref'] for p in listing['observation']['players'] for e in p['board'] if e['card_id']==target),None)
        actions=[a for a in actions if a['card']==ref and a.get('branch')==branch and a.get('target')==target_ref]
    assert actions,(kind,card,branch,target)
    assert port.submit({'revision':listing['revision'],'action':actions[0]})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=('EX1_178','EX1_154','EX1_164'),
        board=('OG_044',),deck=('CS2_182',)*8,mana=10,max_mana=10),
        PlayerSetup('HERO_08',board=('CS2_182',),deck=('CS2_182',)*8)),seed=72,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','EX1_178','both')
    war=next(game.state.entities[i] for i in game.state.players[1].board if game.state.entities[i].card_id=='EX1_178')
    assert (war.attack,war.health)==(10,10) and Keyword.TAUNT in war.keywords
    submit(game,'play_card','EX1_154','both','CS2_182')
    assert game.state.entities[game.state.players[2].board[0]].health==1
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'end_turn');submit(match,'end_turn')
        submit(match,'play_card','EX1_164','both')
        assert [p.branch_id for p in match.state.play_history]==['both']*3
        assert match.state.players[1].mana==5 and match.state.pending_choice is None
        assert len(match.state.players[1].hand)==5
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('choose-one-snapshot.json',snapshot),('choose-one-replay.json',build_replay(game)),
                      ('choose-one-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
