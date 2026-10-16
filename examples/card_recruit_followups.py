"""Real recruit grants and normal attacks through the player command interface."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game, Keyword, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def main():
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_09',hand=('JAIL_516','DINO_131','CORE_CS2_029','TLC_600','TLC_816'),
            deck=('CORE_SW_439','CORE_SW_439','TLC_366'),mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_03',board=('CORE_CS2_182',))),seed=83),build_registry())
    originals=list(game.state.players[1].deck);checkpoints=[]
    def check():
        saved=game.snapshot()
        assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert game.clone().snapshot()==saved
        assert replay(build_replay(game),build_registry()).snapshot()==saved
        checkpoints.append('ready')
    def submit(listing,action):
        result=game.for_player(1).submit({'revision':listing['revision'],'action':action})
        assert result['accepted'],result.get('error');check()
    def play(cid,target=None):
        listing=game.for_player(1).legal_actions();own=listing['observation']['players'][0]
        card=next(c for c in own['hand'] if c['card_id']==cid)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==card['ref'] and a.get('target')==target)
        submit(listing,action)
    check();play('JAIL_516')
    assert all(Keyword.RUSH in game.state.entities[e].keywords for e in originals[:2])
    play('DINO_131');listing=game.for_player(1).legal_actions()
    doctor=next(c['ref'] for c in listing['observation']['players'][0]['board'] if c['card_id']=='DINO_131')
    play('CORE_CS2_029',doctor)
    assert originals[2] in game.state.players[1].board
    assert Keyword.LIFESTEAL in game.state.entities[originals[2]].keywords
    listing=game.for_player(1).legal_actions();own,enemy=listing['observation']['players']
    wing=next(c['ref'] for c in own['board'] if c['card_id']=='TLC_366');target=enemy['board'][0]['ref']
    attack=next(a for a in listing['actions'] if a['type']=='attack' and a['attacker']==wing and a['defender']==target)
    submit(listing,attack)
    listing=game.for_player(1).legal_actions();enemy_hero=listing['observation']['players'][1]['hero']['ref']
    play('TLC_600',enemy_hero);play('TLC_816')
    assert game.state.players[1].mana==4 and game.state.pending_choice is None
    assert sum(e.kind=='recruit_followup_started' for e in game.events)==3
    public=json.dumps(game.for_player(2).observe())+json.dumps(game.player_events(2))
    assert 'recruit_followup_started' not in public and 'followup_started' not in public
    result=dict(content_version=game.registry.version,schema_version=game.snapshot()['schema_version'],
        formal_pool_complete=False,actions=len(game.history),checkpoints=checkpoints,
        original_recruits=originals,followups=3,costs=[r.cost for r in game.state.play_history],
        mana=game.state.players[1].mana,waiting_choices=0)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
