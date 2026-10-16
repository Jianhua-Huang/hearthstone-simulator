"""Actual fixed shuffles, drawn summons and payment through player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182'


def main():
    def harsh(g,play,end,submit):
        play(1,'CAP_404');original=set(g.state.players[2].deck);end(1)
        imps={i for i in g.state.players[1].board if g.state.entities[i].card_id=='CAP_400t2t'}
        assert imps==original and len(imps)==2
        assert all(Keyword.LIFESTEAL in g.state.entities[i].keywords for i in imps)
        s=g.state;e=next(s.entities[i]for i in s.players[2].hand if s.entities[i].card_id==YETI)
        assert quote_cost(s,g.registry,e).amount==6 and s.entities[s.players[2].hero_id].health==29
        before=s.players[2].mana;play(2,YETI);assert g.state.players[2].mana==before-6
        end(2);assert not g.state.players[2].cost_modifiers
    first=session(Scenario((PlayerSetup('HERO_08',hand=('CAP_404',),deck=(YETI,)*8,
        mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',hand=(YETI,),
        mana=30,max_mana=30,mana_cap=30)),seed=1066),harsh)

    def ninjas(g,play,end,submit):
        play(1,'TLC_518');original=set(g.state.players[1].deck);assert len(original)==3
        play(1,'CORE_CS2_023')
        bodies={i for i in g.state.players[1].board if g.state.entities[i].card_id=='TLC_513t2'}
        assert bodies==original and all(Keyword.STEALTH in g.state.entities[i].keywords for i in bodies)
        assert not g.state.players[1].deck and len(g.state.draw_history)==5
        assert g.state.entities[g.state.players[1].hero_id].health==27
    second=session(Scenario((PlayerSetup('HERO_08',hand=('TLC_518','CORE_CS2_023'),
        mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=1067),ninjas)
    scenes=[first,second];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=2,actions=sum(s['actions']for s in scenes),
        checkpoints=sum(len(s['checkpoints'])for s in scenes),scenarios=scenes,lab_fixture_definitions=0,
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(6,8)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
