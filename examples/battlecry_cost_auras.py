"""Weblord taxes both players; saved discovery and source removal share live quotes."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.battlecry_activations import submit


def own_hand(game):
    view=game.for_player(game.state.active_player).observe()['observation']
    return next(p['hand'] for p in view['players'] if p['id']==game.state.active_player)


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_08',hand=('FP1_017','LOE_029'),deck=('CS2_182',)*6,mana=10,max_mana=10),
        PlayerSetup('HERO_06',hand=('LOE_029','EX1_178','CS2_029'),deck=('CS2_182',)*6,mana=10,max_mana=10)),
        seed=78,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','FP1_017')
    assert next(c['cost']['amount'] for c in own_hand(game) if c['card_id']=='LOE_029')==4
    submit(game,'play_card','LOE_029')
    assert game.state.players[1].mana==4
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice');submit(match,'end_turn')
        costs={c['card_id']:c['cost']['amount'] for c in own_hand(match)}
        assert (costs['LOE_029'],costs['EX1_178'],costs['CS2_029'])==(4,7,4)
        port=match.for_player(2);listing=port.legal_actions();view=listing['observation']
        own=next(p for p in view['players'] if p['id']==2)
        enemy=next(p for p in view['players'] if p['id']==1)
        spell=next(c['ref'] for c in own['hand'] if c['card_id']=='CS2_029')
        target=next(c['ref'] for c in enemy['board'] if c['card_id']=='FP1_017')
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==spell and a.get('target')==target)
        assert port.submit({'revision':listing['revision'],'action':action})['accepted']
        assert next(c['cost']['amount'] for c in own_hand(match) if c['card_id']=='LOE_029')==2
        submit(match,'play_card','LOE_029');submit(match,'select_choice')
        assert match.state.players[2].mana==4
        assert [p.cost for p in match.state.play_history if p.card_id=='LOE_029']==[4,2]
        assert len(match.state.battlecry_history)==2
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('battlecry-cost-snapshot.json',snapshot),('battlecry-cost-replay.json',build_replay(game)),
                       ('battlecry-cost-view.json',game.for_player(2).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),battlecries=len(game.state.battlecry_history),
        beetle_costs=[p.cost for p in game.state.play_history if p.card_id=='LOE_029'],
        state_hash=game.state_hash(),restored_and_replayed=True)))


if __name__=='__main__':main()
