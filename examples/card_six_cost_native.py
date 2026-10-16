"""Native player DTO checks for eleven actual summon-pool dependencies."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario,Keyword,Zone
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.model import Resource
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';FROST='CORE_CS2_024';FIRE='CORE_CS2_029'


def setup(hand,board=(),enemy=(),corpses=0,seed=1047):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*10,corpses=corpses,
        mana=60,max_mana=60,mana_cap=60),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*10,
        mana=60,max_mana=60,mana_cap=60)),seed=seed)


def board(g,p=1):
    s=g.state;return[s.entities[i]for i in s.players[p].board]


def main():
    scenarios=[]
    def marrow(g,play,end,submit):
        play(1,'CORE_RLK_505');s=g.state
        assert s.players[1].resources[Resource.CORPSES]==0
        assert s.entities[s.players[2].hero_id].health==24
    scenarios.append(session(setup(('CORE_RLK_505',),corpses=3),marrow))

    def merithra(g,play,end,submit):
        play(1,FIRE,target_card='GIL_820');assert not board(g)
        play(1,'EDR_238');assert sorted(e.card_id for e in board(g))==['EDR_238','GIL_820']
        assert len(g.state.battlecry_history)==1
    scenarios.append(session(setup((FIRE,'EDR_238'),board=('GIL_820',)),merithra))

    def flame(g,play,end,submit):
        play(1,'FIR_940');s=g.state
        assert sorted(quote_unselected_cost(s,g.registry,s.entities[i]).amount for i in s.players[1].hand)==[0,2]
    scenarios.append(session(setup(('FIR_940',FROST,YETI)),flame))

    def gnome(g,play,end,submit):
        play(1,FROST,target_player=1);end(1);s=g.state
        assert s.entities[s.players[1].hero_id].health==30
        assert board(g)[0].health==2 and not board(g,2)
    scenarios.append(session(setup((FROST,),board=('RLK_720',),enemy=(YETI,)),gnome))

    def machine(g,play,end,submit):
        play(1,'TIME_043',target_card=YETI);e=next(e for e in board(g)if e.card_id==YETI)
        assert(e.attack,e.health)==(8,8)
        assert any(a.kind=='attack_policy'for a in e.abilities)
        end(1);end(2);e=next(e for e in board(g)if e.card_id==YETI)
        assert(e.attack,e.health)==(8,8)
    scenarios.append(session(setup(('TIME_043',),board=(YETI,)),machine))

    def hourglass(g,play,end,submit):
        play(1,FROST,target_card='TIME_050');e=board(g)[0]
        assert(e.attack,e.health,e.max_health)==(6,4,4)
    scenarios.append(session(setup((FROST,),board=('TIME_050',)),hourglass))

    def stalker_kindred(g,play,end,submit):
        play(1,'TIME_605');assert len(board(g))==2
        assert all({Keyword.RUSH,Keyword.ELUSIVE}<=e.keywords for e in board(g))
        end(1);end(2);play(1,'TLC_454');assert [e.card_id for e in board(g,2)]==['CORE_CS2_231']
    scenarios.append(session(setup(('TIME_605','TLC_454'),enemy=(YETI,'CORE_CS2_231')),stalker_kindred))

    def stegodon(g,play,end,submit):
        play(1,FIRE,target_card='TLC_401');s=g.state
        assert not board(g)and not board(g,2)
        assert s.entities[s.players[2].hero_id].health==24
        assert len([e for e in g.events if e.kind=='damage_dealt'and e.source_id!=g.state.cast_history[0].source_id])==3
    scenarios.append(session(setup((FIRE,),board=('TLC_401',),enemy=(YETI,YETI)),stegodon))

    def opu(g,play,end,submit):
        play(1,'TLC_522');assert len([c for c in g.state.cast_history if c.card_id=='EX1_129'])==1
        play(1,FIRE,target_card='TLC_522')
        assert len([c for c in g.state.cast_history if c.card_id=='EX1_129'])==2
    scenarios.append(session(setup(('TLC_522',FIRE),enemy=(YETI,)),opu))

    def opu_combo(g,play,end,submit):
        play(1,'GAME_005');play(1,'TLC_522');s=g.state
        fans=[c for c in s.cast_history if c.card_id=='EX1_129'];assert len(fans)==2 and not board(g,2)
        starts=[e.sequence for e in g.events if e.kind=='spell_cast_started'and e.source_id in(c.source_id for c in fans)]
        death=next(e.sequence for e in g.events if e.kind=='minion_died')
        assert starts[0]<death<starts[1]
    scenarios.append(session(setup(('GAME_005','TLC_522'),enemy=('CORE_CS2_231',)),opu_combo))

    def nablya(g,play,end,submit):
        original=board(g)[0].id;play(1,FROST,target_card=YETI);play(1,'TLC_624')
        copies=[e for e in board(g)if e.origin_entity_id==original];assert len(copies)==1
        e=copies[0];assert(e.attack,e.health,e.max_health)==(4,2,5)and Keyword.RUSH in e.keywords
    scenarios.append(session(setup((FROST,'TLC_624'),board=(YETI,)),nablya))
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=11,dependencies=1,lab_fixture_definitions=0,actions=sum(s['actions']for s in scenarios),
        checkpoints=sum(len(s['checkpoints'])for s in scenarios),scenarios=scenarios,
        formal_pool_complete=False,cn_calibrated=False)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
