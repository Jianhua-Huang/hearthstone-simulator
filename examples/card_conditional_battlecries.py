"""Sixteen native conditional/stat/zone roots through public player commands."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_death_followups import attack
from examples.card_health_followups import hero_play
from examples.card_reactive_secrets import exercise
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


def body(game,cid,p=1):
    return next(game.state.entities[e] for e in game.state.players[p].board if game.state.entities[e].card_id==cid)


def main():
    def imbued(game,play,end,submit):
        play(1,'DINO_411');assert game.state.draw_history[0].card_id=='EDR_810t'
        play(1,'EDR_970');target=body(game,'CORE_CS2_182',2).id
        assert game.state.entities[target].attack==2
        play(1,'END_001');play(1,'FIR_921');assert len(game.state.imbue_history)==2
        assert len(game.state.draw_history)==3
        hero_play(game,submit,'CORE_CS2_029',enemy=1);play(1,'EDR_860','CORE_CS2_182')
        assert game.state.entities[target].health==1
        assert game.state.entities[game.state.players[1].hero_id].health==28
        attack(submit,1,None);assert game.state.entities[game.state.players[1].weapon_id].durability==1
        end(1);assert game.state.entities[target].attack==2
        end(2);assert game.state.entities[target].attack==4
    first=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('DINO_411','EDR_970','END_001','FIR_921','CORE_CS2_029','EDR_860'),
            deck=('EDR_810t',)+('CORE_CS2_182',)*4,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*4)),seed=318),imbued)

    def attributes(game,play,end,submit):
        play(1,'CATA_612');play(1,'CORE_OG_149')
        def hit_enemy(listing):
            players={p['id']:p for p in listing['observation']['players']}
            source=next(c['ref'] for c in players[1]['hand'] if c['card_id']=='EDR_472')
            target=next(c['ref'] for c in players[2]['board'] if c['card_id']=='CORE_CS2_182')
            return next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==source and a.get('target')==target)
        submit(1,hit_enemy);assert body(game,'CORE_CS2_182',2).health==1
        play(1,'FIR_961');play(1,'TIME_720');play(1,'TIME_871')
        assert body(game,'CATA_612').frozen
        assert (body(game,'TIME_720').health,body(game,'TIME_871').attack,body(game,'TIME_871').health)==(6,8,12)
    second=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CATA_612','CORE_OG_149','EDR_472','FIR_961','TIME_720','TIME_871','CORE_CS2_032'),
            board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*4,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*4)),seed=319),attributes)

    def histories(game,play,end,submit):
        hero_play(game,submit,'CORE_CS2_029',enemy=1);play(1,'END_019')
        assert (body(game,'END_019').attack,body(game,'END_019').health)==(8,9)
        def use_power(listing):
            enemy=next(p for p in listing['observation']['players'] if p['id']==2)
            return next(a for a in listing['actions'] if a['type']=='use_hero_power' and a.get('target')==enemy['hero']['ref'])
        submit(1,use_power);play(1,'FIR_777');assert body(game,'FIR_777').attack==4
        play(1,'JAIL_513');assert body(game,'JAIL_513').health==2
        before=list(game.state.players[1].deck);play(1,'TIME_705')
        state=game.state;assert state.players[1].deck==before
        assert [quote_cost(state,game.registry,state.entities[e]).amount for e in before]==[4,4,1,1,1,1,1]
    third=exercise(Scenario((
        PlayerSetup('HERO_08',hand=('CORE_CS2_029','END_019','FIR_777','JAIL_513','TIME_705'),
            hero_power_card_id='HERO_08bp',deck=('CORE_CS2_029',)*7,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*4)),seed=320),histories)

    def physical(game,play,end,submit):
        play(1,'JAIL_456');assert len(game.state.players[1].deck)==24
        play(1,'TLC_633','CORE_EX1_012')
        assert not any(game.state.entities[e].card_id=='CORE_EX1_012' for e in game.state.players[2].board)
    fourth=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('JAIL_456','TLC_633'),deck=('CORE_CS2_182',)*25,
            mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=('CORE_CS2_182','CORE_EX1_012'),deck=('CORE_CS2_182',)*4)),seed=321),physical)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=16,new_tokens=0,actions=sum(s['actions'] for s in scenarios),
        checkpoints=sum(len(s['checkpoints']) for s in scenarios),scenarios=scenarios,
        formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(23,27)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
