"""Actual deck spell and Holy history spell target their original causing minions."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup, Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    def run(g,play,end,submit):
        play(1,'TLC_438')
        fish=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='TLC_438')
        assert fish.health==4 and g.state.cast_history[-1].target_id==fish.id
        play(1,'TLC_430');play(1,'CS2_236',target_card='TLC_438');end(1)
        cave=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='TLC_430')
        assert cave.health==10 and g.state.entities[fish.id].health==8
        assert len(g.state.cast_history)==3 and g.state.cast_history[-1].target_id==cave.id
    scene=session(Scenario((PlayerSetup('HERO_08',hand=('TLC_438','TLC_430','CS2_236'),
        deck=('CS2_236','CORE_CS2_182'),mana=20,max_mana=20,mana_cap=20),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*5)),seed=1064),run)
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=2,actions=scene['actions'],checkpoints=len(scene['checkpoints']),
        scenarios=[scene],lab_fixture_definitions=0,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(4,5)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
