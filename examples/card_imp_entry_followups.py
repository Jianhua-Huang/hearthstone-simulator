"""Actual top-deck growth and persistent summoned-Imp rewards by player DTO."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario,Zone
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182'


def main():
    def run(g,play,end,submit):
        play(1,'CAP_406');source=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='CAP_406')
        play(1,'CAP_404');original=set(g.state.players[2].deck);assert len(original)==2
        play(1,'CAP_401');selected=g.state.players[2].deck[0]
        assert g.state.entities[selected].attack==5 and len(g.state.deck_shuffle_history)==1
        play(1,'CORE_CS2_029',target_card='CAP_406')
        assert g.state.entities[source].zone==Zone.GRAVEYARD and len(g.state.players[1].player_effects)==1
        end(1)
        bodies={i for i in g.state.players[1].board if g.state.entities[i].card_id=='CAP_400t2t'}
        assert bodies==original
        assert all(Keyword.LIFESTEAL in g.state.entities[i].keywords for i in bodies)
        assert(g.state.entities[selected].attack,g.state.entities[selected].health)==(7,7)
        other=next(i for i in bodies if i!=selected)
        assert(g.state.entities[other].attack,g.state.entities[other].health)==(5,5)
        assert len(g.state.draw_history)==3 and g.state.entities[g.state.players[2].hero_id].health==29
    scene=session(Scenario((PlayerSetup('HERO_08',hand=('CAP_406','CAP_404','CAP_401','CORE_CS2_029'),
        deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',hand=(YETI,),
        mana=30,max_mana=30,mana_cap=30)),seed=1067),run)
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=2,actions=scene['actions'],checkpoints=len(scene['checkpoints']),scenarios=[scene],lab_fixture_definitions=0,
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(5,6)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
