"""Native retained Reborn and Kindred FIRE bonus through player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    steed='CAP_800';thrasher='TLC_223';fire='CORE_CS2_029';plain='CORE_CS2_182'
    setup=Scenario((PlayerSetup('HERO_08',hand=(steed,thrasher,'CORE_CS2_009',fire),
        deck=(plain,fire)+(plain,)*8,mana=60,max_mana=60,mana_cap=60),
        PlayerSetup('HERO_08',deck=(plain,)*8)),seed=1054)
    def run(g,play,end,submit):
        play(1,steed);play(1,'CORE_CS2_009',target_card=steed);s=g.state
        original=next(i for i in s.players[1].board if s.entities[i].card_id==steed)
        marked=(s.entities[original].attack,s.entities[original].max_health)
        play(1,fire,target_card=steed);s=g.state
        returned=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id==steed)
        assert returned.id!=original and(returned.attack,returned.health)==marked and Keyword.REBORN not in returned.keywords
        assert Keyword.TAUNT in returned.keywords
        end(1);end(2);play(1,thrasher);s=g.state
        drawn=next(s.entities[i]for i in s.players[1].hand if s.entities[i].card_id==fire)
        assert sum(a.spell_damage for a in drawn.abilities if a.kind=='spell_damage')==2
        play(1,fire,target_player=2);assert g.state.entities[g.state.players[2].hero_id].health==22
        assert len(g.state.cast_history[-1].local_spell_damage)==1
    row=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=2,lab_fixture_definitions=0,
        actions=row['actions'],checkpoints=len(row['checkpoints']),scenario=row,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(7,8)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
