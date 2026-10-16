"""Seven real roots through player commands; generation remains experimental."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from examples.card_health_followups import hero_play
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.costs import quote_cost


def main():
    def health(game, play, end, submit):
        hero_play(game, submit, 'CORE_CS2_029', enemy=1)
        play(1, 'CATA_526')
        assert sum(record.player_id == 1 for record in game.state.draw_history) == 2
        play(1, 'CORE_CS2_053')
        state = game.state; drawn = state.draw_history[-1].entity_id
        assert quote_cost(state, game.registry, state.entities[drawn]).amount == 1
        hero_play(game, submit, 'EDR_231', enemy=1)
        assert len(game.state.imbue_history) == 1
        play(1, 'CATA_491')
        assert not game.state.players[2].board
        assert game.state.entities[game.state.players[1].hero_id].health == 27
    first = exercise(Scenario((
        PlayerSetup('HERO_02', hand=('CORE_CS2_029','CATA_526','CORE_CS2_053','EDR_231','CATA_491'),
            board=('CORE_EX1_012',), deck=('CORE_CS2_182',)*7, mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08', board=('CS2_033','CORE_EX1_008'), deck=('CORE_CS2_182',)*5)),seed=251),health)

    def flood(game, play, end, submit):
        play(1,'CATA_533'); assert not game.state.players[2].board
    second = exercise(Scenario((
        PlayerSetup('HERO_08', hand=('CATA_533',), deck=('CORE_CS2_182',)*5,
            mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_EX1_008','CORE_CS2_182','CORE_EX1_012'),
            deck=('CORE_CS2_182',)*5)),seed=252),flood)

    def rite(game, play, end, submit):
        play(1,'GAME_005'); play(1,'CATA_785','CORE_CS2_182')
        assert len(game.state.herald_history) == 1
        assert game.state.entities[game.state.players[2].board[0]].health == 2
    third = exercise(Scenario((
        PlayerSetup('HERO_03', hand=('GAME_005','CATA_785'), deck=('CORE_CS2_182',)*5,
            mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*5)),seed=253,
        generation_context=GenerationContext('local-2026-09-23','experimental')),rite)

    def animation(game, play, end, submit):
        play(1,'CATA_156'); assert len(game.state.herald_history) == 1
        assert game.state.entities[game.state.players[2].board[0]].health == 1
    fourth = exercise(Scenario((
        PlayerSetup('HERO_11', hand=('CATA_156',), deck=('CORE_CS2_182',)*5,
            mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*5)),seed=254,
        generation_context=GenerationContext('local-2026-09-23','experimental')),animation)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=7,
        actions=sum(s['actions'] for s in scenarios),checkpoints=sum(len(s['checkpoints']) for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints']) == (9,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True)); return result


if __name__ == '__main__': main()
