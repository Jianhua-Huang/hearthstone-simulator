"""Four new real-card actions through PlayerPort, with recovery and replay checks."""

import json

from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def main():
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('CORE_EX1_606', 'TIME_023', 'EDR_253'),
            deck=('CORE_CS2_182', 'CORE_EX1_096', 'CORE_BT_292', 'CORE_EX1_012', 'RLK_503'),
            mana=10, max_mana=10),
        PlayerSetup('HERO_08', deck=('CORE_CS2_182',)),
    )), build_registry())
    checkpoints = []

    def check():
        saved = game.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert game.clone().snapshot() == saved
        assert replay(build_replay(game), build_registry()).snapshot() == saved
        checkpoints.append('ready')

    def submit(choose):
        listing = game.for_player(1).legal_actions()
        action = choose(listing)
        reply = game.for_player(1).submit({'revision': listing['revision'], 'action': action})
        assert reply['accepted'], reply['error']
        check()

    check()
    for cid in ('CORE_EX1_606', 'TIME_023', 'EDR_253'):
        def choose(listing, cid=cid):
            own = next(p for p in listing['observation']['players'] if p['id'] == 1)
            card = next(c for c in own['hand'] if c['card_id'] == cid)
            return next(a for a in listing['actions'] if a['type'] == 'play_card' and a['card'] == card['ref'])
        submit(choose)
    def attack(listing):
        players = {p['id']: p for p in listing['observation']['players']}
        return next(a for a in listing['actions'] if a['type'] == 'attack'
                    and a['attacker'] == players[1]['hero']['ref']
                    and a['defender'] == players[2]['hero']['ref'])
    submit(attack)
    state = game.state
    result = dict(formal_pool_complete=False, content_version=game.registry.version,
        actions=len(game.history), checkpoints=checkpoints, mana=state.players[1].mana,
        armor=state.entities[state.players[1].hero_id].armor,
        enemy_health=state.entities[state.players[2].hero_id].health,
        draws=[d.card_id for d in state.draw_history],
        remaining_deck=[state.entities[e].card_id for e in state.players[1].deck])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == '__main__':
    main()
