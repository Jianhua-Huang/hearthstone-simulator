"""Seven reviewed current-stat/draw roots through public player commands."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from examples.card_health_followups import hero_play
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup, Scenario


def main():
    def health(game,play,end,submit):
        hero_play(game,submit,'CORE_CS2_029',enemy=1)
        play(1,'CORE_EX1_619')
        assert all(game.state.entities[eid].health == 1 for eid in game.state.players[2].board)
        play(1,'CORE_RLK_087')
        assert [game.state.entities[eid].card_id for eid in game.state.players[2].board] == ['CS2_033']
        play(1,'EDR_255')
        assert not game.state.players[2].board
        assert game.state.entities[game.state.players[1].hero_id].health == 30
        assert game.state.entities[game.state.players[2].hero_id].health == 25
    first=exercise(Scenario((
        PlayerSetup('HERO_04',hand=('CORE_CS2_029','CORE_EX1_619','CORE_RLK_087','EDR_255'),
            deck=('CORE_CS2_182',)*4,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182','CS2_033'),deck=('CORE_CS2_182',)*4)),seed=263),health)

    def draws(game,play,end,submit):
        play(1,'END_003')
        assert game.state.draw_history[0].card_id == 'CORE_EX1_012'
        assert len(game.state.imbue_history) == 2
        play(1,'JAIL_377')
        assert [record.card_id for record in game.state.draw_history] == ['CORE_EX1_012','CORE_EX1_008','CORE_CS2_182']
    second=exercise(Scenario((
        PlayerSetup('HERO_11',hand=('END_003','JAIL_377'),deck=('CORE_EX1_012','CORE_EX1_008','CORE_CS2_182'),
            mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*4)),seed=264),draws)

    def buffs(game,play,end,submit):
        hero_play(game,submit,'TIME_447',enemy=1)
        play(1,'TIME_449');play(1,'CORE_EX1_008')
        entity=game.state.entities[game.state.players[1].board[0]]
        assert (entity.attack,entity.max_health) == (5,3)
        assert game.state.entities[game.state.players[1].hero_id].attack == 4
        end(1)
        assert game.state.entities[game.state.players[1].hero_id].attack == 0
    third=exercise(Scenario((
        PlayerSetup('HERO_09',hand=('TIME_447','TIME_449','CORE_EX1_008'),deck=(),
            mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*4)),seed=265),buffs)
    scenarios=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=7,
        actions=sum(s['actions'] for s in scenarios),checkpoints=sum(len(s['checkpoints']) for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints']) == (10,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__ == '__main__':main()
