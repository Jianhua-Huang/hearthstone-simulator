"""Six reviewed conditional spells through public player commands."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from examples.card_health_followups import hero_play
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup, Scenario


def main():
    def prices(game, play, end, submit):
        play(1, 'CORE_CS2_072', 'CORE_CS2_182')
        play(1, 'CORE_BT_801', 'CORE_CS2_182')
        assert not any(game.state.entities[e].card_id == 'CORE_CS2_182' for e in game.state.players[2].board)
        play(1, 'CATA_203', 'CORE_EX1_012')
        play(1, 'CATA_308')
        assert game.state.players[1].mana == 26
        assert not game.state.players[2].board
        fandral = game.state.entities[game.state.players[1].board[0]]
        assert (fandral.card_id, fandral.health) == ('CORE_OG_044', 2)
    first = exercise(Scenario((
        PlayerSetup('HERO_08', hand=('CORE_CS2_072', 'CORE_BT_801', 'CATA_203', 'CATA_308'),
            board=('CORE_OG_044',), deck=('CORE_CS2_182',)*4, mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_CS2_182', 'CORE_EX1_012'), deck=('CORE_CS2_182',)*4)), seed=241), prices)

    trace = {}
    def results(game, play, end, submit):
        hero_play(game, submit, 'CORE_CS2_029', enemy=1)
        hero_play(game, submit, 'CORE_CS2_029')
        assert (game.state.entities[game.state.players[1].hero_id].health,
                game.state.entities[game.state.players[2].hero_id].health) == (23, 23)
        play(1, 'CATA_303', 'CORE_CS2_182')
        assert game.state.entities[game.state.players[2].hero_id].health == 28
        play(1, 'CORE_BAR_311')
        rows = [row.health_result for row in game.state.damage_history if row.health_result.source_card_id == 'CORE_BAR_311']
        assert [row.damage_dealt for row in rows] == [0, 1]
        assert game.state.entities[game.state.players[1].hero_id].health == 24
        assert game.state.entities[game.state.players[2].hero_id].health == 28
        assert not game.state.players[2].board
        trace.update(split_packets=2, actual_split_damage=1, enemy_hero_healed=5)
    second = exercise(Scenario((
        PlayerSetup('HERO_08', hand=('CORE_CS2_029', 'CORE_CS2_029', 'CATA_303', 'CORE_BAR_311'),
            board=('CORE_EX1_012',), deck=('CORE_CS2_182',)*4, mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_CS2_182', 'CORE_EX1_008'), deck=('CORE_CS2_182',)*4)), seed=241), results)
    second.update(trace)
    result = dict(content_version=CONTENT_VERSION, snapshot_schema=SNAPSHOT_SCHEMA_VERSION, roots=6,
        formal_pool_complete=False, cn_calibrated=False, waiting_choices=0,
        actions=first['actions']+second['actions'],
        checkpoints=len(first['checkpoints'])+len(second['checkpoints']), scenarios=[first, second])
    assert (result['actions'], result['checkpoints']) == (8, 10)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
