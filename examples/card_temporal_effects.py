"""Four real temporal spells through player DTOs and independent full replay."""
import json
from examples.card_qualified_next import session
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION


def main():
    setup=Scenario((PlayerSetup('HERO_08',hand=('CATA_215','CATA_496','DINO_405','CATA_528'),
        board=('CATA_135t',),deck=('CORE_CS2_182',)*8,mana=20,max_mana=20,mana_cap=30),
        PlayerSetup('HERO_08',board=('CORE_CS2_182','CORE_EX1_008'),deck=('CORE_CS2_182',)*8,
            mana=20,max_mana=20,mana_cap=30)),seed=4170)
    def run(g,play,end,submit):
        s=g.state;returned=s.players[2].board[0];stolen=s.players[2].board[1];friendly=s.players[1].board[0]
        play(1,'CATA_215',target_card='CORE_CS2_182')
        assert g.state.entities[returned].zone==Zone.HAND
        play(1,'CATA_496',target_card='CORE_EX1_008')
        play(1,'DINO_405');play(1,'CATA_528');end(1)
        assert g.state.entities[stolen].controller==1
        listing=g.for_player(2).legal_actions();hand=next(p['hand']for p in listing['observation']['players']if p['id']==2)
        locked=next(c['ref']for c in hand if c['card_id']=='CORE_CS2_182')
        assert not any(a['type']=='play_card'and a['card']==locked for a in listing['actions'])
        end(2);s=g.state;assert s.entities[stolen].controller==2
        naga=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id=='CATA_528t')
        assert(naga.attack,naga.health)==(3,3)and s.entities[friendly].attack==1
        end(1);s=g.state
        assert(s.entities[naga.id].attack,s.entities[naga.id].health)==(5,5)
        assert(s.entities[friendly].attack,s.entities[friendly].health)==(3,4)
        play(2,'CORE_CS2_182');assert g.state.entities[returned].zone==Zone.BOARD
        assert not g.state.players[1].player_effects
    result=session(setup,run)
    result.update(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=4,new_fixed_dependencies=1,lab_fixture_definitions=0,formal_pool_complete=False,cn_calibrated=False)
    result['checkpoints']=len(result['checkpoints'])
    assert(result['actions'],result['checkpoints'])==(8,9)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
