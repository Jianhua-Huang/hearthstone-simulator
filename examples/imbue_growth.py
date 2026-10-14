"""Two class powers, independent growth and save/replay through player ports."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario, imbue_count
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def use_power(game):
    port=game.for_player(game.state.active_player); listing=port.legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='use_hero_power')
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_06',hand=('EDR_852',)*2,deck=('CS2_182',)*4,
                    hero_power_card_id='HERO_06bp',mana=10,max_mana=10),
        PlayerSetup('HERO_08',hand=('EDR_852',),deck=('CS2_182',)*4,
                    hero_power_card_id='HERO_08bp',mana=10,max_mana=10)),seed=60),registry)
    submit(game,'EDR_852');use_power(game)
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match);submit(match,'EDR_852');use_power(match);submit(match)
        submit(match,'EDR_852');use_power(match)
        state=match.state
        golems=[state.entities[i] for i in state.players[1].board if state.entities[i].card_id=='EDR_847pt2']
        assert [(e.attack,e.max_health) for e in golems]==[(1,1),(2,2)]
        assert (imbue_count(state,1),imbue_count(state,2))==(2,1)
        assert state.entities[state.players[1].hero_power_id].card_id=='EDR_847p'
        assert state.entities[state.players[2].hero_power_id].card_id=='EDR_851p'
        assert sum(e.kind=='hero_power_replaced' for e in match.events)==2
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('imbue-snapshot.json',snapshot),('imbue-replay.json',build_replay(game)),
                       ('imbue-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),
        'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
