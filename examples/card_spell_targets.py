"""Five complete target spell roots through ordinary player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';LAVA='TLC_227';STASIS='TIME_611';BARRAGE='TIME_855';PRECISION='TIME_600';CONSUME='CORE_CATA_007'


def setup(hand,*,enemy=(),seed=611):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def lava(g,play,end,submit):
        play(1,LAVA);s=g.state
        assert len(s.players[2].board)==1 and s.entities[s.players[2].board[0]].health==5
        assert s.players[1].overload_owed==1 and s.players[1].mana==37
        end(1);end(2);s=g.state
        assert(s.players[1].overload_owed,s.players[1].overload_locked)==(0,1)
    first=session(setup((LAVA,),enemy=(YETI,YETI)),lava)

    def stasis(g,play,end,submit):
        play(1,STASIS,target_card=YETI);s=g.state
        assert sorted(s.entities[i].health for i in s.players[2].board)==[2,5]
        assert all(s.entities[i].frozen for i in s.players[2].board)
    second=session(setup((STASIS,),enemy=(YETI,YETI),seed=612),stasis)

    def barrage(g,play,end,submit):
        play(1,BARRAGE,target_player=2);s=g.state
        assert s.entities[s.players[2].hero_id].health==27
        assert all(s.entities[i].health==3 for i in s.players[2].board)
        rows=[r.health_result for r in s.damage_history if r.health_result.source_card_id==BARRAGE]
        assert len(rows)==3 and len({r.batch_id for r in rows})==1
    third=session(setup((BARRAGE,),enemy=(YETI,YETI),seed=613),barrage)

    def precision(g,play,end,submit):
        play(1,PRECISION,target_player=2);s=g.state
        assert s.entities[s.players[2].hero_id].health==25
        assert len(s.players[1].hand)==2
    fourth=session(setup((YETI,PRECISION,YETI),seed=614),precision)

    def consume(g,play,end,submit):
        play(1,CONSUME);s=g.state
        assert not s.players[2].board and len(s.players[1].hand)==2
        assert len(s.draw_history)==2 and len(s.death_history)==2
        rows=[r.health_result for r in s.damage_history if r.health_result.source_card_id==CONSUME]
        assert len(rows)==2 and len({r.batch_id for r in rows})==1
    fifth=session(setup((CONSUME,),enemy=('CORE_ICC_023','CORE_EX1_506'),seed=615),consume)
    scenarios=[first,second,third,fourth,fifth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=5,new_dependencies=0,lab_fixture_definitions=0,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(7,12)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
