"""Five real spells through player DTOs, plus the first/another-copy transition."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(hand,board=(),enemy=(),seed=4169):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*8,mana=20,max_mana=20,mana_cap=30),
        PlayerSetup('HERO_08',board=enemy,deck=('CORE_CS2_182',)*8,mana=20,max_mana=20,mana_cap=30)),seed=seed)


def main():
    def five(g,play,end,submit):
        play(1,'CATA_138',target_card='CORE_CS2_182')
        e=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='CORE_CS2_182');assert(e.attack,e.health)==(5,6)
        play(1,'EDR_252',target_card='CORE_CS2_182');e=g.state.entities[e.id];assert(e.attack,e.health)==(3,3)
        play(1,'CATA_557',target_player=2);play(1,'CATA_EVENT_402',target_card='CORE_EX1_008')
        s=g.state;assert not s.players[2].board
        assert all(sum(s.entities[i].card_id=='GAME_005'for i in s.players[p].hand)==1 for p in(1,2))
        play(1,'CATA_135');s=g.state
        assert [(s.entities[i].attack,s.entities[i].health)for i in s.players[1].board if s.entities[i].card_id=='CATA_135t']==[(9,10),(9,10)]
        assert s.players[1].mana==0 and s.mana_consumption_history[-1].actual==8
    first=session(setup(('CATA_138','EDR_252','CATA_557','CATA_EVENT_402','CATA_135'),('CORE_CS2_182',),('CORE_EX1_008',)),five)
    def copies(g,play,end,submit):
        play(1,'CATA_557',target_player=2);play(1,'CATA_557');s=g.state
        assert s.entities[s.players[2].hero_id].health==24
        assert [s.entities[i].health for i in s.players[2].board]==[2]
    second=session(setup(('CATA_557','CATA_557'),enemy=('CORE_CS2_182',),seed=4170),copies)
    scenarios=[first,second];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=5,new_fixed_dependencies=1,reused_dependencies=1,lab_fixture_definitions=0,actions=sum(x['actions']for x in scenarios),
        checkpoints=sum(len(x['checkpoints'])for x in scenarios),scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(7,9)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
