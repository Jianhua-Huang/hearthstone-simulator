"""Four real Demon effects through player DTOs and independent checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';TERROR='CORE_TTN_866';DINO='DINO_132';HOUND='EDR_891';BAT='EDR_892';LOW='TLC_621'


def setup(hand,*,board=(),enemy=(),seed=387):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def terror(g,play,end,submit):
        play(1,'CORE_CS2_029',target_player=1);play(1,TERROR);source=g.state.players[1].board[0]
        end(1);assert g.state.entities[source].health==4
        assert g.state.entities[g.state.players[1].hero_id].health==30
        assert len([e for e in g.events if e.kind=='attack_declared'])==2
        assert len(g.state.players[2].board)==1
    first=session(setup(('CORE_CS2_029',TERROR),enemy=(YETI,'CORE_EX1_506')),terror)

    def dino(g,play,end,submit):
        play(1,DINO);end(1);assert len(g.state.players[2].board)==1
        row=next(x.health_result for x in g.state.damage_history if x.health_result.source_card_id==DINO)
        assert (row.modified_amount,row.spell_bonus)==(5,0)
    second=session(setup((DINO,),board=('CORE_EX1_012',),enemy=(YETI,YETI),seed=388),dino)

    def hound(g,play,end,submit):
        play(1,LOW);play(1,'CORE_EX1_309',target_card=LOW)
        play(1,HOUND);play(1,'CORE_EX1_309',target_card=HOUND)
        bodies=[g.state.entities[e]for e in g.state.players[1].board]
        assert [e.card_id for e in bodies]==[LOW,LOW]
        assert all((e.attack,e.max_health)==(4,7)for e in bodies)
        assert len(g.state.resurrection_history)==1
    third=session(setup((LOW,'CORE_EX1_309',HOUND,'CORE_EX1_309'),seed=389),hound)

    def bat(g,play,end,submit):
        play(1,HOUND);play(1,'CORE_EX1_309',target_card=HOUND)
        play(1,BAT);play(1,'CORE_EX1_309',target_card=BAT)
        assert [g.state.entities[e].card_id for e in g.state.players[1].board]==[HOUND,HOUND]
        assert len(g.state.resurrection_history)==1
    fourth=session(setup((HOUND,'CORE_EX1_309',BAT,'CORE_EX1_309'),seed=390),bat)
    scenarios=[first,second,third,fourth];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=4,new_dependencies=0,lab_fixture_definitions=0,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(13,17)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
