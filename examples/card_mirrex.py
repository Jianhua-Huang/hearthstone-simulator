"""One real native mirror follows two public minions and plays the last copy."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.hand_mirrors import source
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    mirror='DINO_407';plain='CORE_CS2_182';squire='CORE_EX1_008'
    setup=Scenario((PlayerSetup('HERO_03',hand=(mirror,),deck=(plain,)*8,mana=60,max_mana=60,mana_cap=60),
        PlayerSetup('HERO_08',hand=(plain,squire),deck=(plain,)*8,mana=60,max_mana=60,mana_cap=60)),active_player=2,seed=1056)
    def run(g,play,end,submit):
        original=g.state.players[1].hand[0]
        play(2,plain);e=g.state.entities[original];assert(e.card_id,e.attack,e.health,e.base_cost)==(plain,3,4,4)
        play(2,squire);e=g.state.entities[original];assert(e.card_id,e.attack,e.health,e.base_cost)==(squire,3,4,1)
        assert Keyword.DIVINE_SHIELD in e.keywords and source(e).hand_mirror.declaring_card_id==mirror
        end(2);before=g.state.players[1].mana;play(1,squire);e=g.state.entities[original]
        assert(e.attack,e.health)==(3,4)and source(e)is None and Keyword.DIVINE_SHIELD in e.keywords
        assert g.state.players[1].mana==before-1
        end(1);play(2,plain);e=g.state.entities[original];assert(e.card_id,e.attack,e.health)==(squire,3,4)
    row=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=1,lab_fixture_definitions=0,actions=row['actions'],checkpoints=len(row['checkpoints']),
        scenario=row,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(6,7)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
