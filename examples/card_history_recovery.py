"""Two real history consumers driven only by player-visible commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

CALIA='CORE_CATA_002';KRAG='CORE_TRL_345';YETI='CORE_CS2_182';FIRE='CORE_CS2_029'


def setup(hand,enemy=()):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,
        hero_power_card_id='HERO_08bp'),PlayerSetup('HERO_08',hand=enemy,deck=(YETI,)*8,
        mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=433)


def main():
    def calia(g,play,end,submit):
        play(1,YETI);end(1);play(2,FIRE,target_card=YETI);end(2)
        original=g.state.death_history[-1];assert original.card_id==YETI
        play(1,CALIA);result=g.state.resurrection_history[-1]
        assert result.death_id==original.id and result.entity_id!=original.entity_id
        assert g.state.entities[result.entity_id].card_id==YETI
        assert g.state.entities[original.entity_id].zone.value=='graveyard'
    first=session(setup((YETI,CALIA),(FIRE,)),calia)
    def krag(g,play,end,submit):
        for cid in('GAME_005',FIRE,'GAME_005'):
            play(1,cid,target_player=2 if cid==FIRE else None)
        end(1);end(2);mana=g.state.players[1].mana;play(1,KRAG)
        hand=[g.state.entities[i].card_id for i in g.state.players[1].hand]
        assert hand==[YETI,'GAME_005',FIRE,'GAME_005']
        assert g.state.players[1].mana==mana-6
        assert g.state.entities[g.state.players[2].hero_id].health==24
    second=session(setup(('GAME_005',FIRE,'GAME_005',KRAG)),krag)
    scenes=[first,second]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=2,lab_fixture_definitions=0,
        actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),
        scenarios=scenes,formal_pool_complete=False,cn_calibrated=False,
        limit='Cross-class scenario, short deck and explicit mana are internal experiments.')
    assert(result['actions'],result['checkpoints'])==(11,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
