"""Eight real Battlecry roots via public commands and portable checkpoints."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_death_followups import attack
from examples.card_health_followups import hero_play
from examples.card_reactive_secrets import exercise
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario


def main():
    def current_attack(game,play,end,submit):
        play(1,'TIME_449');play(1,'CORE_NEW1_018')
        raider=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CORE_NEW1_018')
        assert raider.attack==3 and game.state.entities[game.state.players[1].hero_id].attack==5
        play(1,'CORE_TRL_240','CORE_CS2_182')
        assert not any(game.state.entities[e].card_id=='CORE_CS2_182' for e in game.state.players[2].board)
        def freeze_enemy_hero(listing):
            players={p['id']:p for p in listing['observation']['players']}
            card=next(c['ref'] for c in players[1]['hand'] if c['card_id']=='CORE_UNG_205')
            return next(a for a in listing['actions'] if a['type']=='play_card' and
                a['card']==card and a.get('target')==players[2]['hero']['ref'])
        submit(1,freeze_enemy_hero);play(1,'CORE_OG_149')
        assert game.state.entities[game.state.players[2].hero_id].frozen
        assert game.state.entities[raider.id].health==2
        ghoul=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CORE_OG_149')
        assert ghoul.health==3
    first=exercise(Scenario((
        PlayerSetup('HERO_03',hand=('TIME_449','CORE_NEW1_018','CORE_TRL_240','CORE_UNG_205','CORE_OG_149'),
            weapon_card_id='CS2_082',deck=('CORE_CS2_182',)*4,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182','CORE_EX1_008'),deck=('CORE_CS2_182',)*4)),seed=308),current_attack)

    def living_forest(game,play,end,submit):
        play(1,'CORE_GIL_623')
        bear=next(game.state.entities[e] for e in game.state.players[1].board if game.state.entities[e].card_id=='CORE_GIL_623')
        assert (bear.health,bear.max_health)==(9,9)
        play(1,'EDR_226');assert game.state.draw_history[0].card_id=='EDR_227'
        play(1,'EDR_449');play(1,'EDR_800')
        assert len(game.state.imbue_history)==3
        assert game.state.entities[game.state.players[1].hero_power_id].card_id=='EDR_850p'
        hero_play(game,submit,'CORE_CS2_029',enemy=1);end(1);end(2)
        attack(submit,1,'EDR_449','CORE_CS2_182')
        assert game.state.entities[game.state.players[1].hero_id].health==27
    second=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('CORE_GIL_623','EDR_226','EDR_449','EDR_800','CORE_CS2_029'),
            deck=('EDR_227','CORE_CS2_182','CORE_CS2_182','CORE_CS2_182'),mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',hand=('CORE_CS2_182',)*3,board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*4)),seed=309),living_forest)
    scenarios=[first,second]
    result=dict(content_version=CONTENT_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=8,new_tokens=0,
        actions=sum(s['actions'] for s in scenarios),checkpoints=sum(len(s['checkpoints']) for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(13,15)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
