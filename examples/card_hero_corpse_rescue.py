"""Real Husk/Fireball actions: departed source rescue, later death and zero case."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.hero_corpse_rescue_cards import HUSK,MARKER
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Resource,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.resource_operations import resource_result
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(fireballs,seed):
    return Scenario((PlayerSetup('HERO_08',hand=(HUSK,)+('CORE_CS2_029',)*fireballs,deck=('CORE_CS2_182',)*8,
        mana=40,max_mana=40,mana_cap=40,corpses=0,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*8,mana=10,max_mana=10,hero_power_card_id='HERO_08bp')),seed=seed)


def main():
    def departed(g,play,end,submit):
        play(1,HUSK);source=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==HUSK)
        play(1,'CORE_CS2_029',target_card=HUSK)
        assert g.state.entities[source].zone==Zone.GRAVEYARD and g.state.players[1].resources[Resource.CORPSES]==1
        for _ in range(5):play(1,'CORE_CS2_029',target_player=1)
        s=g.state;assert s.status=='playing'and s.entities[s.players[1].hero_id].health==1
        assert not any(e.spec_id==MARKER for e in s.players[1].player_effects)
        play(1,'CORE_CS2_029',target_player=1)
        assert(g.state.status,g.state.winner)==('finished',2)
        assert[x.actual_amount for e in g.events if(x:=resource_result(e))is not None]==[1]
    first=session(setup(7,4574),departed)
    def zero(g,play,end,submit):
        play(1,HUSK)
        for _ in range(5):play(1,'CORE_CS2_029',target_player=1)
        assert(g.state.status,g.state.winner)==('finished',2)
        assert[x.actual_amount for e in g.events if(x:=resource_result(e))is not None]==[0]
        assert not any(e.spec_id==MARKER for e in g.state.players[1].player_effects)
    second=session(setup(5,4575),zero)
    scenarios=[first,second]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=1,visual_evidence_rows=3,lab_fixture_definitions=0,scenarios=scenarios,actions=sum(x['actions']for x in scenarios),
        checkpoints=sum(len(x['checkpoints'])for x in scenarios),formal_pool_complete=False,cn_calibrated=False,
        setup_policy='Explicit high-mana test Scenario; all submitted actions use real cards/player DTO legality. This is not formal Standard match/deck validation.')
    assert(result['actions'],result['checkpoints'])==(14,16)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
