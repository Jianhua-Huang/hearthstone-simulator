"""Complete summon/deathrattle/wipe paths through the bound player JSON port."""

import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.replay import build_replay,replay


def main():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_09',hand=('DINO_130','CORE_EX1_309','CORE_EX1_312'),
            board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*2,mana=10,max_mana=10),
        PlayerSetup('HERO_08',board=('CORE_EX1_110','JAIL_877'),deck=('CORE_CS2_182',)*2),
    )),build_registry())
    checkpoints=[]
    def check():
        snapshot=game.snapshot()
        assert Game.from_snapshot(snapshot,build_registry()).snapshot()==snapshot
        assert game.clone().snapshot()==snapshot
        assert replay(build_replay(game),build_registry()).snapshot()==snapshot
        checkpoints.append('ready')
    def play(cid,target_id=None):
        listing=game.for_player(1).legal_actions()
        players={p['id']:p for p in listing['observation']['players']}
        card=next(c for c in players[1]['hand'] if c['card_id']==cid)
        target=None if target_id is None else next(c['ref'] for c in players[1]['board'] if c['card_id']==target_id)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==card['ref']
                    and (target is None or a.get('target')==target))
        reply=game.for_player(1).submit({'revision':listing['revision'],'action':action})
        assert reply['accepted'],reply['error']
        check()
    check()
    play('DINO_130')
    play('CORE_EX1_309','DINO_130')
    grown=[(game.state.entities[e].card_id,game.state.entities[e].attack,
            game.state.entities[e].max_health) for e in game.state.players[1].board]
    assert grown==[('CORE_CS2_182',5,6),('DINO_130t',4,4)]
    listing=game.for_player(1).legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='end_turn')
    assert game.for_player(1).submit({'revision':listing['revision'],'action':action})['accepted']
    check()
    listing=game.for_player(2).legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='end_turn')
    assert game.for_player(2).submit({'revision':listing['revision'],'action':action})['accepted']
    check()
    play('CORE_EX1_312')
    last_wave=game.state.death_history[-1].batch
    assert len([r for r in game.state.death_history if r.batch==last_wave])==4
    result=dict(content_version=game.registry.version,formal_pool_complete=False,
        actions=len(game.history),checkpoints=checkpoints,grown_before_wipe=grown,
        final_boards=[[game.state.entities[e].card_id for e in p.board] for p in game.state.players.values()],
        mana=game.state.players[1].mana,death_batches=[r.batch for r in game.state.death_history])
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result


if __name__=='__main__': main()
