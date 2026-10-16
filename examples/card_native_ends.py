"""Twelve native ending roots and three complete fixed tokens via player DTOs."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from examples.card_health_followups import hero_play
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario


def main():
    def common(game,play,end,submit):
        hero_play(game,submit,'CORE_CS2_029',enemy=1)
        play(1,'CAP_107');play(1,'CAP_107t');end(1)
        matriarch=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CATA_305')
        assert (matriarch.attack,matriarch.health)==(5,7)
        assert game.state.entities[game.state.players[1].hero_id].health==27
        assert game.state.entities[game.state.players[2].hero_id].health==28
    first=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_CS2_029','CAP_107'),
            board=('CATA_133','CATA_305','EDR_816','CATA_999','EDR_971'),
            deck=('CORE_CS2_182',)*6,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*6)),seed=271),common)

    def tokens(game,play,end,submit):
        end(1)
        bodies={game.state.entities[e].card_id:game.state.entities[e] for e in game.state.players[1].board}
        assert (bodies['CATA_476t'].attack,bodies['CATA_476t'].health)==(6,6)
        assert Keyword.DIVINE_SHIELD in bodies['CATA_476t'].keywords
        assert (bodies['CATA_478t'].attack,bodies['CATA_478t'].health)==(3,3)
        assert Keyword.DIVINE_SHIELD in game.state.entities[game.state.players[1].hero_id].keywords
        assert game.state.entities[game.state.players[2].board[0]].health==3
        end(2)
        assert len(game.state.players[1].board)==6
    second=exercise(Scenario((
        PlayerSetup('HERO_08',board=('CATA_475','CATA_476','CATA_478','EDR_942'),
            deck=('CORE_CS2_182',)*6,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*6)),seed=272),tokens)

    def either(game,play,end,submit):
        end(1);end(2)
        play(1,'CORE_CS2_029','JAIL_883')
        reborn=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='JAIL_883')
        assert reborn.health==1 and Keyword.REBORN not in reborn.keywords
        end(1)
        reborn=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='JAIL_883')
        assert Keyword.REBORN in reborn.keywords
        coins=lambda p:sum(game.state.entities[e].card_id=='GAME_005' for e in game.state.players[p].hand)
        assert (coins(1),coins(2))==(2,1)
    third=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_CS2_029',),board=('JAIL_883','TIME_054'),
            deck=('CORE_CS2_182',)*6,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*6)),seed=273),either)
    scenarios=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=12,new_tokens=2,reused_tokens=1,
        actions=sum(s['actions'] for s in scenarios),checkpoints=sum(len(s['checkpoints']) for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(10,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
