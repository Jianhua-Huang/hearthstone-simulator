"""Twelve real trigger cards through projected player commands and fresh checkpoints."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session
from .card_static_providers import attack

YETI='CORE_CS2_182'


def setup(hand=(),board=(),enemy=(),active=1,seed=427):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*10,
        hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*10,hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40)),
        active_player=active,seed=seed)


def main():
    def spells(g,play,end,submit):
        play(1,'CORE_CS2_023');play(1,'CORE_CS2_029',target_card='CORE_NEW1_020')
        actor=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='CORE_EX1_604')
        assert actor.attack==7
        assert sum(g.state.entities[i].card_id=='CS2_029'for i in g.state.players[1].hand)==2
    first=session(setup(('CORE_CS2_023','CORE_CS2_029'),('CORE_EX1_559','CORE_NEW1_020','CORE_EX1_604'),(YETI,)),spells)
    def summon_play(g,play,end,submit):
        play(1,'CORE_EX1_506');play(1,'CS2_033');end(1);end(2)
        current={g.state.entities[i].card_id:g.state.entities[i]for i in g.state.players[1].board}
        assert current['CORE_EX1_509'].attack==3 and current['CORE_WC_042'].attack==2 and current['CORE_GVG_103'].attack==3
    second=session(setup(('CORE_EX1_506','CS2_033'),('CORE_EX1_509','CORE_WC_042','CORE_GVG_103'),seed=428),summon_play)
    def deaths(g,play,end,submit):
        play(1,'CORE_CS2_029',target_card=YETI);play(1,'CORE_CS2_029',target_card='CORE_NEW1_020')
        plant=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='EDR_484')
        assert plant.attack==9 and [g.state.entities[i].card_id for i in g.state.players[1].hand]==[YETI]
    third=session(setup(('CORE_CS2_029','CORE_CS2_029'),('EDR_484','CORE_RLK_121','CORE_NEW1_020'),(YETI,),seed=429),deaths)
    def power(g,play,end,submit):
        def use(listing):
            opponent=next(p for p in listing['observation']['players']if p['id']==2)
            return next(a for a in listing['actions']if a['type']=='use_hero_power'and a.get('target')==opponent['hero']['ref'])
        submit(1,use)
        current={g.state.entities[i].card_id:g.state.entities[i]for i in g.state.players[1].board}
        assert current['EDR_469'].dormancy is None and current['EDR_470'].max_health==4
        assert g.state.entities[g.state.players[2].hero_id].health==24
        end(1);end(2);attack(submit,1,'EDR_469',target_player=2)
        assert g.state.entities[g.state.players[2].hero_id].health==21
    fourth=session(setup(board=('EDR_469','EDR_470','CORE_DRG_256'),seed=430),power)
    def tortolla(g,play,end,submit):
        attack(submit,2,YETI,target_index=0);entity=g.state.entities[g.state.players[1].board[0]]
        assert (entity.attack,entity.health)==(2,26)and g.state.entities[g.state.players[1].hero_id].armor==1
        assert g.state.entities[g.state.players[2].board[0]].health==4
    fifth=session(setup(board=('EDR_471',),enemy=(YETI,),active=2,seed=431),tortolla)
    scenes=[first,second,third,fourth,fifth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=12,actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),scenarios=scenes,
        lab_fixture_definitions=0,formal_pool_complete=False,cn_calibrated=False)
    assert(result['actions'],result['checkpoints'])==(13,18)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
