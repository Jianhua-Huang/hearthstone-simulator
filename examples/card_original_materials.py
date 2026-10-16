"""Six actual original-material spells through player DTOs and checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword,PlayerSetup,Scenario
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';BIG='DINO_132';PENGUIN='CORE_ICC_023'
IMAGE='FIR_941';VICTORY='CATA_978';HIJACK='JAIL_225';ETERNAL='END_025';WIND='FIR_910';TIDE='TIME_702'


def setup(hand,*,enemy=(),deck=(YETI,)*6,seed=911):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def image(g,play,end,submit):
        original=g.state.players[1].deck[0];play(1,IMAGE);s=g.state;e=s.entities[s.players[1].board[0]]
        assert(e.card_id,e.attack,e.health)==(YETI,8,8)and Keyword.DIVINE_SHIELD in e.keywords
        assert e.origin_entity_id==original and original in s.players[1].hand
    first=session(setup((IMAGE,),deck=(YETI,)),image)
    def victory(g,play,end,submit):
        play(1,VICTORY,target_card=PENGUIN);s=g.state;e=s.entities[s.players[1].hand[0]]
        assert e.card_id==BIG and quote_unselected_cost(s,g.registry,e).amount==1
    second=session(setup((VICTORY,BIG),enemy=(PENGUIN,),seed=912),victory)
    def hijack(g,play,end,submit):
        original=g.state.players[2].board[0];play(1,HIJACK,target_card=PENGUIN);s=g.state;e=s.entities[s.players[1].deck[0]]
        assert e.card_id==PENGUIN and e.origin_entity_id==original and e.owner==1
        assert quote_unselected_cost(s,g.registry,e).amount==2 and not s.players[2].board
    third=session(setup((HIJACK,),enemy=(PENGUIN,),deck=(),seed=913),hijack)
    def eternal(g,play,end,submit):
        original=g.state.players[1].hand[0];play(1,ETERNAL,target_card=PENGUIN)
        assert len(g.state.players[1].player_effects)==1;end(1);s=g.state
        assert original in s.players[1].hand and not s.players[1].player_effects
    fourth=session(setup((ETERNAL,),enemy=(PENGUIN,),seed=914),eternal)
    def wind(g,play,end,submit):
        play(1,WIND,target_card=YETI);s=g.state
        assert not s.players[2].board and len(s.discard_history)==1
        assert s.discard_history[0].card_id=='CORE_CS2_029'
    fifth=session(setup((WIND,'CORE_CS2_029'),enemy=(YETI,),seed=915),wind)
    def tide(g,play,end,submit):
        play(1,PENGUIN);play(1,TIDE,target_player=2);s=g.state
        assert s.entities[s.players[1].hero_id].armor==5 and s.entities[s.players[2].hero_id].health==27
    sixth=session(setup((TIDE,PENGUIN),seed=916),tide)
    scenarios=[first,second,third,fourth,fifth,sixth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=6,new_dependencies=0,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(8,14)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
