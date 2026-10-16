"""Eight native Deathrattles through public commands and portable checkpoints."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost


def attack(submit,player,attacker_card,defender_card=None):
    def choose(listing):
        players={p['id']:p for p in listing['observation']['players']}
        own,other=players[player],players[3-player]
        attacker=(own['hero']['ref'] if attacker_card is None else
            next(c['ref'] for c in own['board'] if c['card_id']==attacker_card))
        defender=(other['hero']['ref'] if defender_card is None else
            next(c['ref'] for c in other['board'] if c['card_id']==defender_card))
        return next(a for a in listing['actions'] if a['type']=='attack' and
            a['attacker']==attacker and a['defender']==defender)
    submit(player,choose)


def main():
    def dragons(game,play,end,submit):
        play(1,'CORE_AT_123');play(1,'CORE_EX1_309','CORE_AT_123')
        assert game.state.entities[game.state.players[2].board[0]].health==2
        play(1,'EDR_890');play(1,'CORE_CS2_029','EDR_890')
        state=game.state;held=state.entities[state.players[1].hand[-1]]
        assert held.card_id=='CORE_CS2_182' and quote_cost(state,game.registry,held).amount==2
    first=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_AT_123','EDR_890','CORE_EX1_309','CORE_CS2_029','CORE_CS2_182'),
            deck=('CORE_CS2_182',)*3,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*3)),seed=294),dragons)

    def missiles(game,play,end,submit):
        play(1,'CORE_BT_201');play(1,'CORE_EX1_309','CORE_BT_201')
        assert game.state.entities[game.state.players[2].hero_id].health==28
        play(1,'CORE_DRG_107');play(1,'CORE_EX1_309','CORE_DRG_107');play(1,'EX1_277')
        assert game.state.entities[game.state.players[2].hero_id].health==24
        rows=[r.health_result for r in game.state.damage_history]
        assert sum(r.source_card_id=='CORE_BT_201' for r in rows)==2
        assert sum(r.source_card_id=='EX1_277' for r in rows)==4
    second=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_BT_201','CORE_DRG_107','CORE_EX1_309','CORE_EX1_309'),
            board=('CORE_EX1_012',),deck=('CORE_CS2_182',)*3,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*3)),seed=295),missiles)

    def swords(game,play,end,submit):
        old=game.state.players[1].weapon_id
        play(1,'CORE_EX1_383');play(1,'CORE_EX1_309','CORE_EX1_383')
        sword=game.state.entities[game.state.players[1].weapon_id]
        assert (sword.card_id,sword.attack,sword.durability)==('EX1_383t',5,3)
        assert game.state.entities[old].zone.value=='graveyard'
        play(1,'CORE_WC_701');attack(submit,1,'CORE_WC_701','CORE_CS2_182')
        bodies=[game.state.entities[e] for e in game.state.players[2].board]
        assert [(e.card_id,e.health) for e in bodies]==[('CORE_CS2_182',1),('CORE_EX1_008',1)]
        attack(submit,1,None)
        assert game.state.entities[game.state.players[2].hero_id].health==25
        assert game.state.entities[sword.id].durability==2
    third=exercise(Scenario((
        PlayerSetup('HERO_03',hand=('CORE_EX1_383','CORE_EX1_309','CORE_WC_701'),
            weapon_card_id='CS2_082',deck=('CORE_CS2_182',)*3,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182','CORE_EX1_008'),deck=('CORE_CS2_182',)*3)),seed=296),swords)

    def forest(game,play,end,submit):
        play(1,'EDR_227');attack(submit,1,'EDR_227','CORE_CS2_182')
        power=game.state.entities[game.state.players[1].hero_power_id]
        assert power.card_id=='EDR_850p' and len(game.state.imbue_history)==1
        play(1,'EDR_978');original=game.state.players[1].board[0]
        play(1,'CORE_EX1_309','EDR_978')
        assert len(game.state.players[1].deck)==1 and game.state.players[1].deck[0]!=original
        play(1,'CORE_CS2_023')
        state=game.state;held=state.entities[state.players[1].hand[0]]
        assert (held.card_id,held.attack,held.max_health)==('EDR_978',6,11)
        assert quote_cost(state,game.registry,held).amount==1
    fourth=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('EDR_227','EDR_978','CORE_EX1_309','CORE_CS2_023'),
            mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*3)),seed=297),forest)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=8,new_tokens=1,reused_dependencies=1,
        actions=sum(s['actions'] for s in scenarios),checkpoints=sum(len(s['checkpoints']) for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(19,23)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
