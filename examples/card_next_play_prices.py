"""Real coupled price/Shield and next-turn taxes driven by player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182'


def main():
    def glider(g,play,end,submit):
        play(1,'DINO_404');end(1);end(2);play(1,'TLC_428')
        before=g.state.players[1].mana;play(1,'TLC_427')
        fish=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='TLC_427')
        assert g.state.players[1].mana==before-1 and Keyword.DIVINE_SHIELD in fish.keywords
        play(1,'WW_001t',target_card='TLC_427')
        assert g.state.entities[fish.id].health==3 and Keyword.DIVINE_SHIELD not in g.state.entities[fish.id].keywords
    first=session(Scenario((PlayerSetup('HERO_08',hand=('DINO_404','TLC_428','TLC_427'),deck=(YETI,)*8,
        mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=1065),glider)

    def taxes(g,play,end,submit):
        play(1,'TIME_716');play(1,'TLC_439');end(1)
        def price(cid):
            s=g.state;e=next(s.entities[i]for i in s.players[2].hand if s.entities[i].card_id==cid)
            return quote_cost(s,g.registry,e).amount
        assert(price(YETI),price('WW_001t'))==(7,2)
        before=g.state.players[2].mana;play(2,YETI);play(2,'WW_001t',target_player=1)
        assert g.state.players[2].mana==before-9
        end(2);assert price(YETI)==4 and not g.state.players[2].cost_modifiers
    second=session(Scenario((PlayerSetup('HERO_08',hand=('TIME_716','TLC_439'),deck=(YETI,)*8,
        mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',hand=(YETI,'WW_001t'),board=(YETI,),deck=(YETI,)*8,
        mana=30,max_mana=30,mana_cap=30)),seed=1066),taxes)
    scenes=[first,second];result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,roots=3,actions=sum(s['actions']for s in scenes),
        checkpoints=sum(len(s['checkpoints'])for s in scenes),scenarios=scenes,lab_fixture_definitions=0,
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(12,14)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
