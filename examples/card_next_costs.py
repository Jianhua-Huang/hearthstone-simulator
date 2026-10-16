"""Real neighbor, next-tribe and health-payment effects through player commands."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.replay import build_replay,replay


def main():
    g=Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=('CORE_BT_416','DINO_137','TLC_823',
        'CORE_EX1_145','CORE_CS2_029','CORE_CS2_117','CORE_ETC_523','JAIL_890'),
        mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_03',board=('CORE_CS2_182',))),seed=101),build_registry())
    checkpoints=[]
    def check():
        saved=g.snapshot()
        assert g.clone().snapshot()==saved
        assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert replay(build_replay(g),build_registry()).snapshot()==saved
        checkpoints.append('ready')
    def play(cid,target=None):
        listing=g.for_player(1).legal_actions();own=listing['observation']['players'][0]
        card=next(c for c in own['hand']if c['card_id']==cid)
        action=next(a for a in listing['actions']if a['type']=='play_card'and a['card']==card['ref']and a.get('target')==target)
        result=g.for_player(1).submit({'revision':listing['revision'],'action':action});assert result['accepted'],result.get('error')
        check()
    check();play('DINO_137');play('CORE_BT_416');play('JAIL_890');play('CORE_EX1_145')
    hero=g.for_player(1).observe()['observation']['players'][0]['hero']['ref']
    play('CORE_CS2_029',hero);play('CORE_CS2_117',hero);play('CORE_ETC_523')
    enemy=g.for_player(1).observe()['observation']['players'][1]['board'][0]['ref'];play('TLC_823',enemy)
    assert g.state.players[1].mana==8 and g.state.entities[g.state.players[1].hero_id].health==22
    assert [p.cost for p in g.state.play_history]==[3,3,8,0,2,5,5,1]
    assert [p.payment.value for p in g.state.play_history][-2:] == ['health','mana']
    assert g.state.pending_choice is None
    public=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
    assert 'hand_neighbors'not in public and 'condition_facts'not in public
    result=dict(content_version=g.registry.version,schema_version=g.snapshot()['schema_version'],formal_pool_complete=False,
        actions=len(g.history),checkpoints=checkpoints,costs=[p.cost for p in g.state.play_history],
        payments=[p.payment.value for p in g.state.play_history],mana=g.state.players[1].mana,
        hero_health=g.state.entities[g.state.players[1].hero_id].health,waiting_choices=0)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
