"""Eleven real native providers through ordinary projected player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

YETI='CORE_CS2_182'


def setup(hand=(),board=(),enemy=(),seed=426):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=40,max_mana=40,mana_cap=40)),seed=seed)


def attack(submit,p,source_card,*,target_player=None,target_index=None):
    def choose(listing):
        players={v['id']:v for v in listing['observation']['players']}
        source=next(c['ref']for c in players[p]['board']if c['card_id']==source_card)
        target=players[target_player]['hero']['ref']if target_index is None else players[3-p]['board'][target_index]['ref']
        return next(a for a in listing['actions']if a['type']=='attack'and a['attacker']==source and a['defender']==target)
    submit(p,choose)


def main():
    def spells(g,play,end,submit):
        play(1,'CORE_CS2_029',target_player=2)
        assert g.state.entities[g.state.players[2].hero_id].health==21
        play(1,'CS3_038');attack(submit,1,'CS3_038',target_index=0)
        assert g.state.entities[g.state.players[2].board[0]].health==2
    first=session(setup(('CORE_CS2_029','CS3_038'),('END_031','TIME_856'),(YETI,)),spells)

    def conditions(g,play,end,submit):
        play(1,'CORE_EX1_414');attack(submit,1,'CORE_EX1_414',target_index=0)
        actor=g.state.entities[g.state.players[1].board[0]]
        assert (actor.attack,actor.health)==(10,7)
        assert g.state.entities[g.state.players[2].board[0]].health==1
        play(1,'CORE_OG_218');play(1,'CORE_WON_351');play(1,'CS2_106')
        play(1,'CORE_NEW1_027');play(1,'CORE_EX1_507')
        pirate=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='CORE_WON_351')
        assert (pirate.attack,pirate.health)==(4,3)
    second=session(setup(('CORE_EX1_414','CORE_OG_218','CORE_WON_351','CS2_106','CORE_NEW1_027','CORE_EX1_507'),
        enemy=('CATA_208',),seed=427),conditions)

    def cleave(g,play,end,submit):
        attack(submit,1,'CORE_SCH_605',target_index=1)
        assert [g.state.entities[i].health for i in g.state.players[2].board]==[1,1,1]
        assert g.state.entities[g.state.players[1].board[0]].health==4
    third=session(setup(board=('CORE_SCH_605',),enemy=(YETI,'CATA_208',YETI),seed=428),cleave)

    def quantity(g,play,end,submit):
        play(1,'CORE_DAL_575');play(1,'CORE_EX1_506')
        assert len(g.state.players[1].board)==4 and len(g.state.card_summon_history)==1
    fourth=session(setup(('CORE_DAL_575','CORE_EX1_506'),seed=429),quantity)
    scenes=[first,second,third,fourth]
    result=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=11,lab_fixture_definitions=0,actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),
        scenarios=scenes,formal_pool_complete=False,cn_calibrated=False)
    assert (result['actions'],result['checkpoints'])==(13,17)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return result


if __name__=='__main__':main()
