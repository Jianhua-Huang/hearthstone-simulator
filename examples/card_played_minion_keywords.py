"""Two real native listeners, ordinary minion play and Rush attack via player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Keyword,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    def run(g,play,end,submit):
        play(1,'EDR_849');play(1,'JAIL_880');play(1,'CORE_CFM_120')
        eid=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='CORE_CFM_120')
        assert Keyword.RUSH in g.state.entities[eid].keywords
        def choose(listing):
            own,enemy=listing['observation']['players'];attacker=next(x['ref']for x in own['board']if x['card_id']=='CORE_CFM_120');target=enemy['board'][0]['ref']
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==attacker and a['defender']==target)
        submit(1,choose);assert not g.state.players[2].board
        end(1)
    setup=Scenario((PlayerSetup('HERO_05',hand=('EDR_849','JAIL_880','CORE_CFM_120'),deck=('CORE_CS2_182',)*5,mana=10,max_mana=10),
        PlayerSetup('HERO_08',board=('CS2_050',),deck=('CORE_CS2_182',)*5,mana=10,max_mana=10)),seed=1060)
    case=session(setup,run)
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        actions=case['actions'],checkpoints=len(case['checkpoints']),scenarios=[case],lab_fixture_definitions=0,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(5,6)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
