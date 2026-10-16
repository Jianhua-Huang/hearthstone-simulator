"""Six real source cards through public commands, copies and actual Rush combat."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import PlayerSetup,Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session
from .card_static_providers import attack

YETI='CORE_CS2_182';FIRE='CORE_CS2_029';INTELLECT='CORE_CS2_023';BAT='TTN_843t1'


def setup(hand,board,enemy,seed,enemy_deck=(YETI,)*8):
    return Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
        hero_power_card_id='HERO_08bp',mana=40,max_mana=40,mana_cap=40),
        PlayerSetup('HERO_08',board=enemy,deck=enemy_deck,hero_power_card_id='HERO_08bp',
            mana=40,max_mana=40,mana_cap=40)),seed=seed)


def main():
    def spells(g,play,end,submit):
        play(1,INTELLECT);play(1,FIRE,target_player=2)
        moon=next(g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='EDR_254')
        assert moon.attack==8
        copied=[g.state.entities[i]for i in g.state.players[2].hand if g.state.entities[i].card_id==YETI]
        assert len(copied)==2 and all(e.cost==1 for e in copied)
        assert sum(g.state.entities[i].card_id==FIRE for i in g.state.players[2].hand)==1
        cold=[e for e in g.events if e.kind=='damage_dealt'and dict(e.data)['damage_kind']=='minion_ability']
        assert len(cold)==4 and all(e.amount==1 for e in cold)
    first=session(setup((INTELLECT,FIRE),('CORE_EX1_100','CORE_RLK_083','EDR_254'),
        ('CORE_SCH_717',YETI,YETI),428),spells)
    def draws(g,play,end,submit):
        play(1,INTELLECT);assert sum(g.state.entities[i].card_id==BAT for i in g.state.players[1].board)==2
        play(1,FIRE,target_card='CORE_SW_047')
        held=[g.state.entities[i]for i in g.state.players[1].hand]
        assert len(held)==3 and sum(e.attack==9 and e.health==10 for e in held)==1
        attack(submit,1,BAT,target_index=0)
        target=next(g.state.entities[i]for i in g.state.players[2].board if g.state.entities[i].card_id==YETI)
        assert target.health==4
    second=session(setup((INTELLECT,FIRE,YETI),('CORE_SW_047','CORE_TTN_843'),(YETI,),429),draws)
    def existing_copy(g,play,end,submit):
        play(1,'CORE_EX1_193');play(1,'CORE_DAL_575');play(1,'CORE_EX1_506')
        assert len(g.state.players[1].board)==5
    third=session(setup(('CORE_EX1_193','CORE_EX1_506'),(),(),430,enemy_deck=('CORE_DAL_575',)),existing_copy)
    scenes=[first,second,third]
    value=dict(content_version=CONTENT_VERSION,core_effects_version=CORE_EFFECTS_VERSION,snapshot_schema=SNAPSHOT_SCHEMA_VERSION,
        roots=6,existing_dependency_roots=['CORE_EX1_193','CORE_DAL_575','CORE_EX1_506'],
        actions=sum(s['actions']for s in scenes),checkpoints=sum(len(s['checkpoints'])for s in scenes),scenarios=scenes,
        lab_fixture_definitions=0,formal_pool_complete=False,cn_calibrated=False)
    assert(value['actions'],value['checkpoints'])==(8,11)
    print(json.dumps(value,ensure_ascii=False,sort_keys=True));return value


if __name__=='__main__':main()
