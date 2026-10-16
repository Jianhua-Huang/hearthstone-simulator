"""Four native random damage roots through real player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

BOMBER='CORE_EX1_082';PRIESTESS='CORE_BT_493';BLACKWING='CORE_YOP_034';THASS='RLK_223';YETI='CORE_CS2_182';FIRE='CORE_CS2_029'


def setup(hand,enemy=(),enemy_hand=()):
    return Scenario((PlayerSetup('HERO_08',hand=hand,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40,
        hero_power_card_id='HERO_08bp'),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,
        mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=434)


def main():
    def bomber(g,play,end,send):
        play(1,BOMBER)
        assert sum(g.state.entities[g.state.players[p].hero_id].health for p in(1,2))==57
        body=g.state.entities[g.state.players[1].board[0]];assert body.card_id==BOMBER and body.health==2
    first=session(setup((BOMBER,)),bomber)
    def priestess(g,play,end,send):
        play(1,PRIESTESS);end(1);assert g.state.entities[g.state.players[2].hero_id].health==24
    second=session(setup((PRIESTESS,)),priestess)
    def blackwing(g,play,end,send):
        victim=g.state.players[2].board[0];play(1,BLACKWING);end(1)
        assert g.state.entities[victim].zone.value=='graveyard'
        assert g.state.entities[g.state.players[2].hero_id].health==30
    third=session(setup((BLACKWING,),(YETI,)),blackwing)
    def thass(g,play,end,send):
        play(1,THASS);assert g.state.entities[g.state.players[2].hero_id].health==28;end(1)
        play(2,FIRE,target_card=THASS);assert g.state.entities[g.state.players[2].hero_id].health==26
        assert g.state.entities[g.state.players[1].board[0]].health==1
        play(2,FIRE,target_card=THASS);assert g.state.entities[g.state.players[2].hero_id].health==24
        assert not g.state.players[1].board
    fourth=session(setup((THASS,),enemy_hand=(FIRE,FIRE)),thass)
    scenes=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION,new_roots=4,lab_fixture_definitions=0,
        actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),scenarios=scenes,
        formal_pool_complete=False,cn_calibrated=False,limit='Cross-class scenario, short decks and explicit mana are internal experiments.')
    assert(result['actions'],result['checkpoints'])==(9,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
