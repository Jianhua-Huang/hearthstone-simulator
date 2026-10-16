"""Actual current costs, Holy/Shadow casts and a real both-player aura."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.replay import build_replay,replay


def main():
    g=Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=('END_033','END_033','JAIL_890',
        'TLC_819','CORE_CS2_004','CORE_EX1_302'),deck=('CORE_CS2_182',),mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_03')),seed=91),build_registry())
    checkpoints=[]
    def check():
        saved=g.snapshot()
        assert g.clone().snapshot()==saved
        assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert replay(build_replay(g),build_registry()).snapshot()==saved
        checkpoints.append('ready')
    def play(cid,target=None):
        listing=g.for_player(1).legal_actions();card=next(c for c in listing['observation']['players'][0]['hand'] if c['card_id']==cid)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==card['ref'] and a.get('target')==target)
        result=g.for_player(1).submit({'revision':listing['revision'],'action':action});assert result['accepted'],result.get('error')
        check()
    check();play('END_033');play('JAIL_890')
    listing=g.for_player(1).legal_actions();demon=next(c['ref'] for c in listing['observation']['players'][0]['board'] if c['card_id']=='JAIL_890')
    play('CORE_CS2_004',demon);play('CORE_EX1_302',demon)
    listing=g.for_player(1).legal_actions();hand=listing['observation']['players'][0]['hand']
    assert next(c for c in hand if c['card_id']=='TLC_819')['cost']['amount']==3
    assert next(c for c in hand if c['card_id']=='END_033')['cost']['amount']==9
    play('TLC_819');play('END_033')
    assert g.state.players[1].mana==2 and g.state.pending_choice is None
    assert [p.cost for p in g.state.play_history]==[4,10,1,1,3,9]
    public=json.dumps(g.for_player(2).observe())
    assert 'condition_facts' not in public and 'cast_rows' not in public
    assert g.for_player(2).observe()['observation']['players'][0]['hand'][0]['card_id'] is None
    result=dict(content_version=g.registry.version,formal_pool_complete=False,actions=len(g.history),
        checkpoints=checkpoints,costs=[p.cost for p in g.state.play_history],mana=g.state.players[1].mana,
        spell_casts=len(g.state.cast_history),draws=len(g.state.draw_history),waiting_choices=0)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
