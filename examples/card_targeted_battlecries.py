"""Twelve actual stat/zone/choice/removal roots through public player commands."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


def targeted(submit,cid,target_cid,*,zone='board',player=1):
    def choose(listing):
        players={p['id']:p for p in listing['observation']['players']}
        source=next(c['ref'] for c in players[1]['hand'] if c['card_id']==cid)
        target=next(c['ref'] for c in players[player][zone] if c['card_id']==target_cid)
        return next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==source and a.get('target')==target)
    submit(1,choose)


def body(game,cid,player=1):
    return next(game.state.entities[e] for e in game.state.players[player].board if game.state.entities[e].card_id==cid)


def main():
    def hand(game,play,end,submit):
        targeted(submit,'CATA_161','EDR_227',zone='hand');play(1,'TIME_429')
        targeted(submit,'EDR_518','EDR_227',zone='hand');play(1,'FIR_960')
        copies=[game.state.entities[e] for e in game.state.players[1].hand if game.state.entities[e].card_id=='EDR_227']
        assert len(copies)==2 and all((c.attack,c.health)==(8,8) for c in copies)
        state=game.state;assert all(quote_cost(state,game.registry,state.entities[c.id]).amount==3 for c in copies)
        targeted(submit,'CATA_200','CORE_CS2_029',zone='hand')
        before=game.state.players[1].mana;play(1,'GAME_005');assert game.state.players[1].mana==before+1
        assert len(game.state.imbue_history)==1
    first=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('CATA_161','CATA_200','EDR_518','TIME_429','FIR_960','CORE_CS2_182','EDR_227','CORE_CS2_029'),
            deck=('CORE_CS2_182',)*4,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*4)),seed=338),hand)

    def destruction(game,play,end,submit):
        targeted(submit,'CORE_EX1_198','EDR_227',player=2);assert body(game,'CORE_EX1_198').health==3
        targeted(submit,'CORE_ULD_165','CORE_CS2_182',player=2)
        assert game.state.entities[game.state.players[1].hero_id].health==25
        target=body(game,'CORE_EX1_008',2).id;targeted(submit,'TIME_435','CORE_EX1_008',player=2)
        assert target in game.state.players[1].board and game.state.entities[target].owner==2
    second=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('CORE_EX1_198','CORE_ULD_165','TIME_435'),deck=('CORE_CS2_182',)*4,
            mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=('EDR_227','CORE_CS2_182','CORE_EX1_008'),deck=('CORE_CS2_182',)*4)),seed=339),destruction)

    def choosing(game,play,end,submit):
        play(1,'CORE_ULD_178');assert game.state.pending_choice is not None
        submit(1,lambda listing:next(a for a in listing['actions'] if a['type']=='select_choice'))
        assert len(body(game,'CORE_ULD_178').keywords)==2
        play(1,'TLC_233');assert (body(game,'CORE_EX1_008').attack,body(game,'CORE_EX1_008').health)==(2,2)
        targeted(submit,'TLC_606','CORE_EX1_012',player=2)
        assert game.state.entities[game.state.players[1].hero_id].armor==5
    third=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('CORE_ULD_178','TLC_233','TLC_606'),board=('CORE_EX1_008',),
            deck=('CORE_CS2_182',)*4,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=('CORE_EX1_012','CORE_CS2_182'),deck=('CORE_CS2_182',)*4)),seed=340),choosing)

    def classes(game,play,end,submit):
        play(1,'JAIL_118')
        assert set(game.state.entities[e].card_id for e in game.state.players[1].board)=={'CORE_EX1_383','JAIL_118'}
        assert [game.state.entities[e].card_id for e in game.state.players[2].board]==['CORE_BAR_878']
        assert len(game.state.death_history)==2
    fourth=exercise(Scenario((
        PlayerSetup('HERO_05',hand=('JAIL_118',),board=('CORE_EX1_383','CORE_CS2_182'),
            deck=('CORE_CS2_182',)*4,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=('CORE_BAR_878','CORE_CS2_182'),deck=('CORE_CS2_182',)*4)),seed=341),classes)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=12,new_tokens=0,reused_dependencies=1,actions=sum(s['actions'] for s in scenarios),
        checkpoints=sum(len(s['checkpoints']) for s in scenarios),scenarios=scenarios,
        formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(14,18)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
