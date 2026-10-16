"""Real growth, physical draw linkage, ordinary spell/combat deaths via player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.information import VIEW_VERSION
from examples.card_qualified_next import session


def main():
    def run(g,play,end,submit):
        play(1,'CATA_210');play(1,'TLC_603')
        plat=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='TLC_603')
        link=next(a.deathrattle_memory.draws[0]for a in g.state.entities[plat].abilities if a.deathrattle_memory is not None)
        end(1);end(2);play(1,'CS2_029',target_card='CATA_210')
        whelp=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='CATA_210t')
        assert(whelp.attack,whelp.health)==(3,2)
        def choose(listing):
            own,enemy=listing['observation']['players'];attacker=next(x['ref']for x in own['board']if x['card_id']=='TLC_603')
            target=next(x['ref']for x in enemy['board']if x['card_id']=='CORE_CS2_182')
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==attacker and a['defender']==target)
        submit(1,choose);assert len(g.state.discard_history)==1 and g.state.discard_history[0].entity_id==link.entity_id
        assert sum(g.state.entities[i].card_id=='CORE_CS2_182'for i in g.state.players[1].hand)==1
    setup=Scenario((PlayerSetup('HERO_08',hand=('CATA_210','TLC_603','CS2_029'),deck=('CORE_CS2_182',)*8,mana=20,max_mana=20,mana_cap=20),
        PlayerSetup('HERO_08',board=('CORE_CS2_182',),deck=('CORE_CS2_182',)*8,mana=20,max_mana=20,mana_cap=20)),seed=1062)
    s=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        observation_version=VIEW_VERSION,actions=s['actions'],checkpoints=len(s['checkpoints']),scenarios=[s],lab_fixture_definitions=0,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(6,7)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
