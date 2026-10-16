"""Four real1-Cost roots and their named Holy spell via ordinary player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    cub='CATA_130';chameleon='FIR_908';detective='JAIL_452';ecologist='TLC_820';vines='TLC_813';yeti='CORE_CS2_182'
    setup=Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=(chameleon,detective,vines,vines),board=(cub,ecologist,yeti),deck=(yeti,)*8,mana=6,max_mana=20,mana_cap=20),
        PlayerSetup('HERO_03',deck=(yeti,)*8,mana=20,max_mana=20,mana_cap=20)),seed=1057)
    def run(g,play,end,submit):
        original_cub=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==cub)
        original_ecologist=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==ecologist)
        original_yeti=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==yeti)
        def power(listing):
            target=listing['observation']['players'][1]['hero']['ref']
            return next(a for a in listing['actions']if a['type']=='use_hero_power'and a.get('target')==target)
        submit(1,power);play(1,chameleon,target_card=yeti)
        e=g.state.entities[original_yeti];assert(e.attack,e.health)==(5,7)and Keyword.RUSH in e.keywords
        def disguised(listing):
            card=next(c['ref']for c in listing['observation']['players'][0]['hand']if c['card_id']==detective)
            return next(a for a in listing['actions']if a['type']=='play_card'and a['card']==card and a.get('side')=='enemy')
        submit(1,disguised);assert g.state.players[2].overload_owed==2 and g.state.players[1].overload_owed==0
        original_detective=next(i for i in g.state.players[2].board if g.state.entities[i].card_id==detective)
        play(1,vines,target_card=cub);play(1,vines,target_card=detective)
        e=g.state.entities[original_cub];assert(e.attack,e.health)==(2,4)and g.state.players[1].mana==0
        assert g.state.entities[original_detective].health==1
        end(1);assert g.state.players[2].overload_locked==2
        def attack(listing):
            players=listing['observation']['players'];attacker=next(c['ref']for c in players[1]['board']if c['card_id']==detective)
            defender=next(c['ref']for c in players[0]['board']if c['card_id']==ecologist)
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==attacker and a['defender']==defender)
        submit(2,attack);assert g.state.entities[original_ecologist].zone==Zone.GRAVEYARD
        assert g.state.entities[original_detective].zone==Zone.GRAVEYARD
        assert any(g.state.entities[i].card_id==vines for i in g.state.players[1].hand)
        end(2);play(1,vines,target_card=yeti);assert g.state.entities[original_yeti].health==9
    row=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=4,new_dependencies=1,lab_fixture_definitions=0,actions=row['actions'],checkpoints=len(row['checkpoints']),scenario=row,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(9,10)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
