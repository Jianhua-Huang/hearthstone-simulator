"""Canonical heroes and five default powers through player DTOs; no lab cards."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.model import Resource,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def setup(first,second,seed):
    return Scenario(tuple(PlayerSetup(f'HERO_{hero:02}',hero_power_card_id=f'HERO_{hero:02}bp',
        deck=('CORE_CS2_182',)*8,mana=10,max_mana=10)for hero in (first,second)),seed=seed)


def power(submit,p,target_player=None):
    def choose(listing):
        target=None if target_player is None else next(x['hero']['ref']for x in listing['observation']['players']if x['id']==target_player)
        return next(a for a in listing['actions']if a['type']=='use_hero_power'and a.get('target')==target)
    submit(p,choose)


def attack(submit,p,*,hero=False):
    def choose(listing):
        own=next(x for x in listing['observation']['players']if x['id']==p)
        enemy=next(x for x in listing['observation']['players']if x['id']==3-p)
        attacker=own['hero']['ref']if hero else next(x['ref']for x in own['board']if x['card_id']=='HERO_11bpt')
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==attacker and a['defender']==enemy['hero']['ref'])
    submit(p,choose)


def main():
    def warlock_demon_hunter(g,play,end,submit):
        power(submit,1);assert len(g.state.players[1].hand)==1
        assert g.state.entities[g.state.players[1].hero_id].health==28
        end(1);power(submit,2);attack(submit,2,hero=True)
        assert g.state.entities[g.state.players[1].hero_id].health==27
        end(2);assert g.state.entities[g.state.players[2].hero_id].attack==0
    first=session(setup(7,10,1059),warlock_demon_hunter)

    def shaman_death_knight(g,play,end,submit):
        power(submit,1);assert len(g.state.players[1].board)==1
        end(1);power(submit,2)
        eid=next(i for i in g.state.players[2].board if g.state.entities[i].card_id=='HERO_11bpt')
        attack(submit,2);assert g.state.entities[g.state.players[1].hero_id].health==29
        end(2);assert g.state.entities[eid].zone==Zone.GRAVEYARD
        assert g.state.players[2].resources.get(Resource.CORPSES,0)==1
    second=session(setup(2,11,1059),shaman_death_knight)

    def hunter_priest(g,play,end,submit):
        power(submit,1);assert g.state.entities[g.state.players[2].hero_id].health==28
        end(1);power(submit,2,target_player=2)
        assert g.state.entities[g.state.players[2].hero_id].health==30
        end(2)
    third=session(setup(5,9,1061),hunter_priest)
    cases=[first,second,third]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        actions=sum(x['actions']for x in cases),checkpoints=sum(len(x['checkpoints'])for x in cases),scenarios=cases,
        new_default_powers=5,new_starting_heroes=2,lab_fixture_definitions=0,starting_mode='explicit-scenario',
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(14,17)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
