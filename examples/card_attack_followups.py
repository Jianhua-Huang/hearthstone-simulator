"""Three real attack followups through projected player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup, Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session
from .card_static_providers import attack

YETI='CORE_CS2_182'; REHGAR='CORE_CATA_004'; FINJA='CORE_CFM_344'; INQ='CS3_020'
TIDE='CORE_EX1_509'; HUNTER='CORE_EX1_506'


def setup(hand=(),board=(),enemy=(),deck=(YETI,)*8,seed=429):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
        hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,hero_power_card_id='HERO_08bp',
            mana=40,max_mana=40,mana_cap=40)),seed=seed)


def hero_attack(submit):
    def choose(listing):
        players={row['id']:row for row in listing['observation']['players']}
        source=players[1]['hero']['ref'];target=players[2]['hero']['ref']
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==target)
    submit(1,choose)


def main():
    def rehgar(g,play,end,submit):
        play(1,REHGAR);attack(submit,1,YETI,target_player=2);play(1,'CORE_EX1_238',target_player=2)
        assert g.state.entities[g.state.players[2].hero_id].health==23
        assert g.state.players[1].overload_owed==1
    first=session(setup((REHGAR,),board=(YETI,)),rehgar)

    def finja(g,play,end,submit):
        originals={i for i in g.state.players[1].deck if g.state.entities[i].card_id in (HUNTER,TIDE)}
        play(1,FINJA);end(1);end(2);attack(submit,1,FINJA,target_index=0)
        assert originals<=set(g.state.players[1].board) and len(g.state.players[1].board)==3
        assert all(g.state.entities[i].card_id==YETI for i in g.state.players[1].deck)
    second=session(setup((FINJA,),enemy=(TIDE,),deck=(YETI,HUNTER,TIDE)+(YETI,)*5,seed=430),finja)

    def inquisitor(g,play,end,submit):
        play(1,'CS2_106');play(1,INQ);hero_attack(submit)
        source=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==INQ)
        assert g.state.entities[source].attacks_this_turn==0
        assert g.state.entities[g.state.players[2].hero_id].health==19
        attack(submit,1,INQ,target_index=0)
        assert g.state.entities[source].attacks_this_turn==1 and not g.state.players[2].board
    third=session(setup(('CS2_106',INQ),enemy=(YETI,),seed=431),inquisitor)
    scenes=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=3,lab_fixture_definitions=0,
        actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),
        scenarios=scenes,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(11,14)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
