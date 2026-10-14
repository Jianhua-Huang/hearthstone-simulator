"""Five physical Kobold Miners, a new vein and the lifetime-count Scorpion."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario, excavation_count
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit


def end_turn(game, player):
    port=game.for_player(player);listing=port.legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='end_turn')
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    r=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=('WW_001',)*5,deck=('CS2_182',),max_mana=10,mana=10,
        hero_power_card_id='HERO_03bp'),PlayerSetup('HERO_01',deck=('CS2_182',),hero_power_card_id='HERO_01bp')),seed=55,
        generation_context=GenerationContext('local-2026-09-23','experimental')),r)
    for _ in range(3):submit(game,'WW_001')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),r)
    for match in (game,restored):
        submit(match,'WW_001');submit(match,'WW_001')
        assert [x.tier for x in match.state.excavation_history]==[1,2,3,4,1]
        assert match.state.players[1].mana==0
        end_turn(match,1);end_turn(match,2);submit(match,'WW_001t23')
        assert excavation_count(match.state,1)==5
        assert match.observe(1)['players'][0]['excavation']=={'count':5,'cycle':2,'depth':1}
        assert len(match.state.players[1].board)==6
        spells=[match.state.entities[e.target_id] for e in match.events if e.kind=='card_added_to_hand'][-4:]
        assert all(c.cost==max(1,r.card(c.card_id).cost-5) for c in spells)
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),r).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('excavate-snapshot.json',snapshot),('excavate-replay.json',build_replay(game)),('excavate-view.json',game.observe(2))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'excavations':5,'cycles':2,'restored_and_replayed':True}))


if __name__=='__main__':main()
