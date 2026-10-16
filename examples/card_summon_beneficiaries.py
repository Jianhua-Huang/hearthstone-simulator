"""Two real roots through player commands and independent portable checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

def setup(hand):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=('CORE_CS2_182',)*8,mana=30,max_mana=30,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*8)),seed=1050)

def main():
    def husk(g,play,end,submit):
        play(1,'EDR_810');s=g.state
        assert sum(s.entities[i].card_id=='EDR_810t'for i in s.players[1].board)==2
        end(1);s=g.state;assert s.entities[s.players[1].hero_id].max_health==34
    a=session(setup(('EDR_810',)),husk)
    def tyr(g,play,end,submit):
        play(1,'TLC_240');play(1,'CORE_CS2_029',target_card='TLC_240');s=g.state
        fish=[s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='TLC_240t']
        assert len(fish)==3 and all(len(e.keywords)==1 for e in fish)
        root=s.ordered_group_history[-1];assert len(root.bonus_receipts)==3 and root.status=='completed'
    b=session(setup(('TLC_240','CORE_CS2_029')),tyr)
    rows=[a,b];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=2,new_tokens=1,lab_fixture_definitions=0,actions=sum(x['actions']for x in rows),checkpoints=sum(len(x['checkpoints'])for x in rows),
        scenarios=rows,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(4,6)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result

if __name__=='__main__':main()
