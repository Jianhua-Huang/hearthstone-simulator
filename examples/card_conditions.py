"""A player-port scenario with implicit equipment, physical discovery and choices."""
import json

from hs_sim.cards import build_registry
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.replay import build_replay,replay


def main():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_03',hand=('CORE_CS2_074','CORE_DS1_184','TLC_245',
            'CORE_AT_037','CORE_EX1_309'),board=('CORE_CS2_182',),
            deck=('CORE_CS2_182','CORE_EX1_043','CORE_CS2_029'),
            weapon_card_id='CS2_106',mana=10,max_mana=10),
        PlayerSetup('HERO_08'),),seed=41),build_registry())
    checkpoints=[]
    def check():
        snapshot=game.snapshot()
        assert Game.from_snapshot(snapshot,build_registry()).snapshot()==snapshot
        assert game.clone().snapshot()==snapshot
        assert replay(build_replay(game),build_registry()).snapshot()==snapshot
        checkpoints.append('waiting' if game.state.pending_choice else 'ready')
    def submit(action,listing):
        result=game.for_player(1).submit({'revision':listing['revision'],'action':action})
        assert result['accepted'],result.get('error')
        check()
    def play(cid,branch=None,target=None):
        listing=game.for_player(1).legal_actions();own=listing['observation']['players'][0]
        card=next(c for c in own['hand'] if c['card_id']==cid)
        target_ref=None if target is None else next(c['ref'] for c in own['board'] if c['card_id']==target)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==card['ref']
            and a.get('branch')==branch and a.get('target')==target_ref)
        submit(action,listing)
    def select(option):
        listing=game.for_player(1).legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='select_choice' and a['options']==[option])
        submit(action,listing)
    check();weapon=game.state.players[1].weapon_id
    attack=game.state.entities[weapon].attack
    play('CORE_CS2_074');assert game.state.entities[weapon].attack==attack+2
    original_deck=set(game.state.players[1].deck)
    play('CORE_DS1_184')
    assert game.for_player(2).legal_actions()['observation']['pending_choice']=={'player_id':1}
    select('o1')
    selected=game.state.players[1].hand[-1]
    assert selected in original_deck and selected not in game.state.players[1].deck
    play('TLC_245');select('o3')
    play('CORE_AT_037',branch='second')
    play('CORE_EX1_309',target='TLC_245')
    board=[game.state.entities[e].card_id for e in game.state.players[1].board]
    assert board==['CORE_CS2_182','AT_037t','AT_037t','UNG_999t2t1','UNG_999t2t1']
    assert game.state.players[1].mana==1
    result=dict(content_version=game.registry.version,formal_pool_complete=False,
        actions=len(game.history),checkpoints=checkpoints,
        weapon_attack=game.state.entities[weapon].attack,final_board=board,
        selected_original_deck_card=game.state.entities[selected].card_id,
        mana=game.state.players[1].mana,actual_deck_draw_events=len(game.state.draw_history))
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
