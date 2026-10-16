"""Eight current roots and both non-vanilla tokens through actual player commands."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from hs_sim.engine import PlayerSetup, Scenario


def main():
    def native(game, play, end, submit):
        play(1, 'CORE_CS2_122'); play(1, 'CORE_CS2_222')
        squire = next(game.state.entities[e] for e in game.state.players[1].board
                      if game.state.entities[e].card_id == 'CORE_EX1_008')
        assert (squire.attack, squire.health) == (3, 2)
        play(1, 'CORE_EX1_059', 'CORE_CS2_182')
        enemy = game.state.entities[game.state.players[2].board[0]]
        assert (enemy.attack, enemy.health) == (5, 4)
        play(1, 'CORE_OG_044'); play(1, 'CORE_BT_156')
        sleeper = next(e for e in game.state.entities.values() if e.card_id == 'CORE_BT_156')
        assert not sleeper.active
        play(1, 'CORE_EX1_154', 'CORE_CS2_182')
        assert not game.state.players[2].board
        for player in (1, 2, 1, 2): end(player)
        sleeper = game.state.entities[sleeper.id]
        assert sleeper.active and (sleeper.attack, sleeper.health) == (5, 6)
    first = exercise(Scenario((
        PlayerSetup('HERO_06', hand=('CORE_CS2_122', 'CORE_CS2_222', 'CORE_EX1_059',
            'CORE_OG_044', 'CORE_BT_156', 'CORE_EX1_154'), board=('CORE_EX1_008',),
            deck=('CORE_CS2_182',)*4, mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_CS2_182',), deck=('CORE_CS2_182',)*4)), seed=239), native)

    trace = {}
    def tokens(game, play, end, submit):
        play(1, 'EDR_476')
        assert game.state.entities[game.state.players[2].hero_id].health == 25
        play(1, 'CAP_102'); play(1, 'EDR_817')
        cards = [game.state.entities[e].card_id for e in game.state.players[1].board]
        assert cards.count('CAP_107t') == cards.count('EDR_810t') == 2
        end(1)
        assert game.state.entities[game.state.players[1].hero_id].max_health == 32
        rows = [row.health_result for row in game.state.damage_history if row.health_result.source_card_id == 'CAP_107t']
        assert len(rows) == 2 and all(row.damage_dealt == 1 and row.spell_bonus == 0 for row in rows)
        assert not any(row.health_result.source_card_id == 'EDR_810t' for row in game.state.damage_history)
        trace.update(cannon_packets=len(rows), leech_max_health_gain=2,
                     enemy_max_health=game.state.entities[game.state.players[2].hero_id].max_health)
    second = exercise(Scenario((
        PlayerSetup('HERO_11', hand=('EDR_476', 'CAP_102', 'EDR_817'),
            board=('CORE_EX1_012', 'CORE_CS2_182'), deck=('CORE_CS2_182',)*6,
            mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_08', board=('CS2_033', 'CORE_EX1_008'), deck=('CORE_CS2_182',)*4)), seed=239), tokens)
    second.update(trace)
    result = dict(content_version='constructed-cn37-preview-v18', schema_version=SNAPSHOT_SCHEMA_VERSION,
        roots=8, dependencies=2, formal_pool_complete=False, cn_calibrated=False,
        actions=first['actions']+second['actions'],
        checkpoints=len(first['checkpoints'])+len(second['checkpoints']), waiting_choices=0,
        scenarios=[first, second])
    assert (result['actions'], result['checkpoints']) == (14, 16)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
