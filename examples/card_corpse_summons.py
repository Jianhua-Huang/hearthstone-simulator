"""Four real corpse cards through player DTOs; risen tokens leave no corpse."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.model import Resource
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(card,seed):
    return Scenario((PlayerSetup('HERO_08',hand=(card,),deck=('CORE_CS2_182',)*8,mana=10,max_mana=10,corpses=12),
        PlayerSetup('HERO_08',hand=('CORE_CS2_029',),deck=('CORE_CS2_182',)*8,mana=10,max_mana=10)),seed=seed)


def main():
    scenarios=[]
    for index,(root,token,count,debit,keyword)in enumerate((('CATA_465','CATA_465t',5,8,Keyword.RUSH),
            ('CORE_RLK_118','RLK_118t3',2,4,Keyword.REBORN),('CORE_RLK_506','RLK_061t',6,6,Keyword.TAUNT),
            ('RLK_060','RLK_008t',5,5,Keyword.RUSH))):
        def run(g,play,end,submit,root=root,token=token,count=count,debit=debit,keyword=keyword):
            play(1,root);s=g.state;tokens=[s.entities[i]for i in s.players[1].board if s.entities[i].card_id==token]
            assert len(tokens)==count and all(keyword in e.keywords for e in tokens)
            assert s.players[1].resources[Resource.CORPSES]==12-debit
            assert [row.amount for row in s.corpse_spend_history]==[debit]
            if token in('RLK_061t','RLK_008t'):
                end(1);play(2,'CORE_CS2_029',target_card=token)
                assert g.state.death_history[-1].corpse_value==0
                assert g.state.players[1].resources[Resource.CORPSES]==12-debit
        scenarios.append(session(setup(root,4271+index),run))
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=4,new_fixed_dependencies=4,lab_fixture_definitions=0,scenarios=scenarios,actions=sum(s['actions']for s in scenarios),
        checkpoints=sum(len(s['checkpoints'])for s in scenarios),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(8,12)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
