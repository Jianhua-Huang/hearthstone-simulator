"""True drawn entities and finite costs through the player command interface."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def main():
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('CORE_CS2_023', 'CORE_LOOT_309', 'JAIL_881', 'CATA_724', 'END_030'),
            deck=('EDR_260t', 'CAP_400t2t', 'JAIL_386t', 'JAIL_881t', 'SW_439t', 'CORE_CS2_182', 'CORE_CS2_182'),
            mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_03'),), seed=53), build_registry())
    original = list(game.state.players[1].deck)
    checkpoints = []
    def check():
        saved = game.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert game.clone().snapshot() == saved
        assert replay(build_replay(game), build_registry()).snapshot() == saved
        checkpoints.append('ready')
    def play(cid):
        listing = game.for_player(1).legal_actions()
        card = next(c for c in listing['observation']['players'][0]['hand'] if c['card_id'] == cid)
        action = next(a for a in listing['actions'] if a['type'] == 'play_card' and a['card'] == card['ref'])
        result = game.for_player(1).submit({'revision': listing['revision'], 'action': action})
        assert result['accepted'], result.get('error')
        check()
    check(); play('CORE_CS2_023')
    assert original[0] in game.state.players[1].board
    assert game.state.entities[original[1]].owner == 1 and game.state.entities[original[1]].controller == 2
    assert len(game.state.draw_history) == 7 and len(game.state.play_history) == 1
    assert [c.origin for c in game.state.cast_history] == ['hand', 'draw', 'draw', 'draw']
    assert [game.state.entities[e].card_id for e in game.state.players[1].hand[-2:]] == ['CORE_CS2_182']*2
    opposing = game.for_player(2).observe()['observation']['players'][0]['hand']
    assert opposing[-1]['card_id'] is None and opposing[-2]['card_id'] is None
    play('CORE_LOOT_309'); play('JAIL_881'); play('CATA_724')
    listing = game.for_player(1).legal_actions()
    frog = next(c for c in listing['observation']['players'][0]['hand'] if c['card_id'] == 'END_030')
    assert frog['cost']['amount'] == 3
    play('END_030')
    assert game.state.play_history[-1].cost == 3 and game.state.players[1].mana == 13
    assert game.state.players[1].overload_owed == 3 and game.state.pending_choice is None
    result = dict(content_version=game.registry.version, formal_pool_complete=False,
        actions=len(game.history), checkpoints=checkpoints, draws=len(game.state.draw_history),
        casts=len(game.state.cast_history), original_drawn_minions=original[:2],
        costs=[p.cost for p in game.state.play_history], mana=game.state.players[1].mana,
        overload_owed=game.state.players[1].overload_owed, waiting_choices=0)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__':
    main()
