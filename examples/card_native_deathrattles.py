"""Four real Deathrattles through player DTOs and independent checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session
from examples.card_death_followups import attack

YETI='CORE_CS2_182'


def setup(hand,*,board=(),enemy=(),enemy_hand=(),seed=373):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*5,
        mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,hand=enemy_hand,deck=(YETI,)*5)),seed=seed)


def main():
    def operator(g,play,end,submit):
        def enemy_side(listing):
            return next(a for a in listing['actions']if a['type']=='play_card'and a.get('side')=='enemy')
        submit(1,enemy_side);source=g.state.players[2].board[0]
        assert (g.state.entities[source].owner,g.state.entities[source].controller)==(1,2)
        play(1,'CORE_EX1_309',target_card='CAP_004')
        assert len(g.state.players[1].hand)==2 and not g.state.players[2].hand
    first=session(setup(('CAP_004','CORE_EX1_309')),operator)

    def spore(g,play,end,submit):
        play(1,'EDR_110');play(1,'CORE_CS2_029',target_card='EDR_110')
        assert len(g.state.players[2].board)==1
        row=next(x.health_result for x in g.state.damage_history if x.health_result.source_card_id=='EDR_110')
        assert (row.damage_dealt,row.modified_amount,row.spell_bonus)==(1,1,0)
    second=session(setup(('EDR_110','CORE_CS2_029'),board=('CORE_EX1_012',),enemy=(YETI,YETI),seed=374),spore)

    def twisted(g,play,end,submit):
        held=g.state.players[1].hand[-1];other=g.state.players[2].hand[0]
        play(1,'EDR_495');play(1,'CORE_EX1_309',target_card='EDR_495')
        assert (g.state.entities[held].attack,g.state.entities[other].attack)==(2,2)
        play(1,YETI);assert held in g.state.players[1].board and g.state.entities[held].attack==2
    third=session(setup(('EDR_495','CORE_EX1_309',YETI),enemy_hand=(YETI,),seed=375),twisted)

    def blight(g,play,end,submit):
        play(1,'END_002');play(1,'CORE_CS2_029',target_card='END_002');weapon=g.state.players[1].weapon_id
        assert (g.state.entities[weapon].card_id,g.state.entities[weapon].attack)==('CS2_082',1)
        play(1,'CORE_CS2_029',target_card='END_002')
        assert g.state.players[1].weapon_id==weapon and g.state.entities[weapon].attack==3
        attack(submit,1,None)
        assert g.state.entities[weapon].durability==1
        assert g.state.entities[g.state.players[2].hero_id].health==27
    fourth=session(setup(('END_002','CORE_CS2_029','CORE_CS2_029'),seed=376),blight)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=4,
        new_dependencies=1,reused_dependencies=1,lab_fixture_definitions=0,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),
        scenarios=scenarios,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(11,15)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
