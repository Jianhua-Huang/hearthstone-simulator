"""Real corpse native end/death/summon and Volcoross choice through player DTOs."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.model import Resource
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(hand,*,board=(),enemy_hand=(),corpses=12,seed=4372):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=('CORE_CS2_182',)*8,mana=10,max_mana=10,corpses=corpses),
        PlayerSetup('HERO_08',hand=enemy_hand,deck=('CORE_CS2_182',)*8,mana=10,max_mana=10)),seed=seed)


def body(g,cid,p=1):
    s=g.state;return next(s.entities[i]for i in s.players[p].board if s.entities[i].card_id==cid)


def main():
    def necro(g,play,end,submit):
        play(1,'RLK_061');end(1);e=body(g,'RLK_061t')
        assert(e.attack,e.health,e.corpse_value)==(1,3,0)and Keyword.TAUNT in e.keywords
        assert g.state.players[1].resources[Resource.CORPSES]==1
    first=session(setup(('RLK_061',),corpses=2),necro)
    def direhorn(g,play,end,submit):
        play(1,'DINO_416');play(1,'CORE_CS2_029',target_card='CORE_CS2_182')
        assert Keyword.REBORN in body(g,'DINO_416').keywords and g.state.players[1].resources[Resource.CORPSES]==0
    second=session(setup(('DINO_416','CORE_CS2_029'),board=('CORE_CS2_182',),corpses=2,seed=4373),direhorn)
    def flower(g,play,end,submit):
        play(1,'EDR_815');end(1);play(2,'CORE_CS2_182')
        assert body(g,'CORE_CS2_182',2).health==2 and g.state.players[1].resources[Resource.CORPSES]==10
    third=session(setup(('EDR_815',),enemy_hand=('CORE_CS2_182',),seed=4374),flower)
    def volcoross(g,play,end,submit):
        play(1,'FIR_951');assert g.state.pending_choice is not None
        def choose(listing):
            options=listing['observation']['pending_choice']['options'];key=next(o['ref']for o in options if o['card_id']=='FIR_951t3')
            return next(a for a in listing['actions']if a['type']=='select_choice'and a['options']==[key])
        submit(1,choose);e=body(g,'FIR_951');assert(e.attack,e.health)==(25,25)
        assert g.state.players[1].resources[Resource.CORPSES]==10
    fourth=session(setup(('FIR_951',),corpses=30,seed=4375),volcoross)
    scenarios=[first,second,third,fourth];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=4,real_choice_descriptors=3,reused_dependencies=1,lab_fixture_definitions=0,scenarios=scenarios,actions=sum(s['actions']for s in scenarios),
        checkpoints=sum(len(s['checkpoints'])for s in scenarios),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(9,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
