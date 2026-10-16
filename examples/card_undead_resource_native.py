"""Five real native Undead resource faces through player DTOs; no lab cards."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.undead_resource_native_cards import BROODMOTHER,AESSINA,RAPTOR,EXPERIMENT,CHILLER,BREATH
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def setup(hand,*,board=(),enemy=(),deck=('CORE_CS2_182',)*8,seed=4877):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_08',board=enemy,deck=('CORE_CS2_182',)*8,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed)


def main():
    def mana(g,play,end,submit):
        play(1,BROODMOTHER)
        def choose(listing):
            own,enemy=listing['observation']['players'];source=own['board'][0]['ref'];target=enemy['board'][0]['ref']
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==target)
        submit(1,choose);assert g.state.players[1].mana==38
    first=session(setup((BROODMOTHER,),enemy=('CORE_CS2_182',)),mana)
    def inactive(g,play,end,submit):
        play(1,AESSINA);assert g.state.entities[g.state.players[2].hero_id].health==30
    second=session(setup((AESSINA,),seed=4878),inactive)
    def draw(g,play,end,submit):
        play(1,CHILLER);end(1);end(2);assert len(g.state.players[1].deck)==4
        play(1,RAPTOR);s=g.state;card=next(s.entities[i]for i in s.players[1].hand if s.entities[i].card_id==EXPERIMENT)
        assert quote_cost(s,g.registry,card).amount==0 and len(s.players[1].deck)==3
        before=g.state.players[1].mana;play(1,EXPERIMENT);assert g.state.players[1].mana==before
    third=session(setup((CHILLER,RAPTOR),deck=(EXPERIMENT,)*4,seed=4879),draw)
    def native_value(g,play,end,submit):
        play(1,EXPERIMENT);play(1,'CORE_CS2_029',target_card=EXPERIMENT)
        card=next(x for x in g.observe(1)['players'][0]['hand']if x['card_id']==BREATH);assert card['base_damage']==3
        play(1,BREATH,target_player=2);assert g.state.entities[g.state.players[2].hero_id].health==27
    fourth=session(setup((EXPERIMENT,'CORE_CS2_029'),seed=4880),native_value)
    scenarios=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=5,fixed_dependencies=1,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(x['actions']for x in scenarios),checkpoints=sum(len(x['checkpoints'])for x in scenarios),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(11,15)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
