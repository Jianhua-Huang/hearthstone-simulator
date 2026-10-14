"""Three real keyword adapters, shared numeric conditions and player recovery."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def submit(game, kind, card=None, target=None):
    port=game.for_player(1);listing=port.legal_actions();own,enemy=listing['observation']['players']
    actions=[a for a in listing['actions'] if a['type']==kind]
    if kind=='play_card':
        ref=next(e['ref'] for e in own['hand'] if e['card_id']==card)
        target_ref=next((e['ref'] for p in (own,enemy) for e in p['board'] if e['card_id']==target),None)
        actions=[a for a in actions if a['card']==ref and a.get('target')==target_ref]
    elif kind=='attack':
        source=next(e['ref'] for e in own['board'] if e['card_id']==card)
        defender=next(e['ref'] for e in enemy['board'] if e['card_id']==target)
        actions=[a for a in actions if a['attacker']==source and a['defender']==defender]
    assert port.submit({'revision':listing['revision'],'action':actions[0]})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_09',hero_power_card_id='EDR_449p',
        hand=('CS2_188','CS1_112'),board=('TRL_506','AV_121','AT_011'),deck=('CS2_182',)*3,
        mana=10,max_mana=10),PlayerSetup('HERO_08',board=('FP1_007','CS2_188'),deck=('CS2_182',)*3)),
        seed=69,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','CS2_188','TRL_506')
    submit(game,'attack','TRL_506','FP1_007')
    submit(game,'attack','AV_121','CS2_188')
    submit(game,'use_hero_power');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.for_player(2).legal_actions()['actions'] == [{'type': 'concede'}]
        submit(match,'select_choice');submit(match,'play_card','CS1_112')
        stats={match.state.entities[i].card_id:match.state.entities[i] for i in match.state.players[1].board}
        assert (stats['TRL_506'].attack,stats['TRL_506'].health)==(8,1)
        assert (stats['AV_121'].attack,stats['AV_121'].health)==(3,3)
        assert (stats['AT_011'].attack,stats['AT_011'].health)==(3,4)
        assert match.state.pending_choice is None
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,data in (('health-outcomes-snapshot.json',snapshot),('health-outcomes-replay.json',build_replay(game)),
                      ('health-outcomes-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
