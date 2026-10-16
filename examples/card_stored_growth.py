"""Two real Beasts through player commands; hand/deck/board grow together."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session


def main():
    arch='TLC_811';steg='TLC_827';plain='CORE_CS2_182'
    setup=Scenario((PlayerSetup('HERO_08',hand=(arch,steg,steg),deck=(steg,)+(plain,)*8,
        mana=60,max_mana=60,mana_cap=60),PlayerSetup('HERO_08',board=(plain,),deck=(plain,)*8)),seed=1053)
    def run(g,play,end,submit):
        original=g.state.players[1].deck[0]
        play(1,arch);play(1,steg);end(1);s=g.state
        assert all(e.attack==1 for e in s.entities.values()if e.card_id==steg)
        end(2);s=g.state;assert original in s.players[1].hand and s.entities[original].attack==1
        def attack(listing):
            players={p['id']:p for p in listing['observation']['players']}
            source=next(c['ref']for c in players[1]['board']if c['card_id']==steg)
            target=players[2]['board'][0]['ref']
            return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==target)
        submit(1,attack);s=g.state
        source=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id==steg)
        assert(source.health,source.max_health,source.damage)==(2,6,4)
        end(1);assert all(e.attack==2 for e in g.state.entities.values()if e.card_id==steg)
    row=session(setup,run);result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=2,lab_fixture_definitions=0,
        actions=row['actions'],checkpoints=len(row['checkpoints']),scenario=row,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(6,7)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
