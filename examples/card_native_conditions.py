"""Three live native sources and actual Life Tap through player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    seer='END_022';spider='JAIL_202';fletcher='TIME_606';yeti='CORE_CS2_182';fireball='CORE_CS2_029';healer='CORE_CS2_117'
    setup=Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_07bp',additional_hero_power_card_ids=('HERO_08bp',),
        hand=(yeti,fireball,healer),board=(seer,spider,fletcher),deck=(yeti,)*8,mana=12,max_mana=20,mana_cap=20),
        PlayerSetup('HERO_03',deck=(yeti,)*8,mana=20,max_mana=20,mana_cap=20)),seed=1058)
    def run(g,play,end,submit):
        def cost():
            s=g.state;return quote_cost(s,g.registry,s.entities[s.players[1].hero_power_id]).amount
        def power(listing,cid,target_card=None):
            own=listing['observation']['players'][0]
            ref=next(p['ref']for p in [own['hero_power'],*own['additional_hero_powers']]if p['card_id']==cid)
            target=next((c['ref']for c in own['board']if c['card_id']==target_card),None)
            return next(a for a in listing['actions']if a['type']=='use_hero_power'and a['power']==ref and a.get('target')==target)
        assert cost()==0 and spell_bonus(g.state,1,g.registry)==0
        submit(1,lambda listing:power(listing,'HERO_07bp'));assert len(g.state.players[1].hand)==4 and cost()==2
        assert g.state.entities[g.state.players[1].hero_id].health==28
        play(1,yeti);assert cost()==0
        submit(1,lambda listing:power(listing,'HERO_08bp',seer));assert spell_bonus(g.state,1,g.registry)==2
        play(1,fireball,target_player=2);assert g.state.entities[g.state.players[2].hero_id].health==22
        def attack(listing):
            players=listing['observation']['players'];attacker=players[0]['hero']['ref'];defender=players[1]['hero']['ref']
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==attacker and a['defender']==defender)
        submit(1,attack);assert g.state.entities[g.state.players[2].hero_id].health==21
        play(1,healer,target_card=seer);assert spell_bonus(g.state,1,g.registry)==0
        end(1);assert g.state.entities[g.state.players[1].hero_id].attack==0
        end(2);assert g.state.entities[g.state.players[1].hero_id].attack==1
    row=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        new_roots=3,new_dependencies=1,lab_fixture_definitions=0,actions=row['actions'],checkpoints=len(row['checkpoints']),scenario=row,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(8,9)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
