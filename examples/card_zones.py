"""Real zone cards through player DTOs, with all stable positions independently portable."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.replay import build_replay,replay


def main():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_09',hand=('CORE_EX1_193','CATA_477','CATA_697','CATA_721','CORE_BT_035'),
            deck=('CORE_CS2_182','CORE_EX1_043'),mana=10,max_mana=10),
        PlayerSetup('HERO_03',deck=('CORE_CS2_182',)*3),),seed=31),build_registry())
    checkpoints=[]
    def check():
        saved=game.snapshot()
        assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert game.clone().snapshot()==saved
        assert replay(build_replay(game),build_registry()).snapshot()==saved
        checkpoints.append('ready')
    def submit(listing,action):
        result=game.for_player(1).submit({'revision':listing['revision'],'action':action})
        assert result['accepted'],result.get('error');check()
    def play(cid,target_ref=None):
        listing=game.for_player(1).legal_actions();own=listing['observation']['players'][0]
        card=next(c for c in own['hand'] if c['card_id']==cid)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==card['ref']
            and a.get('target')==target_ref)
        submit(listing,action)
    check();original_deck=list(game.state.players[2].deck)
    play('CORE_EX1_193')
    copy=next(e for e in game.state.players[1].hand if game.state.entities[e].card_id=='CORE_CS2_182')
    assert game.state.entities[copy].origin_entity_id in original_deck
    assert game.state.players[2].deck==original_deck
    assert game.for_player(2).observe()['observation']['players'][0]['hand'][-1]['card_id'] is None
    play('CATA_477')
    listing=game.for_player(1).legal_actions();own=listing['observation']['players'][0]
    target=next(c['ref'] for c in own['hand'] if c['card_id']=='CORE_CS2_182')
    use=next(a for a in listing['actions'] if a['type']=='use_location' and a['target']==target)
    submit(listing,use);assert (game.state.entities[copy].attack,game.state.entities[copy].health)==(6,7)
    listing=game.for_player(1).legal_actions();own=listing['observation']['players'][0]
    fel=next(c['ref'] for c in own['hand'] if c['card_id']=='CORE_BT_035');play('CATA_697',fel)
    assert len([e for e in game.state.players[1].hand if game.state.entities[e].card_id=='CORE_BT_035'])==2
    listing=game.for_player(1).legal_actions();own=listing['observation']['players'][0]
    target=next(c['ref'] for c in own['hand'] if c['card_id']=='CORE_CS2_182');play('CATA_721',target)
    assert game.state.players[1].mana==2 and len(game.state.draw_history)==1
    assert copy in game.state.players[1].deck+game.state.players[1].hand
    result=dict(content_version=game.registry.version,formal_pool_complete=False,
        actions=len(game.history),checkpoints=checkpoints,mana=game.state.players[1].mana,
        enemy_deck_unchanged=game.state.players[2].deck==original_deck,
        copied_current_stats=[game.state.entities[copy].attack,game.state.entities[copy].health],
        fel_copies=2,draws=len(game.state.draw_history),waiting_choices=0)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
