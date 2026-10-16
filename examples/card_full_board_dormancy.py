"""Real Ash Worm, real location occupancy and later ordinary attack via DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    def run(g,play,end,submit):
        play(1,'MEND_040');eid=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='MEND_040')
        assert g.state.entities[eid].dormancy is not None
        play(1,'CORE_REV_990');assert g.state.entities[eid].dormancy is None
        assert sum(e.kind=='minion_awakened'for e in g.events)==1 and len(g.state.successful_summon_history)==1
        end(1);end(2)
        def choose(listing):
            own,enemy=listing['observation']['players'];attacker=next(x['ref']for x in own['board']if x['card_id']=='MEND_040')
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==attacker and a['defender']==enemy['hero']['ref'])
        submit(1,choose);assert g.state.entities[g.state.players[2].hero_id].health==24
    setup=Scenario((PlayerSetup('HERO_06',board=('CORE_CS2_182',)*5,hand=('MEND_040','CORE_REV_990'),deck=('CORE_CS2_182',)*8,mana=10,max_mana=10),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8,mana=10,max_mana=10)),seed=1061)
    s=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        actions=s['actions'],checkpoints=len(s['checkpoints']),scenarios=[s],lab_fixture_definitions=0,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(5,6)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
