"""Eight current Core roots through public player commands, with complete Medic."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from examples.card_health_followups import hero_play
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario


def main():
    def resources(game,play,end,submit):
        play(1,'CORE_AT_052');play(1,'CORE_BAR_878')
        hero_play(game,submit,'CORE_CS2_029',enemy=1)
        play(1,'CORE_CS1_112')
        assert sum(game.state.entities[e].card_id=='BAR_878t' for e in game.state.players[1].board)==1
        play(1,'CORE_BAR_313')
        priest=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CORE_BAR_313')
        assert (priest.attack,priest.health)==(8,8)
        assert game.state.entities[game.state.players[1].hero_id].health==26
        end(1);end(2)
        assert (game.state.players[1].overload_locked,game.state.players[1].mana)==(1,29)
    first=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_AT_052','CORE_BAR_878','CORE_CS2_029','CORE_CS1_112','CORE_BAR_313'),
            deck=('CORE_CS2_182',)*7,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*7)),seed=283),resources)

    def attacks(game,play,end,submit):
        play(1,'CORE_BT_351')
        submit(1,lambda listing:next(a for a in listing['actions'] if a['type']=='attack'))
        fiend=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CORE_BT_351')
        assert (fiend.attack,fiend.health)==(2,1)
        assert game.state.entities[game.state.players[1].hero_id].health==26
        assert game.state.entities[game.state.players[2].board[0]].health==5
    second=exercise(Scenario((
        PlayerSetup('HERO_03',hand=('CORE_BT_351',),weapon_card_id='CS2_082',
            deck=('CORE_CS2_182',)*7,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_BT_510',),deck=('CORE_CS2_182',)*7)),seed=284),attacks)

    def recruits(game,play,end,submit):
        play(1,'CORE_CFM_790');assert not game.state.draw_history
        play(1,'CORE_DMF_067');assert len(game.state.draw_history)==2
        play(1,'CORE_EX1_162')
        vendor=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CORE_DMF_067')
        assert vendor.attack==3
        def remove_own_vendor(listing):
            own=next(p for p in listing['observation']['players'] if p['id']==1)
            source=next(c['ref'] for c in own['hand'] if c['card_id']=='CORE_CS2_029')
            target=next(c['ref'] for c in own['board'] if c['card_id']=='CORE_DMF_067')
            return next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==source and a.get('target')==target)
        submit(1,remove_own_vendor)
        assert len(game.state.draw_history)==4
        rat=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CORE_CFM_790')
        assert rat.attack==3
    third=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_CFM_790','CORE_DMF_067','CORE_EX1_162','CORE_CS2_029'),
            deck=('CORE_CS2_182',)*7,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',hand=('CORE_DMF_067',),deck=('CORE_CS2_182',)*7)),seed=285),recruits)
    scenarios=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=8,new_tokens=1,
        actions=sum(s['actions'] for s in scenarios),checkpoints=sum(len(s['checkpoints']) for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(13,16)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
