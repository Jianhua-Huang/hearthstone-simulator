"""Two new real-card paths driven only by bound player JSON actions."""

import json

from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def run_case(case):
    if case == 'spell_and_battlecry':
        players=(PlayerSetup('HERO_08',hand=('CORE_CS2_042','CORE_TRL_307'),
                             deck=('CORE_CS2_182',)*2,mana=10,max_mana=10),
                 PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*2))
    else:
        players=(PlayerSetup('HERO_08',hand=('EDR_459',),board=('CORE_CS2_182',),
                             deck=('CORE_CS2_182',)*2,mana=10,max_mana=10),
                 PlayerSetup('HERO_08',board=('TLC_248',),deck=('CORE_CS2_182',)*2))
    game=Game.from_scenario(Scenario(players),build_registry())
    checkpoints=[]

    def check():
        saved=game.snapshot()
        assert Game.from_snapshot(saved,build_registry()).snapshot()==saved
        assert game.clone().snapshot()==saved
        assert replay(build_replay(game),build_registry()).snapshot()==saved
        checkpoints.append('waiting' if game.state.pending_choice else 'ready')

    def submit(seat, choose):
        listing=game.for_player(seat).legal_actions()
        action=choose(listing)
        reply=game.for_player(seat).submit({'revision':listing['revision'],'action':action})
        assert reply['accepted'],reply['error']
        check()

    def play(cid,target_seat=None):
        def choose(listing):
            players={p['id']:p for p in listing['observation']['players']}
            card=next(c for c in players[1]['hand'] if c['card_id']==cid)
            target=None if target_seat is None else players[target_seat]['hero']['ref']
            return next(a for a in listing['actions'] if a['type']=='play_card'
                        and a['card']==card['ref'] and (target is None or a.get('target')==target))
        return choose

    check()
    if case=='spell_and_battlecry':
        submit(1,play('CORE_CS2_042',2))
        submit(1,play('CORE_TRL_307',1))
    else:
        submit(1,play('EDR_459'))
        submit(1,lambda listing: next(a for a in listing['actions'] if a['type']=='end_turn'))
        def attack(listing):
            players={p['id']:p for p in listing['observation']['players']}
            target=next(c['ref'] for c in players[1]['board'] if c['card_id']=='EDR_459')
            return next(a for a in listing['actions'] if a['type']=='attack' and a['defender']==target)
        submit(2,attack)
    state=game.state
    return {'case':case,'actions':len(game.history),'checkpoints':checkpoints,
            'mana':state.players[1].mana,
            'enemy_health':state.entities[state.players[2].hero_id].health,
            'boards':[[[state.entities[e].card_id,state.entities[e].health] for e in p.board]
                      for p in state.players.values()]}


def main():
    result={'formal_pool_complete':False,'cases':[run_case(case) for case in
            ('spell_and_battlecry','battlecry_and_deathrattle')]}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result


if __name__=='__main__':
    main()
