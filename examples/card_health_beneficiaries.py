"""Six actual health/draw recipes and real dependencies through player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from examples.card_qualified_next import session

YETI='CORE_CS2_182';BIG='DINO_132';PENGUIN='CORE_ICC_023';WOLF='EDR_850pe';EMBER='TLC_249'
BOND='EDR_262';SPARK='END_014';ROD='TIME_212';SWARM='TLC_221';STORY='TLC_231';RECIPE='JAIL_866'


def setup(hand,*,board=(),enemy=(),deck=(YETI,)*6,mana=40,seed=811):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=mana,max_mana=mana,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def bond(g,play,end,submit):
        play(1,BOND,target_card=PENGUIN);s=g.state;wolf=s.entities[s.players[1].board[0]]
        assert(wolf.card_id,wolf.attack,wolf.health)==(WOLF,3,2)and not s.players[2].board
        assert s.card_summon_history[-1].request.cause.source.card_id==BOND
    first=session(setup((BOND,),enemy=(PENGUIN,)),bond)
    def spark(g,play,end,submit):
        play(1,SPARK,target_card=PENGUIN);s=g.state;e=s.entities[s.players[1].board[0]]
        assert(e.card_id,e.attack,e.health)==(YETI,7,8)and not s.players[2].board
    second=session(setup((SPARK,),board=(YETI,),enemy=(PENGUIN,),seed=812),spark)
    def rod(g,play,end,submit):
        play(1,ROD,target_card=PENGUIN);s=g.state
        assert not s.players[1].board and s.entities[s.players[2].board[0]].health==1
    third=session(setup((ROD,),board=(PENGUIN,),enemy=(YETI,),seed=813),rod)
    def swarm(g,play,end,submit):
        play(1,SWARM,target_player=2);s=g.state
        assert len(s.players[1].board)==3 and all(s.entities[i].card_id==EMBER for i in s.players[1].board)
        play(1,'CORE_CS2_024',target_card=EMBER);s=g.state
        assert len(s.players[1].board)==2 and s.entities[s.players[2].hero_id].health==25
    fourth=session(setup((SWARM,'CORE_CS2_024'),seed=814),swarm)
    def story(g,play,end,submit):
        original=g.state.players[1].deck[0];play(1,STORY);s=g.state
        assert s.players[1].hand==[original]and s.entities[original].max_health==17
        assert s.entities[s.players[1].hero_id].armor==5
    fifth=session(setup((STORY,),deck=(BIG,),seed=815),story)
    def recipe(g,play,end,submit):
        originals=tuple(g.state.players[1].deck);play(1,RECIPE);s=g.state
        assert set(s.players[1].hand)==set(originals)and len(s.draw_history)==2
        stats=sorted((s.entities[i].attack,s.entities[i].max_health)for i in s.players[1].hand)
        assert stats==[(7,8),(9,15)]and s.players[1].mana==7
    sixth=session(setup((RECIPE,),deck=(YETI,BIG),mana=10,seed=816),recipe)
    scenarios=[first,second,third,fourth,fifth,sixth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=6,new_dependencies=1,existing_dependencies=1,lab_fixture_definitions=0,scenarios=scenarios,
        actions=sum(s['actions']for s in scenarios),checkpoints=sum(len(s['checkpoints'])for s in scenarios),
        formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(7,13)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
